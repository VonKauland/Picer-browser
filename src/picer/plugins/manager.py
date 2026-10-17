"""Plugin discovery, lifecycle, contributions and persistent state."""

import copy
import importlib
import importlib.util
import json
import logging
import re
import shutil
import sys
import tempfile
import types
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path, PurePosixPath
from typing import Any

from PySide6.QtCore import QObject, Qt, QThreadPool, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import QDockWidget, QWidget

from picer.annotations import AnnotationStore
from picer.host_style import PLUGIN_STYLE
from picer.panels import DOCK_AREAS, DockTitleSpacer, ProgressDock, dock_surface, saved_layout
from picer.plugins.api import API_VERSION, ImageEvent, PluginContext, PluginError
from picer.plugins.builtin.transforms import Plugin as Transforms
from picer.plugins.manifest import Manifest
from picer.plugins.settings import SettingField
from picer.plugins.skins import COLORS, load_skin
from picer.plugins.tasks import TaskCancelled, Worker
from picer.theme import accent_style


@dataclass
class PluginRecord:
    manifest: Manifest
    directory: Path | None = None
    state: str = "disabled"
    error: str = ""
    instance: Any = None
    context: PluginContext | None = None
    namespace: str = ""


class PluginManager(QObject):
    """Trusted in-process extensions with transactional activation and cleanup."""

    changed = Signal()

    def __init__(
        self, host, root: Path, *, load_external: bool = True, load_examples: bool = True
    ) -> None:
        super().__init__(host)
        self.host = host
        self.root = root.resolve()
        self.paths = host.paths_layout
        self.directory = self.paths.plugins
        self.state_file = self.paths.config / "plugins.json"
        self.log_file = self.paths.logs / "plugins.log"
        self.records: dict[str, PluginRecord] = {}
        self.commands: dict[str, QAction] = {}
        self.panels: dict[str, QDockWidget] = {}
        self.panel_operations = {}
        self.settings_forms = {}
        self.settings_widgets = {}
        self.editing_sessions = {}
        self._panel_transition = False
        self._fullscreen = host.isFullScreen()
        self.subscribers: dict[str, list[tuple[str, Callable]]] = {}
        self.diagnostics: list[str] = [self.paths.notice] if self.paths.notice else []
        self._dispatching = False
        self._closed = False
        self.jobs: dict[int, Worker] = {}
        self._next_job = 0
        self.thumbnail_requests = {}
        self.logger = logging.getLogger(f"picer.plugins.{id(self)}")
        self.logger.propagate = False
        self.log_handler = None
        self.preferences: dict[str, Any] = {"enabled": {}, "settings": {}, "ui": {}}
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            if self.state_file.exists():
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or any(
                    not isinstance(data.get(key, {}), dict) for key in ("enabled", "settings", "ui")
                ):
                    raise ValueError("配置结构无效")
                self.preferences = {key: data.get(key, {}) for key in ("enabled", "settings", "ui")}
        except (OSError, ValueError, UnicodeError) as error:
            self.diagnostics.append(f"配置读取失败：{error}")
        self.annotations = AnnotationStore(
            self.paths.config / "annotations.sqlite3",
            self.preferences["settings"].get("example.info", {}),
        )
        if self.annotations.error:
            self.diagnostics.append("图片标注库：" + self.annotations.error)
        # Restore core bindings before loading plugins that may use a freed shortcut.
        self.host.restore_shortcuts(
            self.preferences["ui"].get("shortcuts", {}),
            self.preferences["ui"].get("input_bindings"),
        )
        try:
            self.log_handler = RotatingFileHandler(
                self.log_file, maxBytes=256 * 1024, backupCount=2, encoding="utf-8"
            )
            self.logger.addHandler(self.log_handler)
        except OSError as error:
            self.diagnostics.append(f"插件日志无法写入：{error}")
        # Preserve the old multi-function built-in's enable preference during migration.
        for plugin_id in ("picer.mirror", "picer.grayscale"):
            self.preferences["enabled"].setdefault(
                plugin_id, self.preferences["enabled"].get("picer.transforms", True) is True
            )
        for plugin_id, label in (
            ("picer.transforms", "顺时针旋转"),
            ("picer.mirror", "水平翻转"),
            ("picer.grayscale", "灰度预览"),
        ):
            builtin = Manifest(
                id=plugin_id,
                name=label,
                version="1.1.0",
                api_version=API_VERSION,
                entrypoint="transforms:Plugin",
                description="仅修改当前预览，不修改原文件。",
                author="Picer",
                permissions=("ui.commands", "image.read", "image.modify"),
            )
            self.records[builtin.id] = PluginRecord(builtin)
        if load_external:
            self.discover()
            if load_examples:
                from picer.bundles import seed_examples

                seed_examples(self)
        # Newly installed external plugins never execute until explicitly enabled.
        for plugin_id, record in list(self.records.items()):
            enabled = self.preferences["enabled"].get(plugin_id, record.directory is None)
            if enabled is True:
                try:
                    self.enable(plugin_id)
                except PluginError as error:
                    record.error = str(error)
                    record.state = (
                        "error" if record.manifest.api_version == API_VERSION else "incompatible"
                    )
                    self.preferences["enabled"][plugin_id] = False
        self._save()

    def discover(self) -> None:
        """Read manifests only; do not execute plugin code during discovery."""
        for base in (self.directory, self.paths.skins):
            if not base.exists():
                continue
            try:
                directories = sorted(base.iterdir())
            except OSError as error:
                self.diagnostics.append(str(error))
                continue
            for directory in directories:
                if (
                    not directory.is_dir()
                    or directory.is_symlink()
                    or directory.name.startswith(".")
                ):
                    continue
                try:
                    manifest = Manifest.read(directory / "manifest.json")
                    if (manifest.type == "skin") != (base == self.paths.skins):
                        raise PluginError("组件存储目录与类型不匹配，请重新安装")
                    if manifest.id in self.records:
                        raise PluginError(f"重复插件 id：{manifest.id}")
                    record = PluginRecord(manifest, directory=directory)
                    if manifest.api_version != API_VERSION:
                        record.state = "incompatible"
                        record.error = f"需要 API {manifest.api_version}，当前为 {API_VERSION}"
                    self.records[manifest.id] = record
                except PluginError as error:
                    self.diagnostics.append(f"{directory.name}：{error}")

    def _save(self) -> None:
        """Write atomically; keep startup usable even if the directory is read-only."""
        temporary = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.state_file.parent,
                prefix=".plugins-",
                delete=False,
            ) as file:
                temporary = Path(file.name)
                json.dump(self.preferences, file, ensure_ascii=False, indent=2, allow_nan=False)
            temporary.replace(self.state_file)
        except (OSError, ValueError, TypeError) as error:
            self.diagnostics.append(f"插件配置保存失败：{error}")
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def enable(self, plugin_id: str) -> None:
        activated: list[str] = []
        previous_skin = next(
            (
                key
                for key, value in self.records.items()
                if value.manifest.type == "skin" and value.state == "enabled"
            ),
            None,
        )
        try:
            self._enable(plugin_id, set(), activated)
        except Exception as error:
            for enabled_id in reversed(activated):
                self._cleanup(self.records[enabled_id])
                self.preferences["enabled"][enabled_id] = False
            if previous_skin and self.records[previous_skin].state != "enabled":
                self._enable(previous_skin, set(), [])
            self._save()
            self.changed.emit()
            raise PluginError(str(error)) from error
        self._save()
        self.changed.emit()

        if plugin_id in activated and self.records[plugin_id].manifest.type == "function":
            self.host.notify(f"{self.records[plugin_id].manifest.name}已启用")

    def _enable(self, plugin_id: str, visiting: set[str], activated: list[str]) -> None:
        if self._closed:
            raise PluginError("插件管理器已关闭")
        if plugin_id not in self.records:
            raise PluginError(f"缺少依赖插件：{plugin_id}")
        record = self.records[plugin_id]
        if record.state == "enabled":
            return
        if record.manifest.api_version != API_VERSION:
            raise PluginError(record.error or "插件 API 不兼容")
        if plugin_id in visiting:
            raise PluginError(f"插件依赖循环：{plugin_id}")
        visiting.add(plugin_id)
        for dependency in record.manifest.requires:
            self._enable(dependency, visiting, activated)
        visiting.remove(plugin_id)
        record.error = ""
        record.state = "activating"
        record.context = PluginContext(self, plugin_id)
        try:
            if record.manifest.type == "skin":
                skin = load_skin(record.directory, record.manifest.theme)
                for old in list(self.records.values()):
                    if old is not record and old.manifest.type == "skin" and old.state == "enabled":
                        if self._dependents(old.manifest.id):
                            raise PluginError("当前皮肤被其他组件依赖，不能切换")
                        self._cleanup(old)
                        self.preferences["enabled"][old.manifest.id] = False
                self.host.apply_skin(skin.style, skin.colors, chrome=skin.chrome)
                record.state = "enabled"
                self.preferences["enabled"][plugin_id] = True
                activated.append(plugin_id)
                return
            if record.directory is None:

                def factory():
                    return Transforms(plugin_id)
            else:
                namespace = f"_picer_plugin_{id(self)}_{plugin_id.encode().hex()}"
                record.namespace = namespace
                package = types.ModuleType(namespace)
                package.__path__ = [str(record.directory)]
                package.__package__ = namespace
                package.__spec__ = importlib.util.spec_from_loader(
                    namespace, loader=None, is_package=True
                )
                sys.modules[namespace] = package
                module_name, class_name = record.manifest.entrypoint.split(":")
                module = importlib.import_module(f"{namespace}.{module_name}")
                factory = getattr(module, class_name)
            record.instance = factory()
            record.instance.activate(record.context)
            if not record.manifest.legacy:
                count = sum(
                    action.property("plugin_id") == plugin_id for action in self.commands.values()
                )
                if record.manifest.type == "function" and count != 1:
                    raise PluginError("功能组件必须且只能注册一个功能按钮")
                if record.manifest.type == "panel" and plugin_id not in self.panels:
                    raise PluginError("面板组件必须注册一个面板")
            record.state = "enabled"
            self.preferences["enabled"][plugin_id] = True
            activated.append(plugin_id)
        except Exception as error:
            self._cleanup(record)
            record.state = "error"
            record.error = f"{type(error).__name__}：{error}"
            self.preferences["enabled"][plugin_id] = False
            self.logger.exception("Plugin activation failed: %s", plugin_id)
            raise PluginError(record.error) from error

    def _dependents(self, plugin_id: str) -> list[str]:
        return [
            key
            for key, record in self.records.items()
            if record.state == "enabled" and plugin_id in record.manifest.requires
        ]

    def disable(self, plugin_id: str) -> None:
        dependents = self._dependents(plugin_id)
        if dependents:
            raise PluginError(f"请先停用依赖此插件的插件：{', '.join(dependents)}")
        record = self.records[plugin_id]
        was_enabled = record.state == "enabled"
        self._cleanup(record)
        self.preferences["enabled"][plugin_id] = False
        self._save()
        self.changed.emit()
        if was_enabled and record.manifest.type == "function":
            self.host.notify(f"{record.manifest.name}已停用")

    def reload(self, plugin_id: str) -> None:
        record = self.records[plugin_id]
        self.disable(plugin_id)
        if record.directory is not None:
            manifest = Manifest.read(record.directory / "manifest.json")
            if manifest.id != plugin_id:
                raise PluginError("重载时不能修改插件 id")
            if manifest.type != record.manifest.type:
                raise PluginError("重载时不能修改组件类型")
            record.manifest = manifest
            try:
                for cache in record.directory.rglob("__pycache__"):
                    if cache.is_dir() and not cache.is_symlink():
                        shutil.rmtree(cache)
            except OSError as error:
                raise PluginError(f"重载无法清理旧字节码：{error}") from error
            importlib.invalidate_caches()
        self.enable(plugin_id)

    def _cleanup(self, record: PluginRecord) -> None:
        """Revoke context and remove contributions even if deactivate raises."""
        plugin_id = record.manifest.id
        was_enabled = record.state == "enabled"
        record.state = "disabled"
        self.settings_forms.pop(plugin_id, None)
        self.settings_widgets.pop(plugin_id, None)
        session = self.editing_sessions.pop(plugin_id, None)
        if session:
            session.close()
        self.panel_operations = {
            name: entry for name, entry in self.panel_operations.items() if entry[0] != plugin_id
        }
        self.host.touch_owners.discard(plugin_id)
        if not self.host.touch_owners and hasattr(self.host, "inputs"):
            self.host.inputs.touch_start = None
        self.host.double_page.set_enabled(plugin_id, False)
        self.host.focus_points.remove(plugin_id)
        self.host.loader.set_camera_preview(plugin_id, False)
        if record.manifest.type == "skin" and was_enabled:
            self.host.apply_skin(None, COLORS)
        self.host.panel_hovers.unregister(plugin_id)
        dock = self.panels.pop(plugin_id, None)
        if dock is not None:
            self.host.removeDockWidget(dock)
            dock.deleteLater()
        for token in self.thumbnail_requests.pop(plugin_id, ()):
            token.cancel()
        for worker in self.jobs.values():
            if worker.plugin_id == plugin_id:
                worker.token.cancel()
        if record.context is not None:
            record.context._active = False
        if record.instance is not None:
            try:
                deactivate = getattr(record.instance, "deactivate", None)
                if deactivate:
                    deactivate()
            except Exception as error:
                record.error = f"停用失败：{error}"
                self.logger.exception("Plugin deactivation failed: %s", plugin_id)
        for key in list(self.commands):
            action = self.commands[key]
            if action.property("plugin_id") == plugin_id:
                self.host.title_bar.release_action(action)
                self.host.removeAction(action)
                for menu in self.host.plugin_menus.values():
                    menu.removeAction(action)
                action.deleteLater()
                del self.commands[key]
        for event in self.subscribers:
            self.subscribers[event] = [
                (key, fn) for key, fn in self.subscribers[event] if key != plugin_id
            ]
        if record.namespace:
            for key in list(sys.modules):
                if key == record.namespace or key.startswith(record.namespace + "."):
                    del sys.modules[key]
        record.namespace = ""
        record.instance = None
        record.context = None

    def _fail(self, plugin_id: str, error: Exception) -> None:
        self.logger.error(
            "Plugin callback failed: %s",
            plugin_id,
            exc_info=(type(error), error, error.__traceback__),
        )
        # Disable dependents first; a broken dependency must not leave them active.
        for dependent in self._dependents(plugin_id):
            self._fail(dependent, PluginError(f"依赖 {plugin_id} 已出错"))
        record = self.records[plugin_id]
        self._cleanup(record)
        record.state = "error"
        record.error = f"{type(error).__name__}：{error}"
        self.preferences["enabled"][plugin_id] = False
        self._save()
        self.changed.emit()

    def _invoke(self, plugin_id: str, callback: Callable, *args) -> None:
        if self.records[plugin_id].state != "enabled":
            return
        try:
            callback(*args)
        except Exception as error:
            self._fail(plugin_id, error)

    def _invoke_command(self, plugin_id, key, callback):
        self._invoke(plugin_id, callback)
        action = self.commands.get(key)
        if action is not None and self.records[plugin_id].state == "enabled":
            suffix = ("已开启" if action.isChecked() else "已关闭") if action.isCheckable() else ""
            self.host.notify(action.text() + suffix)

    def add_command(
        self, plugin_id, command_id, label, callback, shortcut, requires_image, menu, icon=None
    ):
        manifest = self.records[plugin_id].manifest
        if manifest.type != "function":
            raise PluginError("只有功能组件可以注册功能按钮")
        if not manifest.legacy and any(
            action.property("plugin_id") == plugin_id for action in self.commands.values()
        ):
            raise PluginError("功能组件只能注册一个功能按钮")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", command_id):
            raise PluginError("命令 id 无效")
        key = f"{plugin_id}:{command_id}"
        if key in self.commands:
            raise PluginError(f"重复命令：{key}")
        if menu not in self.host.plugin_menus or not label or not callable(callback):
            raise PluginError("菜单、标签或回调无效")
        default_shortcut = shortcut
        saved = self.preferences["ui"].get("input_bindings", {})
        bindings = saved.get(key) if isinstance(saved, dict) else None
        sequences = [shortcut] if shortcut else []
        if isinstance(bindings, list):
            from picer.input_bindings import normalize

            sequences = [
                normalize("keyboard", b.get("value"))
                for b in bindings
                if isinstance(b, dict) and b.get("device") == "keyboard"
            ]
            sequences = [value for value in sequences if value]
        shortcut = sequences[0] if sequences else ""
        sequence = QKeySequence(shortcut)
        if shortcut and (
            sequence.isEmpty()
            or any(
                QKeySequence(value).matches(previous) != QKeySequence.SequenceMatch.NoMatch
                or previous.matches(QKeySequence(value)) != QKeySequence.SequenceMatch.NoMatch
                for value in sequences
                for existing in self.host.actions()
                for previous in existing.shortcuts()
            )
        ):
            raise PluginError(f"快捷键无效或冲突：{shortcut}")
        if icon is not None and not isinstance(icon, QIcon):
            raise PluginError("功能图标必须为 QIcon")
        action = QAction(label, self.host)
        default_icon = icon is None or icon.isNull()
        if default_icon:
            from picer.components import function_icon

            icon = function_icon(label, COLORS["text"])
        action.setIcon(icon)
        action.setProperty("picerDefaultIcon", default_icon)
        action.setShortcuts([QKeySequence(value) for value in sequences])
        action.setProperty("default_shortcut", default_shortcut)
        action.setProperty("plugin_id", plugin_id)
        action.setProperty("requires_image", requires_image)
        action.triggered.connect(lambda: self._invoke_command(plugin_id, key, callback))
        self.host.plugin_menus["插件"].addAction(action)
        if menu != "插件":
            self.host.plugin_menus[menu].addAction(action)
        self.host.addAction(action)
        self.commands[key] = action
        self.update_commands()
        return action

    def bind_panel_operation(self, plugin_id, name, callback):
        if self.records[plugin_id].manifest.type != "panel":
            raise PluginError("只有面板组件可以接入面板操作")
        if name not in {
            "browser.parent",
            "browser.selected",
            "browser.favorite",
            "slideshow.play",
            "slideshow.stop",
        } or not callable(callback):
            raise PluginError("未知面板操作或无效回调")
        if name in self.panel_operations:
            raise PluginError("该面板操作已经由其他面板提供")
        self.panel_operations[name] = (plugin_id, callback)
        label = {
            "browser.parent": "打开父级文件夹",
            "browser.selected": "打开选中文件夹",
        }.get(name)
        if label:
            # Enter/Backspace belong to the browser. Do not steal Enter from
            # the independent thumbnail overlay or from other editing widgets.
            action = self.host.shortcut_actions[label]
            self.host.removeAction(action)
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self.panels[plugin_id].widget().addAction(action)

    def call_panel_operation(self, name, *args):
        entry = self.panel_operations.get(name)
        if entry is None or self.records[entry[0]].state != "enabled":
            return False
        self._invoke(entry[0], entry[1], *args)
        return self.records[entry[0]].state == "enabled"

    def add_panel(self, plugin_id: str, widget: QWidget, area: str) -> None:
        if self.records[plugin_id].manifest.type != "panel":
            raise PluginError("只有面板组件可以注册面板")
        if plugin_id in self.panels:
            raise PluginError("面板组件只能注册一个面板")
        if (
            not isinstance(widget, QWidget)
            or widget is self.host
            or widget is self.host.view
            or widget.parent() is not None
        ):
            raise PluginError("面板必须为无父级的新 QWidget")
        if area not in DOCK_AREAS:
            raise PluginError("面板位置必须为 left、right 或 bottom")
        progress = self.records[plugin_id].manifest.panel_role == "progress"
        allowed = ("bottom",) if progress else ("left", "right")
        if area not in allowed:
            if progress:
                raise PluginError("进度面板只能停靠底部")
            raise PluginError("底部仅用于进度面板，其他面板只能停靠左侧或右侧")
        if progress and any(dock.property("progressPanel") for dock in self.panels.values()):
            raise PluginError("底部只能启用一个进度面板，请先停用当前进度面板")
        preferred = saved_layout(self, plugin_id).get("area")
        if isinstance(preferred, str) and preferred in allowed:
            area = preferred
        dock = (ProgressDock if progress else QDockWidget)(
            self.records[plugin_id].manifest.name, self.host
        )
        dock.setObjectName("panel:" + plugin_id)
        dock.setAllowedAreas(
            DOCK_AREAS["bottom"]
            if progress
            else Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        dock.setProperty("pluginSurface", True)
        dock.setStyleSheet(
            accent_style(PLUGIN_STYLE, COLORS["accent"], self.host.app_preferences["accent_color"])
            + "\nQDockWidget { border: none; background: transparent; }"
        )
        dock.setWidget(dock_surface(self.host, widget))
        if progress:
            dock.widget().radius = 16
        dock.setTitleBarWidget(DockTitleSpacer(dock))
        self.panels[plugin_id] = dock
        if not progress:
            self.host.addDockWidget(DOCK_AREAS[area], dock)
        visibility = self.preferences["ui"].get("panels", {})
        visible = visibility.get(plugin_id, True) if isinstance(visibility, dict) else True
        dock.setVisible(not self._fullscreen and visible is not False)
        dock.visibilityChanged.connect(lambda _: self._remember_panel(plugin_id))
        self.host.panel_hovers.register(dock, plugin_id, self)
        self.host.panel_scrollbars.refresh()
        return dock

    def _remember_panel(self, plugin_id: str) -> None:
        if self._panel_transition or self._fullscreen or plugin_id not in self.panels:
            return
        ui = self.preferences["ui"]
        if not isinstance(ui.get("panels"), dict):
            ui["panels"] = {}
        ui["panels"][plugin_id] = not self.panels[plugin_id].isHidden()
        self._save()

    def fullscreen_changed(self, fullscreen: bool) -> None:
        if fullscreen == self._fullscreen:
            return
        self.host.panel_hovers.close_all()
        if fullscreen:
            for plugin_id in self.panels:
                self._remember_panel(plugin_id)
        self._fullscreen = fullscreen
        self._panel_transition = True
        try:
            visibility = self.preferences["ui"].get("panels", {})
            for plugin_id, dock in self.panels.items():
                visible = visibility.get(plugin_id, True) if isinstance(visibility, dict) else True
                dock.setVisible(not fullscreen and visible is not False)
        finally:
            self._panel_transition = False
            if not fullscreen:
                self.host.panel_hovers.normalize_sides()
            self.host.panel_hovers.layout_strips()

    def update_commands(self) -> None:
        for action in self.commands.values():
            action.setEnabled(
                not action.property("requires_image") or self.host.current_path is not None
            )

    def subscribe(self, plugin_id: str, event: str, callback: Callable) -> None:
        if not callable(callback):
            raise PluginError("事件回调必须可调用")
        self.subscribers.setdefault(event, []).append((plugin_id, callback))

    def emit_image(self, reason: str) -> None:
        self.update_commands()
        if self._dispatching:
            return  # Mutations inside an event listener do not recursively dispatch events.
        image = self.host.view.image_item.pixmap()
        width, height = self.host.source_size
        if self.host.image_rotation % 180:
            width, height = height, width
        event = ImageEvent(
            self.host.current_path, width or image.width(), height or image.height(), reason
        )
        self._dispatching = True
        try:
            for name in (
                ["image.opened", "image.changed"] if reason == "opened" else ["image.changed"]
            ):
                for plugin_id, callback in list(self.subscribers.get(name, [])):
                    self._invoke(plugin_id, callback, event)
        finally:
            self._dispatching = False

    def emit_appearance(self):
        accent = self.host.app_preferences.get("accent_color", "")
        shared = accent_style(PLUGIN_STYLE, COLORS["accent"], accent)
        for dock in self.panels.values():
            dock.setStyleSheet(shared + "\nQDockWidget { border: none; background: transparent; }")
            surface = dock.widget()
            if surface is None:
                controller = self.host.panel_hovers.controllers.get(dock.objectName()[6:])
                surface = controller.surface if controller else None
                if controller and controller.popup:
                    controller.popup.setStyleSheet(shared)
            if surface:
                for widget in surface.findChildren(QWidget):
                    if widget.property("picerPanelContent"):
                        widget.setStyleSheet(
                            shared
                            + "\n"
                            + (widget.property("picerPanelOriginalStyle") or "")
                            + '\nQWidget[picerPanelContent="true"] { background: transparent; }'
                        )
                        widget.update()
        for plugin_id, callback in list(self.subscribers.get("appearance.changed", [])):
            self._invoke(
                plugin_id,
                callback,
                {
                    "accent": accent or COLORS["accent"],
                    "formats": sorted(self.host.supported_suffixes),
                },
            )

    def emit_animation(self, state):
        for plugin_id, callback in list(self.subscribers.get("animation.changed", [])):
            self._invoke(plugin_id, callback, state)

    def run_task(self, context, work, on_result, image_bound):
        if not callable(work) or not callable(on_result):
            raise PluginError("后台任务与结果回调必须可调用")
        if len(self.jobs) >= 16:
            raise PluginError("后台任务队列已满，请等待现有任务完成")
        worker = Worker(work)
        worker.plugin_id = context.plugin_id
        revision = self.host.image_revision
        job_id = self._next_job
        self._next_job += 1
        self.jobs[job_id] = worker

        def finish(result, error):
            self.jobs.pop(job_id, None)
            record = self.records.get(context.plugin_id)
            if (
                worker.token.cancelled
                or record is None
                or record.context is not context
                or record.state != "enabled"
            ):
                return
            if error is not None:
                if not isinstance(error, TaskCancelled):
                    self._fail(context.plugin_id, error)
                return
            if image_bound and revision != self.host.image_revision:
                return
            self._invoke(context.plugin_id, on_result, result)

        worker.signals.finished.connect(finish, Qt.ConnectionType.QueuedConnection)
        QThreadPool.globalInstance().start(worker)
        return worker.token

    def request_thumbnail(self, context, path, on_result, edge, priority):
        tokens = self.thumbnail_requests.setdefault(context.plugin_id, set())
        tokens.difference_update(
            token for token in tuple(tokens) if token.finished or token.cancelled
        )
        if len(tokens) >= 512:
            raise PluginError("缩略图请求队列已满")

        def deliver(image):
            tokens.discard(token)
            record = self.records.get(context.plugin_id)
            if record and record.context is context and record.state == "enabled":
                self._invoke(context.plugin_id, on_result, image)

        token = self.host.thumbnails.request(path, deliver, edge=edge, priority=priority)
        tokens.add(token)
        return token

    def get_setting(self, plugin_id: str, key: str, default: Any) -> Any:
        values = self.preferences["settings"].get(plugin_id, {})
        return copy.deepcopy(values.get(key, default)) if isinstance(values, dict) else default

    def add_settings(self, plugin_id, fields, callback):
        if plugin_id in self.settings_forms or not callable(callback):
            raise PluginError("设置只能注册一次，且须提供应用回调")
        fields = tuple(fields)
        if (
            not fields
            or len(fields) > 32
            or any(not isinstance(field, SettingField) for field in fields)
        ):
            raise PluginError("设置须包含 1 至 32 个 SettingField")
        keys = set()
        for field in fields:
            if not re.fullmatch(r"[a-z][a-z0-9_]*", field.key) or field.key in keys:
                raise PluginError("设置键无效或重复")
            keys.add(field.key)
            if field.kind not in {"bool", "int", "choice", "path", "text"}:
                raise PluginError("未知设置控件类型")
            if not isinstance(field.label, str) or not field.label:
                raise PluginError("设置标签必须为非空字符串")
            if field.kind == "bool" and type(field.default) is not bool:
                raise PluginError("布尔设置默认值必须为 bool")
            if field.kind == "int" and (
                any(type(v) is not int for v in (field.minimum, field.maximum, field.default))
                or not -(2**31) <= field.minimum <= field.default <= field.maximum < 2**31
            ):
                raise PluginError("整数设置默认值或范围无效")
            if field.kind in {"path", "text"} and not isinstance(field.default, str):
                raise PluginError("文本设置默认值必须为字符串")
            if field.kind == "choice":
                if (
                    not field.choices
                    or any(
                        not isinstance(pair, tuple)
                        or len(pair) != 2
                        or any(not isinstance(value, str) for value in pair)
                        for pair in field.choices
                    )
                    or len({key for key, _ in field.choices}) != len(field.choices)
                    or field.default not in tuple(key for key, _ in field.choices)
                ):
                    raise PluginError("选择设置默认值或选项无效")
        self.settings_forms[plugin_id] = (fields, callback)

    def show_settings(self, plugin_id):
        from picer.plugins.dialog import PluginDialog

        if plugin_id not in self.settings_forms:
            raise PluginError("请先启用提供设置的组件")
        dialog = PluginDialog(self, self.host, selected_id=plugin_id, open_settings=True)
        dialog.exec()
        dialog.deleteLater()

    def set_settings(self, plugin_id, values):
        try:
            encoded = json.dumps(values, allow_nan=False)
            if len(encoded) > 64 * 1024:
                raise ValueError("设置不能超过 64 KiB")
        except (ValueError, TypeError) as error:
            raise PluginError(f"设置必须为有限的 JSON 值：{error}") from error
        settings = self.preferences["settings"]
        if not isinstance(settings.get(plugin_id), dict):
            settings[plugin_id] = {}
        settings[plugin_id].update(json.loads(encoded))
        self._save()

    def set_setting(self, plugin_id: str, key: str, value: Any) -> None:
        if not isinstance(key, str) or not key:
            raise PluginError("设置键必须为非空字符串")
        try:
            encoded = json.dumps(value, allow_nan=False)
            if len(encoded) > 64 * 1024:
                raise ValueError("单个设置不能超过 64 KiB")
        except (ValueError, TypeError) as error:
            raise PluginError(f"设置必须为有限的 JSON 值：{error}") from error
        settings = self.preferences["settings"]
        if not isinstance(settings.get(plugin_id), dict):
            settings[plugin_id] = {}
        settings[plugin_id][key] = json.loads(encoded)
        self._save()

    def install(self, archive: Path, *, replace_existing: bool = False) -> str:
        """Install/update a disabled ZIP package without executing it."""
        try:
            with tempfile.TemporaryDirectory(
                prefix=".install-", dir=self.directory, ignore_cleanup_errors=True
            ) as temporary:
                temporary_root = Path(temporary)
                staging = temporary_root / "package"
                staging.mkdir()
                with zipfile.ZipFile(archive) as file:
                    entries = file.infolist()
                    if (
                        len(entries) > 500
                        or sum(info.file_size for info in entries) > 20 * 1024 * 1024
                    ):
                        raise PluginError("插件包最多包含 500 个文件，解压后不超过 20 MiB")
                    seen = set()
                    for info in entries:
                        # ZipInfo normalizes separators on Windows when reading too.
                        # Inspect the original archive name before that normalization.
                        raw_name = info.orig_filename
                        path = PurePosixPath(raw_name)
                        reserved = {"CON", "PRN", "AUX", "NUL"}
                        reserved.update(
                            f"{prefix}{number}"
                            for prefix in ("COM", "LPT")
                            for number in range(1, 10)
                        )
                        if (
                            path.is_absolute()
                            or ".." in path.parts
                            or "\\" in raw_name
                            or ":" in raw_name
                            or any(ord(char) < 32 or char in '<>"|?*' for char in raw_name)
                            or (info.external_attr >> 16) & 0o170000 == 0o120000
                            or any(
                                part.rstrip(" .") != part or part.split(".")[0].upper() in reserved
                                for part in path.parts
                            )
                        ):
                            raise PluginError("插件包含非法路径或符号链接")
                        normalized = str(path).casefold()
                        if normalized in seen:
                            raise PluginError("插件包含重复或大小写冲突的路径")
                        seen.add(normalized)
                    file.extractall(staging)
                manifest = Manifest.read(staging / "manifest.json")
                previous = self.records.get(manifest.id)
                if previous:
                    if not replace_existing or previous.directory is None:
                        raise PluginError("该插件已存在，不能覆盖内置插件")
                    if previous.state == "enabled" or self._dependents(manifest.id):
                        raise PluginError("更新前请先停用插件及其依赖者")
                base = self.paths.skins if manifest.type == "skin" else self.directory
                if manifest.type == "skin":
                    load_skin(staging, manifest.theme)
                if previous and previous.manifest.type != manifest.type:
                    raise PluginError("更新不能更改组件类型，请先卸载旧组件")
                base.mkdir(parents=True, exist_ok=True)
                destination = previous.directory if previous else base / manifest.id
                if destination.exists() and previous is None:
                    raise PluginError("插件目录已存在")
                module_name = manifest.entrypoint.split(":")[0]
                module_path = staging.joinpath(*module_name.split("."))
                if manifest.type != "skin" and (
                    not module_path.with_suffix(".py").is_file()
                    and not (module_path / "__init__.py").is_file()
                ):
                    raise PluginError("插件入口文件不存在")
                backup = temporary_root / "previous"
                if previous:
                    destination.rename(backup)
                try:
                    staging.rename(destination)
                except OSError:
                    if backup.exists():
                        backup.rename(destination)
                    raise
            record = PluginRecord(manifest, directory=destination)
            if manifest.api_version != API_VERSION:
                record.state = "incompatible"
                record.error = f"需要 API {manifest.api_version}，当前为 {API_VERSION}"
            self.records[manifest.id] = record
            self.preferences["enabled"][manifest.id] = False
            self._save()
            self.changed.emit()
            self.host.notify(f"{manifest.name}已安装")
            return manifest.id
        except (OSError, zipfile.BadZipFile, RuntimeError) as error:
            raise PluginError(f"安装失败：{error}") from error

    def uninstall(self, plugin_id: str) -> None:
        record = self.records[plugin_id]
        if record.directory is None:
            raise PluginError("不能卸载内置插件")
        if record.state == "enabled" or self._dependents(plugin_id):
            raise PluginError("请先停用插件及其依赖者")
        try:
            shutil.rmtree(record.directory)
        except OSError as error:
            raise PluginError(f"卸载失败：{error}") from error
        del self.records[plugin_id]
        self.preferences["enabled"].pop(plugin_id, None)
        self.preferences["settings"].pop(plugin_id, None)
        visibility = self.preferences["ui"].get("panels", {})
        if isinstance(visibility, dict):
            visibility.pop(plugin_id, None)
        layouts = self.preferences["ui"].get("panel_layouts", {})
        if isinstance(layouts, dict):
            layouts.pop(plugin_id, None)
        slots = self.preferences["ui"].get("quick_slots", [])
        if isinstance(slots, list):
            self.preferences["ui"]["quick_slots"] = [
                "" if isinstance(key, str) and key.startswith(plugin_id + ":") else key
                for key in slots
            ]
        self._save()
        self.changed.emit()

    def shutdown(self) -> None:
        self._closed = True
        for worker in self.jobs.values():
            worker.token.cancel()
        remaining = {key for key, record in self.records.items() if record.state == "enabled"}
        while remaining:
            leaves = [key for key in remaining if not (set(self._dependents(key)) & remaining)]
            if not leaves:
                leaves = list(remaining)
            for key in leaves:
                self._cleanup(self.records[key])
                remaining.remove(key)

        if self.log_handler is not None:
            self.logger.removeHandler(self.log_handler)
            self.log_handler.close()
            self.log_handler = None
