"""A single-row title and menu bar with a genuinely centered filename."""

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenuBar, QPushButton, QToolButton, QWidget

from picer.theme import STYLE as STYLE


class WindowButton(QPushButton):
    """Equal-sized controls with font-independent, colored line symbols."""

    def __init__(self, name, callback, window):
        super().__init__()
        self.window = window
        self.setObjectName(name)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")
        self.setFixedSize(32, 32)
        self.setAccessibleName(
            {
                "fullscreen": "全屏或退出全屏",
                "minimize": "最小化",
                "maximize": "最大化或还原",
                "close": "关闭",
            }[name]
        )
        self.setToolTip(self.accessibleName())
        self.clicked.connect(callback)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self.window.skin_colors["accent"])
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
        if self.objectName() == "fullscreen":
            for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                corner = QPointF(x + dx * 4, y + dy * 4)
                painter.drawLine(corner, corner - QPointF(dx * 2.5, 0))
                painter.drawLine(corner, corner - QPointF(0, dy * 2.5))
        elif self.objectName() == "minimize":
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
            ("fullscreen", window.toggle_fullscreen),
            ("minimize", window.showMinimized),
            ("maximize", self.toggle_maximized),
            ("close", window.close),
        ):
            button = WindowButton(name, callback, window)
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
