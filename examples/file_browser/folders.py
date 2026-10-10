"""Lazy, nonrecursive directory classification with bounded cache and watches."""

import os
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer
from PySide6.QtGui import QImageReader

from picer.imaging import RAW_SUFFIXES, supported_suffixes

from .icons import folder_icon


class FolderContents(QObject):
    def __init__(self, context, changed, parent):
        super().__init__(parent)
        self.context, self.changed = context, changed
        self.icons = (folder_icon(), folder_icon(True))
        self.cache = OrderedDict()
        self.pending = OrderedDict()
        self.in_flight = set()
        self.generations = {}
        self.busy = self.stopped = False
        self.token = None
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.invalidate)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.load)

    def icon(self, path):
        if path in self.cache:
            self.cache.move_to_end(path)
            return self.icons[self.cache[path]]
        if (
            not self.stopped
            and path not in self.pending
            and path not in self.in_flight
            and len(self.pending) < 128
        ):
            self.pending[path] = self.generations.get(path, 0)
            if not self.busy:
                self.timer.start(0)
        return self.icons[0]

    def invalidate(self, path):
        self.cache.pop(path, None)
        self.generations[path] = self.generations.get(path, 0) + 1
        self.changed(path)

    def load(self):
        if self.stopped or self.busy or not self.pending:
            return
        batch = tuple(self.pending.items())[:8]
        self.in_flight = {path for path, _ in batch}
        for path, _ in batch:
            self.pending.pop(path, None)
        self.busy = True

        def work(token):
            results = []
            suffixes = supported_suffixes()
            for path, generation in batch:
                found = False
                try:
                    with os.scandir(path) as entries:
                        for entry in entries:
                            token.checkpoint()
                            if (
                                Path(entry.name).suffix.lower() in suffixes
                                and entry.is_file()
                                and self.can_read(entry.path, token)
                            ):
                                found = True
                                break
                except OSError:
                    pass
                results.append((path, generation, found))
            return results

        def render(results):
            self.busy = False
            self.in_flight.clear()
            for path, generation, found in results:
                if generation != self.generations.get(path, 0):
                    self.pending[path] = self.generations[path]
                    continue
                self.cache[path] = found
                self.cache.move_to_end(path)
                if path not in self.watcher.directories():
                    self.watcher.addPath(path)
                while len(self.cache) > 256:
                    removed, _ = self.cache.popitem(last=False)
                    self.watcher.removePath(removed)
                    self.generations.pop(removed, None)
                self.changed(path)
            if self.pending:
                self.timer.start(0)

        self.token = self.context.run_task(work, render, image_bound=False)

    @staticmethod
    def can_read(path, token):
        if Path(path).suffix.lower() not in RAW_SUFFIXES:
            return QImageReader(path).canRead()
        try:
            import rawpy

            token.checkpoint()
            with rawpy.RawPy() as raw:
                raw.open_file(path)
                return raw.sizes.width > 0
        except (OSError, ValueError, RuntimeError):
            return False

    def stop(self):
        self.stopped = True
        self.timer.stop()
        self.pending.clear()
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        if self.token:
            self.token.cancel()
