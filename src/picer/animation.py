"""On-demand composited GIF/WebP frames, bounded cache and background seeking."""

from collections import OrderedDict
from threading import Lock

from PIL import Image
from PySide6.QtCore import QObject, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QImageReader

from picer.imaging import MAX_PIXELS, pillow_image
from picer.media_types import AnimationState
from picer.plugins.tasks import Worker


class FrameSource:
    def __init__(self, path):
        self.reader = Image.open(path)
        if self.reader.width * self.reader.height > MAX_PIXELS:
            self.reader.close()
            raise ValueError("动画超过 1.2 亿像素的读取上限")
        self.count = self.reader.n_frames
        self.loop = self.reader.info.get("loop", -1)
        if self.reader.format == "WEBP" and self.loop > 0:
            self.loop -= 1
            if self.loop == 0:
                self.loop = -1
        self.cache = OrderedDict()
        self.bytes = 0
        self.lock = Lock()

    def frame(self, index, token):
        with self.lock:
            token.checkpoint()
            if index in self.cache:
                self.cache.move_to_end(index)
                return self.cache[index]
            self.reader.seek(index)
            image = pillow_image(self.reader)
            duration = max(1, int(self.reader.info.get("duration", 100) or 100))
            self.cache[index] = (image, duration)
            self.bytes += image.sizeInBytes()
            while self.cache and (len(self.cache) > 12 or self.bytes > 64 * 1048576):
                _, (removed, _) = self.cache.popitem(last=False)
                self.bytes -= removed.sizeInBytes()
            token.checkpoint()
            return image, duration

    def close(self):
        with self.lock:
            self.reader.close()
            self.cache.clear()
            self.bytes = 0


def animation_source(path, token):
    if bytes(QImageReader(str(path)).format()).lower() not in {b"gif", b"webp"}:
        return None
    source = FrameSource(path)
    if source.count <= 1:
        source.close()
        return None
    try:
        token.checkpoint()
    except Exception:
        source.close()
        raise
    return source


class AnimationPlayer(QObject):
    changed = Signal(object)
    pixels = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.advance)
        self.source = None
        self.state = AnimationState()
        self.generation = 0
        self.worker = None
        self.workers = {}
        self.loops = 0
        self.closed = False

    def publish(self, **changes):
        from dataclasses import replace

        self.state = replace(self.state, **changes)
        self.changed.emit(self.state)

    def cancel_frames(self):
        for key, worker in list(self.workers.items()):
            if worker.frame_task:
                worker.token.cancel()
                if self.pool.tryTake(worker):
                    self.workers.pop(key, None)
        self.worker = None

    def stop(self):
        self.timer.stop()
        self.generation += 1
        self.cancel_frames()
        source, self.source = self.source, None
        if source:
            self.submit(lambda token: source.close(), lambda result, error: None)
        self.publish(active=False, playing=False, frame=0, count=0, duration=0)

    def start(self, source):
        self.stop()
        self.source = source
        self.loops = 0
        self.publish(active=True, playing=True, frame=0, count=source.count)
        self.seek(0)

    def submit(self, work, callback, *, frame_task=False):
        worker = Worker(work)
        worker.setAutoDelete(False)
        worker.frame_task = frame_task
        key = id(worker)
        self.workers[key] = worker

        def finish(result, error):
            self.workers.pop(key, None)
            if not self.closed:
                callback(result, error)

        worker.signals.finished.connect(finish, Qt.ConnectionType.QueuedConnection)
        self.pool.start(worker)
        return worker

    def seek(self, index):
        if not self.source or not 0 <= index < self.state.count:
            return
        self.timer.stop()
        self.generation += 1
        generation, source = self.generation, self.source
        self.cancel_frames()
        self.publish(frame=index)

        def finish(result, error):
            if generation != self.generation:
                return
            if error:
                self.stop()
                self.failed.emit(str(error))
                return
            image, duration = result
            self.pixels.emit(image)
            self.publish(duration=duration)
            if self.state.playing:
                self.timer.start(duration)
                # Decode the next composited frame while this one is displayed.
                next_index = (index + 1) % source.count
                self.submit(
                    lambda token: source.frame(next_index, token),
                    lambda result, error: None,
                    frame_task=True,
                )

        self.worker = self.submit(lambda token: source.frame(index, token), finish, frame_task=True)

    def advance(self):
        if not self.source:
            return
        index = self.state.frame + 1
        if index == self.state.count:
            self.loops += 1
            if self.source.loop == -1 or (self.source.loop and self.loops > self.source.loop):
                self.toggle(False)
                return
            index = 0
        self.seek(index)

    def toggle(self, playing=None):
        if not self.source:
            return
        playing = not self.state.playing if playing is None else playing
        self.publish(playing=playing)
        if playing:
            self.seek(self.state.frame)
        else:
            self.timer.stop()

    def shutdown(self):
        if self.closed:
            return
        self.stop()
        self.closed = True
        # Finish detached Pillow readers before QObject children are destroyed.
        self.pool.waitForDone()
