"""The public API available to trusted Python plugins."""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QEvent, Qt, QThread
from PySide6.QtGui import QIcon, QImage, QKeySequence
from PySide6.QtWidgets import QWidget

from picer.media_types import AnimationState
from picer.metadata import inspect_image

if TYPE_CHECKING:
    from picer.plugins.manager import PluginManager

API_VERSION = 1
PERMISSIONS = {
    "ui.commands",
    "ui.panels",
    "image.read",
    "image.annotations",
    "image.navigate",
    "image.layout",
    "input.touch",
    "image.modify",
    "events.subscribe",
    "settings",
    "tasks",
    "cache",
}


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
        icon: QIcon | None = None,
        checkable: bool = False,
        checked: bool = False,
    ):
        self._check("ui.commands")
        action = self._manager.add_command(
            self.plugin_id, command_id, label, callback, shortcut, requires_image, menu, icon
        )
        action.setCheckable(checkable)
        action.setChecked(checked)
        return action

    def set_double_page(self, enabled: bool):
        self._check("image.layout")
        if type(enabled) is not bool:
            raise PluginError("双页状态必须为布尔值")
        self._manager.host.double_page.set_enabled(self.plugin_id, enabled)

    def set_touch_enabled(self, enabled: bool):
        self._check("input.touch")
        if type(enabled) is not bool:
            raise PluginError("触控状态必须为布尔值")
        owners = self._manager.host.touch_owners
        owners.add(self.plugin_id) if enabled else owners.discard(self.plugin_id)
        host = self._manager.host
        if not owners and hasattr(host, "inputs"):
            host.inputs.touch_start = None

    def add_panel(self, widget: QWidget, *, area: str = "right"):
        """Register the component's single dockable panel on the GUI thread."""
        self._check("ui.panels")
        return self._manager.add_panel(self.plugin_id, widget, area)

    def bind_panel_operation(self, name: str, callback: Callable) -> None:
        """Provide a core browser/slideshow operation; automatically revoked on disable."""
        self._check("ui.panels")
        self._manager.bind_panel_operation(self.plugin_id, name, callback)

    def handle_browser_key(self, event) -> bool:
        """Respect configurable parent/selected keys before item-view defaults."""
        self._check("ui.panels")
        host = self._manager.host
        if not hasattr(host, "inputs"):
            return False
        for key in ("打开父级文件夹", "打开选中文件夹"):
            action = host.shortcut_actions[key]
            sequence = QKeySequence(event.keyCombination())
            if event.key() == Qt.Key.Key_Enter:
                sequence = QKeySequence(event.modifiers().value | Qt.Key.Key_Return.value)
            if action.isEnabled() and sequence in action.shortcuts():
                if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
                    action.trigger()
                event.accept()
                return True
        return False

    def frosted_surface(self, parent=None, *, popup=False):
        self._check("ui.panels")
        from picer.host_style import PLUGIN_STYLE
        from picer.panels import GlassSurface

        surface = GlassSurface(self._manager.host.glass, parent, popup=popup)
        surface.setStyleSheet(PLUGIN_STYLE)
        return surface

    def accent_color(self) -> str:
        """User accent for opt-in panel UI, independent of the active skin."""
        self._check("ui.panels")
        from picer.theme import COLORS

        return self._manager.host.app_preferences.get("accent_color") or COLORS["accent"]

    def add_settings(self, fields, on_apply: Callable[[], None]) -> None:
        self._check("settings")
        self._manager.add_settings(self.plugin_id, fields, on_apply)

    def add_settings_page(self, factory):
        """Add a custom QWidget with save/reset methods to component settings."""
        self._check("settings")
        if not callable(factory) or self.plugin_id in self._manager.settings_forms:
            raise PluginError("设置页面只能注册一次，且须提供控件工厂")
        self._manager.settings_forms[self.plugin_id] = ((), lambda: None)
        self._manager.settings_widgets[self.plugin_id] = factory

    def create_editing_session(self):
        """Create one revocable, host-owned temporary editing session."""
        for permission in ("ui.panels", "image.read", "image.modify", "tasks"):
            self._check(permission)
        if self.plugin_id in self._manager.editing_sessions:
            raise PluginError("每个组件只能创建一个临时编辑会话")
        from picer.editing.session import EditingSession

        session = EditingSession(self, self._manager.host)
        self._manager.editing_sessions[self.plugin_id] = session
        return session

    def show_settings(self) -> None:
        self._check("settings")
        self._manager.show_settings(self.plugin_id)

    def image_annotations(self):
        """Return an independent snapshot of this installation's recorded photo marks."""
        self._check("image.read")
        return self._manager.annotations.snapshot()

    def image_annotation(self, path):
        """Look up one mark without copying the device-wide index."""
        self._check("image.read")
        import os

        if not isinstance(path, (str, Path)):
            raise PluginError("图片路径无效")
        value = self._manager.annotations.values.get(os.path.abspath(str(path)), (None, ""))
        return {"rating": value[0], "color": value[1]}

    def set_image_annotation(self, path, *, rating=None, color=None):
        """Persist half-star/color marks without modifying the original image."""
        self._check("image.read")
        self._check("image.annotations")
        if not isinstance(path, (str, Path)):
            raise PluginError("图片路径无效")
        try:
            changed = self._manager.annotations.set(path, rating=rating, color=color)
        except (ValueError, OSError, sqlite3.Error) as error:
            raise PluginError(str(error)) from error
        if changed:
            for owner, callback in list(self._manager.subscribers.get("annotations.changed", [])):
                self._manager._invoke(owner, callback, {"path": str(path)})

    def readable_suffixes(self) -> frozenset[str]:
        """Effective user-selected image formats; decoding capabilities are unchanged."""
        self._check("image.read")
        return frozenset(self._manager.host.supported_suffixes)

    def image_paths(self) -> tuple[Path, ...]:
        self._check("image.read")
        return self._manager.host.image_path_snapshot

    def image_index(self) -> int:
        """Current zero-based folder index, or -1 before an image is shown."""
        self._check("image.read")
        host = self._manager.host
        return host.path_positions.get(host.current_path, -1)

    def open_image(self, path: Path) -> bool:
        self._check("image.navigate")
        return self._manager.host.open_image(Path(path))

    def navigate(self, offset: int) -> None:
        self._check("image.navigate")
        if type(offset) is not int:
            raise PluginError("导航偏移必须为整数")
        self._manager.host.navigate(offset)

    def jump_to(self, index: int) -> None:
        self._check("image.navigate")
        paths = self._manager.host.paths
        if type(index) is not int or not 0 <= index < len(paths):
            raise PluginError("图片位置超出范围")
        self._manager.host.open_image(paths[index])

    def request_metadata(self, on_result: Callable):
        self._check("image.read")
        self._check("tasks")
        path = self._manager.host.current_path
        if path is None:
            return None
        return self.run_task(lambda token: inspect_image(path, token), on_result)

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

    def rotate_image(self) -> None:
        """Rotate the viewer while preserving refinement and animated playback."""
        self._check("image.modify")
        self._manager.host.rotate_image()

    def subscribe(
        self, event: str, callback: Callable[[ImageEvent | AnimationState | dict[str, str]], None]
    ) -> None:
        self._check("events.subscribe")
        if event not in {
            "image.opened",
            "image.changed",
            "animation.changed",
            "appearance.changed",
            "annotations.changed",
        }:
            raise PluginError(f"未知事件：{event}")
        self._manager.subscribe(self.plugin_id, event, callback)

    def animation_state(self) -> AnimationState:
        """Immutable GIF/WebP playback snapshot; inactive for still images."""
        self._check("image.read")
        return self._manager.host.animation.state

    def seek_animation(self, frame: int) -> None:
        self._check("image.navigate")
        state = self._manager.host.animation.state
        if type(frame) is not int or not state.active or not 0 <= frame < state.count:
            raise PluginError("动画帧位置超出范围")
        self._manager.host.animation.seek(frame)

    def toggle_animation(self) -> None:
        self._check("image.navigate")
        self._manager.host.animation.toggle()

    def get_setting(self, key: str, default: Any = None) -> Any:
        self._check("settings")
        return self._manager.get_setting(self.plugin_id, key, default)

    def set_setting(self, key: str, value: Any) -> None:
        self._check("settings")
        self._manager.set_setting(self.plugin_id, key, value)

    def thumbnail(self) -> QImage:
        """Return the cached original-image thumbnail, before plugin edits."""
        self._check("image.read")
        return self._manager.host.current_thumbnail.copy()

    def request_thumbnail(self, path, on_result: Callable, *, edge=128, priority=False):
        """Shared asynchronous thumbnail; returns a cancel token, GUI callback gets QImage.

        Not bound to the viewer image revision. Disable/revoke cancels delivery.
        All sizes reuse one auto-oriented 256px master in cache/thumbnails.
        """
        self._check("image.read")
        self._check("tasks")
        if not isinstance(path, (str, Path)) or not callable(on_result):
            raise PluginError("缩略图路径或回调无效")
        if type(edge) is not int or not 16 <= edge <= 256 or type(priority) is not bool:
            raise PluginError("缩略图尺寸须为 16 至 256 像素")
        return self._manager.request_thumbnail(self, path, on_result, edge, priority)

    def cache_directory(self) -> Path:
        """Private writable cache namespace, separate from persistent settings."""
        self._check("cache")
        directory = self._manager.paths.cache / "plugins" / self.plugin_id
        directory.mkdir(parents=True, exist_ok=True)
        return directory

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
