"""Application-local saved locations and compact left-hand navigation tabs."""

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QMenu, QTabBar

from picer.host_style import PLUGIN_STYLE
from picer.plugins import ui_icon

from .thumbnails import configure_view


def saved_paths(context, key):
    value = context.get_setting(key, [])
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(path for path in value if isinstance(path, str) and path))[:64]


class PlacesList(QListWidget):
    def __init__(self, owner, key):
        super().__init__()
        self.owner, self.key = owner, key
        configure_view(self)
        self.viewport().setProperty("browserViewport", True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_actions)
        self.itemDoubleClicked.connect(
            lambda item: owner.open_folder(item.data(Qt.ItemDataRole.UserRole))
        )
        self.setAccessibleName("快速访问" if key == "favorites" else "历史记录")

    def reload(self):
        from pathlib import Path

        self.clear()
        for path in saved_paths(self.owner.context, self.key):
            item = QListWidgetItem(self.owner.model.files.folders.icons[0], Path(path).name or path)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            item.setSizeHint(QSize(0, self.owner.values()["icon_size"] + 16))
            self.addItem(item)
        self.setIconSize(self.owner.tree.iconSize())

    def show_actions(self, position):
        item = self.itemAt(position)
        if item is None:
            return
        menu = QMenu(self)
        menu.setStyleSheet(PLUGIN_STYLE)
        action = menu.addAction("移出快速访问" if self.key == "favorites" else "移除此记录")
        path = item.data(Qt.ItemDataRole.UserRole)
        action.triggered.connect(lambda: self.remove_path(path))
        if self.key == "recent_folders":
            menu.addAction("清空历史记录", self.clear_history)
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(self.viewport().mapToGlobal(position))

    def remove_path(self, path):
        paths = saved_paths(self.owner.context, self.key)
        self.owner.context.set_setting(self.key, [entry for entry in paths if entry != path])
        self.reload()

    def clear_history(self):
        self.owner.context.set_setting(self.key, [])
        self.reload()


class NavigationTabs(QTabBar):
    """Paint upright icons; Qt's native west-tab label rotates them otherwise."""

    def __init__(self):
        super().__init__()
        self.hovered = -1
        self.icons = []
        self.setShape(QTabBar.Shape.RoundedWest)
        self.setExpanding(False)
        self.setDrawBase(False)
        self.setUsesScrollButtons(False)
        self.setMouseTracking(True)
        self.setAccessibleName("文件浏览位置选项卡")
        for symbol, label in (("folder", "文件"), ("star", "快速访问"), ("history", "历史记录")):
            index = self.addTab("")
            icons = (ui_icon(symbol, "#A2A2A6"), ui_icon(symbol, "#E8FF59"))
            self.icons.append(icons)
            self.setTabIcon(index, icons[0])
            self.setTabToolTip(index, label)
            self.setAccessibleTabName(index, label)
        self.setStyleSheet("QTabBar { background: transparent; border: none; }")

    def set_accent(self, color):
        for index, symbol in enumerate(("folder", "star", "history")):
            self.icons[index] = (self.icons[index][0], ui_icon(symbol, color))
        self.update()

    def tabSizeHint(self, index):
        return QSize(36, 40)

    def mouseMoveEvent(self, event):
        self.hovered = self.tabAt(event.position().toPoint())
        self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.hovered = -1
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        for index, icons in enumerate(self.icons):
            rect = self.tabRect(index).adjusted(2, 2, -2, -2)
            selected = index == self.currentIndex()
            if selected or index == self.hovered:
                painter.setBrush(QColor("#414145" if selected else "#343437"))
                painter.drawRoundedRect(QRectF(rect), 9, 9)
            icons[int(selected)].paint(
                painter, QRect(rect.center().x() - 8, rect.center().y() - 8, 18, 18)
            )


def navigation_tabs():
    return NavigationTabs()
