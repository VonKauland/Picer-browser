"""An external plugin that also works in the packaged EXE."""

from picer.i18n import tr
from picer.plugins import PluginContext


class Plugin:
    def activate(self, context: PluginContext) -> None:
        self.context = context
        context.add_command("negative", tr("负片预览"), self.negative)
        context.subscribe("image.opened", self.on_opened)

    def negative(self) -> None:
        image = self.context.image()

        def invert(token):
            token.checkpoint()
            image.invertPixels()
            return image

        self.context.run_task(invert, self.context.replace_image)

    def on_opened(self, event) -> None:
        count = self.context.get_setting("opened_count", 0)
        self.context.set_setting("opened_count", count + 1)

    def deactivate(self) -> None:
        """Context contributions are automatically removed by Picer."""
