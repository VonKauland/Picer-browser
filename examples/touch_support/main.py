"""Enable five touch zones; assignments belong to application input settings."""


class Plugin:
    def activate(self, context):
        self.context = context
        self.action = context.add_command(
            "toggle",
            "触控支持",
            self.toggle,
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
