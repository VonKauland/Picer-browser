"""Application-shipped opt-in temporary editing panel."""

from picer.editing.panel import EditingPanel


class Plugin:
    def activate(self, context):
        self.panel = EditingPanel(context)
        context.add_panel(self.panel, area="right")

    def deactivate(self):
        self.panel.shutdown()
