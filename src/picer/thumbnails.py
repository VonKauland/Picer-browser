"""Host-owned asynchronous thumbnail queue shared by all plugin surfaces."""

from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThreadPool, QTimer
from PySide6.QtGui import QImage

from picer.plugins.tasks import TaskToken, Worker


class ThumbnailRequest(TaskToken):
    def __init__(self):
        super().__init__()
        self.finished = False


class ThumbnailService(QObject):
    def __init__(self, cache, parent=None):
        super().__init__(parent)
        self.cache = cache
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.writer = QThreadPool(self)
        self.writer.setMaxThreadCount(1)
        self.seed_pending = OrderedDict()
        self.seed_worker = None
        self.pending = OrderedDict()
        self.running = {}
        self.closed = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.pump)

    def seed(self, path, image):
        """Persist viewer pixels without occupying its full-resolution lane."""
        if self.closed:
            return
        self.seed_pending[path] = QImage(image)
        self.seed_pending.move_to_end(path)
        while len(self.seed_pending) > 16:
            self.seed_pending.popitem(last=False)
        self.write_next()

    def write_next(self):
        if self.closed or self.seed_worker or not self.seed_pending:
            return
        path, image = self.seed_pending.popitem(last=True)
        worker = Worker(lambda token: self.cache.thumbnail(path, image))
        self.seed_worker = worker
        worker.signals.finished.connect(self.written, Qt.ConnectionType.QueuedConnection)
        self.writer.start(worker)

    def written(self, image, error):
        self.seed_worker = None
        self.write_next()

    def discard_seeds(self):
        self.seed_pending.clear()
        if self.seed_worker:
            self.seed_worker.token.cancel()

    def request(self, path, callback, *, edge=128, priority=False):
        token = ThumbnailRequest()
        path = Path(path).resolve()
        entry = (token, edge, callback)
        if self.closed:
            token.cancel()
            token.finished = True
            return token
        cached = self.cache.peek(path, edge=edge)
        if cached is not None:
            QTimer.singleShot(0, lambda: self.deliver(entry, cached))
            return token
        try:
            key = self.cache.key(path)
        except OSError:
            QTimer.singleShot(0, lambda: self.deliver(entry, QImage()))
            return token
        if key in self.running:
            self.running[key][1].append(entry)
        else:
            if key not in self.pending:
                self.pending[key] = (path, [])
            self.pending[key][1].append(entry)
            if priority:
                self.pending.move_to_end(key, last=False)
        self.timer.start(0)
        return token

    def deliver(self, entry, image):
        token, edge, callback = entry
        token.finished = True
        if not token.cancelled and not self.closed:
            callback(self.cache.scale(image, edge))

    def pump(self):
        for key, (path, entries) in tuple(self.pending.items()):
            live = [entry for entry in entries if not entry[0].cancelled]
            if live:
                self.pending[key] = (path, live)
            else:
                self.pending.pop(key)
        while self.pending and len(self.running) < 2 and not self.closed:
            key, (path, entries) = self.pending.popitem(last=False)
            if all(token.cancelled for token, _, _ in entries):
                for token, _, _ in entries:
                    token.finished = True
                continue
            worker = Worker(lambda token, path=path: self.cache.read(path, edge=256, token=token))
            self.running[key] = (worker, entries)
            worker.signals.finished.connect(
                lambda image, error, key=key: self.finish(key, image, error),
                Qt.ConnectionType.QueuedConnection,
            )
            self.pool.start(worker)

    def finish(self, key, image, error):
        _, entries = self.running.pop(key)
        for entry in entries:
            self.deliver(entry, image if error is None else QImage())
        self.pump()

    def shutdown(self):
        self.closed = True
        self.timer.stop()
        for _, entries in self.pending.values():
            for token, _, _ in entries:
                token.cancel()
                token.finished = True
        self.pending.clear()
        for worker, entries in self.running.values():
            worker.token.cancel()
            for token, _, _ in entries:
                token.cancel()
        self.discard_seeds()
        self.pool.waitForDone()
        self.writer.waitForDone()
