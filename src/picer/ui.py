"""Shared, static desktop controls and monochrome icons for the charcoal UI."""

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QVBoxLayout,
    QWidget,
)

from picer.host_style import mark_host
from picer.theme import COLORS

ACCENT = "#E8FF59"
ICON_PATHS = {
    "plug": '<path d="M8 3v5m8-5v5M6 8h12v3a6 6 0 0 1-12 0zM12 17v4"/>',
    "filter": '<path d="M3 4h18l-7 8v7l-4 2v-9z"/>',
    "sort": '<path d="M6 3v18m-3-3 3 3 3-3M13 5h8M13 10h6M13 15h4"/>',
    "photo": (
        '<rect x="3" y="3" width="18" height="18" rx="4"/>'
        '<circle cx="16" cy="8" r="2"/><path d="m4 17 5-5 4 4 3-3 4 4"/>'
    ),
    "folder": (
        '<path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11'
        'a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7zM3 8h18"/>'
    ),
    "star": '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9z"/>',
    "history": ('<path d="M3 11a9 9 0 1 1 2.5 7M3 4v7h7M12 7v5l3 2"/>'),
    "network": (
        '<rect x="2" y="3" width="12" height="9" rx="1.5"/>'
        '<rect x="11" y="11" width="11" height="9" rx="1.5"/>'
        '<path d="M8 12v4M5 16h5m6.5 4v2M14 22h5"/>'
    ),
    "home": '<path d="m3 11 9-8 9 8M5 10v10h5v-6h4v6h5V10"/>',
    "up": '<path d="M12 21V3m-7 7 7-7 7 7"/>',
    "edit": '<path d="m15 3 6 6-12 12H3v-6zM12 6l6 6"/>',
    "left": '<path d="m15 4-8 8 8 8"/>',
    "right": '<path d="m9 4 8 8-8 8"/>',
    "rotate": '<path d="M20 10a8 8 0 1 0-2 8M20 3v7h-7"/>',
    "reload": '<path d="M20 10a8 8 0 1 0-2 8M20 3v7h-7"/>',
    "grid": (
        '<rect x="3" y="3" width="7" height="7" rx="1"/>'
        '<rect x="14" y="3" width="7" height="7" rx="1"/>'
        '<rect x="3" y="14" width="7" height="7" rx="1"/>'
        '<rect x="14" y="14" width="7" height="7" rx="1"/>'
    ),
    "list": '<path d="M9 5h12M9 12h12M9 19h12M3 5h1M3 12h1M3 19h1"/>',
    "play": '<path d="m7 3 14 9-14 9z"/>',
    "pause": '<path d="M8 4v16M16 4v16"/>',
    "close": '<path d="m5 5 14 14M19 5 5 19"/>',
    "search": '<circle cx="10" cy="10" r="7"/><path d="m15 15 6 6"/>',
    "shuffle": '<path d="M3 6h3l12 12h3M3 18h3L18 6h3M17 2l4 4-4 4M17 14l4 4-4 4"/>',
    "install": '<path d="M12 3v18M3 12h18"/>',
    "settings": (
        '<path d="M4 6h16M4 12h16M4 18h16"/>'
        '<circle cx="9" cy="6" r="2"/><circle cx="16" cy="12" r="2"/>'
        '<circle cx="8" cy="18" r="2"/>'
    ),
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7v.5"/>',
    "panel": '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M9 3v18"/>',
    "function": '<path d="m14 2-9 12h6l-1 8 9-12h-6z"/>',
    "skin": (
        '<circle cx="12" cy="12" r="9"/><circle cx="8" cy="8" r="1"/>'
        '<circle cx="15" cy="7" r="1"/><circle cx="17" cy="13" r="1"/>'
        '<path d="M6 16h6"/>'
    ),
    "storage": (
        '<ellipse cx="12" cy="5" rx="8" ry="3"/>'
        '<path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>'
    ),
    "keyboard": (
        '<rect x="2" y="5" width="20" height="14" rx="3"/>'
        '<path d="M6 9h1m3 0h1m3 0h1m3 0h1M6 13h1m3 0h1m3 0h1m3 0h1M7 16h10"/>'
    ),
    "more": (
        '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/>'
        '<circle cx="19" cy="12" r="1"/>'
    ),
    "log": '<path d="M5 3h10l4 4v14H5zM15 3v5h4M8 12h8M8 16h8"/>',
}


def ui_icon(name, color="#F3F3F0"):
    """Icons supplied to examples keep their color independently of host skins."""
    paths = ICON_PATHS.get(name, ICON_PATHS["photo"])
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="1.5" '
        f'stroke-linecap="round" stroke-linejoin="round">{paths}</svg>'
    )
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    return QIcon(pixmap)


def colors_for(widget):
    ancestor = widget
    plugin = False
    while ancestor is not None:
        plugin |= bool(ancestor.property("pluginSurface"))
        if hasattr(ancestor, "skin_colors"):
            if not plugin:
                return ancestor.skin_colors
            colors = dict(COLORS)
            custom = ancestor.app_preferences.get("accent_color", "")
            if custom:
                colors["accent"] = custom
            return colors
        ancestor = ancestor.parentWidget()
    return dict(COLORS)


