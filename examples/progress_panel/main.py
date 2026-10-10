"""Live navigation with a persistent, independently docked thumbnail strip."""

from PySide6.QtCore import QEasingCurve, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from picer.imaging import read_image
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
        self.playback = QWidget(self.panel)
        playback_row = QHBoxLayout(self.playback)
        playback_row.setContentsMargins(0, 0, 0, 0)
        playback_row.setSpacing(8)
        self.playback_slider = RoundedSlider(Qt.Orientation.Horizontal)
        self.playback_slider.setTracking(True)
        self.playback_slider.valueChanged.connect(context.seek_animation)
        self.playback_count = QLabel("0/0")
        self.playback_button = QPushButton()
        self.playback_button.setObjectName("progressButton")
        self.playback_button.setFixedSize(24, 24)
        self.playback_button.setIconSize(QSize(14, 14))
        self.playback_button.clicked.connect(context.toggle_animation)
        playback_row.addWidget(self.playback_slider, 1)
        playback_row.addWidget(self.playback_count)
        playback_row.addWidget(self.playback_button)
        self.layout.addWidget(self.playback)
        self.playback_opacity = QGraphicsOpacityEffect(self.playback)
        self.playback.setGraphicsEffect(self.playback_opacity)
        self.playback_expansion = 0.0
        self.playback_target = False
        self.playback_motion = QVariantAnimation(self.panel)
        self.playback_motion.valueChanged.connect(self.set_playback_expansion)
        self.playback_motion.finished.connect(self.finish_playback_motion)
        self.playback.hide()
        self.dock = context.add_panel(self.panel, area="bottom")
        self.preview = PreviewStrip(self)
        self.preview_open = False
        self.expansion = 0.0
        self.motion = QVariantAnimation(self.panel)
        self.motion.valueChanged.connect(self.set_expansion)
        self.motion.finished.connect(self.finish_motion)
        self.timer = QTimer(self.panel)
        self.timer.timeout.connect(lambda: context.navigate(1))
        self.preview_token = None
        self.refresh_timer = QTimer(self.panel)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(30)
        self.refresh_timer.timeout.connect(self.refresh_preview)
        self.compact(False, animate=False)
        context.subscribe("image.changed", self.on_image)
        context.subscribe("animation.changed", self.on_animation)
        self.on_animation(context.animation_state())
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

    def compact(self, expanded, *, animate=True):
        target = 1.0 if expanded else 0.0
        self.controls["preview"].setIcon(ui_icon("grid", "#E8FF59" if expanded else "#F3F3F0"))
        self.motion.stop()
        if not animate:
            self.set_expansion(target)
            return
        # Changing endpoints can emit intermediate values from the previous
        # timeline; suppress those while rebuilding a reversed transition.
        self.motion.blockSignals(True)
        self.motion.setDuration(
            max(80, round((280 if expanded else 220) * abs(target - self.expansion)))
        )
        self.motion.setEasingCurve(
            QEasingCurve.Type.OutCubic if expanded else QEasingCurve.Type.InOutCubic
        )
        self.motion.setStartValue(self.expansion)
        self.motion.setEndValue(target)
        self.motion.setCurrentTime(0)
        self.motion.blockSignals(False)
        self.motion.start()

    def set_expansion(self, value):
        self.expansion = float(value)
        for button in self.controls.values():
            button.setFixedSize(30, round(28 - 8 * self.expansion))
        self.layout.setContentsMargins(
            16, round(3 - self.expansion), 16, round(6 - 4 * self.expansion)
        )
        self.layout.setSpacing(round(2 - 2 * self.expansion))
        self.slider.setFixedHeight(round(20 - 4 * self.expansion))
        self.apply_height()
        self.preview.reveal = self.expansion
        self.preview.reposition()
        self.preview.update()

    def apply_height(self):
        extra = round(28 * self.playback_expansion)
        self.playback.setFixedHeight(extra)
        self.panel.setFixedHeight(round(60 - 20 * self.expansion) + extra)
        height = round(72 - 20 * self.expansion) + extra
        self.dock.setFixedHeight(height)
        self.dock.setProperty("compactHeight", height)
        self.dock.parentWidget().panel_hovers.layout_strips()
        self.preview.reposition()

    def on_animation(self, state):
        self.playback_slider.blockSignals(True)
        self.playback_slider.setRange(0, max(0, state.count - 1))
        self.playback_slider.setValue(state.frame)
        self.playback_slider.blockSignals(False)
        self.playback_slider.setEnabled(state.active)
        self.playback_button.setEnabled(state.active)
        self.playback_button.setIcon(ui_icon("pause" if state.playing else "play"))
        tip = "暂停动画" if state.playing else "播放动画"
        self.playback_button.setToolTip(tip)
        self.playback_button.setAccessibleName(tip)
        self.playback_count.setText(f"{state.frame + 1 if state.active else 0}/{state.count}")
        if state.active == self.playback_target:
            return
        self.playback_target = state.active
        target = 1.0 if state.active else 0.0
        self.playback_motion.stop()
        self.playback.show()
        self.playback_motion.blockSignals(True)
        self.playback_motion.setDuration(
            max(80, round((280 if state.active else 220) * abs(target - self.playback_expansion)))
        )
        self.playback_motion.setEasingCurve(
            QEasingCurve.Type.OutCubic if state.active else QEasingCurve.Type.InOutCubic
        )
        self.playback_motion.setStartValue(self.playback_expansion)
        self.playback_motion.setEndValue(target)
        self.playback_motion.setCurrentTime(0)
        self.playback_motion.blockSignals(False)
        self.playback_motion.start()

    def set_playback_expansion(self, value):
        self.playback_expansion = float(value)
        self.playback_opacity.setOpacity(self.playback_expansion)
        self.apply_height()

    def finish_playback_motion(self):
        if not self.playback_target:
            self.playback.hide()

    def finish_motion(self):
        if not self.preview_open:
            self.preview.hide()

    def on_image(self, event):
        self.update_progress()
        if self.preview_open:
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
            self.context.rotate_image()

    def toggle_slideshow(self):
        if self.timer.isActive():
            self.timer.stop()
        elif len(self.context.image_paths()) > 1:
            self.timer.start()
        self.controls["slideshow"].setIcon(ui_icon("pause" if self.timer.isActive() else "play"))

    def show_preview(self):
        if self.preview_open:
            self.preview_open = False
            self.compact(False)
            self.refresh_timer.stop()
            if self.preview_token:
                self.preview_token.cancel()
            return
        if not self.context.image_paths():
            return
        self.preview_open = True
        self.preview.show()
        self.compact(True)
        self.refresh_preview()

    def refresh_preview(self):
        if not self.preview_open:
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
                try:
                    image = read_image(path, edge=size, token=token)
                except (OSError, ValueError, RuntimeError):
                    continue
                thumbnails.append((image_index, str(path), image))
            return thumbnails

        def render(thumbnails):
            if not self.preview.isVisible():
                return
            self.preview.items = thumbnails
            self.preview.update()

        self.preview_token = self.context.run_task(work, render)

    def deactivate(self):
        self.motion.stop()
        self.playback_motion.stop()
        self.preview_open = False
        self.timer.stop()
        self.refresh_timer.stop()
        self.preview.close()
        self.preview.deleteLater()
        if self.preview_token:
            self.preview_token.cancel()
