"""Orientation-aware navigation and asynchronous bounded thumbnail previews."""

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QImageReader, QPixmap, QTransform
from PySide6.QtWidgets import (
    QBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from picer.plugins import RoundedSlider, SettingField, ui_icon


def make_preview(context, parent):
    preview = context.frosted_surface(parent, popup=True)
    layout = QVBoxLayout(preview)
    layout.setContentsMargins(10, 10, 10, 10)
    preview.list = QListWidget()
    preview.list.setWrapping(False)
    preview.list.setResizeMode(QListWidget.ResizeMode.Adjust)
    preview.list.setSpacing(6)
    layout.addWidget(preview.list)
    return preview


class Plugin:
    def activate(self, context):
        self.context = context
        self.fields = (
            SettingField("thumbnail_size", "预览图片大小（像素）", "int", 96, 48, 200),
            SettingField("thumbnail_count", "预览图片数量", "int", 9, 3, 30),
            SettingField("interval", "幻灯片间隔（秒）", "int", 3, 1, 30),
        )
        context.add_settings(self.fields, self.apply_settings)
        self.panel = QWidget()
        self.panel.setMinimumSize(170, 110)
        self.layout = QVBoxLayout(self.panel)
        self.layout.setContentsMargins(12, 12, 12, 12)
        self.buttons = QHBoxLayout()
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
            button.setObjectName("circleButton")
            button.setFixedSize(32, 32)
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.clicked.connect(callback)
            self.buttons.addWidget(button)
            self.controls[key] = button
        self.layout.addLayout(self.buttons)
        self.buttons.addStretch(1)
        self.progress_row = QHBoxLayout()
        self.slider = RoundedSlider(Qt.Orientation.Horizontal)
        self.slider.setTracking(False)
        self.slider.valueChanged.connect(self.seek)
        self.count = QLabel("0/0")
        self.progress_row.addWidget(self.slider, 1)
        self.progress_row.addWidget(self.count)
        self.layout.addLayout(self.progress_row)
        self.dock = context.add_panel(self.panel, area="bottom")
        self.dock.dockLocationChanged.connect(self.reorient)
        self.preview = make_preview(context, self.panel)
        self.preview.list.itemClicked.connect(self.select_preview)
        self.timer = QTimer(self.panel)
        self.timer.timeout.connect(lambda: context.navigate(1))
        self.preview_token = None
        self.reorient(self.dock.parentWidget().dockWidgetArea(self.dock))
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
            self.show_preview()

    def reorient(self, area):
        self.vertical = area in (
            Qt.DockWidgetArea.LeftDockWidgetArea,
            Qt.DockWidgetArea.RightDockWidgetArea,
        )
        self.slider.setOrientation(
            Qt.Orientation.Vertical if self.vertical else Qt.Orientation.Horizontal
        )
        self.slider.setInvertedAppearance(self.vertical)
        self.buttons.setDirection(
            QBoxLayout.Direction.TopToBottom if self.vertical else QBoxLayout.Direction.LeftToRight
        )
        self.layout.setDirection(
            QBoxLayout.Direction.LeftToRight if self.vertical else QBoxLayout.Direction.TopToBottom
        )
        self.progress_row.setDirection(
            QBoxLayout.Direction.TopToBottom if self.vertical else QBoxLayout.Direction.LeftToRight
        )
        self.preview.list.setFlow(
            QListWidget.Flow.TopToBottom if self.vertical else QListWidget.Flow.LeftToRight
        )
        self.preview.hide()

    def on_image(self, event):
        self.update_progress()
        self.preview.hide()

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
        if self.context.image_paths():
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
        self.preview.list.clear()
        self.preview.list.setIconSize(QSize(size, size))
        self.preview.resize(
            size + 70 if self.vertical else min(1000, count * (size + 26)),
            min(700, count * (size + 28)) if self.vertical else size + 70,
        )
        origin = self.panel.mapToGlobal(self.panel.rect().topLeft())
        screen = self.panel.screen().availableGeometry()
        x = min(max(screen.left(), origin.x()), screen.right() - self.preview.width())
        y = min(
            max(screen.top(), origin.y() - self.preview.height()),
            screen.bottom() - self.preview.height(),
        )
        self.preview.move(x, y)
        self.preview.show()

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
            for image_index, path, image in thumbnails:
                item = QListWidgetItem(QIcon(QPixmap.fromImage(image)), str(image_index + 1))
                item.setToolTip(path)
                item.setData(Qt.ItemDataRole.UserRole, image_index)
                self.preview.list.addItem(item)

        self.preview_token = self.context.run_task(work, render)

    def select_preview(self, item):
        self.context.jump_to(item.data(Qt.ItemDataRole.UserRole))
        self.preview.hide()

    def deactivate(self):
        self.timer.stop()
        self.preview.close()
        if self.preview_token:
            self.preview_token.cancel()
