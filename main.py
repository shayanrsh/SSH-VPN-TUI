from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import (
    DATE_FORMAT,
    DATETIME_FORMAT,
    ExpiryMode,
    LOG_PATH,
    PROJECT_ROOT,
    ResetMode,
    VERSION,
)
from db import Database, DBUser
from scheduler import Scheduler
from system import (
    apply_match_block,
    check_openssh,
    check_root,
    clear_authorized_key,
    create_user,
    delete_user,
    ensure_sshd_config_dir,
    get_last_login,
    lock_user,
    reapply_hardening,
    remove_match_block,
    rotate_password,
    set_authorized_key_for_user,
    unlock_user,
    user_exists,
    validate_username,
)
from traffic import TrafficManager


def configure_logging() -> None:
    """Configure file logging for the application."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(LOG_PATH),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def run_script(script_name: str) -> int:
    """Run a bundled shell script by name."""
    script_path = PROJECT_ROOT / script_name
    if not script_path.exists():
        print(f"Missing script: {script_name}")
        return 1
    result = subprocess.run(["/bin/bash", str(script_path)], check=False)
    return result.returncode


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="SSH VPN Admin")
    parser.add_argument("--update", action="store_true", help="Update ssh-vpn-admin")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall ssh-vpn-admin")
    parser.add_argument("--init-db", action="store_true", help="Initialize database")
    return parser.parse_args()


def format_bytes(value: int) -> str:
    """Format byte values for display."""
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024.0:
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}PB"


def print_user_table(users: list[DBUser]) -> None:
    """Print a simple table of users."""
    headers = ["Username", "Status", "Traffic", "Expiry"]
    rows = []
    for user in users:
        status = "active" if user.is_active else "disabled"
        traffic = (
            f"{format_bytes(user.traffic_used_bytes)} / unlimited"
            if user.traffic_limit_bytes == 0
            else f"{format_bytes(user.traffic_used_bytes)} / {format_bytes(user.traffic_limit_bytes)}"
        )
        expiry = user.expiry_at or "Unlimited"
        rows.append([user.username, status, traffic, expiry])

    col_widths = [max(len(str(item)) for item in column) for column in zip(headers, *rows)]
    header_line = " | ".join(
        str(header).ljust(col_widths[idx]) for idx, header in enumerate(headers)
    )
    print(header_line)
    print("-" * len(header_line))
    for row in rows:
        print(
            " | ".join(
                str(cell).ljust(col_widths[idx]) for idx, cell in enumerate(row)
            )
        )


def prompt(text: str) -> str:
    """Prompt for input and return stripped text."""
    return input(text).strip()


def prompt_optional(text: str, current: str | None = None) -> str | None:
    """Prompt for optional input, returning None if left blank."""
    if current:
        value = input(f"{text} [{current}]: ").strip()
        return value if value else current
    value = input(f"{text}: ").strip()
    return value if value else None


def compute_expiry(mode: str, value: str) -> str:
    """Compute an expiry timestamp from the chosen mode."""
    now = datetime.now(timezone.utc)
    if mode == ExpiryMode.DATE:
        dt = datetime.strptime(value, DATE_FORMAT).replace(tzinfo=timezone.utc)
    else:
        count = int(value)
        if count < 1:
            raise ValueError("Expiry must be at least 1")
        if mode == ExpiryMode.WEEKS:
            dt = now + timedelta(weeks=count)
        elif mode == ExpiryMode.MONTHS:
            dt = now + timedelta(days=count * 30)
        else:
            dt = now + timedelta(days=count)
    if dt <= now:
        raise ValueError("Expiry must be in the future")
    return dt.strftime(DATETIME_FORMAT)


def select_expiry() -> tuple[str, str | None, str | None]:
    """Prompt for expiry settings."""
    print("Expiry modes: unlimited, date, days, weeks, months")
    mode = prompt("Expiry mode: ").lower() or ExpiryMode.UNLIMITED
    if mode == ExpiryMode.UNLIMITED:
        return mode, None, None
    value = prompt("Expiry value (YYYY-MM-DD for date or number): ")
    expiry_at = compute_expiry(mode, value)
    return mode, value, expiry_at


def select_traffic() -> tuple[int, str]:
    """Prompt for traffic limit and reset schedule."""
    unit = prompt("Traffic limit unit (unlimited/mb/gb): ").lower() or "unlimited"
    limit_bytes = 0
    if unit != "unlimited":
        value = int(prompt("Traffic limit value: "))
        if value <= 0:
            raise ValueError("Traffic limit must be > 0")
        limit_bytes = value * (1024**2 if unit == "mb" else 1024**3)

    reset = prompt("Reset schedule (never/daily/weekly/monthly): ").lower() or ResetMode.UNLIMITED
    if reset == "never":
        reset = ResetMode.UNLIMITED
    return limit_bytes, reset


def create_user_flow(db: Database, traffic: TrafficManager) -> None:
    """Create a user from prompt input."""
    username = prompt("Username: ")
    validate_username(username)
    if user_exists(username):
        raise ValueError("User already exists")

    full_name = prompt_optional("Full name") or ""
    ssh_key = prompt_optional("SSH public key")
    notes = prompt_optional("Notes")
    expiry_mode, expiry_value, expiry_at = select_expiry()
    traffic_limit_bytes, traffic_reset = select_traffic()

    password = create_user(username, ssh_key)
    apply_match_block(username)
    traffic.ensure_user(username)
    db.create_user_record(
        {
            "username": username,
            "full_name": full_name,
            "created_at": Database.utcnow(),
            "is_active": 1,
            "expiry_mode": expiry_mode,
            "expiry_value": expiry_value,
            "expiry_at": expiry_at,
            "traffic_limit_bytes": traffic_limit_bytes,
            "traffic_used_bytes": 0,
            "traffic_reset_mode": traffic_reset,
            "last_traffic_reset": None,
            "ssh_public_key": ssh_key,
            "notes": notes,
            "deleted_at": None,
        }
    )
    db.record_event(username, "create", "User created")
    print(f"User created. Password: {password}")


def update_user_flow(db: Database) -> None:
    """Update an existing user's metadata and hardening."""
    username = prompt("Username to edit: ")
    user = db.get_user(username)
    if not user:
        raise ValueError("User not found")

    full_name = prompt_optional("Full name", user.full_name) or ""
    ssh_key = prompt_optional("SSH public key (empty to keep, 'none' to clear)")
    notes = prompt_optional("Notes", user.notes or "") or ""

    expiry_mode, expiry_value, expiry_at = select_expiry()
    traffic_limit_bytes, traffic_reset = select_traffic()

    if ssh_key and ssh_key.lower() == "none":
        clear_authorized_key(username)
        ssh_key = None
    elif ssh_key:
        set_authorized_key_for_user(username, ssh_key)

    reapply_hardening(username)
    db.update_user_record(
        username,
        {
            "full_name": full_name,
            "expiry_mode": expiry_mode,
            "expiry_value": expiry_value,
            "expiry_at": expiry_at,
            "traffic_limit_bytes": traffic_limit_bytes,
            "traffic_reset_mode": traffic_reset,
            "ssh_public_key": ssh_key,
            "notes": notes,
        },
    )
    db.record_event(username, "update", "User updated")
    print("User updated.")


