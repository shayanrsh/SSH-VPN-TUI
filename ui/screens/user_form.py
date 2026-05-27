from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static, TextArea

from config import DATE_FORMAT, DATETIME_FORMAT, ExpiryMode, ResetMode
from system import user_exists, validate_username


KEY_RE = re.compile(r"^(ssh-rsa|ssh-ed25519)\s+")


@dataclass
class FormField:
    """Container for form input and error display."""
    input: Input | TextArea | Select
    error: Static


class UserFormScreen(ModalScreen[None]):
    """Modal screen for creating or editing users."""
    def __init__(self, username: str | None = None) -> None:
        """Initialize the form for create or edit mode."""
        super().__init__()
        self.username = username

    def compose(self) -> ComposeResult:
        """Compose the form layout."""
        yield Static("User form", id="header")
        with Container():
            yield Label("Username", classes="form-label")
            yield Input(id="username")
            yield Static("", classes="error-text", id="username_error")

            yield Label("Full name", classes="form-label")
            yield Input(id="full_name")
            yield Static("", classes="error-text", id="full_name_error")

            yield Label("SSH public key", classes="form-label")
            yield Input(id="ssh_key")
            yield Static("", classes="error-text", id="ssh_key_error")

            yield Label("Notes", classes="form-label")
            yield TextArea(id="notes")
            yield Static("", classes="error-text", id="notes_error")

            yield Label("Expiry mode", classes="form-label")
            yield Select(
                options=[
                    ("Unlimited", ExpiryMode.UNLIMITED),
                    ("Exact date", ExpiryMode.DATE),
                    ("Days from now", ExpiryMode.DAYS),
                    ("Weeks from now", ExpiryMode.WEEKS),
                    ("Months from now", ExpiryMode.MONTHS),
                ],
                id="expiry_mode",
                value=ExpiryMode.UNLIMITED,
            )
            yield Static("", classes="error-text", id="expiry_mode_error")

            yield Label("Expiry value", classes="form-label")
            yield Input(id="expiry_value")
            yield Static("", classes="error-text", id="expiry_value_error")

            yield Label("Traffic limit", classes="form-label")
            yield Input(id="traffic_limit")
            yield Static("", classes="error-text", id="traffic_limit_error")

            yield Label("Traffic unit", classes="form-label")
            yield Select(
                options=[("Unlimited", "unlimited"), ("MB", "mb"), ("GB", "gb")],
                id="traffic_unit",
                value="unlimited",
            )
            yield Static("", classes="error-text", id="traffic_unit_error")

            yield Label("Reset schedule", classes="form-label")
            yield Select(
                options=[
                    ("Never", ResetMode.UNLIMITED),
                    ("Daily", ResetMode.DAILY),
                    ("Weekly", ResetMode.WEEKLY),
                    ("Monthly", ResetMode.MONTHLY),
                ],
                id="traffic_reset",
                value=ResetMode.UNLIMITED,
            )
            yield Static("", classes="error-text", id="traffic_reset_error")

        with Container(classes="button-row"):
            yield Button("Save", id="save", variant="primary")
            yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        """Populate fields when editing an existing user."""
        if self.username:
            user = self.app.db.get_user(self.username)
            if user:
                self.query_one("#username", Input).value = user.username
                self.query_one("#username", Input).disabled = True
                self.query_one("#full_name", Input).value = user.full_name
                self.query_one("#ssh_key", Input).value = user.ssh_public_key or ""
                self.query_one("#notes", TextArea).text = user.notes or ""
                self.query_one("#expiry_mode", Select).value = user.expiry_mode
                self.query_one("#expiry_value", Input).value = user.expiry_value or ""
                if user.traffic_limit_bytes > 0:
                    self.query_one("#traffic_unit", Select).value = "gb"
                    self.query_one("#traffic_limit", Input).value = str(
                        int(user.traffic_limit_bytes / (1024**3))
                    )
                else:
                    self.query_one("#traffic_unit", Select).value = "unlimited"
                self.query_one("#traffic_reset", Select).value = user.traffic_reset_mode

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle save and cancel actions."""
        if event.button.id == "cancel":
            self.dismiss()
            return
        if event.button.id == "save":
            self._save()

    def _clear_errors(self) -> None:
        """Clear inline error messages."""
        for error in self.query(".error-text"):
            error.update("")

    def _set_error(self, field_id: str, message: str) -> None:
        """Set an inline error message for a field."""
        self.query_one(f"#{field_id}", Static).update(message)

    def _save(self) -> None:
        """Validate and submit the form."""
        self._clear_errors()
        username = self.query_one("#username", Input).value.strip()
        full_name = self.query_one("#full_name", Input).value.strip()
        ssh_key = self.query_one("#ssh_key", Input).value.strip()
        notes = self.query_one("#notes", TextArea).text.strip()
        expiry_mode = self.query_one("#expiry_mode", Select).value
        expiry_value = self.query_one("#expiry_value", Input).value.strip()
        traffic_limit = self.query_one("#traffic_limit", Input).value.strip()
        traffic_unit = self.query_one("#traffic_unit", Select).value
        traffic_reset = self.query_one("#traffic_reset", Select).value

        errors = False
        if not self.username and not username:
            self._set_error("username_error", "Username is required")
            errors = True
        if not self.username:
            try:
                validate_username(username)
            except Exception as exc:
                self._set_error("username_error", str(exc))
                errors = True
            if user_exists(username):
                self._set_error("username_error", "Username already exists")
                errors = True
        if ssh_key and not KEY_RE.match(ssh_key):
            self._set_error("ssh_key_error", "Invalid SSH key format")
            errors = True

        expiry_at = None
        if expiry_mode != ExpiryMode.UNLIMITED:
            try:
                expiry_at = self._compute_expiry(expiry_mode, expiry_value)
            except ValueError as exc:
                self._set_error("expiry_value_error", str(exc))
                errors = True

        traffic_limit_bytes = 0
        if traffic_unit != "unlimited":
            try:
                value = int(traffic_limit)
                if value <= 0:
                    raise ValueError("Traffic limit must be > 0")
                factor = 1024**2 if traffic_unit == "mb" else 1024**3
                traffic_limit_bytes = value * factor
            except ValueError:
                self._set_error("traffic_limit_error", "Invalid traffic limit")
                errors = True

        if errors:
            return

        if self.username:
            self._update_user(
                username,
                full_name,
                ssh_key,
                notes,
                expiry_mode,
                expiry_value,
                expiry_at,
                traffic_limit_bytes,
                traffic_reset,
            )
        else:
            self._create_user(
                username,
                full_name,
                ssh_key,
                notes,
                expiry_mode,
                expiry_value,
                expiry_at,
                traffic_limit_bytes,
                traffic_reset,
            )

    def _compute_expiry(self, mode: str, value: str) -> str:
        """Compute an expiry timestamp from mode and input value."""
        now = datetime.now(timezone.utc)
        if mode == ExpiryMode.DATE:
            dt = datetime.strptime(value, DATE_FORMAT).replace(tzinfo=timezone.utc)
        else:
            count = int(value)
            if count < 1:
                raise ValueError("Expiry must be at least 1")
            delta = timedelta(days=count)
            if mode == ExpiryMode.WEEKS:
                delta = timedelta(weeks=count)
            if mode == ExpiryMode.MONTHS:
                delta = timedelta(days=count * 30)
            dt = now + delta
        if dt <= now:
            raise ValueError("Expiry must be in the future")
        return dt.strftime(DATETIME_FORMAT)

    def _create_user(
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
        """Create a new user using app services."""
        try:
            password = self.app.system_create_user(
                username,
                full_name,
                ssh_key,
                notes,
                expiry_mode,
                expiry_value,
                expiry_at,
                traffic_limit_bytes,
                traffic_reset,
            )
            self.app.show_info(f"Password for {username}: {password}")
            self.dismiss()
        except Exception as exc:
            self.app.show_error(str(exc))

    def _update_user(
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
        """Update a user using app services."""
        try:
            self.app.system_update_user(
                username,
                full_name,
                ssh_key,
                notes,
                expiry_mode,
                expiry_value,
                expiry_at,
                traffic_limit_bytes,
                traffic_reset,
            )
            self.app.show_info("User updated")
            self.dismiss()
        except Exception as exc:
            self.app.show_error(str(exc))
