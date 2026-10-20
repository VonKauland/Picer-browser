"""A filesystem-backed tree panel; no recursive eager scans or private host access."""

import random
from pathlib import Path

from PySide6.QtCore import QDir, QSize, QStandardPaths, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMenu,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from picer.file_drag import ImageFileDrag
from picer.host_style import PLUGIN_STYLE
from picer.i18n import tr
from picer.imaging import supported_suffixes
from picer.messages import MessageBox as QMessageBox
from picer.plugins import SettingField, ui_icon

from .address import AddressBar
from .input import BrowserPanel, ParentEntry
from .model import BrowserModel
from .network import NetworkLocations, is_network_path, normalize_path
from .places import PlacesList, navigation_tabs, saved_paths
from .thumbnails import PhotoTree, configure_view


class Plugin:
    def activate(self, context):
        self.active = True
        self.context = context
        self.history = []
        self.history_index = -1
        self.home = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.PicturesLocation
        )
        self.fields = (
            SettingField("home", tr("首页路径"), "path", self.home or str(Path.home())),
            SettingField("icon_size", tr("图标大小（像素）"), "int", 24, 16, 64),
            SettingField(
                "sort",
                tr("普通文件夹默认排序"),
                "choice",
                "name",
                choices=(
                    ("name", tr("名称")),
                    ("size", tr("大小")),
                    ("type", tr("类型")),
                    ("modified", tr("修改时间")),
                ),
            ),
            SettingField("descending", tr("倒序排列"), "bool", False),
            SettingField(
                "view",
                tr("浏览视图"),
                "choice",
                "list",
                choices=(("list", tr("列表")), ("tiles", tr("平铺"))),
            ),
        )
        self.fields += (
            SettingField(
                "photo_sort",
                tr("图片文件夹默认排序"),
                "choice",
                "name",
                choices=self.fields[2].choices,
            ),
        )
        context.add_settings(self.fields, self.apply_settings)
        self.panel = BrowserPanel(
            self.resize_icons, self.go_up, self.go_back, self.go_forward, context
        )
        self.panel.setMinimumWidth(220)
        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(12, 12, 12, 12)
        toolbar = QHBoxLayout()
        for icon, tip, callback in (
            ("home", tr("首页"), self.go_home),
            ("up", tr("上一级"), self.go_up),
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
        self.view_button.setToolTip(tr("快速设置"))
        self.view_button.setAccessibleName(tr("快速设置"))
        self.create_quick_menu()
        self.view_button.clicked.connect(self.show_quick_menu)
        toolbar.addWidget(self.view_button)
        layout.addLayout(toolbar)
        self.location = AddressBar(self.panel)
        self.location.pathRequested.connect(self.open_folder)
        layout.addWidget(self.location)
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("搜索当前文件夹"))
        self.search.setAccessibleName(tr("搜索当前级的文件和文件夹"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.search_changed)
        search_row.addWidget(self.search, 1)
        self.random_button = QPushButton()
        self.random_button.setObjectName("circleButton")
        self.random_button.setFixedSize(32, 32)
        self.random_button.setIcon(ui_icon("shuffle"))
        self.random_button.setToolTip(tr("随机定位一个当前层文件夹"))
        self.random_button.setAccessibleName(tr("随机定位文件夹"))
        self.random_button.clicked.connect(self.random_folder)
        search_row.addWidget(self.random_button)
        layout.addLayout(search_row)
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
        self.file_drags = [
            ImageFileDrag(
                view,
                lambda index: None if self.model.isDir(index) else self.model.filePath(index),
                context.readable_suffixes,
            )
            for view in (self.tree, self.tiles)
        ]
        self.views = QStackedWidget()
        self.views.addWidget(self.tree)
        self.views.addWidget(self.tiles)
        files_layout.addWidget(self.views, 1)
        self.favorites = PlacesList(self, "favorites")
        self.recent = PlacesList(self, "recent_folders")
        self.pages.addWidget(self.favorites)
        self.pages.addWidget(self.recent)
        self.network = NetworkLocations(self)
        self.pages.addWidget(self.network)
        self.tabs.currentChanged.connect(self.change_tab)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.dock = context.add_panel(self.panel, area="left")
        for operation, callback in (
            ("browser.parent", self.go_up),
            ("browser.selected", self.open_selected),
            ("browser.favorite", self.add_favorite),
        ):
            context.bind_panel_operation(operation, callback)
        self.return_path = None
        self.return_timer = QTimer(self.panel)
        self.return_timer.setInterval(30)
        self.return_timer.timeout.connect(self.restore_return_selection)
        self.image_selection_path = None
        self.image_timer = QTimer(self.panel)
        self.image_timer.setInterval(30)
        self.image_timer.timeout.connect(self.sync_image_selection)
        context.subscribe("image.opened", self.on_image)
        context.subscribe("appearance.changed", self.on_appearance)
        self.on_appearance({"accent": context.accent_color()})
        self.apply_settings()
        self.favorites.reload()
        self.recent.reload()

    def on_image(self, event):
        path = self.context.current_path()
        if path is None or str(path.parent) != self.location.text():
            return
        self.image_selection_path = str(path)
        self.image_selection_attempts = 0
        self.image_timer.start()
        self.sync_image_selection()

    def sync_image_selection(self):
        path = self.image_selection_path
        self.image_selection_attempts += 1
        if not path or str(Path(path).parent) != self.location.text():
            self.image_timer.stop()
            self.image_selection_path = None
            return
        if self.image_selection_attempts > 100:
            self.image_timer.stop()
            return  # directoryLoaded can resume this request without busy polling.
        index = self.model.index(path)
        if not index.isValid() and self.search.text():
            self.search.clear()
            index = self.model.index(path)
        if not index.isValid():
            return
        self.parent_entry.setChecked(False)
        for view in (self.tree, self.tiles):
            view.setCurrentIndex(index)
            view.scrollTo(index, view.ScrollHint.EnsureVisible)
        self.image_timer.stop()
        self.image_selection_path = None

    def on_appearance(self, event):
        formats = frozenset(event.get("formats", supported_suffixes()))
        if hasattr(self, "readable_formats") and formats != self.readable_formats:
            self.readable_formats = formats
            self.refresh()
        self.readable_formats = formats
        self.parent_entry.set_accent(event["accent"])
        self.tabs.set_accent(event["accent"])
        for view in (self.tree, self.tiles, self.favorites, self.recent, self.network.list):
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
        self.network.reload()

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
        self.model.files.setNameFilters(
            [f"*{suffix}" for suffix in sorted(self.context.readable_suffixes())]
            or ["*.picer-no-enabled-format"]
        )
        self.model.files.setNameFilterDisables(False)
        self.model.files.folderClassified.connect(self.folder_classified)
        self.model.files.directoryLoaded.connect(self.directory_loaded)

    def directory_loaded(self, path):
        # A huge folder can finish after the bounded selection retry timer.
        # Recheck only its current image; never navigate away from the browser's path.
        if not self.active or self.model.stopped:
            return
        current = self.context.current_path()
        if (
            self.image_selection_path
            and current is not None
            and Path(path) == Path(self.location.text()) == current.parent
        ):
            self.on_image(None)

    def create_quick_menu(self):
        self.quick_menu = QMenu(self.panel)
        self.quick_menu.setStyleSheet(PLUGIN_STYLE)
        self.quick_actions = {}
        for key, label, callback, checkable in (
            ("tiles", tr("平铺视图"), lambda: self.set_view("tiles"), True),
            ("list", tr("列表视图"), lambda: self.set_view("list"), True),
            (None, None, None, False),
            ("refresh", tr("刷新"), self.refresh, False),
            (None, None, None, False),
            ("ascending", tr("正序排列"), lambda: self.set_descending(False), True),
            ("descending", tr("倒序排列"), lambda: self.set_descending(True), True),
            (None, None, None, False),
            ("favorite", tr("加入快速访问"), self.add_favorite, False),
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
            self.tabs.currentIndex() != 3
            and bool(path)
            and path not in saved_paths(self.context, "favorites")
        )
        for key in ("ascending", "descending"):
            self.quick_actions[key].setEnabled(self.tabs.currentIndex() != 3)

    def set_view(self, mode):
        self.context.set_setting("view", mode)
        self.apply_view()
        self.tabs.setCurrentIndex(0)

    def set_descending(self, descending):
        self.save_order(self.current_order()[0], descending)

    def change_tab(self, index):
        network = index == 3
        previous_network = self.pages.currentWidget() is self.network
        self.pages.setCurrentIndex(index)
        if network != previous_network:
            self.network.cancel_navigation()
            self.search.clear()
            self.model.set_search("")
        self.location.set_virtual(tr("网络位置") if network else None)
        self.search.setPlaceholderText(tr("搜索网络位置") if network else tr("搜索当前文件夹"))
        self.search.setAccessibleName(
            tr("搜索已保存的网络位置") if network else tr("搜索当前级的文件和文件夹")
        )
        self.random_button.setEnabled(not network)
        self.sort.setEnabled(not network)
        if index == 1:
            self.favorites.reload()
        elif index == 2:
            self.recent.reload()
        elif network:
            self.network.show_saved()
        self.note.setText(
            tr("尚未收藏文件夹。快速设置 → 加入快速访问。")
            if index == 1 and not self.favorites.count()
            else tr("暂无历史记录。")
            if index == 2 and not self.recent.count()
            else ""
        )

    def search_changed(self, text):
        if self.tabs.currentIndex() == 3:
            self.network.reload()
        else:
            self.model.set_search(text)

    def add_favorite(self):
        if self.tabs.currentIndex() == 3:
            return
        path = self.location.text()
        if path:
            paths = saved_paths(self.context, "favorites")
            if path not in paths:
                self.context.set_setting("favorites", (paths + [path])[-64:])
            self.favorites.reload()
            self.context.notify(tr("已加入快速访问"))

    def open_selected(self):
        if self.pages.currentWidget() is self.files_page and self.parent_entry.isChecked():
            self.go_up()
        elif self.pages.currentWidget() is self.files_page:
            index = self.views.currentWidget().currentIndex()
            if index.isValid() and self.model.isDir(index):
                self.enter_folder(index)
        else:
            view = self.pages.currentWidget()
            if view is self.network:
                self.network.open_item(self.network.list.currentItem())
                return
            item = view.currentItem()
            if item is not None:
                self.open_folder(item.data(Qt.ItemDataRole.UserRole))

    def random_folder(self):
        path = self.location.text()
        if not path:
            return
        # QFileSystemModel enumerates only the current level in its own worker.
        # Select a source row so hidden search matches can also be located.
        source = self.model.files
        root = source.index(path)
        folders = [
            source.filePath(index)
            for row in range(source.rowCount(root))
            if source.isDir(index := source.index(row, 0, root))
        ]
        if not folders:
            return
        target = random.choice(folders)
        self.search.clear()
        self.tabs.setCurrentIndex(0)
        index = self.model.index(target)
        self.return_path = None
        self.return_timer.stop()
        self.image_timer.stop()
        self.image_selection_path = None
        self.parent_entry.setChecked(False)
        for view in (self.tree, self.tiles):
            view.setCurrentIndex(index)
            view.scrollTo(index, view.ScrollHint.PositionAtCenter)

    def refresh(self):
        if self.tabs.currentIndex() == 3:
            self.network.reload()
            return
        query = self.search.text()
        # QFileSystemModel has no public refresh API. Recreate the lazy model
        # so cached directory contents and same-path thumbnails are reread.
        old = self.model
        self.model = BrowserModel(self.context, self.panel)
        self.configure_model()
        self.model.set_search(self.search.text())
        for view in (self.tree, self.tiles):
            view.setModel(self.model)
        for column in (1, 2, 3):
            self.tree.hideColumn(column)
        self.sort_tree()
        old.stop()
        old.deleteLater()
        self.open_folder(
            self.location.text(), remember=False, on_open=lambda: self.search.setText(query)
        )

    def open_folder(self, directory, *, remember=True, on_open=None, _network_ready=False):
        if is_network_path(str(directory)) and not _network_ready:
            self.network.open_path(str(directory), remember, on_open)
            return False
        self.network.cancel_navigation()
        if str(directory) == "":
            target = ""
        elif _network_ready:
            target = normalize_path(str(directory))
        else:
            path = Path(directory).expanduser()
            if not path.is_dir():
                self.note.setText(tr("文件夹不存在，请修改首页路径或输入其他路径。"))
                return False
            target = str(path.resolve())
        self.remember_location(target, remember)
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
        self.image_timer.stop()
        self.image_selection_path = None
        self.return_timer.stop()
        self.tabs.setCurrentIndex(0)
        self.search.clear()
        self.location.setText(target)
        root = self.model.setRootPath(target)
        self.tree.setRootIndex(root)
        self.tiles.setRootIndex(root)
        self.parent_entry.setChecked(False)
        self.parent_entry.setVisible(bool(target))
        parent = str(Path(target).parent) if target else ""
        at_root = bool(target) and parent == target
        if is_network_path(target) and len(target[2:].rstrip("\\").split("\\")) == 2:
            parent, at_root = "\\\\" + target[2:].split("\\")[0], False
        self.parent_entry.setText(tr("..  此电脑") if at_root else tr("..  上层文件夹"))
        self.parent_entry.setToolTip(
            tr("双击返回：{0} · Backspace").format("此电脑" if at_root else parent)
        )
        self.note.setText("")
        self.sort_tree()
        if target:
            self.model.files.folders.icon(target)
        if self.return_path:
            self.return_timer.start()
        elif self.context.current_path() and str(self.context.current_path().parent) == target:
            self.on_image(None)
        if on_open:
            on_open()
        return True

    def remember_location(self, target, remember=True):
        if remember and (self.history_index < 0 or self.history[self.history_index] != target):
            self.history = (self.history[: self.history_index + 1] + [target])[-64:]
            self.history_index = len(self.history) - 1

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
        if is_network_path(path):
            self.open_folder(path)
            return
        self.open_folder(path if Path(path).expanduser().is_dir() else str(Path.home()))
        if not Path(path).expanduser().is_dir():
            self.note.setText(tr("系统图片目录不存在，已暂时打开用户目录。可在设置中自定义首页。"))

    def go_up(self):
        if self.tabs.currentIndex() == 3 and self.network.server:
            self.network.show_saved()
            return
        path = self.location.text()
        if path:
            if is_network_path(path) and len(path[2:].rstrip("\\").split("\\")) == 2:
                self.open_folder("\\\\" + path[2:].split("\\")[0])
                return
            parent = str(Path(path).parent)
            self.open_folder("" if parent == path else parent)

    def go_back(self):
        if self.tabs.currentIndex() == 3 and self.network.server:
            self.network.show_saved()
            return
        if self.history_index > 0:
            target = self.history_index - 1
            self.open_folder(
                self.history[target],
                remember=False,
                on_open=lambda: setattr(self, "history_index", target),
            )
        else:
            self.go_up()

    def go_forward(self):
        if self.history_index + 1 < len(self.history):
            target = self.history_index + 1
            self.open_folder(
                self.history[target],
                remember=False,
                on_open=lambda: setattr(self, "history_index", target),
            )

    def select_entry(self, index):
        self.image_timer.stop()
        self.image_selection_path = None
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
            QMessageBox.warning(
                self.panel, tr("无法打开"), tr("无法读取图片：{0}").format(path.name)
            )

    def deactivate(self):
        for drag in self.file_drags:
            drag.stop()
        self.active = False
        self.network.stop()
        self.image_timer.stop()
        self.return_timer.stop()
        self.panel.stop()
        self.model.stop()
