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

from picer.plugins import PluginError, SettingField
from picer.ui import Toggle

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
                ("ai", "AI 生成信息"),
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
        self.ai_box, ai_layout = section("AI 生成信息")
        self.ai_notice = DetailLabel()
        ai_layout.addWidget(self.ai_notice)
        self.ai_table = QFormLayout()
        self.ai_table.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.ai_table.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        ai_layout.addLayout(self.ai_table)
        self.body.addWidget(self.ai_box)
        self.ai_box.hide()
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
        focus_row = QHBoxLayout()
        focus_row.addWidget(DetailLabel("显示对焦点"), 1)
        self.focus_switch = Toggle()
        self.focus_switch.setAccessibleName("在图片中显示记录的对焦点")
        self.focus_switch.setChecked(bool(context.get_setting("show_focus_points", False)))
        self.focus_switch.setEnabled(False)
        self.focus_switch.toggled.connect(self.set_focus_enabled)
        focus_row.addWidget(self.focus_switch)
        focus_row.addSpacing(8)
        focus_row.addWidget(DetailLabel("机内直出"), 1)
        self.camera_switch = Toggle()
        self.camera_switch.setAccessibleName("查看 RAW 内嵌的机内直出预览")
        self.camera_switch.setEnabled(False)
        self.camera_switch.toggled.connect(self.set_camera_enabled)
        focus_row.addWidget(self.camera_switch)
        exif_layout.addLayout(focus_row)
        layout.addWidget(self.exif_box, 0)
        self.exif_box.hide()
        self.rating = Annotations()
        self.rating.ratingChanged.connect(self.set_rating)
        self.rating.categoryChanged.connect(self.set_category)
        layout.addWidget(self.rating, 0)
        self.dock = context.add_panel(self.panel, area="right")
        context.subscribe("image.changed", self.on_image)
        context.subscribe("annotations.changed", self.on_annotations)
        self.apply_settings()
        try:
            context.set_raw_camera_preview(bool(context.get_setting("raw_camera_preview", False)))
        except PluginError:
            context.set_setting("raw_camera_preview", False)
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
            self.ai_table.setRowWrapPolicy(policy)
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
        self.ai_box.setVisible(
            bool(self.metadata and self.metadata.get("ai_generation"))
            and bool(self.context.get_setting("ai", True))
        )

    def on_image(self, event):
        if event and event.reason in ("rotated", "raw-preview") and self.metadata:
            self.update_focus()
            return
        self.refresh()

    def refresh(self):
        self.context.show_focus_points(None)
        self.focus_switch.setEnabled(False)
        self.camera_switch.setEnabled(False)
        self.camera_switch.blockSignals(True)
        self.camera_switch.setChecked(False)
        self.camera_switch.blockSignals(False)
        self.read_timer.stop()
        if self.token:
            self.token.cancel()
        path = self.context.current_path()
        self.title.setText(path.name if path else "打开图片后查看信息")
        self.exif_box.hide()
        self.exif_view.clear()
        self.metadata = None
        self.ai_box.hide()
        while self.ai_table.rowCount():
            self.ai_table.removeRow(0)
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
        self.exif_box.setVisible(bool(data["exif"]) or "raw_camera_preview_available" in data)
        self.update_focus()
        available = bool(data.get("raw_camera_preview_available"))
        self.camera_switch.setEnabled(available)
        self.camera_switch.blockSignals(True)
        self.camera_switch.setChecked(
            available and bool(self.context.get_setting("raw_camera_preview", False))
        )
        self.camera_switch.blockSignals(False)
        self.camera_switch.setToolTip(
            "使用 RAW 内嵌的相机处理预览，分辨率取决于相机"
            if available
            else "此图片没有可用的 RAW 机内预览"
        )
        ai = data.get("ai_generation")
        while self.ai_table.rowCount():
            self.ai_table.removeRow(0)
        self.ai_box.setVisible(bool(ai) and bool(self.context.get_setting("ai", True)))
        if ai:
            self.ai_notice.setText(ai["message"])
            for label, value in ai["fields"].items():
                widget = DetailLabel(str(value) or "未记录")
                widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                self.ai_table.addRow(DetailLabel(str(label)), widget)
        self.warning.setText("\n".join(data["warnings"]))
        self.update_annotations()
        self.rating.setEnabled(True)

    def set_focus_enabled(self, enabled):
        self.context.set_setting("show_focus_points", bool(enabled))
        self.update_focus()

    def set_camera_enabled(self, enabled):
        previous = bool(self.context.get_setting("raw_camera_preview", False))
        try:
            self.context.set_setting("raw_camera_preview", bool(enabled))
            self.context.set_raw_camera_preview(bool(enabled))
        except PluginError as error:
            self.context.set_setting("raw_camera_preview", previous)
            self.camera_switch.blockSignals(True)
            self.camera_switch.setChecked(not enabled)
            self.camera_switch.blockSignals(False)
            self.context.notify(str(error))

    def update_focus(self):
        data = self.metadata.get("focus_points", {}) if self.metadata else {}
        available = bool(data.get("boxes") or data.get("faces") or data.get("face_points"))
        self.focus_switch.blockSignals(True)
        self.focus_switch.setChecked(
            available and bool(self.context.get_setting("show_focus_points", False))
        )
        self.focus_switch.blockSignals(False)
        self.focus_switch.setEnabled(available)
        self.focus_switch.setToolTip(
            "实线显示记录的对焦区域，虚线显示人脸框；仅有中心记录时显示定位标记。"
            if available
            else data.get("message", "此照片未记录可识别的对焦点或人脸区域")
        )
        try:
            self.context.show_focus_points(
                data if available and self.focus_switch.isChecked() else None
            )
        except PluginError as error:
            self.focus_switch.setToolTip(str(error))

    def update_annotations(self):
        if self.metadata:
            mark = self.context.image_annotation(self.metadata["path"])
            rating = mark.get("rating")
            self.rating.set_values(
                self.metadata.get("embedded_rating", 0) if rating is None else rating,
                mark.get("color", ""),
            )

    def on_annotations(self, event):
        if self.metadata and event["path"] == self.metadata["path"]:
            self.update_annotations()

    def save_annotations(self, **values):
        if self.metadata:
            try:
                self.context.set_image_annotation(self.metadata["path"], **values)
            except PluginError as error:
                self.update_annotations()
                self.context.notify(f"标注未保存：{error}")

    def set_rating(self, value):
        self.save_annotations(rating=value)

    def set_category(self, value):
        self.save_annotations(color=value)

    def deactivate(self):
        self.read_timer.stop()
        if self.token:
            self.token.cancel()
