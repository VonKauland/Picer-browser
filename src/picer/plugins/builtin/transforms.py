"""Core editing functionality implemented against the public plugin SDK."""

from PySide6.QtGui import QImage

from picer.plugins.api import PluginContext


class Plugin:
    def __init__(self, plugin_id: str = "picer.transforms") -> None:
        self.plugin_id = plugin_id

    def activate(self, context: PluginContext) -> None:
        self.context = context
        if self.plugin_id == "picer.transforms":
            context.add_command("rotate", "顺时针旋转", self.rotate, shortcut="Ctrl+R", menu="编辑")
        elif self.plugin_id == "picer.mirror":
            context.add_command("mirror", "水平翻转", self.mirror, menu="编辑")
        else:
            context.add_command("grayscale", "灰度预览", self.grayscale, menu="编辑")

    def rotate(self) -> None:
        self.context.rotate_image()

    def mirror(self) -> None:
        self.context.replace_image(self.context.image().mirrored(True, False))

    def grayscale(self) -> None:
        self.context.replace_image(
            self.context.image().convertToFormat(QImage.Format.Format_Grayscale8)
        )

    def deactivate(self) -> None:
        """No resources are owned outside the context."""
