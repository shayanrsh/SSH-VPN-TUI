from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Button, Static

from ui.widgets.traffic_bar import TrafficBar


class UserDetailScreen(Screen[None]):
    """Detailed view for a single user."""
    def __init__(self, username: str) -> None:
        """Initialize with the target username."""
        super().__init__()
        self.username = username

    def compose(self) -> ComposeResult:
        """Compose the detail layout."""
        yield Static("User detail", id="header")
        with Container(id="content"):
            yield Static(id="summary")
            yield TrafficBar(id="traffic")
            yield Static(id="timeline")
            yield Static(id="last_login")
        with Container(classes="button-row"):
            yield Button("Enable/Disable", id="toggle")
            yield Button("Edit", id="edit")
            yield Button("Reset traffic", id="reset")
            yield Button("Rotate password", id="rotate")
            yield Button("Delete", id="delete", variant="error")
            yield Button("Back", id="back")

    def on_mount(self) -> None:
        """Populate detail data on mount."""
        self.refresh_view()

    def refresh_view(self) -> None:
        """Refresh the displayed user data."""
        user = self.app.db.get_user(self.username)
        if not user:
            self.app.show_error("User not found")
            self.app.pop_screen()
            return
        summary = self.query_one("#summary", Static)
        summary.update(
            f"Username: {user.username}\n"
            f"Name: {user.full_name}\n"
            f"Active: {bool(user.is_active)}\n"
            f"Expiry: {user.expiry_at or 'Unlimited'}\n"
            f"Traffic: {user.traffic_used_bytes} / {user.traffic_limit_bytes or 'Unlimited'}\n"
            f"Notes: {user.notes or ''}"
        )

        traffic = self.query_one(TrafficBar)
        traffic.update_usage(user.traffic_used_bytes, user.traffic_limit_bytes)

        timeline = self.query_one("#timeline", Static)
        timeline.update(
            f"Created: {user.created_at}\n"
            f"Last reset: {user.last_traffic_reset or 'Never'}"
        )

        last_login = self.query_one("#last_login", Static)
        last_login.update(self.app.system_last_login(user.username))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button actions."""
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "edit":
            self.app.open_user_form(self.username)
        elif event.button.id == "toggle":
            self._toggle()
        elif event.button.id == "reset":
            self._reset_traffic()
        elif event.button.id == "rotate":
            self._rotate_password()
        elif event.button.id == "delete":
            self._delete_user()

    def _toggle(self) -> None:
        """Toggle user lock state."""
        try:
            self.app.system_toggle_user(self.username)
            self.refresh_view()
        except Exception as exc:
            self.app.show_error(str(exc))

    def _reset_traffic(self) -> None:
        """Reset traffic for this user."""
        try:
            self.app.system_reset_traffic(self.username)
            self.app.show_info("Traffic reset")
            self.refresh_view()
        except Exception as exc:
            self.app.show_error(str(exc))

    def _rotate_password(self) -> None:
        """Rotate the user password."""
        try:
            password = self.app.system_rotate_password(self.username)
            self.app.show_info(f"New password: {password}")
        except Exception as exc:
            self.app.show_error(str(exc))

    def _delete_user(self) -> None:
        """Delete the user after confirmation."""
        def _confirm() -> None:
            try:
                self.app.system_delete_user(self.username)
                self.app.show_info("User deleted")
                self.app.pop_screen()
            except Exception as exc:
                self.app.show_error(str(exc))

        self.app.confirm("Delete user", f"Delete {self.username}?", _confirm)