def show_user_detail(db: Database) -> None:
    """Display a single user's details."""
    username = prompt("Username: ")
    user = db.get_user(username)
    if not user:
        raise ValueError("User not found")

    print(f"Username: {user.username}")
    print(f"Full name: {user.full_name}")
    print(f"Active: {bool(user.is_active)}")
    print(f"Expiry: {user.expiry_at or 'Unlimited'}")
    print(f"Traffic: {format_bytes(user.traffic_used_bytes)}")
    print(f"Limit: {format_bytes(user.traffic_limit_bytes)}" if user.traffic_limit_bytes else "Limit: Unlimited")
    print(f"Last reset: {user.last_traffic_reset or 'Never'}")
    print(f"Notes: {user.notes or ''}")
    print(f"Last login: {get_last_login(user.username)}")


def toggle_user(db: Database) -> None:
    """Toggle a user's active status."""
    username = prompt("Username: ")
    user = db.get_user(username)
    if not user:
        raise ValueError("User not found")
    if user.is_active:
        lock_user(username)
        db.update_user_record(username, {"is_active": 0})
        db.record_event(username, "lock", "User locked")
        print("User locked.")
    else:
        unlock_user(username)
        db.update_user_record(username, {"is_active": 1})
        db.record_event(username, "unlock", "User unlocked")
        print("User unlocked.")


