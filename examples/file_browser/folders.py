"""Lazy, nonrecursive directory classification with bounded cache and watches."""

import os
from collections import OrderedDict
from heapq import nsmallest
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
        self.previews = {}
        self.sources = {}
        self.preview_pending = OrderedDict()
        self.preview_tokens = {}
        self.pending = OrderedDict()
        self.in_flight = set()
        self.generations = {}
        self.busy = self.stopped = False
        self.token = None
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.invalidate)
        self.watcher.fileChanged.connect(self.source_changed)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.load)

    def icon(self, path):
        if path in self.cache:
            self.cache.move_to_end(path)
            return self.previews.get(path, self.icons[self.cache[path]])
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
        self.forget_preview(path)
        self.generations[path] = self.generations.get(path, 0) + 1
        self.changed(path)

    def source_changed(self, source):
        for path, current in tuple(self.sources.items()):
            if current == source:
                self.invalidate(path)

    def forget_preview(self, path):
        self.previews.pop(path, None)
        source = self.sources.pop(path, None)
        if source in self.watcher.files():
            self.watcher.removePath(source)
        self.preview_pending.pop(path, None)
        token = self.preview_tokens.pop(path, None)
        if token:
            token.cancel()

    def load_previews(self):
        while not self.stopped and self.preview_pending and len(self.preview_tokens) < 4:
            path, (generation, source) = self.preview_pending.popitem(last=False)

            def render(image, path=path, generation=generation, source=source):
                if self.stopped or generation != self.generations.get(path, 0):
                    return
                self.preview_tokens.pop(path, None)
                if self.sources.get(path) == source and not image.isNull():
                    self.previews[path] = folder_icon(True, image)
                    self.changed(path)
                self.load_previews()

            self.preview_tokens[path] = self.context.request_thumbnail(source, render, edge=128)

    def load(self):
        if self.stopped or self.busy or not self.pending:
            return
        batch = tuple(self.pending.items())[:8]
        self.in_flight = {path for path, _ in batch}
        for path, _ in batch:
            self.pending.pop(path, None)
        self.busy = True

        suffixes = (
            self.context.readable_suffixes()
            if hasattr(self.context, "readable_suffixes")
            else supported_suffixes()
        )

        def work(token):
            results = []
            for path, generation in batch:
                first = None
                try:
                    first = self.first_photo(path, suffixes, token)
                except OSError:
                    pass
                results.append((path, generation, first))
            return results

        def render(results):
            if self.stopped:
                return
            self.busy = False
            self.in_flight.clear()
            for path, generation, first in results:
                if generation != self.generations.get(path, 0):
                    self.pending[path] = self.generations[path]
                    continue
                self.cache[path] = first is not None
                self.cache.move_to_end(path)
                if path not in self.watcher.directories():
                    self.watcher.addPath(path)
                while len(self.cache) > 256:
                    removed, _ = self.cache.popitem(last=False)
                    self.forget_preview(removed)
                    self.watcher.removePath(removed)
                    self.generations.pop(removed, None)
                if first is not None:
                    self.sources[path] = first
                    self.watcher.addPath(first)
                    self.preview_pending[path] = (generation, first)
                self.changed(path)
            self.load_previews()
            if self.pending:
                self.timer.start(0)

        self.token = self.context.run_task(work, render, image_bound=False)

    def first_photo(self, path, suffixes, token):
        after = None
        while True:
            # Keep only eight names, even in huge directories. Probe headers
            # after choosing names, rather than opening every earlier candidate
            # when scandir happens to return files in descending order.
            def candidates(entries, after=after):
                for entry in entries:
                    token.checkpoint()
                    key = (entry.name.casefold(), entry.name)
                    if (
                        (after is None or key > after)
                        and Path(entry.name).suffix.lower() in suffixes
                        and entry.is_file()
                    ):
                        yield key, entry.path

            with os.scandir(path) as entries:
                batch = nsmallest(8, candidates(entries))
            if not batch:
                return None
            for _, source in batch:
                token.checkpoint()
                if self.can_read(source, token):
                    return source
            after = batch[-1][0]

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
        self.preview_pending.clear()
        for token in self.preview_tokens.values():
            token.cancel()
        self.preview_tokens.clear()
        self.previews.clear()
        self.sources.clear()
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        if self.watcher.files():
            self.watcher.removePaths(self.watcher.files())
        if self.token:
            self.token.cancel()
