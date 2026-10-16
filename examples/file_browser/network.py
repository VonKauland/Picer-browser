"""Saved UNC locations without probing offline servers while drawing the list."""

import json
import ntpath
from pathlib import Path, PureWindowsPath

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from picer.host_style import PLUGIN_STYLE, mark_host
from picer.plugins import PluginError, ui_icon
from picer.ui import StyledDialog, colors_for

from .icons import folder_icon
from .thumbnails import configure_view, paint_item


def is_network_path(path):
    return isinstance(path, str) and path.replace("/", "\\").startswith("\\\\")


def normalize_path(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("请输入有效的网络共享路径")
    value = value.strip().replace("/", "\\")
    if not is_network_path(value) or any(ord(c) < 32 or c in '<>:"|?*' for c in value):
        raise ValueError("请输入网络共享路径，例如 \\\\NAS\\Photos")
    path = PureWindowsPath(ntpath.normpath(value))
    parts = path.drive[2:].split("\\")
    if len(parts) != 2 or any(p in ("", ".", "..") for p in parts) or not path.is_absolute():
        raise ValueError("路径需要包含服务器及共享文件夹")
    return str(path)


def saved_locations(context):
    entries = context.get_setting("network_locations", [])
    if not isinstance(entries, list):
        return []
    result, seen = [], set()
    for entry in entries[:64]:
        try:
            path = normalize_path(entry["path"])
            name = entry["name"].strip()
            if not name or len(name) > 48 or any(ord(c) < 32 for c in name):
                continue
            if path.casefold() not in seen:
                result.append({"name": name, "path": path})
                seen.add(path.casefold())
        except (KeyError, TypeError, AttributeError, ValueError):
            continue
    return result


class LocationDialog(StyledDialog):
    def __init__(self, entries, parent):
        super().__init__("添加网络位置", parent=parent)
        self.resize(440, 320)
        self.entries = entries
        self.result_entry = None
        self.body.addWidget(QLabel("名称"))
        self.name = QLineEdit()
        self.name.setMaxLength(48)
        self.name.setPlaceholderText("例如：家庭 NAS")
        self.body.addWidget(self.name)
        self.body.addWidget(QLabel("网络路径"))
        self.path = QLineEdit()
        self.path.setMaxLength(2048)
        self.path.setPlaceholderText(r"\\NAS\Photos")
        self.body.addWidget(self.path)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.body.addWidget(self.error)
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.confirm = QPushButton("添加")
        self.confirm.setObjectName("primaryButton")
        self.confirm.clicked.connect(self.accept)
        row.addWidget(self.confirm)
        self.body.addLayout(row)
        self.name.textChanged.connect(self.check)
        self.path.textChanged.connect(self.check)
        self.check()
        mark_host(self)

    def check(self):
        self.result_entry = None
        try:
            path = normalize_path(self.path.text())
            parsed = PureWindowsPath(path)
            name = self.name.text().strip() or parsed.name or parsed.drive.split("\\")[-1]
            if any(ord(c) < 32 for c in name) or len(name) > 48:
                raise ValueError("名称最多 48 个字符")
            if any(row["path"].casefold() == path.casefold() for row in self.entries):
                raise ValueError("该网络位置已添加")
            if len(self.entries) >= 64:
                raise ValueError("最多保存 64 个网络位置")
            entry = {"name": name, "path": path}
            if len(json.dumps(self.entries + [entry])) > 64 * 1024:
                raise ValueError("网络位置列表已满，请先移除不再使用的位置")
            self.result_entry = entry
            self.error.setText("")
        except ValueError as error:
            self.error.setText(str(error) if self.path.text() else r"例如：\\NAS\Photos")
        self.confirm.setEnabled(self.result_entry is not None)


class LocationDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        painter.save()
        paint_item(painter, option.rect, option.state, colors_for(option.widget)["accent"])
        size = option.decorationSize.width()
        icon_rect = option.rect.adjusted(9, 0, 0, 0)
        icon_rect.setTop(option.rect.center().y() - size // 2)
        icon_rect.setSize(QSize(size, size))
        index.data(Qt.ItemDataRole.DecorationRole).paint(painter, icon_rect)
        rect = QRectF(option.rect).adjusted(size + 19, 6, -10, -6)
        painter.setFont(option.font)
        painter.setPen(QColor("#F3F3F0"))
        painter.drawText(
            rect.adjusted(0, 0, 0, -rect.height() / 2),
            Qt.AlignmentFlag.AlignVCenter,
            option.fontMetrics.elidedText(
                index.data(), Qt.TextElideMode.ElideRight, int(rect.width())
            ),
        )
        font = option.font
        font.setPointSizeF(max(8, font.pointSizeF() - 1))
        painter.setFont(font)
        painter.setPen(QColor("#A2A2A6"))
        painter.drawText(
            rect.adjusted(0, rect.height() / 2, 0, 0),
            Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(
                index.data(Qt.ItemDataRole.UserRole), Qt.TextElideMode.ElideRight, int(rect.width())
            ),
        )
        painter.restore()


class NetworkLocations(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.generation = 0
        self.busy = False
        self.token = None
        self.folder_icon = folder_icon(network=True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel("网络位置"), 1)
        self.add_button = QPushButton()
        self.add_button.setObjectName("circleButton")
        self.add_button.setFixedSize(32, 32)
        self.add_button.setStyleSheet(
            "QPushButton { background: #38383B; border: none; border-radius: 16px; padding: 0; "
            "min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px; }"
            "QPushButton:hover { background: #454549; }"
        )
        self.add_button.setIcon(ui_icon("install"))
        self.add_button.setToolTip("添加网络位置")
        self.add_button.setAccessibleName("添加网络位置")
        self.add_button.clicked.connect(self.add_location)
        row.addWidget(self.add_button)
        layout.addLayout(row)
        self.list = QListWidget()
        configure_view(self.list)
        self.list.setItemDelegate(LocationDelegate(self.list))
        self.list.setAccessibleName("已添加的网络位置")
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.show_actions)
        self.list.itemDoubleClicked.connect(self.open_item)
        layout.addWidget(self.list, 1)
        self.empty = QLabel("尚未添加网络位置，点击 ＋ 添加。")
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.setInterval(10000)
        self.timeout.timeout.connect(self.timed_out)

    def reload(self):
        selected = self.list.currentItem()
        path = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        query = self.owner.search.text().casefold() if self.owner.tabs.currentIndex() == 3 else ""
        self.list.clear()
        for entry in saved_locations(self.owner.context):
            item = QListWidgetItem(self.folder_icon, entry["name"])
            item.setData(Qt.ItemDataRole.UserRole, entry["path"])
            item.setToolTip(entry["path"])
            item.setSizeHint(QSize(0, max(56, self.owner.values()["icon_size"] + 20)))
            self.list.addItem(item)
            item.setHidden(query not in (entry["name"] + " " + entry["path"]).casefold())
            if path == entry["path"]:
                self.list.setCurrentItem(item)
        self.list.setIconSize(self.owner.tree.iconSize())
        self.empty.setVisible(self.list.count() == 0)

    def add_location(self):
        dialog = LocationDialog(saved_locations(self.owner.context), self.owner.panel)
        try:
            if dialog.exec() and dialog.result_entry is not None:
                entries = saved_locations(self.owner.context)
                entries.append(dialog.result_entry)
                self.owner.context.set_setting("network_locations", entries)
                self.owner.search.clear()
                self.reload()
                self.list.setCurrentRow(self.list.count() - 1)
                self.owner.context.notify("已添加网络位置")
        finally:
            dialog.deleteLater()

    def open_item(self, item):
        if item:
            self.owner.open_folder(item.data(Qt.ItemDataRole.UserRole))

    def show_actions(self, position):
        item = self.list.itemAt(position)
        if not item:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.setStyleSheet(PLUGIN_STYLE)
        menu.addAction("打开", lambda: self.open_item(item))
        menu.addAction("移除网络位置", lambda: self.remove(path))
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(self.list.viewport().mapToGlobal(position))

    def remove(self, path):
        self.cancel_navigation()
        entries = [row for row in saved_locations(self.owner.context) if row["path"] != path]
        self.owner.context.set_setting("network_locations", entries)
        self.reload()

    def open_path(self, path, remember, on_open):
        try:
            path = normalize_path(path)
        except ValueError as error:
            self.owner.note.setText(str(error))
            return
        if self.busy:
            self.owner.note.setText("正在等待网络响应，请稍后重试。")
            return
        self.generation += 1
        generation = self.generation
        self.busy = True
        self.owner.note.setText("正在连接网络位置…")
        self.timeout.start()

        def work(token):
            token.checkpoint()
            try:
                readable = Path(path).is_dir()
            except OSError:
                readable = False
            return readable

        def render(readable):
            self.busy = False
            self.token = None
            if not self.owner.active or generation != self.generation:
                return
            self.timeout.stop()
            if readable:
                self.owner.open_folder(
                    path, remember=remember, on_open=on_open, _network_ready=True
                )
            else:
                self.owner.note.setText("无法访问网络位置，请检查连接及 Windows 访问权限。")

        try:
            self.token = self.owner.context.run_task(work, render, image_bound=False)
        except PluginError:
            self.busy = False
            self.timeout.stop()
            self.owner.note.setText("后台繁忙，请稍后重试。")

    def cancel_navigation(self):
        self.generation += 1
        self.timeout.stop()

    def timed_out(self):
        self.cancel_navigation()
        self.owner.note.setText("网络响应超时。你可以继续浏览本地文件，稍后再试。")

    def stop(self):
        self.cancel_navigation()
        if self.token:
            self.token.cancel()
