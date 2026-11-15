"""Opt-in local image/folder tags with a bottom-anchored upward library drawer."""

import sqlite3
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from picer.color_picker import ColorPicker
from picer.host_style import prepare_popup
from picer.i18n import tr
from picer.messages import MessageBox
from picer.ui import StyledDialog, Toggle, colors_for, ui_icon

from .store import TagStore
from .widgets import TagList

PALETTE = ("#488FFF", "#FF9D42", "#44CFC1", "#F65B62", "#A271F1", "#A0A0A0")


def pick_color(initial, parent):
    dialog = ColorPicker(initial, parent, title="标签颜色", subtitle="")
    dialog.follow.hide()
    try:
        return dialog.selected_value if dialog.exec() else None
    finally:
        dialog.deleteLater()


class TagEditor(StyledDialog):
    def __init__(self, owner, tag=None):
        super().__init__(tr("编辑标签") if tag else tr("新建标签"), "", owner.panel)
        self.owner, self.tag = owner, tag
        self.result_id = None
        self.color = tag["color"] if tag else PALETTE[0]
        self.name = QLineEdit(tag["name"] if tag else "")
        self.name.setMaxLength(64)
        self.name.setPlaceholderText(tr("标签名称"))
        self.name.setAccessibleName(tr("标签名称"))
        self.body.addWidget(self.name)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("标签颜色")))
        self.color_button = QPushButton(self.color)
        self.color_button.clicked.connect(self.choose_color)
        row.addWidget(self.color_button)
        self.body.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("标签可见")), 1)
        self.visible_toggle = Toggle()
        self.visible_toggle.setAccessibleName(tr("标签可见"))
        self.visible_toggle.setChecked(bool(tag["visible"]) if tag else True)
        row.addWidget(self.visible_toggle)
        self.body.addLayout(row)
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton(tr("取消"))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        save = QPushButton(tr("保存"))
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save)
        row.addWidget(save)
        self.body.addLayout(row)
        self.resize(360, 270)

    def choose_color(self):
        if value := pick_color(self.color, self):
            self.color = value
            self.color_button.setText(value)

    def save(self):
        def write():
            self.result_id = self.owner.store.save(
                self.name.text(),
                self.color,
                self.visible_toggle.isChecked(),
                self.tag["id"] if self.tag else None,
            )

        if self.owner.operation(write):
            self.accept()


