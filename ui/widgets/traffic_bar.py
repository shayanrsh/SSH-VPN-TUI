from __future__ import annotations

from textual.widgets import ProgressBar, Static
from textual.containers import Container
from textual.app import ComposeResult


class TrafficBar(Container):
    """Traffic usage progress widget."""
    def compose(self) -> ComposeResult:
        """Compose progress bar widgets."""
        yield Static("Traffic usage")
        yield ProgressBar(total=100, id="bar")

    def update_usage(self, used: int, limit: int) -> None:
        """Update progress bar based on usage and limit."""
        bar = self.query_one("#bar", ProgressBar)
        if limit <= 0:
            bar.total = 100
            bar.progress = 0
        else:
            bar.total = limit
            bar.progress = min(used, limit)
