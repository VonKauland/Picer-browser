"""Optional two-page composition with cancellable second-page decoding."""

from PySide6.QtCore import QEvent, QObject, Qt, QThreadPool, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem

from picer.imaging import read_image
from picer.plugins.tasks import Worker


class DoublePage(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.owners = set()
        self.second = QGraphicsPixmapItem()
        host.view.scene.addItem(self.second)
        self.second.hide()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.jobs = {}
        self.generation = 0
        self.pairs = {}
        self.path = None
        self.closed = False
        self.refine = QTimer(self)
        self.refine.setSingleShot(True)
        self.refine.setInterval(240)
        self.refine.timeout.connect(self.full)
        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.setInterval(100)
        self.resize_timer.timeout.connect(self.refresh)
        host.view.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize and self.owners and not self.closed:
            self.resize_timer.start()
        return False

    def clear(self):
        self.generation += 1
        self.refine.stop()
        for worker in self.jobs.values():
            worker.token.cancel()
        self.second.hide()
        self.second.setPixmap(QPixmap())
        self.path = None
        self.host.view.image_item.setPos(0, 0)
        self.host.view.scene.setSceneRect(self.host.view.image_item.sceneBoundingRect())

    def set_enabled(self, owner, enabled):
        if (owner in self.owners) == enabled:
            return
        if enabled:
            self.owners.add(owner)
        else:
            self.owners.discard(owner)
        self.refresh()

    def refresh(self):
        self.clear()
        host = self.host
        if self.closed or not self.owners or host.current_path is None:
            return
        self.pairs.pop(host.current_path, None)
        half = host.view.viewport().width() / 2
        if host.source_size[0] > half:
            host.view.fit_image() if host.view.fit_mode else None
            return
        index = host.path_positions.get(host.current_path, -1)
        if not 0 <= index < len(host.paths) - 1:
            return
        self.path = host.paths[index + 1]
        self.load(960 if host.loader.rapid else 1600)

    def load(self, edge):
        host = self.host
        generation, first, path = self.generation, host.current_path, self.path
        try:
            key = host.loader.key(path, edge)
        except OSError:
            return
        cached = host.loader.cached(key)

        def done(image, error):
            if (
                self.closed
                or generation != self.generation
                or first != host.current_path
                or error
                or image is None
            ):
                return
            width = int(image.text("picer.native_width") or image.width())
            if (
                width > host.view.viewport().width() / 2
                or host.source_size[0] > host.view.viewport().width() / 2
            ):
                self.clear()
                host.view.fit_image() if host.view.fit_mode else None
                return
            host.loader.remember(key, image)
            self.second.setPixmap(QPixmap.fromImage(image))
            self.second.setScale(width / image.width())
            if host.app_preferences["reading_direction"] == "rtl":
                host.view.image_item.setPos(width + 12, 0)
                self.second.setPos(0, 0)
            else:
                self.second.setPos(host.source_size[0] + 12, 0)
            self.second.show()
            self.pairs[first] = path
            if len(self.pairs) > 256:
                del self.pairs[next(iter(self.pairs))]
            host.view.scene.setSceneRect(host.view.scene.itemsBoundingRect())
            if host.view.fit_mode:
                host.view.fit_image()
            if edge and not host.loader.rapid:
                self.refine.start()

        if cached is not None:
            done(cached, None)
            return
        worker = Worker(
            lambda token: read_image(
                path, edge=edge, auto_orient=host.app_preferences["auto_orient"], token=token
            )
        )
        worker.setAutoDelete(False)
        identity = id(worker)
        self.jobs[identity] = worker

        def finish(image, error):
            self.jobs.pop(identity, None)
            done(image, error)

        worker.signals.finished.connect(finish, Qt.ConnectionType.QueuedConnection)
        self.pool.start(worker)

    def full(self):
        if self.path and self.second.isVisible() and not self.host.loader.rapid:
            self.load(0)

    def offset(self, offset):
        if not self.owners or abs(offset) != 1:
            return offset
        host = self.host
        requested = host.loader.requested or host.current_path
        if offset > 0 and requested in self.pairs:
            return 2
        index = host.path_positions.get(requested, 0)
        if (
            offset < 0
            and index >= 2
            and self.pairs.get(host.paths[index - 2]) == host.paths[index - 1]
        ):
            return -2
        return offset

    def dispose(self):
        self.closed = True
        self.resize_timer.stop()
        self.host.view.viewport().removeEventFilter(self)
        self.clear()
        self.pool.waitForDone()
        self.jobs.clear()
