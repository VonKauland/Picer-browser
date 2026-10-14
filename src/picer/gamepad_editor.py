"""Unbranded asymmetric controller schematic and staged XInput selection."""

from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from picer.gamepad import GAMEPAD_LABELS, SHOULDERS, normalize_gamepad

# Front-facing, asymmetric sticks. No brand name or logo is embedded in the art.
CANVAS = (1536, 1024)
CENTERS = {
    "LT": (380, 85),
    "RT": (1145, 85),
    "LB": (394, 156),
    "RB": (1141, 156),
    "LS": (390, 350),
    "RS": (973, 566),
    "Back": (682, 387),
    "Start": (855, 387),
    "Guide": (768, 299),
    "Y": (1148, 277),
    "X": (1055, 365),
    "B": (1244, 365),
    "A": (1148, 455),
    "DpadUp": (575, 500),
    "DpadDown": (575, 626),
    "DpadLeft": (510, 564),
    "DpadRight": (641, 564),
    "LSUp": (390, 242),
    "LSDown": (390, 456),
    "LSLeft": (282, 350),
    "LSRight": (494, 350),
    "RSUp": (973, 458),
    "RSDown": (973, 674),
    "RSLeft": (865, 566),
    "RSRight": (1081, 566),
}


class GamepadMap(QWidget):
    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.setObjectName("gamepadMap")
        assets = getattr(page.host, "paths_layout", None)
        root = assets.assets if assets else Path(__file__).parent / "assets"
        self.artwork = QPixmap(str(root / "ui" / "gamepad.png"))
        self.setMinimumHeight(200)
        self.setMaximumHeight(280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName("手柄示意图，左摇杆在上，右摇杆在下；也可用下方列表选择按键")
        self.setToolTip("点击按钮选择；摇杆外侧四个方向也可绑定。")

    def transform(self):
        scale = max(0.001, min(self.width() / CANVAS[0], self.height() / CANVAS[1]))
        return (
            scale,
            (self.width() - CANVAS[0] * scale) / 2,
            (self.height() - CANVAS[1] * scale) / 2,
        )

    def hit_test(self, point):
        scale, x, y = self.transform()
        point = QPointF((point.x() - x) / scale, (point.y() - y) / scale)
        distances = {
            key: (point - QPointF(*center)).manhattanLength() for key, center in CENTERS.items()
        }
        key = min(distances, key=distances.get)
        return key if distances[key] <= 64 else None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            key = self.hit_test(event.position())
            if key:
                self.page.select_button(key)
                event.accept()
                return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale, x, y = self.transform()
        painter.translate(x, y)
        painter.scale(scale, scale)
        colors = self.page.host.skin_colors
        accent, text = QColor(colors["accent"]), QColor(colors["text"])
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if not self.artwork.isNull():
            painter.drawPixmap(QRectF(0, 0, *CANVAS), self.artwork, QRectF(self.artwork.rect()))
        else:
            painter.setPen(text)
            painter.drawText(
                QRectF(0, 0, *CANVAS), Qt.AlignmentFlag.AlignCenter, "手柄示意图不可用"
            )
        font = painter.font()
        font.setPixelSize(round(10 / scale))
        painter.setFont(font)
        selected = set(self.page.value().split("+"))
        held = self.page.monitor.held[self.page.device.currentIndex()]
        for key, center in CENTERS.items():
            pos = QPointF(*center)
            direction = key.startswith(("LS", "RS")) and len(key) > 2
            chosen = key in selected
            highlighted = chosen or key in held
            fill = QColor(accent)
            fill.setAlpha(180 if chosen else 70)
            painter.setBrush(fill if highlighted else Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(accent, 1.5 / scale) if highlighted else Qt.PenStyle.NoPen)
            radius = (
                95
                if key in ("LS", "RS")
                else 24
                if direction
                else 32
                if key.startswith("Dpad")
                else 46
            )
            if key in SHOULDERS:
                rect = QRectF(pos.x() - 88, pos.y() - 26, 176, 52)
                painter.drawRoundedRect(rect, 22, 22)
            else:
                rect = QRectF(pos.x() - radius, pos.y() - radius, radius * 2, radius * 2)
                painter.drawEllipse(rect)
            painter.setPen(QColor("#202022") if chosen else text)
            label = {
                "Guide": "○",
                "Back": "▣",
                "Start": "≡",
                "DpadUp": "↑",
                "DpadDown": "↓",
                "DpadLeft": "←",
                "DpadRight": "→",
            }.get(key, key)
            if direction:
                label = ""
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)


