"""Approved charcoal About dialog with accent pixels and a five-character acrostic."""

import random
import sys

from PySide6.QtCore import QRectF, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from picer import __version__
from picer.host_style import mark_host
from picer.ui import DialogHeader, StyledDialog, colors_for, ui_icon

PROJECT_URL = "https://github.com/VonKauland/Picer-browser"
POEM = "揽景入方寸，\n映眸见万象。"


class PixelSurface(QFrame):
    def __init__(self):
        super().__init__()
        seed = random.Random(731)
        self.pixels = tuple(
            (
                seed.randrange(1, 15) / 60 if i < 72 else seed.randrange(50, 59) / 60,
                seed.randrange(14, 51) / 56,
                seed.choice((2, 3, 4, 6)),
                0.6 if i % 19 == 0 else seed.random() * 0.16 + 0.04,
                i % 8 == 0,
            )
            for i in range(120)
        )

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 17, 17)
        painter.setClipPath(clip)
        painter.setPen(Qt.PenStyle.NoPen)
        accent = QColor(colors_for(self)["accent"])
        for u, v, edge, opacity, diamond in self.pixels:
            painter.save()
            painter.setOpacity(opacity)
            painter.setBrush(accent)
            painter.translate(u * self.width(), v * self.height())
            if diamond:
                painter.rotate(45)
            painter.drawRect(QRectF(0, 0, edge, edge))
            painter.restore()


class AboutDialog(StyledDialog):
    def __init__(self, host):
        super().__init__("关于", parent=host.settings_dialog or host, surface_type=PixelSurface)
        self.host = host
        self.setMinimumSize(560, 340)
        self.resize(600, 360)
        self.setWindowIcon(host.windowIcon())
        header = self.findChild(DialogHeader)
        self.close_button = header.findChild(QPushButton)
        self.close_button.setIcon(ui_icon("close", colors_for(self)["accent"]))
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background: {colors_for(self)['border']}; border: none;")
        self.body.addWidget(divider)
        self.body.addStretch()
        row = QHBoxLayout()
        row.setSpacing(24)
        self.artwork = QLabel()
        self.artwork.setFixedSize(112, 112)
        self.artwork.setPixmap(
            QPixmap(str(host.paths_layout.icon)).scaled(
                112,
                112,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        row.addWidget(self.artwork, 0, Qt.AlignmentFlag.AlignVCenter)
        text = QVBoxLayout()
        text.setSpacing(6)
        self.name = QLabel("揽映")
        self.name.setStyleSheet("font-size: 28px; font-weight: 600;")
        text.addWidget(self.name)
        english = QLabel("Picer")
        english.setStyleSheet("font-size: 20px;")
        text.addWidget(english)
        platform = (
            "Windows x64"
            if sys.platform == "win32"
            else "Linux"
            if sys.platform.startswith("linux")
            else sys.platform
        )
        self.version = QLabel(f"版本 {__version__} · {platform}")
        self.version.setObjectName("muted")
        text.addWidget(self.version)
        self.poem = QLabel()
        accent = colors_for(self)["accent"]
        muted = colors_for(self)["muted"]
        self.poem.setText(
            f'<span style="color:{accent}">揽</span>景入方寸，<br>'
            f'<span style="color:{accent}">映</span>眸见万象。'
        )
        self.poem.setStyleSheet(f"font-size: 15px; color: {muted};")
        self.poem.setAccessibleName(POEM)
        text.addWidget(self.poem)
        row.addLayout(text, 1)
        self.body.addLayout(row)
        self.body.addStretch()
        footer = QHBoxLayout()
        footer.addStretch()
        self.project_button = QPushButton("项目主页")
        self.project_button.setObjectName("quietButton")
        self.project_button.clicked.connect(self.open_project)
        footer.addWidget(self.project_button)
        self.done_button = QPushButton("关闭")
        self.done_button.setObjectName("primaryButton")
        self.done_button.clicked.connect(self.accept)
        footer.addWidget(self.done_button)
        self.body.addLayout(footer)
        mark_host(self)

    def open_project(self):
        if not QDesktopServices.openUrl(QUrl(PROJECT_URL)):
            self.host.notify("无法打开项目主页")
