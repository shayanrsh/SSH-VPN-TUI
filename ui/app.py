from __future__ import annotations

import logging
from typing import Any

from textual.app import App

from db import Database
from scheduler import Scheduler
from system import (
    SystemError,
    apply_match_block,
    clear_authorized_key,
    delete_user,
    lock_user,
    reapply_hardening,
    remove_match_block,
    rotate_password,
    set_authorized_key_for_user,
    unlock_user,
)
from traffic import TrafficManager
from ui.screens.dashboard import DashboardScreen
from ui.screens.user_detail import UserDetailScreen
from ui.screens.user_form import UserFormScreen
from ui.screens.confirm import ConfirmScreen, UpdateLogScreen

logger = logging.getLogger(__name__)


class SSHVPNAdminApp(App[None]):
    """Textual application for SSH VPN administration."""
    CSS = """
    Screen { layout: vertical; }
    #header { height: 3; padding: 1 2; background: #1d1f21; color: #e6e6e6; }
    #filter { height: 3; padding: 0 2; }
    #content { padding: 0 1; }
    #status { height: 2; padding: 0 2; background: #1d1f21; color: #c5c8c6; }
    .form-row { height: auto; padding: 0 1; }
    .form-label { width: 18; }
    .error-text { color: red; height: 1; }
    .button-row { padding: 1 1; }
    """

    def __init__(self, db: Database, traffic: TrafficManager, version: str) -> None:
        """Initialize the app with database and traffic managers."""
        super().__init__()
        self.db = db
        self.traffic = traffic
        self.version = version
        self.scheduler = Scheduler(db=db, traffic=traffic)

    def on_mount(self) -> None:
        """Start background scheduler and open dashboard."""
        self.scheduler.start()
        self.push_screen(DashboardScreen())

    def on_shutdown_request(self) -> None:
        """Stop background scheduler on exit."""
        self.scheduler.stop()

    def show_error(self, message: str) -> None:
        """Display an error notification."""
        self.notify(message, severity="error")

    def show_info(self, message: str) -> None:
        """Display an info notification."""
        self.notify(message, severity="information")

    def open_user_detail(self, username: str) -> None:
        """Open the user detail screen."""
        self.push_screen(UserDetailScreen(username=username))

    def open_user_form(self, username: str | None = None) -> None:
        """Open the user form screen."""
        self.push_screen(UserFormScreen(username=username))

    def confirm(self, title: str, message: str, on_confirm: callable) -> None:
        """Show a confirmation modal."""
        self.push_screen(ConfirmScreen(title=title, message=message, on_confirm=on_confirm))

    def run_update_script(self) -> None:
        """Launch the update script output screen."""
        self.push_screen(UpdateLogScreen())

    def system_create_user(
        self,
        username: str,
        full_name: str,
        ssh_key: str,
        notes: str,
        expiry_mode: str,
        expiry_value: str,
        expiry_at: str | None,
        traffic_limit_bytes: int,
        traffic_reset: str,
    ) -> str:
        """Create a Linux user and record it in the database."""
        from db import Database
        from system import create_user

        created_at = Database.utcnow()
        password = None
        try:
            password = create_user(username, ssh_key or None)
            apply_match_block(username)
            self.traffic.ensure_user(username)
            self.db.create_user_record(
                {
                    "username": username,
                    "full_name": full_name,
                    "created_at": created_at,
                    "is_active": 1,
                    "expiry_mode": expiry_mode,
                    "expiry_value": expiry_value or None,
                    "expiry_at": expiry_at,
                    "traffic_limit_bytes": traffic_limit_bytes,
                    "traffic_used_bytes": 0,
                    "traffic_reset_mode": traffic_reset,
                    "last_traffic_reset": None,
                    "ssh_public_key": ssh_key or None,
                    "notes": notes or None,
                    "deleted_at": None,
                }
            )
            self.db.record_event(username, "create", "User created")
            logger.info("User created: %s", username)
            return password
        except Exception as exc:
            if password is not None:
                try:
                    remove_match_block(username)
                except Exception:
                    pass
                try:
                    delete_user(username)
                except Exception:
                    pass
            raise exc

    def system_update_user(
        self,
        username: str,
        full_name: str,
        ssh_key: str,
        notes: str,
        expiry_mode: str,
        expiry_value: str,
        expiry_at: str | None,
        traffic_limit_bytes: int,
        traffic_reset: str,
    ) -> None:
        """Update Linux user hardening and persist metadata changes."""
        if ssh_key:
            set_authorized_key_for_user(username, ssh_key)
        else:
            clear_authorized_key(username)

        reapply_hardening(username)
        self.db.update_user_record(
            username,
            {
                "full_name": full_name,
                "expiry_mode": expiry_mode,
                "expiry_value": expiry_value or None,
                "expiry_at": expiry_at,
                "traffic_limit_bytes": traffic_limit_bytes,
                "traffic_reset_mode": traffic_reset,
                "ssh_public_key": ssh_key or None,
                "notes": notes or None,
            },
        )
        self.db.record_event(username, "update", "User updated")
        logger.info("User updated: %s", username)

    def system_delete_user(self, username: str) -> None:
        """Delete a Linux user and soft-delete the DB record."""
        remove_match_block(username)
        delete_user(username)
        self.db.soft_delete_user(username)
        self.db.record_event(username, "delete", "User deleted")
        logger.info("User deleted: %s", username)

    def system_toggle_user(self, username: str) -> None:
        """Toggle a user's lock state."""
        user = self.db.get_user(username)
        if not user:
            raise SystemError("User not found")
        if user.is_active:
            lock_user(username)
            self.db.update_user_record(username, {"is_active": 0})
            logger.info("User locked: %s", username)
        else:
            unlock_user(username)
            self.db.update_user_record(username, {"is_active": 1})
            logger.info("User unlocked: %s", username)

    def system_rotate_password(self, username: str) -> str:
        """Rotate the user's password and return it."""
        password = rotate_password(username)
        self.db.record_event(username, "rotate_password", "Password rotated")
        logger.info("Password rotated: %s", username)
        return password

    def system_reset_traffic(self, username: str) -> None:
        """Reset traffic counters and database usage."""
        self.traffic.reset_user(username)
        self.db.reset_traffic(username)
        self.db.record_event(username, "traffic_reset", "Traffic reset")
        logger.info("Traffic reset: %s", username)

    def system_last_login(self, username: str) -> str:
        """Fetch the last login line for display."""
        from system import get_last_login

        return get_last_login(username)
