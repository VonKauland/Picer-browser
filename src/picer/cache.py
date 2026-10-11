"""Shared, thread-safe thumbnail pixels with persistent and memory tiers."""

import hashlib
import os
import time
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
        self._flights = {}
        self._generation = 0
        self._last_prune = 0.0
        self._disk_count = None
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
        """GUI-safe memory lookup; disk access/decoding belongs in read()."""
        try:
            key = self.key(path)
        except OSError:
            return None
        with self._lock:
            image = self.memory.get(key)
            if image is None:
                return None
            self.memory.move_to_end(key)
            return self.scale(image, edge)

    def read(self, path, *, edge=128, token=None):
        return self._load(Path(path), edge, None, token)

    def thumbnail(self, path: Path, image: QImage) -> QImage:
        """Seed the same cache from already-decoded, auto-oriented viewer pixels."""
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
                    return self.scale(cached, edge)
                flight = self._flights.get(key)
                if flight is None:
                    flight = Event()
                    self._flights[key] = flight
                    generation = self._generation
                    break
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
            # A replaced file or cleared cache must not receive stale pixels.
            if self.key(path) != key:
                return QImage()
            with self._lock:
                if generation == self._generation:
                    self._remember(key, image)
                    try:
                        self.directory.mkdir(parents=True, exist_ok=True)
                        if not image.isNull() and (rebuild or not target.is_file()):
                            previous_size = target.stat().st_size if target.is_file() else 0
                            temporary = self.directory / f"{key}.{uuid.uuid4().hex}.tmp"
                            try:
                                if image.save(str(temporary), "PNG"):
                                    os.replace(temporary, target)
                                    if self._disk_count is not None:
                                        self._disk_count += int(previous_size == 0)
                                        self._disk_bytes += target.stat().st_size - previous_size
                            finally:
                                temporary.unlink(missing_ok=True)
                        if target.is_file():
                            target.touch()
                        if (
                            self._disk_count is None
                            or self._disk_count > self.limit
                            or self._disk_bytes > self.byte_limit
                            or time.monotonic() - self._last_prune > 1
                        ):
                            self.prune()
                    except OSError:
                        pass
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

    def prune(self):
        with self._lock:
            self._last_prune = time.monotonic()
            try:
                files = sorted(
                    self.directory.glob("*.png"), key=lambda file: file.stat().st_mtime_ns
                )
                total = sum(file.stat().st_size for file in files)
                count = len(files)
                for file in files:
                    if count <= self.limit and total <= self.byte_limit:
                        break
                    size = file.stat().st_size
                    file.unlink(missing_ok=True)
                    total -= size
                    count -= 1
                self._disk_count, self._disk_bytes = count, total
            except OSError:
                pass

    def clear(self) -> None:
        with self._lock:
            self._generation += 1
            self.memory.clear()
            self.memory_bytes = 0
            self._disk_count, self._disk_bytes = 0, 0
            for file in self.directory.glob("*.png"):
                file.unlink(missing_ok=True)
