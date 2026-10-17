"""Outbound-only image file drags, interoperable with Windows CF_HDROP targets."""

import struct
from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, QObject, Qt, QUrl
from PySide6.QtGui import QDrag, QIcon, QImage, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QApplication
from shiboken6 import isValid

from picer.video import VIDEO_SUFFIXES


class ImageFileDrag(QObject):
    def __init__(self, view, path_at, suffixes, preview=None):
        super().__init__(view)
        self.view, self.path_at, self.suffixes, self.preview = view, path_at, suffixes, preview
        self.origin, self.path = None, None
        self.active = True
        self.suppress_release = False
        view.setDragEnabled(False)  # Never delegate folder/internal moves to QFileSystemModel.
        view.setAcceptDrops(False)
        view.viewport().setAcceptDrops(False)
        view.setProperty("outboundImageFiles", True)
        view.viewport().installEventFilter(self)

    def eligible(self, path):
        try:
            path = Path(path) if path else None
            if (
                self.active
                and path
                and path.suffix.lower() in self.suffixes() - VIDEO_SUFFIXES
                and path.is_file()
            ):
                return path.absolute()
        except (OSError, RuntimeError, ValueError):
            pass
        return None

    def mime_data(self, path):
        path = self.eligible(path)
        if path is None:
            return None
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])
        # Qt's Windows backend exports local URLs as CF_HDROP, like Explorer.
        mime.setData(
            'application/x-qt-windows-mime;value="Preferred DropEffect"', struct.pack("<I", 1)
        )
        return mime

    def start(self, path, index):
        mime = self.mime_data(path)
        if mime is None:
            return
        drag = QDrag(self.view)
        drag.setMimeData(mime)
        image = self.preview(path) if self.preview else index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(image, QIcon):
            drag.setPixmap(image.pixmap(96, 96))
        elif isinstance(image, QImage) and not image.isNull():
            drag.setPixmap(
                QPixmap.fromImage(image).scaled(
                    96,
                    96,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        try:
            drag.exec(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)
        finally:
            if isValid(self.view):
                self.view.setState(QAbstractItemView.State.NoState)
            if isValid(drag):
                drag.deleteLater()

    def eventFilter(self, obj, event):
        if not self.active:
            return False
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self.suppress_release = False
            self.origin = event.position().toPoint()
            index = self.view.indexAt(self.origin)
            self.path = self.eligible(self.path_at(index)) if index.isValid() else None
        elif kind == QEvent.Type.MouseMove and self.path and self.origin is not None:
            if (
                event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self.origin).manhattanLength()
                >= QApplication.startDragDistance()
            ):
                path, origin = self.path, self.origin
                self.path, self.origin = None, None
                self.suppress_release = True
                self.start(path, self.view.indexAt(origin))
                event.accept()
                return True
        elif kind in (QEvent.Type.MouseButtonRelease, QEvent.Type.Hide):
            self.path, self.origin = None, None
            if kind == QEvent.Type.MouseButtonRelease and self.suppress_release:
                self.suppress_release = False
                event.accept()
                return True
        return False

    def stop(self):
        self.active = False
        self.path, self.origin = None, None
        self.view.viewport().removeEventFilter(self)
