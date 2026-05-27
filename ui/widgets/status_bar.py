from __future__ import annotations

from textual.widgets import Static


class StatusBar(Static):
    """Bottom status bar with shortcut hints."""
    def on_mount(self) -> None:
        """Render default shortcuts."""
        self.update("N New | Enter View | D Toggle | X Delete | R Reset | U Update | / Search | Q Quit")
