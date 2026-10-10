"""Bounded thumbnails keyed by original file metadata."""

import hashlib
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage


class ThumbnailCache:
    def __init__(self, root: Path, *, limit: int = 256, byte_limit: int = 512 * 1048576) -> None:
        self.directory = root / "thumbnails"
        self.limit = limit
        self.byte_limit = byte_limit

    def thumbnail(self, path: Path, image: QImage) -> QImage:
        thumbnail = image.scaled(
            min(256, image.width()),
            min(256, image.height()),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        try:
            stat = path.stat()
            key = hashlib.sha256(
                f"{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}".encode()
            ).hexdigest()
            self.directory.mkdir(parents=True, exist_ok=True)
            target = self.directory / f"{key}.png"
            if target.is_file():
                cached = QImage(str(target))
                if not cached.isNull():
                    target.touch()
                    return cached
            if thumbnail.save(str(target)):
                self.prune()
        except OSError:
            pass  # Cache failure must not prevent viewing the original image.
        return thumbnail

    def prune(self):
        try:
            files = sorted(self.directory.glob("*.png"), key=lambda file: file.stat().st_mtime_ns)
            total = sum(file.stat().st_size for file in files)
            count = len(files)
            for file in files:
                if count <= self.limit and total <= self.byte_limit:
                    break
                size = file.stat().st_size
                file.unlink(missing_ok=True)
                total -= size
                count -= 1
        except OSError:
            pass

    def clear(self) -> None:
        if self.directory.exists():
            for file in self.directory.glob("*.png"):
                file.unlink(missing_ok=True)
