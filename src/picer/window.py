"""An image browser with folder navigation and zoom controls."""

from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, Qt, QUrl
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QIcon,
    QImage,
    QKeySequence,
    QPixmap,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from picer.animation import AnimationPlayer
from picer.cache import ThumbnailCache
from picer.chrome import STYLE, TitleBar
from picer.components import ComponentUI
from picer.host_style import HostStyleFilter, mark_host, scope_style
from picer.imaging import supported_suffixes
from picer.loading import ImageLoader
from picer.navigation import NavigationKeys
from picer.panels import GlassBackdrop, PanelHovers
from picer.paths import AppPaths
from picer.plugins.dialog import PluginDialog
from picer.plugins.manager import PluginManager
from picer.plugins.skins import COLORS
from picer.preferences import DEFAULTS, read_preferences
from picer.thumbnails import ThumbnailService


class ImageView(QGraphicsView):
    """Display an image with drag-to-pan and bounded zoom."""

    def __init__(self) -> None:
        super().__init__()
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.image_item = QGraphicsPixmapItem()
        self.scene.addItem(self.image_item)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QColor(COLORS["background"]))
        self.fit_mode = True
        self.native_width = 0
        self.zoom_step = 25
        self.double_click = "toggle"

    def fit_image(self) -> None:
        self.fit_mode = True
        if not self.image_item.pixmap().isNull():
            self.fitInView(self.image_item, Qt.AspectRatioMode.KeepAspectRatio)

    def zoom(self, factor: float) -> None:
        if self.image_item.pixmap().isNull():
            return
        if 0.01 <= self.transform().m11() * factor <= 32:
            self.fit_mode = False
            self.scale(factor, factor)

    def actual_size(self) -> None:
        self.fit_mode = False
        self.resetTransform()

    def wheelEvent(self, event) -> None:
        factor = 1 + self.zoom_step / 100
        self.zoom(factor if event.angleDelta().y() > 0 else 1 / factor)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.double_click == "fit" or (self.double_click == "toggle" and not self.fit_mode):
                self.fit_image()
            else:
                self.actual_size()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.fit_mode:
            self.fit_image()
        if hasattr(self, "empty_label"):
            self.empty_label.setGeometry(self.rect())


