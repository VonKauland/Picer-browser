"""Metadata groups scroll independently of the fixed bottom EXIF region."""

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from picer.plugins import SettingField


class Histogram(QWidget):
    def __init__(self):
        super().__init__()
        self.channels = []
        self.setMinimumHeight(90)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        peak = max((max(channel) for channel in self.channels), default=1) or 1
        for channel, color in zip(self.channels, ("#fb7185", "#6ee7b7", "#60a5fa"), strict=False):
            line = QPainterPath()
            line.moveTo(0, self.height())
            for index, count in enumerate(channel):
                line.lineTo(
                    QPointF(
                        index * self.width() / 255,
                        self.height() * (1 - math.log1p(count) / math.log1p(peak)),
                    )
                )
            painter.setPen(QPen(QColor(color), 1.2))
            painter.drawPath(line)


class Plugin:
    def activate(self, context):
        self.context = context
        self.metadata = None
        self.token = None
        self.fields = tuple(
            SettingField(key, label, "bool", True)
            for key, label in (
                ("file", "文件信息"),
                ("dimensions", "尺寸与格式"),
                ("color", "颜色信息"),
                ("histogram", "RGB 直方图"),
                ("rating", "星级"),
                ("extra", "其他元数据"),
            )
        )
        context.add_settings(self.fields, self.apply_settings)
        self.panel = QWidget()
        self.panel.setMinimumWidth(270)
        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(12, 12, 12, 12)
        top = QHBoxLayout()
        self.title = QLabel("图片信息")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(True)
        top.addWidget(self.title, 1)
        layout.addLayout(top)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.groups = {}
        self.tables = {}
        for key, label in (
            ("file", "文件"),
            ("dimensions", "尺寸与格式"),
            ("color", "颜色"),
            ("extra", "其他元数据"),
        ):
            group = QGroupBox(label)
            table = QFormLayout(group)
            self.groups[key], self.tables[key] = group, table
            self.body.addWidget(group)
        group = self.groups["histogram"] = QGroupBox("RGB 直方图（对数刻度）")
        row = QVBoxLayout(group)
        self.histogram = Histogram()
        self.sample_label = QLabel()
        row.addWidget(self.histogram)
        row.addWidget(self.sample_label)
        self.body.addWidget(group)
        group = self.groups["rating"] = QGroupBox("星级 · 保存在插件配置，不修改原图")
        row = QVBoxLayout(group)
        self.rating = QComboBox()
        self.rating.addItem("未评级", 0)
        for stars in range(1, 6):
            self.rating.addItem("★" * stars, stars)
        self.rating.currentIndexChanged.connect(self.set_rating)
        row.addWidget(self.rating)
        self.body.addWidget(group)
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.body.addWidget(self.warning)
        self.body.addStretch()
        self.scroll.setWidget(body)
        layout.addWidget(self.scroll, 1)
        # A separate layout region, never a scroll child or overlay over other details.
        self.exif_box = QGroupBox("相机 EXIF")
        self.exif_box.setMaximumHeight(210)
        exif_layout = QVBoxLayout(self.exif_box)
        self.exif_text = QTextEdit()
        self.exif_text.setReadOnly(True)
        exif_layout.addWidget(self.exif_text)
        layout.addWidget(self.exif_box, 0)
        self.exif_box.hide()
        self.dock = context.add_panel(self.panel, area="right")
        context.subscribe("image.changed", self.on_image)
        self.apply_settings()
        self.refresh()

    def apply_settings(self):
        for field in self.fields:
            self.groups[field.key].setVisible(
                field.validate(self.context.get_setting(field.key, True))
            )

    def on_image(self, event):
        self.refresh()

    def refresh(self):
        if self.token:
            self.token.cancel()
        path = self.context.current_path()
        self.title.setText(path.name if path else "打开图片后查看信息")
        self.exif_box.hide()
        self.metadata = None
        self.warning.setText("正在读取元数据…" if path else "")
        for table in self.tables.values():
            while table.rowCount():
                table.removeRow(0)
        self.histogram.channels = []
        self.histogram.update()
        self.rating.setEnabled(False)
        if path:
            self.token = self.context.request_metadata(self.show_metadata)

    def show_metadata(self, data):
        if str(self.context.current_path()) != data["path"]:
            return
        self.metadata = data
        for key, table in self.tables.items():
            for label, value in data.get(key, {}).items():
                widget = QLabel(str(value))
                widget.setTextFormat(Qt.TextFormat.PlainText)
                widget.setWordWrap(True)
                widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                table.addRow(str(label), widget)
        self.histogram.channels = data.get("histogram", [])
        self.histogram.update()
        self.sample_label.setText(
            "采样尺寸：" + " × ".join(str(v) for v in data.get("sample_size", ()))
        )
        self.exif_text.setPlainText(
            "\n".join(f"{key}: {value}" for key, value in data["exif"].items())
        )
        self.exif_box.setVisible(bool(data["exif"]))
        self.warning.setText("\n".join(data["warnings"]))
        ratings = self.context.get_setting("ratings", {})
        rating = (
            ratings.get(data["path"], data.get("embedded_rating", 0))
            if isinstance(ratings, dict)
            else 0
        )
        self.rating.blockSignals(True)
        self.rating.setCurrentIndex(max(0, min(5, rating)) if type(rating) is int else 0)
        self.rating.blockSignals(False)
        self.rating.setEnabled(True)

    def set_rating(self):
        if not self.metadata:
            return
        ratings = self.context.get_setting("ratings", {})
        ratings = ratings if isinstance(ratings, dict) else {}
        path = self.metadata["path"]
        ratings.pop(path, None)
        ratings[path] = self.rating.currentData()
        while len(ratings) > 256:
            del ratings[next(iter(ratings))]
        self.context.set_setting("ratings", ratings)

    def deactivate(self):
        if self.token:
            self.token.cancel()