def reset_traffic(db: Database, traffic: TrafficManager) -> None:
    """Reset traffic counters for a user."""
    username = prompt("Username: ")
    traffic.reset_user(username)
    db.reset_traffic(username)
    db.record_event(username, "traffic_reset", "Traffic reset")
    print("Traffic reset.")


def rotate_user_password(db: Database) -> None:
    """Rotate a user's password."""
    username = prompt("Username: ")
    password = rotate_password(username)
    db.record_event(username, "rotate_password", "Password rotated")
    print(f"New password: {password}")


def delete_user_flow(db: Database) -> None:
    """Delete a user and soft-delete the database record."""
    username = prompt("Username: ")
    confirm = prompt(f"Type DELETE to remove {username}: ")
    if confirm != "DELETE":
        print("Delete canceled.")
        return
    remove_match_block(username)
    delete_user(username)
    db.soft_delete_user(username)
    db.record_event(username, "delete", "User deleted")
    print("User deleted.")


def run_cli(db: Database, traffic: TrafficManager) -> None:
    """Run a simple interactive CLI menu."""
    scheduler = Scheduler(db=db, traffic=traffic)
    scheduler.start()
    try:
        while True:
            print("\nSSH VPN Admin")
            print(f"Version: {VERSION}")
            print("1) List users")
            print("2) Create user")
            print("3) View user")
            print("4) Edit user")
            print("5) Toggle user")
            print("6) Reset traffic")
            print("7) Rotate password")
            print("8) Delete user")
            print("9) Update")
            print("0) Quit")

            choice = prompt("Select: ")
            try:
                if choice == "1":
                    print_user_table(db.list_users())
                elif choice == "2":
                    create_user_flow(db, traffic)
                elif choice == "3":
                    show_user_detail(db)
                elif choice == "4":
                    update_user_flow(db)
                elif choice == "5":
                    toggle_user(db)
                elif choice == "6":
                    reset_traffic(db, traffic)
                elif choice == "7":
                    rotate_user_password(db)
                elif choice == "8":
                    delete_user_flow(db)
                elif choice == "9":
                    run_script("update.sh")
                elif choice == "0":
                    break
                else:
                    print("Invalid selection.")
            except Exception as exc:
                print(f"Error: {exc}")
    finally:
        scheduler.stop()


def main() -> int:
    """Application entry point."""
    args = parse_args()
    configure_logging()

    if args.update:
        return run_script("update.sh")
    if args.uninstall:
        return run_script("uninstall.sh")

    try:
        check_root()
    except Exception as exc:
        print(str(exc))
        return 1

    if args.init_db:
        db = Database()
        db.initialize()
        print("Database initialized.")
        return 0

    try:
        check_openssh()
    except Exception as exc:
        print(str(exc))
        return 1

    try:
        ensure_sshd_config_dir()
    except Exception as exc:
        print(str(exc))
        return 1

    db = Database()
    db.initialize()
    traffic = TrafficManager()
    if not traffic.available():
        print("Warning: iptables/vnstat not available; traffic tracking disabled.")

    run_cli(db, traffic)
    return 0


if __name__ == "__main__":
    sys.exit(main())
