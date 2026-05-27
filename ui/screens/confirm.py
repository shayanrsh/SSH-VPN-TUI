from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Button, Static, RichLog

from config import PROJECT_ROOT
from system import run_script_stream


class ConfirmScreen(ModalScreen[None]):
    """Reusable confirmation modal."""
    def __init__(self, title: str, message: str, on_confirm: callable) -> None:
        """Create a confirmation modal with a callback."""
        super().__init__()
        self.title = title
        self.message = message
        self.on_confirm = on_confirm

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        yield Static(self.title)
        yield Static(self.message)
        with Container(classes="button-row"):
            yield Button("Confirm", id="confirm", variant="error")
            yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle confirm and cancel actions."""
        if event.button.id == "confirm":
            try:
                self.on_confirm()
            except Exception as exc:
                self.app.show_error(str(exc))
            self.dismiss()
        elif event.button.id == "cancel":
            self.dismiss()


class UpdateLogScreen(ModalScreen[None]):
    """Modal screen showing update script output."""
    def compose(self) -> ComposeResult:
        """Compose the update log layout."""
        yield Static("Update ssh-vpn-admin")
        yield RichLog(id="log", highlight=False)
        with Container(classes="button-row"):
            yield Button("Close", id="close")

    def on_mount(self) -> None:
        """Run the update script when mounted."""
        self._run_update()

    def _run_update(self) -> None:
        """Execute update script and stream logs."""
        log = self.query_one(RichLog)
        script = PROJECT_ROOT / "update.sh"
        if not script.exists():
            log.write("update.sh not found")
            return
        for line in run_script_stream(script):
            log.write(line)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Close the modal when requested."""
        if event.button.id == "close":
            self.dismiss()
