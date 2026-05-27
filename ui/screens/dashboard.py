from __future__ import annotations

from datetime import datetime, timezone
import platform
from typing import Iterable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Input, Static
from textual.containers import Container

from config import DATETIME_FORMAT, UI_REFRESH_SECONDS
from ui.widgets.status_bar import StatusBar
from ui.widgets.user_table import UserTable


class DashboardScreen(Screen[None]):
    """Main dashboard with user list and shortcuts."""
    BINDINGS = [
        Binding("n", "new_user", "New"),
        Binding("enter", "open_user", "View"),
        Binding("d", "toggle_user", "Toggle"),
        Binding("x", "delete_user", "Delete"),
        Binding("r", "reset_traffic", "Reset traffic"),
        Binding("u", "update", "Update"),
        Binding("/", "filter", "Search"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        """Initialize dashboard state."""
        super().__init__()
        self.filter_text = ""

    def compose(self) -> ComposeResult:
        """Compose dashboard layout."""
        yield Static(id="header")
        yield Input(placeholder="Filter by username or name", id="filter")
        with Container(id="content"):
            yield UserTable()
        yield StatusBar(id="status")

    def on_mount(self) -> None:
        """Initialize refresh timers and table content."""
        self.query_one(Input).display = False
        self.refresh_header()
        self.refresh_table()
        self.set_interval(UI_REFRESH_SECONDS, self.refresh_table)

    def refresh_header(self) -> None:
        """Update the header summary."""
        users = self.app.db.list_users()
        total = len([u for u in users if u.deleted_at is None])
        active = len([u for u in users if u.deleted_at is None and u.is_active])
        traffic_today = sum(
            u.traffic_used_bytes for u in users if u.deleted_at is None
        )
        hostname = platform.node()
        header = self.query_one("#header", Static)
        header.update(
            f"{hostname} | v{self.app.version} | total {total} | active {active} | traffic {self._format_bytes(traffic_today)}"
        )

    def refresh_table(self) -> None:
        """Refresh table rows from the database."""
        users = self.app.db.list_users()
        table = self.query_one(UserTable)
        filtered = self.filter_users(users)
        last_seen = {user.username: self.app.system_last_login(user.username) for user in filtered}
        table.update_users(filtered, last_seen)
        self.refresh_header()

    def filter_users(self, users: Iterable) -> list:
        """Filter users by the active search string."""
        if not self.filter_text:
            return list(users)
        needle = self.filter_text.lower()
        return [
            user
            for user in users
            if needle in user.username.lower() or needle in user.full_name.lower()
        ]

    def action_new_user(self) -> None:
        """Open new user form."""
        self.app.open_user_form()

    def action_open_user(self) -> None:
        """Open selected user detail."""
        table = self.query_one(UserTable)
        username = table.selected_username()
        if username:
            self.app.open_user_detail(username)

    def action_toggle_user(self) -> None:
        """Toggle the selected user state."""
        table = self.query_one(UserTable)
        username = table.selected_username()
        if not username:
            return
        try:
            self.app.system_toggle_user(username)
            self.refresh_table()
        except Exception as exc:
            self.app.show_error(str(exc))

    def action_delete_user(self) -> None:
        """Delete the selected user after confirmation."""
        table = self.query_one(UserTable)
        username = table.selected_username()
        if not username:
            return

        def _confirm() -> None:
            try:
                self.app.system_delete_user(username)
                self.app.show_info("User deleted")
                self.refresh_table()
            except Exception as exc:
                self.app.show_error(str(exc))

        self.app.confirm("Delete user", f"Delete {username}?", _confirm)

    def action_reset_traffic(self) -> None:
        """Reset traffic for the selected user."""
        table = self.query_one(UserTable)
        username = table.selected_username()
        if not username:
            return

        def _confirm() -> None:
            try:
                self.app.system_reset_traffic(username)
                self.app.show_info("Traffic reset")
                self.refresh_table()
            except Exception as exc:
                self.app.show_error(str(exc))

        self.app.confirm("Reset traffic", f"Reset traffic for {username}?", _confirm)

    def action_update(self) -> None:
        """Run updater after confirmation."""
        def _confirm() -> None:
            self.app.run_update_script()

        self.app.confirm("Update", "Run update now?", _confirm)

    def action_filter(self) -> None:
        """Open the filter input."""
        filter_input = self.query_one(Input)
        filter_input.display = True
        filter_input.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Apply filter when input is submitted."""
        self.filter_text = event.value
        event.input.display = False
        self.refresh_table()

    def action_quit(self) -> None:
        """Exit the application."""
        self.app.exit()

    @staticmethod
    def _format_bytes(value: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        size = float(value)
        for unit in units:
            if size < 1024.0:
                return f"{size:.1f}{unit}"
            size /= 1024.0
        return f"{size:.1f}PB"
