"""Metadata groups scroll independently of the fixed bottom EXIF region."""

import math

from PySide6.QtCore import QEvent, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from picer.plugins import SettingField

from .annotations import Annotations
from .exif_view import ExifView
from .labels import DetailLabel


def section(label):
    group = QGroupBox()
    layout = QVBoxLayout(group)
    layout.setContentsMargins(0, 6, 0, 6)
    heading = DetailLabel(label)
    heading.setStyleSheet("color: #A2A2A6;")
    layout.addWidget(heading)
    return group, layout


class DetailPanel(QWidget):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def eventFilter(self, obj, event):
        return self.callback(obj, event)


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
        self.read_timer = QTimer()
        self.read_timer.setSingleShot(True)
        self.read_timer.setInterval(180)
        self.read_timer.timeout.connect(self.read_metadata)
        self.fields = tuple(
            SettingField(key, label, "bool", True)
            for key, label in (
                ("file", "文件信息"),
                ("dimensions", "尺寸与格式"),
                ("color", "颜色信息"),
                ("histogram", "RGB 直方图"),
                ("rating", "星级"),
                ("classification", "颜色分类"),
                ("extra", "其他元数据"),
            )
        )
        context.add_settings(self.fields, self.apply_settings)
        self.panel = DetailPanel(self.resize_details)
        self.panel.setMinimumWidth(180)
        self.panel.setStyleSheet("QGroupBox { margin: 0; padding: 0; border: none; }")
        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(12, 12, 12, 0)
        top = QHBoxLayout()
        self.title = DetailLabel("图片信息")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(True)
        top.addWidget(self.title, 1)
        layout.addLayout(top)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().installEventFilter(self.panel)
        body = QWidget()
        body.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
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
            group, rows = section(label)
            table = QFormLayout()
            table.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            table.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
            rows.addLayout(table)
            self.groups[key], self.tables[key] = group, table
            self.body.addWidget(group)
        group, row = section("RGB 直方图（对数刻度）")
        self.groups["histogram"] = group
        self.histogram = Histogram()
        self.sample_label = DetailLabel()
        row.addWidget(self.histogram)
        row.addWidget(self.sample_label)
        self.body.addWidget(group)
        self.warning = DetailLabel()
        self.warning.setWordWrap(True)
        self.body.addWidget(self.warning)
        self.body.addStretch()
        self.scroll.setWidget(body)
        layout.addWidget(self.scroll, 1)
        # A separate layout region, never a scroll child or overlay over other details.
        self.exif_box, exif_layout = section("相机 EXIF")
        self.exif_view = ExifView(self.panel)
        exif_layout.addWidget(self.exif_view)
        layout.addWidget(self.exif_box, 0)
        self.exif_box.hide()
        self.rating = Annotations()
        self.rating.ratingChanged.connect(self.set_rating)
        self.rating.categoryChanged.connect(self.set_category)
        layout.addWidget(self.rating, 0)
        self.dock = context.add_panel(self.panel, area="right")
        context.subscribe("image.changed", self.on_image)
        self.apply_settings()
        self.refresh()

    def resize_details(self, obj, event):
        if event.type() == QEvent.Type.Resize and hasattr(self, "tables"):
            policy = (
                QFormLayout.RowWrapPolicy.WrapAllRows
                if obj.width() < 320
                else QFormLayout.RowWrapPolicy.DontWrapRows
            )
            for table in self.tables.values():
                table.setRowWrapPolicy(policy)
        return False

    def apply_settings(self):
        for field in self.fields:
            if field.key in self.groups:
                self.groups[field.key].setVisible(
                    field.validate(self.context.get_setting(field.key, True))
                )
        self.rating.configure(
            bool(self.context.get_setting("rating", True)),
            bool(self.context.get_setting("classification", True)),
        )

    def on_image(self, event):
        self.refresh()

    def refresh(self):
        self.read_timer.stop()
        if self.token:
            self.token.cancel()
        path = self.context.current_path()
        self.title.setText(path.name if path else "打开图片后查看信息")
        self.exif_box.hide()
        self.exif_view.clear()
        self.metadata = None
        self.warning.setText("正在读取元数据…" if path else "")
        for table in self.tables.values():
            while table.rowCount():
                table.removeRow(0)
        self.histogram.channels = []
        self.histogram.update()
        self.rating.set_values(0, "")
        self.rating.setEnabled(False)
        if path:
            self.read_timer.start()

    def read_metadata(self):
        self.token = self.context.request_metadata(self.show_metadata)

    def show_metadata(self, data):
        if str(self.context.current_path()) != data["path"]:
            return
        self.metadata = data
        for key, table in self.tables.items():
            for label, value in data.get(key, {}).items():
                widget = DetailLabel(str(value))
                widget.setTextFormat(Qt.TextFormat.PlainText)
                widget.setWordWrap(True)
                widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                table.addRow(DetailLabel(str(label)), widget)
        self.histogram.channels = data.get("histogram", [])
        self.histogram.update()
        self.sample_label.setText(
            "采样尺寸：" + " × ".join(str(v) for v in data.get("sample_size", ()))
        )
        self.exif_view.set_data(data.get("exif_sections", {}))
        self.exif_box.setVisible(bool(data["exif"]))
        self.warning.setText("\n".join(data["warnings"]))
        ratings = self.context.get_setting("ratings", {})
        rating = (
            ratings.get(data["path"], data.get("embedded_rating", 0))
            if isinstance(ratings, dict)
            else 0
        )
        categories = self.context.get_setting("color_labels", {})
        category = categories.get(data["path"], "") if isinstance(categories, dict) else ""
        self.rating.set_values(rating, category)
        self.rating.setEnabled(True)

    def set_rating(self, value):
        if not self.metadata:
            return
        ratings = self.context.get_setting("ratings", {})
        ratings = ratings if isinstance(ratings, dict) else {}
        path = self.metadata["path"]
        ratings.pop(path, None)
        ratings[path] = value
        while len(ratings) > 256:
            del ratings[next(iter(ratings))]
        self.context.set_setting("ratings", ratings)

    def set_category(self, value):
        if not self.metadata:
            return
        categories = self.context.get_setting("color_labels", {})
        categories = categories if isinstance(categories, dict) else {}
        path = self.metadata["path"]
        categories.pop(path, None)
        if value:
            categories[path] = value
        self.context.set_setting("color_labels", categories)

    def deactivate(self):
        self.read_timer.stop()
        if self.token:
            self.token.cancel()
