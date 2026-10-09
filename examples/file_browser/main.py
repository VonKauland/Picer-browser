"""A filesystem-backed tree panel; no recursive eager scans or private host access."""

from pathlib import Path

from PySide6.QtCore import QDir, QSize, QStandardPaths, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileSystemModel,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from picer.plugins import SettingField


class Plugin:
    def activate(self, context):
        self.context = context
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
        )
        context.add_settings(self.fields, self.apply_settings)
        self.panel = QWidget()
        self.panel.setMinimumWidth(220)
        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(12, 12, 12, 12)
        toolbar = QHBoxLayout()
        for label, tip, callback in (
            ("⌂", "首页", self.go_home),
            ("↑", "上一级", self.go_up),
            ("⚙", "插件设置", context.show_settings),
        ):
            button = QPushButton(label)
            button.setFixedSize(28, 28)
            button.setToolTip(tip)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        self.sort = QComboBox()
        for key, label in self.fields[2].choices:
            self.sort.addItem(label, key)
        self.sort.currentIndexChanged.connect(self.sort_changed)
        toolbar.addWidget(self.sort, 1)
        layout.addLayout(toolbar)
        self.location = QLineEdit()
        self.location.setPlaceholderText("输入文件夹路径")
        self.location.returnPressed.connect(lambda: self.open_folder(self.location.text()))
        layout.addWidget(self.location)
        self.model = QFileSystemModel(self.panel)
        self.model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)
        self.model.setNameFilters(
            ["*.png", "*.jpg", "*.jpeg", "*.bmp", "*.gif", "*.webp", "*.tif", "*.tiff", "*.ico"]
        )
        self.model.setNameFilterDisables(False)
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(True)
        self.tree.setAnimated(True)
        self.tree.setHeaderHidden(True)
        for column in (1, 2, 3):
            self.tree.hideColumn(column)
        self.tree.clicked.connect(self.open_entry)
        layout.addWidget(self.tree, 1)
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
        self.tree.setIconSize(QSize(values["icon_size"], values["icon_size"]))
        self.sort.blockSignals(True)
        self.sort.setCurrentIndex(self.sort.findData(values["sort"]))
        self.sort.blockSignals(False)
        self.sort_tree()
        self.go_home()

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

    def open_folder(self, directory):
        path = Path(directory).expanduser()
        if not path.is_dir():
            self.note.setText("文件夹不存在，请修改首页路径或输入其他路径。")
            return
        self.location.setText(str(path.resolve()))
        self.location.setToolTip(str(path.resolve()))
        self.location.setCursorPosition(0)
        self.tree.setRootIndex(self.model.setRootPath(str(path.resolve())))
        self.note.setText("")

    def go_home(self):
        path = self.values()["home"]
        self.open_folder(path if Path(path).expanduser().is_dir() else str(Path.home()))
        if not Path(path).expanduser().is_dir():
            self.note.setText("系统图片目录不存在，已暂时打开用户目录。可在设置中自定义首页。")

    def go_up(self):
        self.open_folder(str(Path(self.location.text()).parent))

    def open_entry(self, index):
        path = Path(self.model.filePath(index))
        if path.is_file() and not self.context.open_image(path):
            QMessageBox.warning(self.panel, "无法打开", f"无法读取图片：{path.name}")
