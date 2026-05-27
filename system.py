from __future__ import annotations

import logging
import os
import pwd
import re
import secrets
import string
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from config import (
    DEFAULT_HOME_BASE,
    DEFAULT_SHELL,
    MAX_USERNAME_LEN,
    SSHD_CONFIG_BACKUP,
    SSHD_CONFIG_DIR,
    SSHD_CONFIG_FILE,
)

logger = logging.getLogger(__name__)


class SystemError(RuntimeError):
    """System command or validation error."""
    pass


USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


@dataclass(frozen=True)
class CommandResult:
    """Result of a system command invocation."""
    returncode: int
    stdout: str
    stderr: str


def run_cmd(args: list[str]) -> CommandResult:
    """Run a system command and return captured output."""
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    return CommandResult(result.returncode, result.stdout.strip(), result.stderr.strip())


def check_root() -> None:
    """Raise if the current user is not root."""
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise SystemError("This tool must be run as root.")


def validate_username(username: str) -> None:
    """Validate a Linux username against policy constraints."""
    if not USERNAME_RE.match(username):
        raise SystemError("Invalid username format.")
    if len(username) > MAX_USERNAME_LEN:
        raise SystemError("Username too long.")


def user_exists(username: str) -> bool:
    """Return True if the Linux user exists."""
    try:
        pwd.getpwnam(username)
        return True
    except KeyError:
        return False


def get_uid(username: str) -> int:
    """Return the UID for a Linux username."""
    return pwd.getpwnam(username).pw_uid


def generate_password(length: int = 32) -> str:
    """Generate a random alphanumeric password."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def create_home_dir(username: str) -> Path:
    """Ensure the user's home directory exists with secure permissions."""
    home = DEFAULT_HOME_BASE / username
    home.mkdir(parents=True, exist_ok=True)
    os.chmod(home, 0o700)
    return home


def set_authorized_key(home: Path, public_key: str) -> None:
    """Write an SSH public key into authorized_keys with secure permissions."""
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(mode=0o700, exist_ok=True)
    auth_keys = ssh_dir / "authorized_keys"
    auth_keys.write_text(public_key.strip() + "\n", encoding="utf-8")
    os.chmod(auth_keys, 0o600)


def set_authorized_key_for_user(username: str, public_key: str) -> None:
    """Set authorized_keys for a specific user."""
    home = Path(pwd.getpwnam(username).pw_dir)
    set_authorized_key(home, public_key)


def clear_authorized_key(username: str) -> None:
    """Remove a user's authorized_keys file if present."""
    home = Path(pwd.getpwnam(username).pw_dir)
    auth_keys = home / ".ssh" / "authorized_keys"
    if auth_keys.exists():
        auth_keys.unlink()


