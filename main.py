from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

from config import LOG_PATH, PROJECT_ROOT, VERSION
from db import Database
from system import check_openssh, check_root, ensure_sshd_config_dir
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
    parser = argparse.ArgumentParser(description="SSH VPN Admin TUI")
    parser.add_argument("--update", action="store_true", help="Update ssh-vpn-admin")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall ssh-vpn-admin")
    parser.add_argument("--init-db", action="store_true", help="Initialize database")
    return parser.parse_args()


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

    from ui.app import SSHVPNAdminApp

    app = SSHVPNAdminApp(db=db, traffic=traffic, version=VERSION)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