class MainWindow(QMainWindow):
    """Browse supported images in the selected file's directory."""

    def createPopupMenu(self):
        # QMainWindow's native dock menu would duplicate fixed/auto-hide controls.
        return None

    def __init__(
        self,
        *,
        plugin_root: Path | None = None,
        load_external: bool = True,
        load_examples: bool = True,
    ) -> None:
        super().__init__()
        self.paths_layout = AppPaths.resolve(plugin_root)
        self.thumbnail_cache = ThumbnailCache(self.paths_layout.cache)
        self.thumbnails = ThumbnailService(self.thumbnail_cache, self)
        self.current_thumbnail = QImage()
        self.setWindowIcon(QIcon(str(self.paths_layout.icon)))
        self.setWindowTitle("揽映")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(800, 420)
        self.resize(1200, 800)
        self._base_skin_colors = dict(COLORS)
        self.skin_colors = dict(COLORS)
        self.app_preferences = dict(DEFAULTS)
        self._skin_style = STYLE
        self.shortcut_actions, self.default_shortcuts = {}, {}
        self.chrome_style = "standard"
        self._skin_filter = HostStyleFilter(self)
        QApplication.instance().installEventFilter(self._skin_filter)
        self.setStyleSheet(scope_style(STYLE))
        self.setAcceptDrops(True)
        self.paths: list[Path] = []
        self.path_positions = {}
        self.path_source = None
        self.image_path_snapshot = ()
        self.current_path: Path | None = None
        self.source_size = (0, 0)
        self.image_rotation = 0
        self.navigation_request = None
        self.last_error = ""
        self.view = ImageView()
        self.title_bar = TitleBar(self)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 0, 6, 6)
        layout.setSpacing(0)
        self.setMenuWidget(self.title_bar)
        layout.addWidget(self.view, 1)
        self.setCentralWidget(container)
        self.empty_label = QLabel("打开图片，开始浏览\nCtrl+O  ·  或将图片拖入窗口", self.view)
        self.view.empty_label = self.empty_label
        self.empty_label.setObjectName("empty")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.supported_suffixes = supported_suffixes()
        self.animation = AnimationPlayer(self)
        self.loader = ImageLoader(self)
        self.animation.pixels.connect(self.animation_frame)
        self.animation.changed.connect(self.animation_changed)
        self.animation.failed.connect(lambda error: setattr(self, "last_error", error))
        file_menu = self.title_bar.menu.addMenu("文件")
        edit_menu = self.title_bar.menu.addMenu("编辑")
        view_menu = self.title_bar.menu.addMenu("视图")
        plugin_menu = self.title_bar.menu.addMenu("插件")
        help_menu = self.title_bar.menu.addMenu("帮助")
        self.main_menus = (file_menu, edit_menu, view_menu, plugin_menu, help_menu)
        run_menu = plugin_menu.addMenu("调用功能")
        self.plugin_menus = {"编辑": edit_menu, "视图": view_menu, "插件": run_menu}
        self.open_action = self.add_action(file_menu, "打开图片…", "Ctrl+O", self.choose_image)
        self.add_action(file_menu, "打开文件夹…", "Ctrl+Shift+O", self.choose_folder)
        file_menu.addSeparator()
        self.add_action(file_menu, "退出", "Alt+F4", self.close)
        self.copy_action = self.add_action(
            edit_menu, "复制文件路径", "Ctrl+Shift+C", self.copy_path
        )
        self.settings_action = self.add_action(edit_menu, "设置…", "Ctrl+,", self.show_settings)
        self.previous_action = self.add_action(
            view_menu, "上一张", "Left", lambda: self.navigate(-1)
        )
        self.next_action = self.add_action(view_menu, "下一张", "Right", lambda: self.navigate(1))
        view_menu.addSeparator()
        self.zoom_in_action = self.add_action(
            view_menu, "放大", "Ctrl+=", lambda: self.view.zoom(1.25)
        )
        self.zoom_out_action = self.add_action(
            view_menu, "缩小", "Ctrl+-", lambda: self.view.zoom(0.8)
        )
        self.fit_action = self.add_action(view_menu, "适应窗口", "Ctrl+0", self.view.fit_image)
        self.actual_action = self.add_action(view_menu, "原始大小", "Ctrl+1", self.view.actual_size)
        view_menu.addSeparator()
        self.fullscreen_action = self.add_action(view_menu, "全屏", "F11", self.toggle_fullscreen)
        self.add_action(view_menu, "退出全屏", "Esc", self.exit_fullscreen)
        self.add_action(help_menu, "关于揽映", "", self.show_about)
        self.add_action(plugin_menu, "插件管理…", "Ctrl+Shift+P", self.show_plugins)
        plugin_menu.addSeparator()
        self.add_action(help_menu, "打开应用数据目录", "", self.open_data_directory)
        self.add_action(help_menu, "清理图片缓存", "", self.clear_thumbnail_cache)
        self.image_revision = 0
        mark_host(self)
        self.glass = GlassBackdrop(self)
        self.panel_hovers = PanelHovers(self)
        self.plugins = PluginManager(
            self, self.paths_layout.root, load_external=load_external, load_examples=load_examples
        )
        self.plugins.changed.connect(self.panel_hovers.layout_strips)
        self.components = ComponentUI(self, plugin_menu)
        self.apply_preferences()
        self.navigation_keys = NavigationKeys(self)
        self.update_actions()
        self.title_bar.arrange()

    def showEvent(self, event):
        super().showEvent(event)
        self.panel_hovers.layout_strips()

    def add_action(self, menu, text, shortcut, callback) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(callback)
        menu.addAction(action)
        self.addAction(action)
        if shortcut:
            self.shortcut_actions[text] = action
            self.default_shortcuts[text] = shortcut
        return action

    def apply_skin(self, style: str | None, colors: dict[str, str], *, chrome="standard") -> None:
        self._base_skin_colors = dict(colors)
        self.skin_colors = dict(colors)
        self.chrome_style = chrome
        self._skin_style = STYLE if style is None else style
        self.apply_host_style()
        self.title_bar.set_chrome(chrome)
        self.view.setBackgroundBrush(QColor(colors["background"]))
        if hasattr(self, "components"):
            self.components.refresh_slots()

    def apply_host_style(self):
        from picer.theme import accent_style

        self.skin_colors = dict(self._base_skin_colors)
        custom = self.app_preferences["accent_color"]
        if custom:
            self.skin_colors["accent"] = custom
        style = accent_style(self._skin_style, self._base_skin_colors["accent"], custom)
        if self.app_preferences["density"] == "compact":
            style += "\nQWidget { font-size: 12px; } QMenu::item { padding: 6px 24px 6px 12px; }"
        self.setStyleSheet(scope_style(style))
        for button in self.title_bar.control_buttons.values():
            button.update()

    def apply_preferences(self):
        self.app_preferences = read_preferences(self.plugins)
        self.view.zoom_step = self.app_preferences["zoom_step"]
        self.view.double_click = self.app_preferences["double_click"]
        self.thumbnail_cache.byte_limit = self.app_preferences["cache_mb"] * 1048576
        self.thumbnails.trim()
        self.apply_host_style()
        self.restore_shortcuts(self.plugins.preferences["ui"].get("shortcuts", {}))
        for surface in tuple(self.glass.surfaces):
            surface.update()
        self.title_bar.arrange()
        if hasattr(self, "navigation_keys") and self.navigation_keys.timer.isActive():
            self.navigation_keys.timer.setInterval(self.app_preferences["key_repeat_ms"])
        self.plugins.emit_appearance()
        self.panel_hovers.update_progress_ring()
        self.update()

    def restore_shortcuts(self, shortcuts):
        if isinstance(shortcuts, dict):
            used = set()
            for name, action in self.shortcut_actions.items():
                value = shortcuts.get(name, self.default_shortcuts[name])
                if isinstance(value, str) and len(value) <= 128:
                    sequence = QKeySequence(value)
                    normalized = sequence.toString(QKeySequence.SequenceFormat.PortableText)
                    if normalized and normalized in used:
                        sequence = QKeySequence()
                    action.setShortcut(sequence)
                    if normalized:
                        used.add(normalized)
        shortcut = self.open_action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
        self.empty_label.setText(
            "打开图片，开始浏览\n" + (shortcut + "  ·  " if shortcut else "") + "或将图片拖入窗口"
        )

    def restore_startup(self, *, restore_image=True):
        ui = self.plugins.preferences["ui"]
        geometry = ui.get("window_geometry")
        if (
            self.app_preferences["remember_window"]
            and isinstance(geometry, str)
            and len(geometry) <= 16384
        ):
            self.restoreGeometry(QByteArray.fromHex(geometry.encode()))
        last = ui.get("last_image")
        if restore_image and self.app_preferences["start"] == "last" and isinstance(last, str):
            path = Path(last)
            if path.is_file():
                self.open_image(path)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "plugins"):
            self.plugins.fullscreen_changed(self.isFullScreen())

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "打开文件夹")
        if not folder:
            return
        self.loader.open_folder(Path(folder).resolve())

    def copy_path(self) -> None:
        if self.current_path:
            QApplication.clipboard().setText(str(self.current_path))

    @property
    def rotate_action(self):
        return self.plugins.commands.get("picer.transforms:rotate")

    def replace_image(self, image) -> None:
        self.loader.generation += 1
        self.loader.refine.stop()
        self.animation.stop()
        self.image_rotation = 0
        self.source_size = (image.width(), image.height())
        self.view.native_width = image.width()
        self.view.image_item.setScale(1)
        self.view.image_item.setPixmap(QPixmap.fromImage(image))
        self.view.scene.setSceneRect(self.view.image_item.sceneBoundingRect())
        self.view.fit_image()
        self.image_revision += 1
        self.plugins.emit_image("edited")

    def rotate_image(self):
        if self.current_path is None:
            return
        self.image_rotation = (self.image_rotation + 90) % 360
        image = self.view.image_item.pixmap().toImage().transformed(QTransform().rotate(90))
        self.view.native_width = self.source_size[1 if self.image_rotation % 180 else 0]
        self.view.image_item.setPixmap(QPixmap.fromImage(image))
        self.view.image_item.setScale(self.view.native_width / image.width())
        self.view.scene.setSceneRect(self.view.image_item.sceneBoundingRect())
        self.view.fit_image()
        self.image_revision += 1
        self.plugins.emit_image("rotated")

    def plugin_notification(self, message: str) -> None:
        QMessageBox.information(self, "揽映 · 插件", str(message))

    def show_plugins(self) -> None:
        dialog = PluginDialog(self.plugins, self)
        dialog.exec()
        dialog.deleteLater()

    def show_settings(self):
        from picer.settings import ApplicationSettings

        dialog = ApplicationSettings(self)
        dialog.exec()
        dialog.deleteLater()

    def closeEvent(self, event) -> None:
        ui = self.plugins.preferences["ui"]
        if self.app_preferences["remember_window"] and not self.isFullScreen():
            ui["window_geometry"] = bytes(self.saveGeometry().toHex()).decode()
        if self.current_path:
            ui["last_image"] = str(self.current_path)
        self.plugins._save()
        self.navigation_keys.dispose()
        self.loader.shutdown()
        self.animation.shutdown()
        self.plugins.shutdown()
        self.thumbnails.shutdown()
        super().closeEvent(event)

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.exit_fullscreen()
        else:
            self.was_maximized = self.isMaximized()
            self.showFullScreen()

    def exit_fullscreen(self) -> None:
        if self.isFullScreen():
            if getattr(self, "was_maximized", False):
                self.showMaximized()
            else:
                self.showNormal()

    def open_data_directory(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.paths_layout.root)))

    def clear_thumbnail_cache(self) -> None:
        try:
            self.loader.clear_cache()
            self.thumbnails.discard_seeds()
            self.thumbnail_cache.clear()
        except OSError as error:
            QMessageBox.warning(self, "清理缓存失败", str(error))

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "关于揽映",
            "揽映 Picer 0.14.1\n以插件为核心的本地图片浏览器。\n"
            "滚轮缩放 · 拖动平移 · 左右键切换\n"
            "旋转仅影响当前显示，不修改原文件。",
        )

    def mousePressEvent(self, event) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not self.isMaximized()
            and not self.isFullScreen()
        ):
            position = event.position()
            edges = Qt.Edge(0)
            if position.x() < 6:
                edges |= Qt.Edge.LeftEdge
            if position.x() >= self.width() - 6:
                edges |= Qt.Edge.RightEdge
            if position.y() < 6:
                edges |= Qt.Edge.TopEdge
            if position.y() >= self.height() - 6:
                edges |= Qt.Edge.BottomEdge
            if edges and self.windowHandle():
                self.windowHandle().startSystemResize(edges)
        super().mousePressEvent(event)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile() and self.open_image(Path(url.toLocalFile())):
                event.acceptProposedAction()
                return
        QMessageBox.warning(self, "无法打开图片", self.last_error)

    def choose_image(self) -> None:
        patterns = " ".join(f"*{suffix}" for suffix in sorted(self.supported_suffixes))
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "打开图片",
            str(self.current_path.parent) if self.current_path else "",
            f"图片 ({patterns});;所有文件 (*)",
        )
        if filename:
            if not self.open_image(Path(filename)):
                QMessageBox.warning(self, "无法打开图片", self.last_error)

    def open_image(self, path: Path) -> bool:
        """Accept a request; large images/RAW/animation finish in the background."""
        self.navigation_request = None
        self.loader.folder_candidates.clear()
        return self.loader.open(path)

    def set_image_paths(self, paths):
        self.path_source = paths
        paths = list(paths)
        if self.current_path and self.current_path not in paths:
            paths.append(self.current_path)
        self.paths = paths
        self.path_positions = {path: index for index, path in enumerate(paths)}
        self.image_path_snapshot = tuple(paths)
        self.update_actions()
        self.plugins.emit_image("indexed")

    def present_image(self, path, image, *, paths=None, preview=False):
        self.animation.stop()
        self.current_path = path
        self.navigation_request = None
        if not self.app_preferences["browse_folder"]:
            paths = [path]
        elif paths is None:
            paths = self.paths if self.paths and self.paths[0].parent == path.parent else [path]
        if not ((paths is self.path_source or paths is self.paths) and path in self.path_positions):
            self.path_source = paths
            self.paths = list(paths)
            if path not in self.paths:
                self.paths.append(path)
            self.path_positions = {item: index for index, item in enumerate(self.paths)}
            self.image_path_snapshot = tuple(self.paths)
        self.current_thumbnail = image.scaled(
            min(256, image.width()),
            min(256, image.height()),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_rotation = 0
        self.source_size = (
            int(image.text("picer.native_width") or image.width()),
            int(image.text("picer.native_height") or image.height()),
        )
        self.view.native_width = self.source_size[0]
        self.view.image_item.setPixmap(QPixmap.fromImage(image))
        self.view.image_item.setScale(self.view.native_width / image.width())
        self.view.scene.setSceneRect(self.view.image_item.sceneBoundingRect())
        if self.app_preferences["default_scale"] == "fit":
            self.view.fit_image()
        else:
            self.view.actual_size()
        self.last_error = ""
        self.empty_label.hide()
        self.setWindowTitle(f"{path.name} — 揽映")
        self.title_bar.set_filename(path.name)
        self.update_actions()
        self.image_revision += 1
        self.plugins.emit_image("opened")
        if self.app_preferences["focus_image"]:
            self.view.setFocus(Qt.FocusReason.OtherFocusReason)

    def refine_image(self, image):
        # Preview and original occupy the same logical source-pixel rectangle.
        center = self.view.mapToScene(self.view.viewport().rect().center())
        if self.image_rotation:
            image = image.transformed(QTransform().rotate(self.image_rotation))
        self.view.image_item.setPixmap(QPixmap.fromImage(image))
        self.view.image_item.setScale(self.view.native_width / image.width())
        self.view.scene.setSceneRect(self.view.image_item.sceneBoundingRect())
        if self.view.fit_mode:
            self.view.fit_image()
        else:
            self.view.centerOn(center)

    def animation_frame(self, image):
        self.refine_image(image)

    def animation_changed(self, state):
        if hasattr(self, "panel_hovers"):
            self.panel_hovers.update_progress_ring()
        if hasattr(self, "plugins"):
            self.plugins.emit_animation(state)

    def loading_failed(self, path, error):
        self.last_error = f"无法打开 {path.name}：{error}"
        request, self.navigation_request = self.navigation_request, None
        if request and request[0] == path and request[2] > 0:
            self.loader.requested = path
            self.continue_navigation(request[1], request[2])
            return
        self.loader.requested = self.current_path
        # Keep the last good image and expose a nonmodal failure on the caption.
        self.title_bar.caption.setToolTip(self.last_error)
        if self.current_path is None:
            self.empty_label.setText(self.last_error)
            self.empty_label.show()

    def navigate(self, offset: int) -> None:
        """Skip unreadable images and wrap around at folder boundaries."""
        if self.current_path is None or len(self.paths) < 2:
            return
        self.loader.folder_candidates.clear()
        self.loader.direction = 1 if offset > 0 else -1
        self.continue_navigation(offset, len(self.paths) - 1)

    def continue_navigation(self, offset, budget):
        paths = self.paths
        requested = self.loader.requested or self.current_path
        index = self.path_positions.get(requested, self.path_positions.get(self.current_path, 0))
        for step in range(1, budget + 1):
            target = index + offset * step
            if not self.app_preferences["wrap"] and not 0 <= target < len(paths):
                return
            path = paths[target % len(paths)]
            if self.loader.open(path):
                self.navigation_request = (
                    None if self.current_path == path else (path, offset, budget - step)
                )
                return
        self.loader.requested = self.current_path

    def update_actions(self) -> None:
        self.previous_action.setEnabled(len(self.paths) > 1)
        self.next_action.setEnabled(len(self.paths) > 1)
        for action in (
            self.zoom_in_action,
            self.zoom_out_action,
            self.fit_action,
            self.actual_action,
            self.copy_action,
        ):
            action.setEnabled(self.current_path is not None)

        self.plugins.update_commands()
        self.panel_hovers.update_progress_ring()
