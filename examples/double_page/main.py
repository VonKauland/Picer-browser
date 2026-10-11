"""Toggle the host's asynchronous two-page presentation."""

from pathlib import Path

from PySide6.QtGui import QIcon


class Plugin:
    def activate(self, context):
        self.context = context
        self.action = context.add_command(
            "toggle",
            "显示双页",
            self.toggle,
            icon=QIcon(str(Path(__file__).with_name("icon.svg"))),
            requires_image=False,
            checkable=True,
            checked=context.get_setting("active", False) is True,
        )
        context.set_double_page(self.action.isChecked())

    def toggle(self):
        active = self.action.isChecked()
        self.context.set_double_page(active)
        self.context.set_setting("active", active)

    def deactivate(self):
        pass
