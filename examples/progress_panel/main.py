"""Live navigation with a persistent, independently docked thumbnail strip."""

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QImageReader, QTransform
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from picer.plugins import RoundedSlider, SettingField, ui_icon

from .preview import PreviewStrip


class Plugin:
    def activate(self, context):
        self.context = context
        self.fields = (
            SettingField("thumbnail_size", "预览图片大小（像素）", "int", 80, 48, 200),
            SettingField("thumbnail_count", "预览图片数量", "int", 9, 3, 30),
            SettingField("interval", "幻灯片间隔（秒）", "int", 3, 1, 30),
        )
        context.add_settings(self.fields, self.apply_settings)
        self.panel = QWidget()
        self.panel.setMinimumWidth(200)
        self.panel.setStyleSheet(
            "QPushButton#progressButton { padding: 0; border: none;"
            " border-radius: 10px; background: #38383B; }"
            " QSlider { background: transparent; }"
        )
        self.layout = QVBoxLayout(self.panel)
        self.layout.setContentsMargins(16, 3, 16, 6)
        self.layout.setSpacing(2)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(8)
        self.buttons.addStretch(1)
        self.controls = {}
        for key, icon, tip, callback in (
            ("previous", "left", "上一张", lambda: context.navigate(-1)),
            ("next", "right", "下一张", lambda: context.navigate(1)),
            ("preview", "grid", "弹出缩略预览", self.show_preview),
            ("rotate", "rotate", "旋转", self.rotate),
            ("slideshow", "play", "幻灯片", self.toggle_slideshow),
        ):
            button = QPushButton()
            button.setIcon(ui_icon(icon))
            button.setObjectName("progressButton")
            button.setFixedSize(30, 28)
            button.setIconSize(QSize(16, 16))
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.clicked.connect(callback)
            self.buttons.addWidget(button)
            self.controls[key] = button
        self.layout.addLayout(self.buttons)
        self.buttons.addStretch(1)
        self.progress_row = QHBoxLayout()
        self.slider = RoundedSlider(Qt.Orientation.Horizontal)
        self.slider.setTracking(True)
        self.slider.valueChanged.connect(self.seek)
        self.count = QLabel("0/0")
        self.progress_row.addWidget(self.slider, 1)
        self.progress_row.addWidget(self.count)
        self.layout.addLayout(self.progress_row)
        self.dock = context.add_panel(self.panel, area="bottom")
        self.preview = PreviewStrip(self)
        self.timer = QTimer(self.panel)
        self.timer.timeout.connect(lambda: context.navigate(1))
        self.preview_token = None
        self.refresh_timer = QTimer(self.panel)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(30)
        self.refresh_timer.timeout.connect(self.refresh_preview)
        self.compact(False)
        context.subscribe("image.changed", self.on_image)
        self.apply_settings()
        self.update_progress()

    def values(self):
        return {
            field.key: field.validate(self.context.get_setting(field.key, field.default))
            for field in self.fields
        }

    def apply_settings(self):
        self.timer.setInterval(self.values()["interval"] * 1000)
        if self.preview.isVisible():
            self.refresh_timer.start()

    def compact(self, expanded):
        for button in self.controls.values():
            button.setFixedSize(30, 20 if expanded else 28)
        self.controls["preview"].setIcon(ui_icon("grid", "#E8FF59" if expanded else "#F3F3F0"))
        self.layout.setContentsMargins(16, 2 if expanded else 3, 16, 2 if expanded else 6)
        self.layout.setSpacing(0 if expanded else 2)
        self.slider.setFixedHeight(16 if expanded else 20)
        self.panel.setFixedHeight(40 if expanded else 60)
        self.dock.setFixedHeight(52 if expanded else 72)
        self.dock.setProperty("compactHeight", 52 if expanded else 72)
        host = self.dock.parentWidget()
        host.panel_hovers.layout_strips()

    def on_image(self, event):
        self.update_progress()
        if self.preview.isVisible():
            paths = self.context.image_paths()
            path = self.context.current_path()
            self.preview.items = [
                item
                for item in self.preview.items
                if 0 <= item[0] < len(paths) and str(paths[item[0]]) == item[1]
            ]
            self.preview.center_index = paths.index(path) if path in paths else 0
            self.preview.update()
            self.refresh_timer.start()

    def update_progress(self):
        paths = self.context.image_paths()
        path = self.context.current_path()
        index = paths.index(path) if path in paths else -1
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(0, len(paths) - 1))
        self.slider.setValue(max(0, index))
        self.slider.blockSignals(False)
        self.slider.setEnabled(len(paths) > 1)
        self.count.setText(f"{index + 1}/{len(paths)}")
        for button in self.controls.values():
            button.setEnabled(bool(paths))
        if len(paths) < 2 and self.timer.isActive():
            self.timer.stop()
            self.controls["slideshow"].setIcon(ui_icon("play"))

    def seek(self, index):
        paths = self.context.image_paths()
        if paths and paths[index] != self.context.current_path():
            self.context.jump_to(index)

    def rotate(self):
        if self.context.current_path():
            self.context.replace_image(self.context.image().transformed(QTransform().rotate(90)))

    def toggle_slideshow(self):
        if self.timer.isActive():
            self.timer.stop()
        elif len(self.context.image_paths()) > 1:
            self.timer.start()
        self.controls["slideshow"].setIcon(ui_icon("pause" if self.timer.isActive() else "play"))

    def show_preview(self):
        if self.preview.isVisible():
            self.preview.hide()
            self.refresh_timer.stop()
            if self.preview_token:
                self.preview_token.cancel()
            return
        if not self.context.image_paths():
            return
        self.preview.show()
        self.refresh_preview()

    def refresh_preview(self):
        if not self.preview.isVisible():
            return
        paths = self.context.image_paths()
        if not paths:
            return
        if self.preview_token:
            self.preview_token.cancel()
        values = self.values()
        index = paths.index(self.context.current_path())
        count = min(len(paths), values["thumbnail_count"])
        start = max(0, min(index - count // 2, len(paths) - count))
        selected = tuple((i, paths[i]) for i in range(start, start + count))
        size = values["thumbnail_size"]
        self.preview.thumbnail_size = size
        self.preview.center_index = index
        # Expansion compresses the controls first; anchor to the resulting card.
        self.preview.reposition()

        def work(token):
            thumbnails = []
            for image_index, path in selected:
                token.checkpoint()
                reader = QImageReader(str(path))
                reader.setAutoTransform(True)
                original = reader.size()
                if original.isValid():
                    reader.setScaledSize(
                        original.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio)
                    )
                thumbnails.append((image_index, str(path), reader.read()))
            return thumbnails

        def render(thumbnails):
            if not self.preview.isVisible():
                return
            self.preview.items = thumbnails
            self.preview.update()

        self.preview_token = self.context.run_task(work, render)

    def deactivate(self):
        self.timer.stop()
        self.refresh_timer.stop()
        self.preview.close()
        self.preview.deleteLater()
        if self.preview_token:
            self.preview_token.cancel()
