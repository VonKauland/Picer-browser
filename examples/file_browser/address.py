"""Clickable, width-aware path breadcrumbs with an editable address mode."""

from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QMenu, QPushButton, QStackedLayout, QWidget

from picer.host_style import PLUGIN_STYLE
from picer.plugins import ui_icon


def path_parts(path):
    """Keep real cumulative targets, including drive and UNC share roots."""
    return tuple(
        (part.name or part.anchor.rstrip("\\/") or "/", part)
        for part in (*reversed(path.parents), path)
    )


class CrumbButton(QPushButton):
    def __init__(self, label, target, trailing, parent):
        super().__init__(parent)
        self.label, self.target = label, target
        self.trailing = trailing
        self.setObjectName("crumbButton")
        self.setAccessibleName(label)
        self.setToolTip(str(target))
        self.setFixedHeight(28)
        self.setMinimumWidth(0)

    def resizeEvent(self, event):
        self.setText(
            self.fontMetrics().elidedText(
                self.label,
                Qt.TextElideMode.ElideRight,
                max(0, self.width() - (24 if self.trailing else 12)),
            )
        )
        super().resizeEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.trailing:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor("#A2A2A6"), 1.2))
            x, y = self.width() - 7, self.height() // 2
            painter.drawLine(x - 2, y - 3, x + 1, y)
            painter.drawLine(x + 1, y, x - 2, y + 3)


class AddressBar(QWidget):
    pathRequested = Signal(str)

    def __init__(self, panel):
        super().__init__(panel)
        self.path = ""
        self.virtual_label = None
        self.buttons = []
        self.hidden_parts = []
        self.setAccessibleName("文件夹地址")
        self.setFixedHeight(36)
        self.setMinimumWidth(0)
        self.setStyleSheet("""
QWidget#addressRow { background: #38383B; border: none; border-radius: 12px; }
QPushButton#crumbButton, QPushButton#addressButton { background: transparent;
border: none; border-radius: 6px; padding: 0; min-height: 0; }
QPushButton#crumbButton:hover, QPushButton#addressButton:hover { background: #414145; }
QPushButton#crumbButton:focus, QPushButton#addressButton:focus { border: none; }
""")
        self.stack = QStackedLayout(self)
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.row = QWidget()
        self.row.setObjectName("addressRow")
        self.crumbs = QHBoxLayout(self.row)
        self.crumbs.setContentsMargins(4, 4, 4, 4)
        self.crumbs.setSpacing(0)
        self.overflow = QPushButton("…")
        self.overflow.setObjectName("addressButton")
        self.overflow.setFixedSize(24, 28)
        self.overflow.setAccessibleName("更多上级文件夹")
        self.overflow.setToolTip("更多上级文件夹")
        self.overflow.clicked.connect(self.show_ancestors)
        self.edit = QPushButton()
        self.edit.setObjectName("addressButton")
        self.edit.setFixedSize(24, 28)
        self.edit.setIcon(ui_icon("edit"))
        self.edit.setIconSize(QSize(14, 14))
        self.edit.setAccessibleName("编辑地址")
        self.edit.setToolTip("编辑地址 · Ctrl+L")
        self.edit.clicked.connect(self.start_edit)
        self.editor = QLineEdit()
        self.editor.installEventFilter(self)
        self.editor.setAccessibleName("输入文件夹路径")
        self.editor.returnPressed.connect(lambda: self.pathRequested.emit(self.editor.text()))
        self.stack.addWidget(self.row)
        self.stack.addWidget(self.editor)
        self.edit_shortcut = QShortcut(QKeySequence("Ctrl+L"), panel)
        self.edit_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.edit_shortcut.activated.connect(self.start_edit)

    def eventFilter(self, watched, event):
        # Editing a path consumes Escape before the host's fullscreen shortcut.
        if event.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            if event.key() == Qt.Key.Key_Escape:
                event.accept()
                if event.type() == QEvent.Type.KeyPress:
                    self.stack.setCurrentWidget(self.row)
                    self.edit.setFocus()
                return True
        return super().eventFilter(watched, event)

    def minimumSizeHint(self):
        return QSize(0, 36)

    def sizeHint(self):
        return QSize(240, 36)

    def text(self):
        return self.path

    def setText(self, path):
        self.path = str(path)
        self.setToolTip(self.virtual_label or self.path)
        for button in self.buttons:
            button.hide()
            button.deleteLater()
        self.buttons = []
        parts = (
            ((self.virtual_label, None),)
            if self.virtual_label
            else path_parts(Path(path))
            if path
            else (("此电脑", ""),)
        )
        for index, (label, target) in enumerate(parts):
            button = CrumbButton(label, target, index < len(parts) - 1, self.row)
            if target is None:
                button.setToolTip(label)
            button.clicked.connect(
                lambda checked=False, target=target: (
                    self.pathRequested.emit(str(target)) if target is not None else None
                )
            )
            self.buttons.append(button)
        self.stack.setCurrentWidget(self.row)
        self.fit()

    def set_virtual(self, label):
        self.virtual_label = label
        self.setText(self.path)

    def fit(self):
        while self.crumbs.count():
            item = self.crumbs.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
        if not self.buttons:
            return
        available = max(32, self.width() - 8 - self.edit.width())
        widths = [
            min(
                150,
                max(
                    28,
                    button.fontMetrics().horizontalAdvance(button.label)
                    + (24 if button.trailing else 12),
                ),
            )
            for button in self.buttons
        ]
        visible = list(range(len(self.buttons)))
        hidden = []
        while (
            len(visible) > 2 and sum(widths[i] for i in visible) + (24 if hidden else 0) > available
        ):
            hidden.append(visible.pop(1))
        self.hidden_parts = [self.buttons[i] for i in hidden]
        budget = max(24, available - (24 if hidden else 0))
        total = sum(widths[i] for i in visible)
        remaining = budget
        for position, index in enumerate(visible):
            button = self.buttons[index]
            width = min(widths[index], max(12, round(widths[index] * min(1, budget / total))))
            width = min(width, remaining)
            remaining -= width
            button.setFixedWidth(width)
            self.crumbs.addWidget(button)
            button.show()
            if position == 0 and hidden:
                self.crumbs.addWidget(self.overflow)
                self.overflow.show()
        self.crumbs.addStretch(1)
        self.crumbs.addWidget(self.edit)
        self.edit.setVisible(not self.virtual_label)

    def resizeEvent(self, event):
        self.fit()
        super().resizeEvent(event)

    def start_edit(self):
        if self.virtual_label:
            return
        self.editor.setText(self.path)
        self.stack.setCurrentWidget(self.editor)
        self.editor.setFocus()
        self.editor.selectAll()

    def show_ancestors(self):
        menu = QMenu(self)
        menu.setStyleSheet(PLUGIN_STYLE)
        for button in self.hidden_parts:
            label = self.fontMetrics().elidedText(button.label, Qt.TextElideMode.ElideRight, 240)
            action = menu.addAction(label)
            action.setToolTip(str(button.target))
            action.triggered.connect(
                lambda checked=False, target=button.target: self.pathRequested.emit(str(target))
            )
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(self.overflow.mapToGlobal(self.overflow.rect().bottomLeft()))