def set_password(username: str, password: str) -> None:
    """Set a user's password using chpasswd."""
    result = subprocess.run(
        ["chpasswd"],
        input=f"{username}:{password}",
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemError(f"Failed to set password: {result.stderr.strip()}")


def create_user(username: str, ssh_public_key: str | None) -> str:
    """Create a Linux user and return the generated password."""
    validate_username(username)
    if user_exists(username):
        raise SystemError("User already exists.")

    password = generate_password()

    try:
        result = run_cmd(
            [
                "useradd",
                "-m",
                "-d",
                str(DEFAULT_HOME_BASE / username),
                "-s",
                DEFAULT_SHELL,
                username,
            ]
        )
        if result.returncode != 0:
            raise SystemError(f"useradd failed: {result.stderr}")

        home = create_home_dir(username)
        if ssh_public_key:
            set_authorized_key(home, ssh_public_key)

        set_password(username, password)
    except Exception as exc:
        logger.error("Create user failed: %s", exc)
        if user_exists(username):
            run_cmd(["userdel", "-r", username])
        raise

    return password


def delete_user(username: str) -> None:
    """Delete a Linux user and remove their home directory."""
    result = run_cmd(["userdel", "-r", username])
    if result.returncode != 0:
        raise SystemError(f"userdel failed: {result.stderr}")


def lock_user(username: str) -> None:
    """Lock a Linux user account."""
    result = run_cmd(["usermod", "-L", username])
    if result.returncode != 0:
        raise SystemError(f"Failed to lock user: {result.stderr}")


def unlock_user(username: str) -> None:
    """Unlock a Linux user account."""
    result = run_cmd(["usermod", "-U", username])
    if result.returncode != 0:
        raise SystemError(f"Failed to unlock user: {result.stderr}")


def rotate_password(username: str) -> str:
    """Rotate a user's password and return the new value."""
    password = generate_password()
    set_password(username, password)
    return password


def ensure_sshd_config_dir() -> None:
    """Ensure the sshd_config.d directory exists."""
    SSHD_CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def sshd_validate() -> None:
    """Validate sshd configuration."""
    result = run_cmd(["sshd", "-t"])
    if result.returncode != 0:
        raise SystemError(f"sshd config validation failed: {result.stderr}")


def sshd_reload() -> None:
    """Reload sshd configuration."""
    result = run_cmd(["systemctl", "reload", "ssh"])
    if result.returncode != 0:
        raise SystemError(f"sshd reload failed: {result.stderr}")


def _match_block(username: str) -> str:
    """Render a Match User block for sshd."""
    return (
        f"# BEGIN SSH-VPN-ADMIN USER {username}\n"
        f"Match User {username}\n"
        "    ForceCommand /bin/false\n"
        "    PermitTTY no\n"
        "    X11Forwarding no\n"
        "    AllowTcpForwarding yes\n"
        "    GatewayPorts no\n"
        f"# END SSH-VPN-ADMIN USER {username}\n"
    )


def _remove_block(content: str, username: str) -> str:
    """Remove the Match User block for a username from content."""
    start = f"# BEGIN SSH-VPN-ADMIN USER {username}"
    end = f"# END SSH-VPN-ADMIN USER {username}"
    lines = content.splitlines()
    output: list[str] = []
    skip = False
    for line in lines:
        if line.strip() == start:
            skip = True
            continue
        if skip and line.strip() == end:
            skip = False
            continue
        if not skip:
            output.append(line)
    return "\n".join(output).rstrip() + "\n"


def apply_match_block(username: str) -> None:
    """Apply or replace the Match User block and reload sshd."""
    ensure_sshd_config_dir()
    original = ""
    if SSHD_CONFIG_FILE.exists():
        original = SSHD_CONFIG_FILE.read_text(encoding="utf-8")

    updated = _remove_block(original, username)
    updated = updated + _match_block(username)

    SSHD_CONFIG_BACKUP.write_text(original, encoding="utf-8")
    SSHD_CONFIG_FILE.write_text(updated, encoding="utf-8")

    try:
        sshd_validate()
        sshd_reload()
    except SystemError:
        SSHD_CONFIG_FILE.write_text(original, encoding="utf-8")
        raise


def remove_match_block(username: str) -> None:
    """Remove the Match User block and reload sshd."""
    ensure_sshd_config_dir()
    original = ""
    if SSHD_CONFIG_FILE.exists():
        original = SSHD_CONFIG_FILE.read_text(encoding="utf-8")

    updated = _remove_block(original, username)

    SSHD_CONFIG_BACKUP.write_text(original, encoding="utf-8")
    SSHD_CONFIG_FILE.write_text(updated, encoding="utf-8")

    try:
        sshd_validate()
        sshd_reload()
    except SystemError:
        SSHD_CONFIG_FILE.write_text(original, encoding="utf-8")
        raise


def reapply_hardening(username: str) -> None:
    """Reapply shell, permissions, and Match User hardening."""
    result = run_cmd(["usermod", "-s", DEFAULT_SHELL, username])
    if result.returncode != 0:
        raise SystemError(f"Failed to set shell: {result.stderr}")
    home = Path(pwd.getpwnam(username).pw_dir)
    if home.exists():
        os.chmod(home, 0o700)
    apply_match_block(username)


def get_last_login(username: str) -> str:
    """Return the most recent login line from the last command."""
    result = run_cmd(["last", "-n", "1", username])
    if result.returncode != 0:
        return "No data"
    line = result.stdout.splitlines()[0] if result.stdout else ""
    return line.strip() or "No data"


def check_openssh() -> None:
    """Raise if openssh-server is not active."""
    result = run_cmd(["systemctl", "is-active", "--quiet", "ssh"])
    if result.returncode != 0:
        raise SystemError("openssh-server is not running.")


def run_script_stream(script_path: Path) -> Iterable[str]:
    """Run a shell script and yield combined stdout lines."""
    process = subprocess.Popen(
        ["/bin/bash", str(script_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if process.stdout:
        for line in process.stdout:
            yield line.rstrip()
    process.wait()
