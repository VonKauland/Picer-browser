"""Revocable GUI session with one background preview/save job and stale-result guards."""

import copy

from PIL import Image
from PySide6.QtCore import QEvent, QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QApplication, QGraphicsRectItem

from picer.editing.engine import defaults, fingerprint, render, save_image, to_pillow
from picer.imaging import pillow_image, read_image
from picer.plugins.api import PluginError


class EditingSession(QObject):
    changed = Signal()
    picked = Signal(int)
    cropped = Signal(object)
    saved = Signal(object)

    def __init__(self, context, host):
        super().__init__(host)
        self.context, self.host = context, host
        self.active, self.applying, self.applied = True, False, False
        self.touched = False
        self.path, self.source, self.stamp = None, None, None
        self.native = (0, 0)
        self.state = defaults()
        self.error, self.busy, self.saving = "", False, False
        self.generation = 0
        self.mode, self.origin, self.outline = "", None, None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self.refresh)
        context.subscribe("image.changed", self.on_image)
        QApplication.instance().installEventFilter(self)
        self.on_image(None)

    def on_image(self, event):
        if not self.active or self.applying or (event and event.reason != "opened"):
            return
        self.cancel_tool()
        self.path = self.host.current_path
        self.source, self.stamp = None, None
        self.native = (0, 0)
        self.state = defaults()
        self.applied, self.error = False, ""
        self.touched = False
        self.generation += 1
        self.timer.start()
        self.changed.emit()

    def set_state(self, state):
        from picer.editing.engine import validate

        self.state = validate(state)
        self.generation += 1
        self.cancel_tool()
        self.timer.start()
        self.changed.emit()

    def refresh(self):
        if not self.active or not self.path or self.busy or self.saving:
            return
        generation, path = self.generation, self.path
        state, source, native, stamp = (
            copy.deepcopy(self.state),
            self.source,
            self.native,
            self.stamp,
        )
        self.busy = True
        self.changed.emit()

        def work(token):
            try:
                base, size, mark = source, native, stamp
                if base is None:
                    mark = fingerprint(path)
                    try:
                        with Image.open(path) as opened:
                            if getattr(opened, "n_frames", 1) > 1:
                                return {"error": "动态图暂不支持简易编辑"}
                    except OSError:
                        pass  # RAW and Qt-only formats use the shared decoder below.
                    image = read_image(path, edge=1600, token=token)
                    base = to_pillow(image)
                    size = (
                        int(image.text("picer.native_width")),
                        int(image.text("picer.native_height")),
                    )
                    if fingerprint(path) != mark:
                        return {"error": "原文件已改变，请重新打开"}
                output, dimensions = render(base, state, native=size, edge=1600, token=token)
                return {
                    "source": base,
                    "native": size,
                    "stamp": mark,
                    "image": pillow_image(output),
                    "size": dimensions,
                }
            except Exception as error:
                return {"error": str(error)}

        def done(result):
            self.busy = False
            if generation != self.generation or self.host.current_path != path:
                self.timer.start(0)
                return
            self.error = result.get("error", "")
            if not self.error:
                self.source, self.native, self.stamp = (
                    result["source"],
                    result["native"],
                    result["stamp"],
                )
                if source is None and not state["resize"]["enabled"]:
                    self.state["resize"].update(width=self.native[0], height=self.native[1])
                if any(row["enabled"] for row in state.values()):
                    self.present(result["image"], result["size"])
                elif self.applied:
                    self.present(pillow_image(self.source), self.native)
                    self.applied = False
                    self.host.image_edited = False
            self.changed.emit()

        try:
            self.context.run_task(work, done, image_bound=False)
        except PluginError as error:
            self.busy = False
            self.error = str(error)
            self.changed.emit()
            self.timer.start(250)

    def present(self, image, size):
        self.applying = True
        try:
            self.host.replace_image(image)
            self.host.source_size = size
            self.host.view.native_width = size[0]
            self.host.view.image_item.setScale(size[0] / image.width())
            self.host.view.scene.setSceneRect(self.host.view.image_item.sceneBoundingRect())
            self.host.view.fit_image()
            self.applied = True
            self.touched = True
        finally:
            self.applying = False

    def save(self, overwrite):
        if not self.active or self.saving or self.busy or not self.source or not self.stamp:
            return False
        path, state, stamp, generation = (
            self.path,
            copy.deepcopy(self.state),
            self.stamp,
            self.generation,
        )
        self.cancel_tool()
        self.saving = True
        self.changed.emit()

        def work(token):
            try:
                return {"path": save_image(path, state, stamp, overwrite=overwrite, token=token)}
            except Exception as error:
                return {"error": str(error)}

        def done(result):
            self.saving = False
            if result.get("error"):
                self.error = result["error"]
                self.context.notify("未保存：" + self.error)
            else:
                self.context.notify("已保存覆盖" if overwrite else "已保存副本")
                self.saved.emit(result["path"])
                if generation == self.generation and self.host.current_path == path:
                    self.host.loader.cache.clear()
                    self.host.loader.cache_bytes = 0
                    self.host.open_image(result["path"])
            if generation != self.generation:
                self.timer.start(0)
            self.changed.emit()

        try:
            self.context.run_task(work, done, image_bound=False)
        except PluginError as error:
            self.saving = False
            self.error = str(error)
            self.changed.emit()
            return False
        return True

    def begin_tool(self, mode):
        if not self.source or self.error or self.saving or self.busy:
            return
        self.cancel_tool()
        self.mode = mode
        if mode == "crop":
            # Select on unmodified source coordinates; apply the complete chain afterwards.
            self.present(pillow_image(self.source), self.native)
        self.host.view.viewport().setCursor(Qt.CursorShape.CrossCursor)
        self.host.view.setFocus()

    def cancel_tool(self):
        if self.outline:
            self.host.view.scene.removeItem(self.outline)
            self.outline = None
        self.origin, self.mode = None, ""
        self.host.view.viewport().unsetCursor()

    def eventFilter(self, obj, event):
        if not self.active or not self.mode or self.host.current_path != self.path:
            return False
        view = self.host.view
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.cancel_tool()
            self.timer.start()
            return True
        if obj is not view.viewport() or event.type() not in {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonRelease,
        }:
            return False
        item = view.image_item
        point = item.mapFromScene(view.mapToScene(event.position().toPoint()))
        bounds = item.boundingRect()
        point.setX(max(0, min(bounds.width(), point.x())))
        point.setY(max(0, min(bounds.height(), point.y())))
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
        ):
            if self.mode == "pick":
                image = item.pixmap().toImage()
                color = image.pixelColor(
                    min(image.width() - 1, int(point.x())), min(image.height() - 1, int(point.y()))
                )
                self.cancel_tool()
                self.picked.emit(max(0, color.hsvHue()))
            else:
                self.origin = point
                self.outline = QGraphicsRectItem(item)
                pen = QPen(QColor(self.context.accent_color()), 1, Qt.PenStyle.DashLine)
                pen.setCosmetic(True)
                self.outline.setPen(pen)
            return True
        if self.origin is not None and event.type() == QEvent.Type.MouseMove:
            self.outline.setRect(QRectF(self.origin, point).normalized())
            return True
        if self.origin is not None and event.type() == QEvent.Type.MouseButtonRelease:
            rect = QRectF(self.origin, point).normalized()
            self.cancel_tool()
            if rect.width() > 1 and rect.height() > 1:
                self.cropped.emit(
                    {
                        "x": rect.x() / bounds.width(),
                        "y": rect.y() / bounds.height(),
                        "w": rect.width() / bounds.width(),
                        "h": rect.height() / bounds.height(),
                    }
                )
            else:
                self.timer.start()
            return True
        return False

    def close(self):
        self.active = False
        self.timer.stop()
        self.cancel_tool()
        QApplication.instance().removeEventFilter(self)
        self.source = None
        if self.touched and self.host.current_path == self.path and not self.host.plugins._closed:
            self.host.open_image(self.path)
        self.deleteLater()
