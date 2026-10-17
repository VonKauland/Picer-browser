"""Route local image drops before QGraphicsView hands them to its scene."""

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt

from picer.messages import MessageBox as QMessageBox


class ImageDropTarget(QObject):
    def __init__(self, host, viewport):
        super().__init__(host)
        self.host = host
        for target in (host, viewport.parentWidget(), viewport):
            target.setAcceptDrops(True)
            target.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() not in (
            QEvent.Type.DragEnter,
            QEvent.Type.DragMove,
            QEvent.Type.Drop,
        ):
            return False
        source = event.source()
        if source is not None and source.property("outboundImageFiles"):
            event.ignore()
            return True
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
            and Path(url.toLocalFile()).suffix.lower() in self.host.supported_suffixes
        ]
        if not paths or not event.possibleActions() & Qt.DropAction.CopyAction:
            event.ignore()
            return True
        if event.type() == QEvent.Type.Drop:
            for path in paths:
                if self.host.open_image(path):
                    break
            else:
                event.ignore()
                QMessageBox.warning(self.host, "无法打开图片", self.host.last_error)
                return True
        # Opening an image must never advertise moving the Explorer source file.
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        return True
