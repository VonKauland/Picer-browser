"""A single-row title and menu bar with a genuinely centered filename."""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenuBar, QPushButton, QToolButton, QWidget


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
        control_layout = QHBoxLayout(self.controls)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(0)
        self.control_buttons = {}
        for text, name, callback in (
            ("—", "minimize", window.showMinimized),
            ("□", "maximize", self.toggle_maximized),
            ("×", "close", window.close),
        ):
            button = QPushButton(text)
            button.setObjectName(name)
            button.setAccessibleName(
                {"minimize": "最小化", "maximize": "最大化或还原", "close": "关闭"}[name]
            )
            button.setFixedSize(46, 48)
            button.clicked.connect(callback)
            control_layout.addWidget(button)
            self.control_buttons[name] = button
        buttons.addWidget(self.controls)
        self.drag_origin: QPoint | None = None

    def set_chrome(self, style):
        mac = style == "macos"
        self.controls.setParent(self.left if mac else self.right)
        if mac:
            self.left.layout().insertWidget(0, self.controls)
        else:
            self.right.layout().addWidget(self.controls)
        order = ("close", "minimize", "maximize") if mac else ("minimize", "maximize", "close")
        layout = self.controls.layout()
        for name in order:
            button = self.control_buttons[name]
            layout.removeWidget(button)
            layout.addWidget(button)
            button.setFixedSize(14, 14) if mac else button.setFixedSize(46, 48)
            button.setProperty("macChrome", mac)
            button.style().unpolish(button)
            button.style().polish(button)
        layout.setSpacing(8 if mac else 0)
        self.controls.show()
        self.icon_label.setVisible(not mac)
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
QWidget#titleLeft, QWidget#titleRight, QLabel { background: transparent; }
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
QDockWidget::title { background: #202226; padding: 8px; }
QMainWindow::separator { background: #3a3d44; width: 3px; height: 3px; }
QLabel#empty { color: #92969e; font-size: 15px; background: transparent; }
QScrollBar { background: #202226; width: 9px; height: 9px; }
QScrollBar::handle { background: #4a4e56; border-radius: 4px; min-height: 20px; min-width: 20px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
"""
