"""Enable five touch zones; assignments belong to application input settings."""

from pathlib import Path

from PySide6.QtGui import QIcon

from picer.i18n import tr


class Plugin:
    def activate(self, context):
        self.context = context
        self.action = context.add_command(
            "toggle",
            tr("触控支持"),
            self.toggle,
            icon=QIcon(str(Path(__file__).with_name("icon.svg"))),
            requires_image=False,
            checkable=True,
            checked=context.get_setting("active", True) is True,
        )
        context.set_touch_enabled(self.action.isChecked())

    def toggle(self):
        active = self.action.isChecked()
        self.context.set_touch_enabled(active)
        self.context.set_setting("active", active)

    def deactivate(self):
        pass
