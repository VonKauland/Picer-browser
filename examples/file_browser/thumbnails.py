"""Lazy, bounded filesystem thumbnails and frame-free view painting."""

from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QPersistentModelIndex, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QFileSystemModel,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeView,
)

from picer.plugins import ui_icon
from picer.ui import colors_for

from .folders import FolderContents


def paint_item(painter, rect, state, accent):
    selected = bool(state & QStyle.StateFlag.State_Selected)
    hovered = bool(state & QStyle.StateFlag.State_MouseOver)
    if not (selected or hovered):
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#414145" if selected else "#343437"))
    painter.setPen(QPen(QColor(accent), 1.2) if selected else QPen(Qt.PenStyle.NoPen))
    painter.drawRoundedRect(QRectF(rect).adjusted(1.5, 1.5, -1.5, -1.5), 9, 9)
    painter.restore()


class PhotoModel(QFileSystemModel):
    folderClassified = Signal(str)

    def __init__(self, context, parent):
        super().__init__(parent)
        self.context = context
        self.cache = OrderedDict()
        self.pending = {}
        self.tokens = {}
        self.busy = False
        self.stopped = False
        self.placeholder = ui_icon("image")
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.load_batch)
        self.folders = FolderContents(context, self.folder_changed, self)

    def folder_changed(self, path):
        self.folderClassified.emit(path)
        index = self.index(path)
        if index.isValid():
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DecorationRole])

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if (
            index.isValid()
            and index.column() == 0
            and role == Qt.ItemDataRole.DecorationRole
            and self.isDir(index)
        ):
            return self.folders.icon(str(Path(self.filePath(index))))
        if (
            index.isValid()
            and role == Qt.ItemDataRole.DecorationRole
            and index.column() == 0
            and not self.isDir(index)
        ):
            # QFileSystemModel uses forward slashes on Windows, while the
            # application and persisted filesystem paths use native separators.
            path = str(Path(self.filePath(index)))
            info = self.fileInfo(index)
            key = (path, info.lastModified().toMSecsSinceEpoch(), info.size())
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            if not self.stopped and key not in self.tokens and len(self.pending) < 256:
                self.pending[key] = None
                if not self.busy and not self.timer.isActive():
                    self.timer.start(0)
            return self.placeholder
        return super().data(index, role)

    def load_batch(self):
        if self.stopped or not self.pending:
            return
        keys = tuple(self.pending)[: max(0, 8 - len(self.tokens))]
        for key in keys:
            self.pending.pop(key, None)
        for key in keys:

            def render(image, key=key):
                self.tokens.pop(key, None)
                self.busy = bool(self.tokens)
                if self.stopped:
                    return
                self.cache[key] = (
                    self.placeholder if image.isNull() else QIcon(QPixmap.fromImage(image))
                )
                self.cache.move_to_end(key)
                while len(self.cache) > 256:
                    self.cache.popitem(last=False)
                index = self.index(key[0])
                if index.isValid():
                    self.dataChanged.emit(index, index, [Qt.ItemDataRole.DecorationRole])
                if self.pending:
                    self.timer.start(0)

            self.tokens[key] = self.context.request_thumbnail(key[0], render, edge=128)
        self.busy = bool(self.tokens)

    def stop(self):
        self.stopped = True
        self.timer.stop()
        self.pending.clear()
        self.folders.stop()
        for token in self.tokens.values():
            token.cancel()
        self.tokens.clear()


class PhotoDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        # Windows' native focus frame draws a white rectangle over rounded rows.
        option.state &= ~QStyle.StateFlag.State_HasFocus

    def paint(self, painter, option, index):
        if not isinstance(self.parent(), QTreeView):
            paint_item(painter, option.rect, option.state, colors_for(self.parent())["accent"])
        copy = QStyleOptionViewItem(option)
        copy.state &= ~(
            QStyle.StateFlag.State_Selected
            | QStyle.StateFlag.State_MouseOver
            | QStyle.StateFlag.State_HasFocus
        )
        super().paint(painter, copy, index)


class PhotoTree(QTreeView):
    def __init__(self):
        super().__init__()
        self.hover_index = QPersistentModelIndex()

    def mouseMoveEvent(self, event):
        self.hover_index = QPersistentModelIndex(self.indexAt(event.position().toPoint()))
        self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.hover_index = QPersistentModelIndex()
        self.viewport().update()
        super().leaveEvent(event)

    def drawRow(self, painter, option, index):
        # Include the branch gutter in the single selection container.
        state = option.state
        if self.selectionModel().isSelected(index):
            state |= QStyle.StateFlag.State_Selected
        if self.hover_index == index:
            state |= QStyle.StateFlag.State_MouseOver
        paint_item(painter, option.rect, state, colors_for(self)["accent"])
        copy = QStyleOptionViewItem(option)
        copy.state &= ~(QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver)
        super().drawRow(painter, copy, index)

    def drawBranches(self, painter, rect, index):
        if not self.model().isDir(index):
            return
        # Draw only a small chevron, without native branch boxes/white connectors.
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#A2A2A6"), 1.4))
        x, y = rect.right() - 9, rect.center().y()
        if self.isExpanded(index):
            painter.drawLine(x - 3, y - 2, x, y + 1)
            painter.drawLine(x, y + 1, x + 3, y - 2)
        else:
            painter.drawLine(x - 1, y - 3, x + 2, y)
            painter.drawLine(x + 2, y, x - 1, y + 3)
        painter.restore()


def configure_view(view):
    view.setItemDelegate(PhotoDelegate(view))
    view.setFrameShape(view.Shape.NoFrame)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    view.setTextElideMode(Qt.TextElideMode.ElideRight)
    view.setEditTriggers(view.EditTrigger.NoEditTriggers)
    view.setIconSize(QSize(24, 24))
    view.setMouseTracking(True)
    view.viewport().setMouseTracking(True)
    view.setVerticalScrollMode(view.ScrollMode.ScrollPerPixel)
    view.verticalScrollBar().setSingleStep(36)
    view.viewport().setAutoFillBackground(False)
    # Qt paints the branch selection before drawBranches. An unspecified native
    # Highlight color leaks blue/white around QSS-rounded branch backgrounds.
    palette = view.palette()
    for group in (
        QPalette.ColorGroup.Active,
        QPalette.ColorGroup.Inactive,
        QPalette.ColorGroup.Disabled,
    ):
        palette.setColor(group, QPalette.ColorRole.Highlight, QColor(Qt.GlobalColor.transparent))
        palette.setColor(group, QPalette.ColorRole.HighlightedText, QColor("#F3F3F0"))
    view.setPalette(palette)
    view.setStyleSheet("""
QTreeView, QListView { background: transparent; border: none; outline: none; }
QTreeView::item, QListView::item { padding: 6px; border: none; border-radius: 8px; }
QTreeView::item:selected, QListView::item:selected,
QTreeView::item:hover, QListView::item:hover { background: transparent; border: none; }
QTreeView::branch { background: transparent; border: none; }
QTreeView::branch:selected, QTreeView::branch:hover, QTreeView::branch:focus {
background: transparent; border: none; outline: none; image: none; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; border: none; }
QScrollBar::handle:vertical { background: #454549; min-height: 24px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; border: none;
background: transparent; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent;
border: none; }
""")
