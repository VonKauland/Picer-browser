"""The public API available to trusted Python plugins."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QThread
from PySide6.QtGui import QImage

if TYPE_CHECKING:
    from picer.plugins.manager import PluginManager

API_VERSION = 1
PERMISSIONS = {"ui.commands", "image.read", "image.modify", "events.subscribe", "settings", "tasks"}


class PluginError(Exception):
    """A plugin operation cannot be completed."""


@dataclass(frozen=True)
class ImageEvent:
    """Image metadata snapshot; pixels are requested separately through the context."""

    path: Path | None
    width: int
    height: int
    reason: str


class PluginContext:
    """Per-plugin host facade. Permissions govern API use, not Python execution."""

    def __init__(self, manager: "PluginManager", plugin_id: str) -> None:
        self._manager = manager
        self.plugin_id = plugin_id
        self._active = True

    def _check(self, permission: str) -> None:
        if QThread.currentThread() != self._manager.host.thread():
            raise PluginError("插件上下文只能在 GUI 线程使用")
        if not self._active:
            raise PluginError("插件上下文已停用")
        if permission not in self._manager.records[self.plugin_id].manifest.permissions:
            raise PluginError(f"插件未声明权限：{permission}")

    def add_command(
        self,
        command_id: str,
        label: str,
        callback: Callable[[], None],
        *,
        shortcut: str = "",
        requires_image: bool = True,
        menu: str = "插件",
    ) -> None:
        self._check("ui.commands")
        self._manager.add_command(
            self.plugin_id, command_id, label, callback, shortcut, requires_image, menu
        )

    def current_path(self) -> Path | None:
        self._check("image.read")
        return self._manager.host.current_path

    def image(self) -> QImage:
        self._check("image.read")
        return self._manager.host.view.image_item.pixmap().toImage().copy()

    def replace_image(self, image: QImage) -> None:
        self._check("image.modify")
        if not isinstance(image, QImage) or image.isNull():
            raise PluginError("必须提供有效的 QImage")
        if self._manager.host.current_path is None:
            raise PluginError("尚未打开图片")
        self._manager.host.replace_image(image)

    def subscribe(self, event: str, callback: Callable[[ImageEvent], None]) -> None:
        self._check("events.subscribe")
        if event not in {"image.opened", "image.changed"}:
            raise PluginError(f"未知事件：{event}")
        self._manager.subscribe(self.plugin_id, event, callback)

    def get_setting(self, key: str, default: Any = None) -> Any:
        self._check("settings")
        return self._manager.get_setting(self.plugin_id, key, default)

    def set_setting(self, key: str, value: Any) -> None:
        self._check("settings")
        self._manager.set_setting(self.plugin_id, key, value)

    def run_task(self, work: Callable, on_result: Callable, *, image_bound: bool = True):
        """Return a cancellation token; stale image results are discarded by default."""
        self._check("tasks")
        return self._manager.run_task(self, work, on_result, image_bound)

    def notify(self, message: str) -> None:
        if QThread.currentThread() != self._manager.host.thread():
            raise PluginError("通知只能在 GUI 线程使用")
        if not self._active:
            raise PluginError("插件上下文已停用")
        self._manager.host.plugin_notification(message)
