"""A filesystem-backed tree panel; no recursive eager scans or private host access."""

from pathlib import Path

from PySide6.QtCore import QDir, QSize, QStandardPaths, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListView,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from picer.host_style import PLUGIN_STYLE
from picer.imaging import supported_suffixes
from picer.plugins import SettingField, ui_icon

from .address import AddressBar
from .input import BrowserPanel, ParentEntry
from .model import BrowserModel
from .places import PlacesList, navigation_tabs, saved_paths
from .thumbnails import PhotoTree, configure_view


class Plugin:
    def activate(self, context):
        self.context = context
        self.history = []
        self.history_index = -1
        self.home = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.PicturesLocation
        )
        self.fields = (
            SettingField("home", "首页路径", "path", self.home or str(Path.home())),
            SettingField("icon_size", "图标大小（像素）", "int", 24, 16, 64),
            SettingField(
                "sort",
                "普通文件夹默认排序",
                "choice",
                "name",
                choices=(
                    ("name", "名称"),
                    ("size", "大小"),
                    ("type", "类型"),
                    ("modified", "修改时间"),
                ),
            ),
            SettingField("descending", "倒序排列", "bool", False),
            SettingField(
                "view", "浏览视图", "choice", "list", choices=(("list", "列表"), ("tiles", "平铺"))
            ),
        )
        self.fields += (
            SettingField(
                "photo_sort", "图片文件夹默认排序", "choice", "name", choices=self.fields[2].choices
            ),
        )
        context.add_settings(self.fields, self.apply_settings)
        self.panel = BrowserPanel(self.resize_icons, self.go_up, self.go_back, self.go_forward)
        self.panel.setMinimumWidth(220)
        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(12, 12, 12, 12)
        toolbar = QHBoxLayout()
        for icon, tip, callback in (
            ("home", "首页", self.go_home),
            ("up", "上一级", self.go_up),
        ):
            button = QPushButton()
            button.setIcon(ui_icon(icon))
            button.setObjectName("circleButton")
            button.setFixedSize(32, 32)
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        self.sort = QComboBox()
        for key, label in self.fields[2].choices:
            self.sort.addItem(label, key)
        self.sort.currentIndexChanged.connect(self.sort_changed)
        toolbar.addWidget(self.sort, 1)
        self.view_button = QPushButton()
        self.view_button.setObjectName("circleButton")
        self.view_button.setFixedSize(32, 32)
        self.view_button.setIcon(ui_icon("settings"))
        self.view_button.setToolTip("快速设置")
        self.view_button.setAccessibleName("快速设置")
        self.create_quick_menu()
        self.view_button.clicked.connect(self.show_quick_menu)
        toolbar.addWidget(self.view_button)
        layout.addLayout(toolbar)
        self.location = AddressBar(self.panel)
        self.location.pathRequested.connect(self.open_folder)
        layout.addWidget(self.location)
        body = QHBoxLayout()
        body.setSpacing(6)
        self.tabs = navigation_tabs()
        body.addWidget(self.tabs, 0, Qt.AlignmentFlag.AlignTop)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        layout.addLayout(body, 1)
        self.files_page = QWidget()
        files_layout = QVBoxLayout(self.files_page)
        files_layout.setContentsMargins(0, 0, 0, 0)
        self.pages.addWidget(self.files_page)
        self.parent_entry = ParentEntry()
        self.parent_entry.activated.connect(self.go_up)
        self.parent_entry.clicked.connect(self.select_parent)
        files_layout.addWidget(self.parent_entry)
        self.model = BrowserModel(context, self.panel)
        self.parent_entry.setIcon(self.model.files.folders.icons[0])
        self.configure_model()
        self.tree = PhotoTree()
        self.tree.setModel(self.model)
        configure_view(self.tree)
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(True)
        self.tree.setAnimated(True)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setHeaderHidden(True)
        for column in (1, 2, 3):
            self.tree.hideColumn(column)
        self.tree.clicked.connect(self.select_entry)
        self.tree.doubleClicked.connect(self.enter_folder)
        self.tiles = QListView()
        self.tiles.setModel(self.model)
        configure_view(self.tiles)
        self.tiles.setViewMode(QListView.ViewMode.IconMode)
        self.tiles.setResizeMode(QListView.ResizeMode.Adjust)
        self.tiles.setMovement(QListView.Movement.Static)
        self.tiles.setWrapping(True)
        self.tiles.setSpacing(4)
        self.tiles.clicked.connect(self.select_entry)
        self.tiles.doubleClicked.connect(self.enter_folder)
        for view in (self.tree, self.tiles):
            view.viewport().setProperty("browserViewport", True)
        self.views = QStackedWidget()
        self.views.addWidget(self.tree)
        self.views.addWidget(self.tiles)
        files_layout.addWidget(self.views, 1)
        self.favorites = PlacesList(self, "favorites")
        self.recent = PlacesList(self, "recent_folders")
        self.pages.addWidget(self.favorites)
        self.pages.addWidget(self.recent)
        self.tabs.currentChanged.connect(self.change_tab)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.dock = context.add_panel(self.panel, area="left")
        self.return_path = None
        self.return_timer = QTimer(self.panel)
        self.return_timer.setInterval(30)
        self.return_timer.timeout.connect(self.restore_return_selection)
        context.subscribe("appearance.changed", self.on_appearance)
        self.on_appearance({"accent": context.accent_color()})
        self.apply_settings()
        self.favorites.reload()
        self.recent.reload()

    def on_appearance(self, event):
        self.parent_entry.set_accent(event["accent"])
        self.tabs.set_accent(event["accent"])
        for view in (self.tree, self.tiles, self.favorites, self.recent):
            view.viewport().update()

    def values(self):
        return {
            field.key: field.validate(self.context.get_setting(field.key, field.default))
            for field in self.fields
        }

    def apply_settings(self):
        self.apply_icon_size()
        self.apply_view()
        self.go_home()

    def apply_icon_size(self):
        size = self.values()["icon_size"]
        self.parent_entry.setIconSize(QSize(size, size))
        self.parent_entry.setFixedHeight(size + 14)
        self.tree.setIconSize(QSize(size, size))
        self.tiles.setIconSize(QSize(size * 2, size * 2))
        self.tiles.setGridSize(QSize(size * 2 + 32, size * 2 + 40))
        self.favorites.reload()
        self.recent.reload()

    def resize_icons(self, steps):
        field = self.fields[1]
        size = max(field.minimum, min(field.maximum, self.values()["icon_size"] + steps * 4))
        self.context.set_setting("icon_size", size)
        self.apply_icon_size()

    def folder_orders(self):
        orders = self.context.get_setting("folder_orders", {})
        return orders if isinstance(orders, dict) else {}

    def current_order(self):
        values = self.values()
        path = self.location.text()
        is_photo = self.model.files.folders.cache.get(path, False)
        key = values["photo_sort"] if is_photo else values["sort"]
        order = self.folder_orders().get(path, {})
        if not isinstance(order, dict):
            order = {}
        keys = dict(self.fields[2].choices)
        selected = order.get("sort", key)
        return selected if isinstance(selected, str) and selected in keys else key, bool(
            order.get("descending", values["descending"])
        )

    def sort_tree(self):
        key, descending = self.current_order()
        self.sort.blockSignals(True)
        self.sort.setCurrentIndex(self.sort.findData(key))
        self.sort.blockSignals(False)
        column = {"name": 0, "size": 1, "type": 2, "modified": 3}[key]
        order = Qt.SortOrder.DescendingOrder if descending else Qt.SortOrder.AscendingOrder
        self.tree.sortByColumn(column, order)
        self.quick_actions["ascending"].setChecked(not descending)
        self.quick_actions["descending"].setChecked(descending)
        if self.return_path:
            self.return_timer.start()

    def save_order(self, key, descending):
        orders = self.folder_orders()
        path = self.location.text()
        orders.pop(path, None)
        orders[path] = {"sort": key, "descending": descending}
        self.context.set_setting("folder_orders", dict(list(orders.items())[-128:]))
        self.sort_tree()

    def sort_changed(self):
        self.save_order(self.sort.currentData(), self.current_order()[1])

    def folder_classified(self, path):
        if path == self.location.text():
            self.sort_tree()

    def apply_view(self):
        tiled = self.values()["view"] == "tiles"
        self.views.setCurrentWidget(self.tiles if tiled else self.tree)
        self.quick_actions["tiles"].setChecked(tiled)
        self.quick_actions["list"].setChecked(not tiled)

    def configure_model(self):
        self.model.files.setFilter(
            QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot
        )
        self.model.files.setNameFilters([f"*{suffix}" for suffix in sorted(supported_suffixes())])
        self.model.files.setNameFilterDisables(False)
        self.model.files.folderClassified.connect(self.folder_classified)

    def create_quick_menu(self):
        self.quick_menu = QMenu(self.panel)
        self.quick_menu.setStyleSheet(PLUGIN_STYLE)
        self.quick_actions = {}
        for key, label, callback, checkable in (
            ("tiles", "平铺视图", lambda: self.set_view("tiles"), True),
            ("list", "列表视图", lambda: self.set_view("list"), True),
            (None, None, None, False),
            ("refresh", "刷新", self.refresh, False),
            (None, None, None, False),
            ("ascending", "正序排列", lambda: self.set_descending(False), True),
            ("descending", "倒序排列", lambda: self.set_descending(True), True),
            (None, None, None, False),
            ("favorite", "加入快速访问", self.add_favorite, False),
        ):
            if key is None:
                self.quick_menu.addSeparator()
            else:
                action = self.quick_menu.addAction(label)
                action.setCheckable(checkable)
                action.triggered.connect(callback)
                self.quick_actions[key] = action
        self.quick_menu.aboutToShow.connect(self.sync_quick_menu)

    def show_quick_menu(self):
        self.quick_menu.popup(self.view_button.mapToGlobal(self.view_button.rect().bottomLeft()))

    def sync_quick_menu(self):
        self.apply_view()
        descending = self.current_order()[1]
        self.quick_actions["ascending"].setChecked(not descending)
        self.quick_actions["descending"].setChecked(descending)
        path = self.location.text()
        self.quick_actions["favorite"].setEnabled(
            bool(path) and path not in saved_paths(self.context, "favorites")
        )

    def set_view(self, mode):
        self.context.set_setting("view", mode)
        self.apply_view()
        self.tabs.setCurrentIndex(0)

    def set_descending(self, descending):
        self.save_order(self.current_order()[0], descending)

    def change_tab(self, index):
        self.pages.setCurrentIndex(index)
        if index == 1:
            self.favorites.reload()
        elif index == 2:
            self.recent.reload()
        self.note.setText(
            "尚未收藏文件夹。快速设置 → 加入快速访问。"
            if index == 1 and not self.favorites.count()
            else "暂无历史记录。"
            if index == 2 and not self.recent.count()
            else ""
        )

    def add_favorite(self):
        path = self.location.text()
        if path:
            paths = saved_paths(self.context, "favorites")
            if path not in paths:
                self.context.set_setting("favorites", (paths + [path])[-64:])
            self.favorites.reload()

    def refresh(self):
        # QFileSystemModel has no public refresh API. Recreate the lazy model
        # so cached directory contents and same-path thumbnails are reread.
        old = self.model
        self.model = BrowserModel(self.context, self.panel)
        self.configure_model()
        for view in (self.tree, self.tiles):
            view.setModel(self.model)
        for column in (1, 2, 3):
            self.tree.hideColumn(column)
        self.sort_tree()
        old.stop()
        old.deleteLater()
        self.open_folder(self.location.text(), remember=False)

    def open_folder(self, directory, *, remember=True):
        if str(directory) == "":
            target = ""
        else:
            path = Path(directory).expanduser()
            if not path.is_dir():
                self.note.setText("文件夹不存在，请修改首页路径或输入其他路径。")
                return False
            target = str(path.resolve())
        if remember and (self.history_index < 0 or self.history[self.history_index] != target):
            self.history = self.history[: self.history_index + 1] + [target]
            self.history = self.history[-64:]
            self.history_index = len(self.history) - 1
        if target:
            recent = saved_paths(self.context, "recent_folders")
            updated = [target] + [entry for entry in recent if entry != target][:63]
            if updated != recent:
                self.context.set_setting("recent_folders", updated)
        previous = self.location.text()
        self.return_path = (
            previous
            if previous
            and (
                (target and str(Path(previous).parent) == target and previous != target)
                or (not target and Path(previous).parent == Path(previous))
            )
            else None
        )
        self.return_attempts = 0
        self.return_timer.stop()
        self.tabs.setCurrentIndex(0)
        self.location.setText(target)
        root = self.model.setRootPath(target)
        self.tree.setRootIndex(root)
        self.tiles.setRootIndex(root)
        self.parent_entry.setChecked(False)
        self.parent_entry.setVisible(bool(target))
        parent = str(Path(target).parent) if target else ""
        at_root = bool(target) and parent == target
        self.parent_entry.setText("..  此电脑" if at_root else "..  上层文件夹")
        self.parent_entry.setToolTip(f"双击返回：{'此电脑' if at_root else parent} · Backspace")
        self.note.setText("")
        self.sort_tree()
        if target:
            self.model.files.folders.icon(target)
        if self.return_path:
            self.return_timer.start()
        return True

    def restore_return_selection(self):
        self.return_attempts += 1
        if not self.return_path or self.return_attempts > 100:
            self.return_timer.stop()
            self.return_path = None
            return
        index = self.model.index(self.return_path)
        view = self.views.currentWidget()
        if not index.isValid() or not view.visualRect(index).isValid():
            return
        for target in (self.tree, self.tiles):
            target.setCurrentIndex(index)
            target.scrollTo(index, target.ScrollHint.PositionAtTop)
        self.return_timer.stop()

    def go_home(self):
        path = self.values()["home"]
        self.open_folder(path if Path(path).expanduser().is_dir() else str(Path.home()))
        if not Path(path).expanduser().is_dir():
            self.note.setText("系统图片目录不存在，已暂时打开用户目录。可在设置中自定义首页。")

    def go_up(self):
        path = self.location.text()
        if path:
            parent = str(Path(path).parent)
            self.open_folder("" if parent == path else parent)

    def go_back(self):
        if self.history_index > 0:
            target = self.history_index - 1
            if self.open_folder(self.history[target], remember=False):
                self.history_index = target
        else:
            self.go_up()

    def go_forward(self):
        if self.history_index + 1 < len(self.history):
            target = self.history_index + 1
            if self.open_folder(self.history[target], remember=False):
                self.history_index = target

    def select_entry(self, index):
        self.return_path = None
        self.return_timer.stop()
        self.parent_entry.setChecked(False)
        if not self.model.isDir(index):
            self.open_entry(index)

    def select_parent(self):
        self.tree.clearSelection()
        self.tiles.clearSelection()

    def enter_folder(self, index):
        if self.model.isDir(index):
            self.open_folder(self.model.filePath(index))

    def open_entry(self, index):
        if not index.isValid():
            return
        path = Path(self.model.filePath(index))
        if path.is_dir():
            self.open_folder(str(path))
            return
        if path.is_file() and not self.context.open_image(path):
            QMessageBox.warning(self.panel, "无法打开", f"无法读取图片：{path.name}")

    def deactivate(self):
        self.return_timer.stop()
        self.panel.stop()
        self.model.stop()
