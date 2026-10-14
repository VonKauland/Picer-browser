"""Shared thumbnail pixels; disk maintenance never holds the GUI memory lock."""

import hashlib
import os
import uuid
from collections import OrderedDict
from pathlib import Path
from threading import Event, RLock

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from picer.imaging import read_image


class ThumbnailCache:
    EDGE = 256

    def __init__(self, root: Path, *, limit: int = 4096, byte_limit: int = 512 * 1048576) -> None:
        self.directory = root / "thumbnails"
        self.limit = limit
        self.byte_limit = byte_limit
        self.memory_limit = 32 * 1048576
        self.memory = OrderedDict()
        self.memory_bytes = 0
        self._lock = RLock()
        self._disk_lock = RLock()
        self._flights = {}
        self._generation = 0
        self._disk_entries = None
        self._disk_bytes = 0

    @staticmethod
    def key(path):
        path = Path(path).resolve()
        stat = path.stat()
        return hashlib.sha256(
            f"v2:oriented:256:{os.path.normcase(str(path))}:{stat.st_mtime_ns}:{stat.st_size}".encode()
        ).hexdigest()

    @staticmethod
    def scale(image, edge):
        if max(image.width(), image.height()) <= edge:
            return QImage(image)
        return image.scaled(
            edge,
            edge,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _remember(self, key, image):
        old = self.memory.pop(key, None)
        if old is not None:
            self.memory_bytes -= old.sizeInBytes()
        self.memory[key] = QImage(image)
        self.memory_bytes += image.sizeInBytes()
        while len(self.memory) > 256 or self.memory_bytes > self.memory_limit:
            _, removed = self.memory.popitem(last=False)
            self.memory_bytes -= removed.sizeInBytes()

    def peek(self, path, *, edge=128):
        """Memory lookup never waits for PNG encoding, disk pruning or deletion."""
        try:
            key = self.key(path)
        except OSError:
            return None
        with self._lock:
            image = self.memory.get(key)
            if image is None:
                return None
            self.memory.move_to_end(key)
            image = QImage(image)
        return self.scale(image, edge)

    def offer(self, path, image):
        """Host-only memory warmup before image events; persistence stays asynchronous."""
        try:
            key = self.key(path)
        except OSError:
            return
        thumbnail = self.scale(image, self.EDGE)
        with self._lock:
            old = self.memory.get(key)
            if old is None or old.isNull():
                self._remember(key, thumbnail)

    def read(self, path, *, edge=128, token=None):
        return self._load(Path(path), edge, None, token)

    def thumbnail(self, path: Path, image: QImage) -> QImage:
        """Seed the cache from already-decoded, auto-oriented viewer pixels."""
        return self._load(path, self.EDGE, image, None)

    def _load(self, path, edge, supplied, token):
        try:
            key = self.key(path)
        except OSError:
            return self.scale(supplied, edge) if supplied is not None else QImage()
        while True:
            if token:
                token.checkpoint()
            with self._lock:
                cached = self.memory.get(key)
                if cached is not None:
                    self.memory.move_to_end(key)
                    cached = QImage(cached)
                    generation = self._generation
                else:
                    flight = self._flights.get(key)
                    if flight is None:
                        flight = Event()
                        self._flights[key] = flight
                        generation = self._generation
                        break
            if cached is not None:
                if supplied is not None:
                    self._persist(key, cached, generation, False)
                return self.scale(cached, edge)
            flight.wait(0.025)
        try:
            target = self.directory / f"{key}.png"
            image = QImage(str(target)) if target.is_file() else QImage()
            rebuild = image.isNull()
            if rebuild:
                image = (
                    self.scale(supplied, self.EDGE)
                    if supplied is not None
                    else read_image(path, edge=self.EDGE, auto_orient=True, token=token)
                )
            if token:
                token.checkpoint()
            if self.key(path) != key:
                return QImage()
            with self._lock:
                if generation == self._generation:
                    self._remember(key, image)
            self._persist(key, image, generation, rebuild)
            return self.scale(image, edge)
        except (OSError, ValueError, RuntimeError):
            image = self.scale(supplied, edge) if supplied is not None else QImage()
            with self._lock:
                if generation == self._generation:
                    self._remember(key, image)
            return image
        finally:
            with self._lock:
                self._flights.pop(key, None)
                flight.set()

    def _persist(self, key, image, generation, rebuild):
        try:
            with self._disk_lock:
                with self._lock:
                    if generation != self._generation:
                        return
                self.directory.mkdir(parents=True, exist_ok=True)
                if self._disk_entries is None:
                    self._scan_disk()
                target = self.directory / f"{key}.png"
                if not image.isNull() and (rebuild or not target.is_file()):
                    temporary = self.directory / f"{key}.{uuid.uuid4().hex}.tmp"
                    try:
                        if image.save(str(temporary), "PNG"):
                            os.replace(temporary, target)
                    finally:
                        temporary.unlink(missing_ok=True)
                if target.is_file():
                    target.touch()
                    previous = self._disk_entries.pop(target.name, 0)
                    size = target.stat().st_size
                    self._disk_entries[target.name] = size
                    self._disk_bytes += size - previous
                self._trim_disk()
        except OSError:
            pass  # Persistence is optional; decoded pixels remain usable.

    def _scan_disk(self):
        """One startup/explicit scan; normal reads/writes update the index incrementally."""
        entries = []
        for file in self.directory.glob("*.png"):
            try:
                stat = file.stat()
                entries.append((stat.st_mtime_ns, file.name, stat.st_size))
            except FileNotFoundError:
                continue
        entries.sort()
        self._disk_entries = OrderedDict((name, size) for _, name, size in entries)
        self._disk_bytes = sum(self._disk_entries.values())

    def _trim_disk(self):
        while self._disk_entries and (
            len(self._disk_entries) > self.limit or self._disk_bytes > self.byte_limit
        ):
            name, size = next(iter(self._disk_entries.items()))
            (self.directory / name).unlink(missing_ok=True)
            self._disk_entries.pop(name)
            self._disk_bytes -= size

    def prune(self):
        with self._disk_lock:
            try:
                self._scan_disk()
                self._trim_disk()
            except OSError:
                self._disk_entries = None

    def clear(self) -> None:
        # Release the memory lock before disk IO. A concurrent old writer is
        # serialized by _disk_lock and its files are removed before clear returns.
        with self._lock:
            self._generation += 1
            self.memory.clear()
            self.memory_bytes = 0
        with self._disk_lock:
            self._disk_entries = None
            self._disk_bytes = 0
            for file in self.directory.glob("*.png"):
                file.unlink(missing_ok=True)
