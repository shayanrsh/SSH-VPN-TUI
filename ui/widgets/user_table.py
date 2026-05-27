from __future__ import annotations

from datetime import datetime, timezone

from textual.widgets import DataTable

from config import DATETIME_FORMAT


class UserTable(DataTable):
    """Data table for user overview."""
    def __init__(self) -> None:
        """Initialize table columns."""
        super().__init__(zebra_stripes=True)
        self.add_columns(
            "Username",
            "Full name",
            "Status",
            "Traffic",
            "Expiry",
            "Last seen",
        )

    def update_users(self, users: list, last_seen: dict[str, str] | None = None) -> None:
        """Replace table rows with user records."""
        self.clear()
        last_seen = last_seen or {}
        for user in users:
            status = self._status(user)
            traffic = self._traffic(user)
            expiry = user.expiry_at or "Unlimited"
            seen = last_seen.get(user.username, "N/A")
            self.add_row(
                user.username,
                user.full_name,
                status,
                traffic,
                expiry,
                seen,
                key=user.username,
            )
            style = self._style_for_status(user, status)
            if style:
                self.set_row_style(user.username, style)

    def selected_username(self) -> str | None:
        """Return the username for the selected row."""
        if self.cursor_row is None:
            return None
        row_key = self.get_row_key(self.cursor_row)
        return str(row_key) if row_key else None

    def _status(self, user) -> str:
        """Return status string for display."""
        if user.is_active == 0:
            return "disabled"
        if user.expiry_at:
            expiry = datetime.fromisoformat(user.expiry_at)
            if expiry <= datetime.now(timezone.utc):
                return "expired"
        return "active"

    def _traffic(self, user) -> str:
        """Return traffic usage string for display."""
        if user.traffic_limit_bytes == 0:
            return f"{user.traffic_used_bytes} / unlimited"
        return f"{user.traffic_used_bytes} / {user.traffic_limit_bytes}"

    def _style_for_status(self, user, status: str) -> str:
        """Return a row style string based on status thresholds."""
        if status in {"expired", "disabled"}:
            return "red"
        if status == "active":
            if self._expiring_soon(user) or self._traffic_high(user):
                return "yellow"
            return "green"
        return ""

    def _expiring_soon(self, user) -> bool:
        """Return True if the user expires within 7 days."""
        if not user.expiry_at:
            return False
        expiry = datetime.fromisoformat(user.expiry_at)
        days = (expiry - datetime.now(timezone.utc)).days
        return days <= 7

    def _traffic_high(self, user) -> bool:
        """Return True if traffic usage exceeds 80 percent."""
        if user.traffic_limit_bytes <= 0:
            return False
        return user.traffic_used_bytes / user.traffic_limit_bytes >= 0.8