class GamepadPage(QWidget):
    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.monitor = host.inputs.gamepad
        self.setObjectName("bindingPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.device = QComboBox()
        self.device.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.device.setMinimumContentsLength(8)
        self.device.setAccessibleName("识别输入的手柄设备")
        self.device.setToolTip(
            "选择用于识别按键的设备；保存的按键绑定适用于所有已连接 XInput 手柄。"
        )
        for index in range(4):
            self.device.addItem(f"通用手柄 · {index + 1}号设备", index)
        layout.addWidget(self.device)
        self.diagram = GamepadMap(self)
        layout.addWidget(self.diagram, 1)
        self.selection = QLabel("当前选择：A")
        self.selection.setWordWrap(True)
        layout.addWidget(self.selection)
        row = QHBoxLayout()
        self.modifiers = {}
        layout.addWidget(QLabel("组合肩键"))
        for key in SHOULDERS:
            check = QCheckBox(key)
            check.setAccessibleName(key + "作为组合修饰键")
            check.toggled.connect(self.update_selection)
            self.modifiers[key] = check
            row.addWidget(check)
        row.addStretch()
        layout.addLayout(row)
        self.button = QComboBox()
        self.button.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.button.setMinimumContentsLength(8)
        self.button.setAccessibleName("待添加手柄按钮")
        for key, label in GAMEPAD_LABELS.items():
            self.button.addItem(label, key)
        self.button.currentIndexChanged.connect(self.update_selection)
        layout.addWidget(self.button)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        layout.addWidget(self.status)
        note = QLabel("按键识别或点击选择；肩键支持组合绑定。")
        note.setToolTip(
            "手柄默认未分配。肩键用作组合修饰键后，不可同时单独绑定；其余肩键不受影响。"
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)
        self.device.currentIndexChanged.connect(self.device_changed)
        self.subscribed = False
        self.connections = []
        self.refresh_status()

    def value(self):
        base = self.button.currentData()
        return normalize_gamepad(
            "+".join(
                [key for key, check in self.modifiers.items() if check.isChecked() and key != base]
                + [base]
            )
        )

    def display_value(self):
        return "+".join(GAMEPAD_LABELS[part] for part in self.value().split("+"))

    def update_selection(self, *_):
        if hasattr(self, "button"):
            base = self.button.currentData()
            if base in self.modifiers and self.modifiers[base].isChecked():
                self.modifiers[base].setChecked(False)
            self.diagram.update()
            self.selection.setText("当前选择：" + self.display_value())

    def select_button(self, key):
        self.button.setCurrentIndex(self.button.findData(key))

    def set_value(self, value):
        parts = normalize_gamepad(value).split("+")
        if not parts or not parts[-1]:
            return
        self.select_button(parts[-1])
        for key, check in self.modifiers.items():
            check.setChecked(key in parts[:-1])

    def identify(self, index, key):
        if not self.isVisible() or index != self.device.currentIndex():
            return
        if QApplication.activePopupWidget() or QApplication.activeModalWidget() not in (
            None,
            self.window(),
        ):
            return
        # On Windows a native dialog activation group can still report its owner
        # as QApplication.activeWindow(), while the dialog is active itself.
        if not self.window().isActiveWindow():
            return
        current = self.monitor.held[index]
        self.select_button(key)
        for shoulder, check in self.modifiers.items():
            check.setChecked(shoulder in current and shoulder != key)

    def live_buttons(self, index, held):
        if index == self.device.currentIndex() and self.isVisible():
            self.diagram.update()

    def device_changed(self, *_):
        self.monitor.rebaseline()
        self.refresh_status()
        self.diagram.update()

    def refresh_status(self):
        for index in range(4):
            suffix = "已连接" if self.monitor.connected[index] else "未连接"
            self.device.setItemText(index, f"通用手柄 · {index + 1}号设备 · {suffix}")
        backend = self.monitor.backend
        text = backend.message
        if backend.available and not backend.guide_supported:
            text += " 当前驱动不支持识别引导键，该键可保存供兼容设备使用。"
        self.status.setText(text)

    def showEvent(self, event):
        super().showEvent(event)
        if not isValid(self.monitor) or self.monitor.disposed:
            return
        if not self.subscribed:
            self.connections = [
                self.monitor.status_changed.connect(self.refresh_status),
                self.monitor.buttons_changed.connect(self.live_buttons),
                self.monitor.pressed.connect(self.identify),
            ]
            self.subscribed = True
        self.monitor.set_capture(self)
        self.refresh_status()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.detach()

    def detach(self):
        if isValid(self.monitor):
            self.monitor.release_capture(self)
            for connection in self.connections:
                if connection:
                    QObject.disconnect(connection)
        self.connections = []
        self.subscribed = False