class Plugin(QObject):
    def activate(self, context):
        self.context, self.active = context, True
        self.store = TagStore(context.data_directory() / "tags.sqlite3")
        self.folder_override, self.selected_tag = None, None
        self.panel = QWidget()
        self.setParent(self.panel)
        self.panel.setMinimumWidth(230)
        self.panel.installEventFilter(self)
        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(9)
        row = QHBoxLayout()
        self.scope = QButtonGroup(self.panel)
        for index, (label, icon) in enumerate(((tr("图片"), "photo"), (tr("文件夹"), "folder"))):
            button = QPushButton(label)
            button.setIcon(ui_icon(icon))
            button.setCheckable(True)
            button.setStyleSheet(
                "QPushButton:checked { background:#515155; border:1px solid #626266; }"
            )
            self.scope.addButton(button, index)
            row.addWidget(button)
        self.scope.button(0).setChecked(True)
        self.scope.idClicked.connect(lambda _: self.render())
        layout.addLayout(row)
        row = QHBoxLayout()
        self.target_name = QLabel()
        self.target_name.setWordWrap(True)
        row.addWidget(self.target_name, 1)
        self.choose_folder = QPushButton()
        self.choose_folder.setIcon(ui_icon("folder"))
        self.choose_folder.setObjectName("circleButton")
        self.choose_folder.setFixedSize(30, 30)
        self.choose_folder.setAccessibleName(tr("选择文件夹"))
        self.choose_folder.setToolTip(tr("选择文件夹"))
        self.choose_folder.clicked.connect(self.select_folder)
        row.addWidget(self.choose_folder)
        layout.addLayout(row)
        self.target_path = QLabel()
        self.target_path.setWordWrap(True)
        self.target_path.setMaximumHeight(40)
        self.target_path.setObjectName("muted")
        layout.addWidget(self.target_path)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("显示隐藏标签")), 1)
        self.show_hidden = Toggle()
        self.show_hidden.setAccessibleName(tr("显示隐藏标签"))
        self.show_hidden.setChecked(context.get_setting("show_hidden", False) is True)
        self.show_hidden.toggled.connect(self.hidden_changed)
        row.addWidget(self.show_hidden)
        layout.addLayout(row)
        hint = QLabel(tr("实线为可见，虚线为隐藏"))
        hint.setObjectName("muted")
        layout.addWidget(hint)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("当前标签")), 1)
        self.count = QLabel()
        row.addWidget(self.count)
        layout.addLayout(row)
        self.chips = TagList()
        self.chips.removeRequested.connect(self.remove_tag)
        layout.addWidget(self.chips)
        self.add = QPushButton("+ " + tr("添加标签"))
        self.add.clicked.connect(self.add_tag)
        layout.addWidget(self.add, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        self.footer = QWidget()
        row = QHBoxLayout(self.footer)
        row.setContentsMargins(0, 0, 0, 0)
        self.library_button = QPushButton()
        self.library_button.setCheckable(True)
        self.library_button.setAccessibleName(tr("标签库"))
        self.library_button.setMinimumHeight(36)
        self.library_button.toggled.connect(self.toggle_library)
        row.addWidget(self.library_button, 1)
        self.create = QPushButton("+")
        self.create.setObjectName("circleButton")
        self.create.setFixedSize(32, 32)
        self.create.setAccessibleName(tr("新建标签"))
        self.create.setToolTip(tr("新建标签"))
        self.create.clicked.connect(lambda: self.edit_tag())
        row.addWidget(self.create)
        layout.addWidget(self.footer)
        self.drawer = QFrame(self.panel)
        self.drawer.setObjectName("tagLibrary")
        drawer = QVBoxLayout(self.drawer)
        drawer.setContentsMargins(10, 10, 10, 10)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("搜索标签"))
        self.search.setAccessibleName(tr("搜索标签"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.render_library)
        drawer.addWidget(self.search)
        self.library = TagList(library=True)
        self.library.itemClicked.connect(self.library_clicked)
        self.library.currentItemChanged.connect(self.library_current)
        self.library.visibilityRequested.connect(self.toggle_visibility)
        self.library.editRequested.connect(self.tag_menu)
        drawer.addWidget(self.library, 1)
        self.empty = QLabel(tr("尚无标签"))
        drawer.addWidget(self.empty)
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(QLabel(tr("标签颜色")), 1)
        self.color_buttons = []
        for color in PALETTE:
            button = QPushButton()
            button.setFixedSize(18, 18)
            button.setAccessibleName(color)
            button.setStyleSheet(
                f"background:{color}; border-radius:9px; border:none; padding:0; min-height:0;"
            )
            button.clicked.connect(lambda _, color=color: self.set_color(color))
            row.addWidget(button)
            self.color_buttons.append(button)
        custom = QPushButton("…")
        custom.setObjectName("circleButton")
        custom.setFixedSize(22, 22)
        custom.setToolTip(tr("自定义标签颜色"))
        custom.setAccessibleName(tr("自定义标签颜色"))
        custom.clicked.connect(self.custom_color)
        row.addWidget(custom)
        self.color_buttons.append(custom)
        drawer.addLayout(row)
        self.drawer.hide()
        self.dock = context.add_panel(self.panel, area="right")
        context.subscribe("image.opened", self.on_image)
        context.subscribe("appearance.changed", self.appearance)
        self.appearance({})
        self.render()
        self.library_button.setChecked(context.get_setting("library_open", False) is True)

    # QWidget event filters need QObject ownership for automatic disconnection.
    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.position_drawer()
        return False

    def operation(self, callback):
        if not self.active:
            return False
        try:
            callback()
        except (OSError, ValueError, sqlite3.Error) as error:
            MessageBox.warning(self.panel, tr("标签操作失败"), str(error))
            return False
        return True

    def target(self):
        current = self.context.current_path()
        if self.scope.checkedId() == 0:
            return current, "image"
        return self.folder_override or (current.parent if current else None), "folder"

    def on_image(self, event):
        self.folder_override = None
        self.render()

    def select_folder(self):
        path, _ = self.target()
        folder = QFileDialog.getExistingDirectory(self.panel, tr("选择文件夹"), str(path or ""))
        if folder:
            self.folder_override = Path(folder)
            self.render()

    def hidden_changed(self, value):
        self.context.set_setting("show_hidden", value)
        self.render()

    def render(self):
        path, kind = self.target()
        self.target_name.setText(path.name if path else tr("打开图片或选择文件夹"))
        self.target_path.setText(str(path.parent) if path else "")
        self.target_name.setToolTip(str(path or ""))
        self.choose_folder.setVisible(kind == "folder")
        self.add.setEnabled(path is not None)
        self.chips.clear()
        assigned = self.store.assigned(path, kind) if path else set()
        for tag in self.store.tags():
            if tag["id"] in assigned and (tag["visible"] or self.show_hidden.isChecked()):
                self.add_item(self.chips, tag)
        self.count.setText(str(self.chips.count()))
        self.chips.fit_height()
        self.render_library()

    @staticmethod
    def add_item(view, tag):
        item = QListWidgetItem(tag["name"])
        item.setData(Qt.ItemDataRole.UserRole, tag)
        item.setToolTip(tag["name"])
        if not view.library:
            item.setSizeHint(
                QSize(min(200, view.fontMetrics().horizontalAdvance(tag["name"]) + 42), 32)
            )
        view.addItem(item)
        return item

    def render_library(self):
        wanted = self.selected_tag
        self.library.blockSignals(True)
        self.library.clear()
        selected = None
        query = self.search.text().strip().casefold()
        tags = self.store.tags()
        for tag in tags:
            if (tag["visible"] or self.show_hidden.isChecked()) and query in tag["name"].casefold():
                item = self.add_item(self.library, tag)
                if tag["id"] == wanted:
                    selected = item
        self.library.blockSignals(False)
        self.library.setCurrentItem(selected or self.library.item(0))
        self.library_current(self.library.currentItem(), None)
        self.empty.setVisible(self.library.count() == 0)
        arrow = "▾" if self.library_button.isChecked() else "▴"
        self.library_button.setText(f"{arrow}  {tr('标签库')}    {len(tags)}")
        self.position_drawer()

    def library_current(self, current, previous):
        self.selected_tag = current.data(Qt.ItemDataRole.UserRole)["id"] if current else None
        for button in self.color_buttons:
            button.setEnabled(current is not None)

    def toggle_library(self, value):
        self.context.set_setting("library_open", value)
        self.drawer.setVisible(value)
        self.render_library()
        if value:
            self.drawer.raise_()

    def position_drawer(self):
        if not hasattr(self, "drawer"):
            return
        bottom = self.footer.y() - 6
        content_height = max(160, min(390, self.library.count() * 40 + 102))
        content_height = max(content_height, self.drawer.minimumSizeHint().height())
        height = max(0, min(content_height, bottom - 8))
        self.drawer.setGeometry(12, bottom - height, max(1, self.panel.width() - 24), height)

    def add_tag(self):
        if not self.store.tags():
            self.edit_tag(assign=True)
        else:
            self.library_button.setChecked(True)
            self.search.setFocus()

    def library_clicked(self, item):
        tag = item.data(Qt.ItemDataRole.UserRole)
        self.selected_tag = tag["id"]
        path, kind = self.target()
        if path:
            enabled = tag["id"] not in self.store.assigned(path, kind)
            self.operation(lambda: self.store.assign(path, kind, tag["id"], enabled))
            self.render()

    def remove_tag(self, tag_id):
        path, kind = self.target()
        if path:
            self.operation(lambda: self.store.assign(path, kind, tag_id, False))
            self.render()

    def tag(self, tag_id=None):
        return next(
            (tag for tag in self.store.tags() if tag["id"] == (tag_id or self.selected_tag)), None
        )

    def edit_tag(self, tag_id=None, *, assign=False):
        dialog = TagEditor(self, self.tag(tag_id) if tag_id else None)
        try:
            if dialog.exec():
                self.selected_tag = dialog.result_id
                path, kind = self.target()
                if assign and path:
                    self.operation(lambda: self.store.assign(path, kind, dialog.result_id, True))
                self.render()
        finally:
            dialog.deleteLater()

    def toggle_visibility(self, tag_id):
        if tag := self.tag(tag_id):
            self.operation(
                lambda: self.store.save(tag["name"], tag["color"], not tag["visible"], tag_id)
            )
            self.render()

    def set_color(self, color):
        if tag := self.tag():
            self.operation(lambda: self.store.save(tag["name"], color, tag["visible"], tag["id"]))
            self.render()

    def custom_color(self):
        if tag := self.tag():
            if value := pick_color(tag["color"], self.panel):
                self.set_color(value)

    def tag_menu(self, tag_id):
        self.selected_tag = tag_id
        menu = QMenu(self.panel)
        prepare_popup(menu)
        menu.addAction(tr("编辑标签"), lambda: self.edit_tag(tag_id))
        menu.addAction(tr("删除标签"), lambda: self.delete_tag(tag_id))
        menu.exec(self.library.mapToGlobal(self.library.rect().center()))
        menu.deleteLater()

    def delete_tag(self, tag_id):
        if (
            MessageBox.question(
                self.panel,
                tr("删除标签"),
                tr("删除标签及其所有关联？"),
                MessageBox.StandardButton.Yes | MessageBox.StandardButton.No,
                MessageBox.StandardButton.No,
            )
            == MessageBox.StandardButton.Yes
        ):
            self.operation(lambda: self.store.delete(tag_id))
            self.render()

    def appearance(self, event):
        colors = colors_for(self.panel)
        border = QColor(self.context.accent_color()).darker(260).name()
        self.drawer.setStyleSheet(
            f"QFrame#tagLibrary {{ background:{colors['menu']}; border:1px solid {border};"
            "border-radius:12px; }"
        )
        self.chips.viewport().update()
        self.library.viewport().update()

    def deactivate(self):
        self.active = False
        self.drawer.hide()
        self.panel.removeEventFilter(self)
