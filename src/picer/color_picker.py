"""App-owned HSV picker; no platform or Qt standard color-dialog chrome."""

from PySide6.QtCore import QPointF, QRectF, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from picer.ui import StyledDialog, colors_for

SWATCHES = ("#E8FF59", "#9BE870", "#66DAC9", "#79B8FF", "#BBA2FF", "#FF98BC", "#FFBC79", "#F3F3F0")


class ColorPlane(QWidget):
    changed = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hue, self.saturation, self.brightness = 0.0, 1.0, 1.0
        self.setMinimumSize(240, 160)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("饱和度与亮度色板，方向键微调")

    def plane_rect(self):
        return QRectF(self.rect()).adjusted(8, 8, -8, -8)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.plane_rect()
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        horizontal = QLinearGradient(rect.topLeft(), rect.topRight())
        horizontal.setColorAt(0, QColor("white"))
        horizontal.setColorAt(1, QColor.fromHsvF(self.hue, 1, 1))
        vertical = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        vertical.setColorAt(0, QColor(0, 0, 0, 0))
        vertical.setColorAt(1, QColor("black"))
        painter.fillPath(path, horizontal)
        painter.fillPath(path, vertical)
        if self.hasFocus():
            painter.setPen(QPen(QColor(colors_for(self)["accent"]), 1.5))
            painter.drawPath(path)
        point = QPointF(
            rect.left() + self.saturation * rect.width(),
            rect.top() + (1 - self.brightness) * rect.height(),
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(0, 0, 0, 170), 4))
        painter.drawEllipse(point, 6, 6)
        painter.setPen(QPen(QColor("white"), 2))
        painter.drawEllipse(point, 6, 6)

    def change(self, saturation, brightness):
        self.saturation = min(1, max(0, saturation))
        self.brightness = min(1, max(0, brightness))
        self.update()
        self.changed.emit(self.saturation, self.brightness)

    def pick(self, position):
        rect = self.plane_rect()
        self.change(
            (position.x() - rect.left()) / rect.width(),
            1 - (position.y() - rect.top()) / rect.height(),
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self.pick(event.position())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.pick(event.position())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def keyPressEvent(self, event):
        step = 0.05 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 0.01
        changes = {
            Qt.Key.Key_Left: (-step, 0),
            Qt.Key.Key_Right: (step, 0),
            Qt.Key.Key_Up: (0, step),
            Qt.Key.Key_Down: (0, -step),
        }
        if event.key() in changes:
            dx, dy = changes[event.key()]
            self.change(self.saturation + dx, self.brightness + dy)
            event.accept()
        else:
            super().keyPressEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()


class HueSlider(QSlider):
    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(0, 359)
        self.setFixedHeight(28)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.setAccessibleName("色相")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(8, self.height() / 2 - 4, self.width() - 16, 8)
        gradient = QLinearGradient(rect.topLeft(), rect.topRight())
        for index in range(7):
            gradient.setColorAt(index / 6, QColor.fromHsvF(index / 6, 1, 1))
        painter.setBrush(gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 4, 4)
        center = QPointF(rect.left() + rect.width() * self.value() / 359, rect.center().y())
        painter.setBrush(QColor.fromHsv(self.value(), 255, 255))
        painter.setPen(QPen(QColor("white"), 2))
        painter.drawEllipse(center, 7, 7)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(colors_for(self)["accent"]), 1))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)

    def pick(self, position):
        self.setValue(round(min(1, max(0, (position.x() - 8) / max(1, self.width() - 16))) * 359))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self.setSliderDown(True)
            self.pick(event.position())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            self.pick(event.position())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            self.pick(event.position())
            self.setSliderDown(False)
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class ColorPicker(StyledDialog):
    def __init__(self, initial, parent=None):
        super().__init__("选择强调色", "自定义色彩，让界面更合心意", parent)
        self.setMinimumSize(440, 400)
        self.resize(500, 590)
        self.color = QColor(initial)
        self.selected_value = self.color.name().upper()
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        scroll.setWidget(content)
        self.body.addWidget(scroll, 1)
        self.plane = ColorPlane()
        layout.addWidget(self.plane, 1)
        self.hue = HueSlider()
        layout.addWidget(self.hue)
        presets = QHBoxLayout()
        self.swatches = []
        for value in SWATCHES:
            button = QPushButton()
            button.setFixedSize(32, 32)
            button.setToolTip(value)
            button.setAccessibleName("选择颜色 " + value)
            button.setStyleSheet(
                f"QPushButton {{ background: {value}; border: none;"
                "border-radius: 16px; padding: 0; min-height: 32px; max-height: 32px; }"
                "QPushButton:focus { border: 2px solid #A2A2A6; }"
            )
            button.clicked.connect(lambda checked=False, value=value: self.set_color(QColor(value)))
            presets.addWidget(button)
            self.swatches.append(button)
        presets.addStretch()
        layout.addLayout(presets)
        preview = QHBoxLayout()
        self.original = QLabel("当前颜色")
        self.preview = QLabel("新颜色")
        self.paint_preview(self.original, QColor(initial))
        preview.addWidget(self.original)
        preview.addWidget(self.preview)
        layout.addLayout(preview)
        fields = QHBoxLayout()
        self.hex = QLineEdit()
        self.hex.setMaxLength(7)
        self.hex.setAccessibleName("HEX 颜色值")
        self.hex.setMinimumWidth(115)
        fields.addWidget(self.field("HEX", self.hex), 2)
        self.rgb = []
        for label in ("R", "G", "B"):
            spin = QSpinBox()
            spin.setRange(0, 255)
            spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            spin.setAccessibleName(label + " 颜色分量")
            fields.addWidget(self.field(label, spin), 1)
            spin.valueChanged.connect(self.rgb_changed)
            self.rgb.append(spin)
        layout.addLayout(fields)
        self.error = QLabel()
        self.error.setObjectName("muted")
        self.error.setWordWrap(True)
        self.error.setMinimumHeight(20)
        layout.addWidget(self.error)
        buttons = QHBoxLayout()
        self.follow = QPushButton("跟随皮肤")
        self.follow.setObjectName("quietButton")
        self.follow.clicked.connect(self.follow_skin)
        buttons.addWidget(self.follow)
        buttons.addStretch()
        self.cancel = QPushButton("取消")
        self.cancel.clicked.connect(self.reject)
        buttons.addWidget(self.cancel)
        self.apply = QPushButton("使用颜色")
        self.apply.setObjectName("primaryButton")
        self.apply.clicked.connect(self.use_color)
        buttons.addWidget(self.apply)
        self.body.addLayout(buttons)
        self.plane.changed.connect(self.plane_changed)
        self.hue.valueChanged.connect(self.hue_changed)
        self.hex.textEdited.connect(self.hex_changed)
        self.set_color(self.color)

    @staticmethod
    def field(label, editor):
        container = QWidget()
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        text = QLabel(label)
        text.setObjectName("muted")
        column.addWidget(text)
        column.addWidget(editor)
        return container

    @staticmethod
    def paint_preview(label, color):
        foreground = "#242426" if color.lightnessF() > 0.5 else "#F3F3F0"
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setMinimumHeight(36)
        label.setStyleSheet(
            f"background: {color.name()}; color: {foreground}; border-radius: 12px; padding: 4px;"
        )

    def set_color(self, color, *, keep_hsv=False):
        self.color = QColor(color).toRgb()
        if not keep_hsv:
            hue, saturation, brightness, _ = self.color.getHsvF()
            with QSignalBlocker(self.hue):
                if hue >= 0:
                    self.hue.setValue(min(359, round(hue * 360)))
            self.plane.hue = self.hue.value() / 360
            self.plane.saturation, self.plane.brightness = saturation, brightness
        with QSignalBlocker(self.hex):
            self.hex.setText(self.color.name().upper())
        for spin, value in zip(self.rgb, self.color.getRgb()[:3], strict=True):
            with QSignalBlocker(spin):
                spin.setValue(value)
        self.error.clear()
        self.apply.setEnabled(True)
        self.plane.update()
        self.paint_preview(self.preview, self.color)

    def plane_changed(self, saturation, brightness):
        self.set_color(QColor.fromHsvF(self.plane.hue, saturation, brightness), keep_hsv=True)

    def hue_changed(self, hue):
        self.plane.hue = hue / 360
        self.plane_changed(self.plane.saturation, self.plane.brightness)

    def rgb_changed(self):
        self.set_color(QColor(*(spin.value() for spin in self.rgb)))

    def hex_changed(self, value):
        from picer.color_editor import valid_accent

        if value and valid_accent(value):
            self.set_color(QColor(value))
        else:
            self.error.setText("请输入完整的 #RRGGBB 色值")
            self.apply.setEnabled(False)

    def use_color(self):
        if self.apply.isEnabled():
            self.selected_value = self.color.name().upper()
            self.accept()

    def follow_skin(self):
        self.selected_value = ""
        self.accept()