class RoundedSlider(QSlider):
    """Paint a transparent, round-capped track using Qt's native handle geometry.

    Mouse dragging, tracking, keyboard input, range and accessibility stay in QSlider.
    Qt's stylesheet sub-page renderer can fill the whole widget height on Windows;
    painting the track explicitly avoids both that block and squared endpoints.
    """

    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None, *, jump_on_click=False):
        super().__init__(orientation, parent)
        self.jump_on_click = jump_on_click
        self.setMinimumSize(24, 24)

    def mousePressEvent(self, event):
        if self.jump_on_click and event.button() == Qt.MouseButton.LeftButton:
            option = QStyleOptionSlider()
            self.initStyleOption(option)
            if not self.handle_rect(option).contains(event.position()):
                endpoints = QStyleOptionSlider(option)
                endpoints.sliderPosition = endpoints.sliderValue = self.minimum()
                start = self.handle_rect(endpoints).center()
                endpoints.sliderPosition = endpoints.sliderValue = self.maximum()
                end = self.handle_rect(endpoints).center()
                horizontal = self.orientation() == Qt.Orientation.Horizontal
                low = start.x() if horizontal else start.y()
                high = end.x() if horizontal else end.y()
                position = event.position().x() if horizontal else event.position().y()
                self.setSliderPosition(
                    QStyle.sliderValueFromPosition(
                        self.minimum(),
                        self.maximum(),
                        round(position - min(low, high)),
                        round(abs(high - low)),
                        low > high,
                    )
                )
        # Once moved under the pointer, native Qt handle dragging/release retains
        # tracking, keyboard, RTL, inverted ranges and accessibility semantics.
        super().mousePressEvent(event)

    def handle_rect(self, option):
        return QRectF(
            self.style().subControlRect(
                QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self
            )
        )

    def paintEvent(self, event):
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        handle = self.handle_rect(option)
        endpoints = QStyleOptionSlider(option)
        endpoints.minimum, endpoints.maximum = 0, 100
        endpoints.sliderPosition = endpoints.sliderValue = 0
        start = self.handle_rect(endpoints).center()
        endpoints.sliderPosition = endpoints.sliderValue = 100
        end = self.handle_rect(endpoints).center()
        colors = colors_for(self)
        accent = QColor(colors["accent"] if self.isEnabled() else colors["muted"])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(
            QPen(QColor(colors["border"]), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        )
        painter.drawLine(start, end)
        painter.setPen(QPen(accent, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(start, handle.center())
        if self.hasFocus():
            painter.setPen(QPen(QColor(colors["muted"]), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(handle.adjusted(-2, -2, 2, 2))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawEllipse(handle)


class Toggle(QCheckBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(42, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, event):
        colors = colors_for(self)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(1 if self.isEnabled() else 0.45)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors["accent"] if self.isChecked() else colors["border"]))
        painter.drawRoundedRect(QRectF(1, 2, 40, 20), 10, 10)
        painter.setBrush(QColor(colors["title"] if self.isChecked() else colors["text"]))
        painter.drawEllipse(QRectF(23 if self.isChecked() else 3, 4, 16, 16))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QColor(colors["text"]))
            painter.drawRoundedRect(QRectF(0.5, 0.5, 41, 23), 12, 12)


class Card(QFrame):
    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 18, 20, 18)
        self.body.setSpacing(16)
        if title:
            label = QLabel(title)
            label.setObjectName("sectionHeading")
            self.body.addWidget(label)


def form_row(label, editor):
    row = QHBoxLayout()
    text = QLabel(label)
    text.setWordWrap(True)
    editor.setAccessibleName(label)
    row.addWidget(text, 1)
    row.addWidget(editor)
    return row


class DialogHeader(QWidget):
    def __init__(self, dialog, title, subtitle):
        super().__init__(dialog)
        self.setObjectName("dialogHeader")
        self.dialog, self.origin = dialog, None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 20, 20, 12)
        labels = QVBoxLayout()
        heading = QLabel(title)
        heading.setObjectName("dialogHeading")
        labels.addWidget(heading)
        if subtitle:
            label = QLabel(subtitle)
            label.setObjectName("muted")
            labels.addWidget(label)
        layout.addLayout(labels, 1)
        close = QPushButton()
        close.setIcon(ui_icon("close", colors_for(dialog)["text"]))
        close.setObjectName("circleButton")
        close.setProperty("picerDialogClose", True)
        close.setFixedSize(32, 32)
        close.setAccessibleName("关闭窗口")
        close.clicked.connect(dialog.reject)
        layout.addWidget(close)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.dialog.windowHandle()
            if handle is None or not handle.startSystemMove():
                self.origin = event.globalPosition().toPoint() - self.dialog.pos()

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            self.dialog.move(event.globalPosition().toPoint() - self.origin)

    def mouseReleaseEvent(self, event):
        self.origin = None


class DialogSurface(QFrame):
    """Paint an opaque surface even when inherited plugin QSS is transparent."""

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = colors_for(self)
        painter.setBrush(QColor("#242426"))
        painter.setPen(QPen(QColor(colors["accent"]).darker(230), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 18, 18)


class StyledDialog(QDialog):
    def __init__(self, title, subtitle="", parent=None, *, surface_type=DialogSurface):
        super().__init__(parent)
        self.setWindowTitle("揽映 · " + title)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame = surface_type()
        frame.setObjectName("dialogSurface")
        outer.addWidget(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 12)
        layout.addWidget(DialogHeader(self, title, subtitle))
        self.body = QVBoxLayout()
        self.body.setContentsMargins(24, 8, 24, 12)
        self.body.setSpacing(16)
        layout.addLayout(self.body, 1)
        mark_host(self)
