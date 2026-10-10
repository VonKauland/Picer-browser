"""A filesystem-backed tree panel; no recursive eager scans or private host access."""

from pathlib import Path

from PySide6.QtCore import QDir, QSize, QStandardPaths, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListView,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
)

from picer.imaging import supported_suffixes
from picer.plugins import SettingField, ui_icon

from .address import AddressBar
from .input import BrowserPanel, ParentEntry
from .model import BrowserModel
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
                "排序方式",
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
        self.view_button.clicked.connect(self.toggle_view)
        toolbar.addWidget(self.view_button)
        layout.addLayout(toolbar)
        self.location = AddressBar(self.panel)
        self.location.pathRequested.connect(self.open_folder)
        layout.addWidget(self.location)
        self.parent_entry = ParentEntry()
        self.parent_entry.activated.connect(self.go_up)
        self.parent_entry.clicked.connect(self.select_parent)
        layout.addWidget(self.parent_entry)
        self.model = BrowserModel(context, self.panel)
        self.parent_entry.setIcon(self.model.files.folders.icons[0])
        self.model.files.setFilter(
            QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot
        )
        self.model.files.setNameFilters([f"*{suffix}" for suffix in sorted(supported_suffixes())])
        self.model.files.setNameFilterDisables(False)
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
        layout.addWidget(self.views, 1)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.dock = context.add_panel(self.panel, area="left")
        self.apply_settings()

    def values(self):
        return {
            field.key: field.validate(self.context.get_setting(field.key, field.default))
            for field in self.fields
        }

    def apply_settings(self):
        values = self.values()
        self.apply_icon_size()
        self.apply_view()
        self.sort.blockSignals(True)
        self.sort.setCurrentIndex(self.sort.findData(values["sort"]))
        self.sort.blockSignals(False)
        self.sort_tree()
        self.go_home()

    def apply_icon_size(self):
        size = self.values()["icon_size"]
        self.parent_entry.setIconSize(QSize(size, size))
        self.parent_entry.setFixedHeight(size + 14)
        self.tree.setIconSize(QSize(size, size))
        self.tiles.setIconSize(QSize(size * 2, size * 2))
        self.tiles.setGridSize(QSize(size * 2 + 32, size * 2 + 40))

    def resize_icons(self, steps):
        field = self.fields[1]
        size = max(field.minimum, min(field.maximum, self.values()["icon_size"] + steps * 4))
        self.context.set_setting("icon_size", size)
        self.apply_icon_size()

    def sort_tree(self):
        values = self.values()
        column = {"name": 0, "size": 1, "type": 2, "modified": 3}[values["sort"]]
        order = (
            Qt.SortOrder.DescendingOrder if values["descending"] else Qt.SortOrder.AscendingOrder
        )
        self.tree.sortByColumn(column, order)

    def sort_changed(self):
        self.context.set_setting("sort", self.sort.currentData())
        self.sort_tree()

    def apply_view(self):
        tiled = self.values()["view"] == "tiles"
        self.views.setCurrentWidget(self.tiles if tiled else self.tree)
        self.view_button.setIcon(ui_icon("grid" if not tiled else "list"))
        self.view_button.setToolTip("切换到列表视图" if tiled else "切换到平铺视图")
        self.view_button.setAccessibleName(self.view_button.toolTip())

    def toggle_view(self):
        self.context.set_setting("view", "list" if self.values()["view"] == "tiles" else "tiles")
        self.apply_view()

    def open_folder(self, directory, *, remember=True):
        path = Path(directory).expanduser()
        if not path.is_dir():
            self.note.setText("文件夹不存在，请修改首页路径或输入其他路径。")
            return False
        path = path.resolve()
        if remember and (self.history_index < 0 or self.history[self.history_index] != path):
            self.history = self.history[: self.history_index + 1] + [path]
            self.history = self.history[-64:]
            self.history_index = len(self.history) - 1
        self.location.setText(str(path))
        self.location.setToolTip(str(path.resolve()))
        root = self.model.setRootPath(str(path.resolve()))
        self.tree.setRootIndex(root)
        self.tiles.setRootIndex(root)
        self.parent_entry.setChecked(False)
        self.parent_entry.setVisible(path.parent != path)
        self.parent_entry.setToolTip(f"双击返回：{path.parent} · Backspace")
        self.note.setText("")
        return True

    def go_home(self):
        path = self.values()["home"]
        self.open_folder(path if Path(path).expanduser().is_dir() else str(Path.home()))
        if not Path(path).expanduser().is_dir():
            self.note.setText("系统图片目录不存在，已暂时打开用户目录。可在设置中自定义首页。")

    def go_up(self):
        self.open_folder(str(Path(self.location.text()).parent))

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
        self.panel.stop()
        self.model.stop()
