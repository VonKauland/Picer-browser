"""An external plugin that also works in the packaged EXE."""

from picer.plugins import PluginContext


class Plugin:
    def activate(self, context: PluginContext) -> None:
        self.context = context
        context.add_command("negative", "负片预览", self.negative)
        context.add_command("count", "查看打开图片数", self.show_count, requires_image=False)
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

    def show_count(self) -> None:
        self.context.notify(
            f"本插件累计观察到 {self.context.get_setting('opened_count', 0)} 次图片打开。"
        )

    def deactivate(self) -> None:
        """Context contributions are automatically removed by Picer."""
