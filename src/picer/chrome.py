"""A single-row title and menu bar with a genuinely centered filename."""

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenuBar, QPushButton, QToolButton, QWidget


class WindowButton(QPushButton):
    """Equal-sized controls with font-independent, colored line symbols."""

    COLORS = {"minimize": "#d5ad67", "maximize": "#70b781", "close": "#d76b6b"}

    def __init__(self, name, callback):
        super().__init__()
        self.setObjectName(name)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")
        self.setFixedSize(32, 32)
        self.setAccessibleName(
            {"minimize": "最小化", "maximize": "最大化或还原", "close": "关闭"}[name]
        )
        self.setToolTip(self.accessibleName())
        self.clicked.connect(callback)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self.COLORS[self.objectName()])
        if self.underMouse() or self.hasFocus():
            tint = QColor(color)
            tint.setAlpha(48 if self.isDown() else 24)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(tint)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(2, 2, -2, -2), 6, 6)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(color, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        center = QPointF(self.rect().center()) + QPointF(0.5, 0.5)
        x, y = center.x(), center.y()
        if self.objectName() == "minimize":
            painter.drawLine(QPointF(x - 4, y), QPointF(x + 4, y))
        elif self.objectName() == "maximize":
            painter.drawRect(QRectF(x - 4, y - 3, 8, 6))
        else:
            painter.drawLine(QPointF(x - 4, y - 4), QPointF(x + 4, y + 4))
            painter.drawLine(QPointF(x + 4, y - 4), QPointF(x - 4, y + 4))


class TitleBar(QWidget):
    """Keep native window actions and dragging in a compact custom title bar."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.filename = ""
        self.setObjectName("titleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFixedHeight(48)
        self.left = QWidget(self)
        self.left.setObjectName("titleLeft")
        layout = QHBoxLayout(self.left)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(16)
        self.icon_label = icon_label = QLabel()
        self.base_icon = window.windowIcon()
        icon_label.setPixmap(window.windowIcon().pixmap(20, 20))
        layout.addWidget(icon_label)
        self.brand = QLabel("揽映")
        self.brand.setObjectName("brand")
        layout.addWidget(self.brand)
        self.menu = QMenuBar()
        self.menu.setNativeMenuBar(False)
        self.menu.setFixedHeight(36)
        layout.addWidget(self.menu, 0, Qt.AlignmentFlag.AlignVCenter)
        self.caption = QLabel(self)
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.right = QWidget(self)
        self.right.setObjectName("titleRight")
        buttons = QHBoxLayout(self.right)
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(0)
        self.quick_slots = []
        for index in range(5):
            button = QToolButton(self.right)
            button.setObjectName("quickSlot")
            button.setFixedSize(28, 28)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.setAccessibleName(f"功能快捷栏位 {index + 1}")
            buttons.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
            self.quick_slots.append(button)
        buttons.addSpacing(8)
        self.controls = QWidget(self.right)
        self.controls.setObjectName("windowControls")
        control_layout = QHBoxLayout(self.controls)
        control_layout.setSpacing(6)
        control_layout.setContentsMargins(0, 0, 8, 0)
        self.control_buttons = {}
        for name, callback in (
            ("minimize", window.showMinimized),
            ("maximize", self.toggle_maximized),
            ("close", window.close),
        ):
            button = WindowButton(name, callback)
            control_layout.addWidget(button)
            self.control_buttons[name] = button
        buttons.addWidget(self.controls, 0, Qt.AlignmentFlag.AlignVCenter)
        self.drag_origin: QPoint | None = None

    def set_chrome(self, style):
        mac = style == "macos"
        # Keep the user's reference controls consistent across all host skins.
        self.icon_label.show()
        self.left.layout().setSpacing(12 if mac else 16)
        self.left.layout().activate()
        self.right.layout().activate()
        minimum = 2 * (max(self.left.sizeHint().width(), self.right.sizeHint().width()) + 20) + 40
        self.window.setMinimumWidth(max(800, minimum))
        self.arrange()

    def release_action(self, action) -> None:
        for button in self.quick_slots:
            if button.defaultAction() is action:
                button.setDefaultAction(None)

    def set_filename(self, filename: str) -> None:
        self.filename = filename
        self.caption.setToolTip(filename)
        self.arrange()

    def arrange(self) -> None:
        left_width = self.left.sizeHint().width()
        right_width = self.right.sizeHint().width()
        self.left.setGeometry(0, 0, left_width, self.height())
        self.right.setGeometry(self.width() - right_width, 0, right_width, self.height())
        inset = max(left_width, right_width) + 20
        width = max(0, self.width() - 2 * inset)
        self.caption.setGeometry(inset, 0, width, self.height())
        self.caption.setText(
            self.caption.fontMetrics().elidedText(
                self.filename, Qt.TextElideMode.ElideMiddle, width
            )
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.arrange()

    def toggle_maximized(self) -> None:
        if self.window.isMaximized():
            self.window.showNormal()
        else:
            self.window.showMaximized()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window.windowHandle()
            if handle is None or not handle.startSystemMove():
                self.drag_origin = event.globalPosition().toPoint() - self.window.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.drag_origin is not None and not self.window.isMaximized():
            self.window.move(event.globalPosition().toPoint() - self.drag_origin)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self.drag_origin = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()


STYLE = """
QWidget { background: #191b1f; color: #e5e6e8; font-size: 13px;
font-family: 'Microsoft YaHei', 'Noto Sans CJK SC', sans-serif; }
QWidget#titleBar { background: #202226; }
QWidget#titleLeft, QWidget#titleRight, QWidget#windowControls, QLabel { background: transparent; }
QLabel#brand { font-size: 15px; font-weight: 600; }
QMenuBar { background: transparent; padding: 0; }
QMenuBar::item { padding: 8px 10px; background: transparent; }
QMenuBar::item:selected { background: #32353b; border-radius: 4px; }
QMenu { background: #25272c; border: 1px solid #3a3d44; padding: 6px; }
QMenu::item { padding: 7px 28px 7px 14px; border-radius: 3px; }
QMenu::item:selected { background: #3a3d44; }
QMenu::item:disabled { color: #777b83; }
QMenu::separator { height: 1px; background: #3a3d44; margin: 5px 8px; }
QPushButton { border: none; background: transparent; font-size: 18px; }
QPushButton:hover { background: #35383e; }
QPushButton#close:hover { background: #c42b3a; color: white; }
QGraphicsView { border: none; background: #191b1f; }
QToolButton#quickSlot { border: none; border-radius: 6px; margin: 2px;
background: transparent; color: #92969e; font-size: 16px; }
QToolButton#quickSlot:hover { background: #35383e; }
QToolButton#quickSlot:disabled { color: #777b83; }
QDockWidget { font-size: 12px; }
QMainWindow::separator { background: transparent; width: 0px; height: 0px; }
QLabel#empty { color: #92969e; font-size: 15px; background: transparent; }
QScrollBar { background: #202226; width: 9px; height: 9px; }
QScrollBar::handle { background: #4a4e56; border-radius: 4px; min-height: 20px; min-width: 20px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
"""
