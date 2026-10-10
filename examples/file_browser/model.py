"""Sort filesystem entries with directories first in both sort directions."""

from pathlib import Path

from PySide6.QtCore import QSortFilterProxyModel, Qt

from .thumbnails import PhotoModel


class BrowserModel(QSortFilterProxyModel):
    def __init__(self, context, parent):
        super().__init__(parent)
        self.files = PhotoModel(context, self)
        self.setSourceModel(self.files)
        self.setDynamicSortFilter(True)

    def index(self, *args):
        if len(args) == 1 and isinstance(args[0], (str, Path)):
            return self.mapFromSource(self.files.index(str(args[0])))
        return super().index(*args)

    def setRootPath(self, path):
        return self.mapFromSource(self.files.setRootPath(path))

    def filePath(self, index):
        return self.files.filePath(self.mapToSource(index))

    def isDir(self, index):
        return self.files.isDir(self.mapToSource(index))

    @property
    def cache(self):
        return self.files.cache

    @property
    def pending(self):
        return self.files.pending

    @property
    def busy(self):
        return self.files.busy

    @property
    def stopped(self):
        return self.files.stopped

    @property
    def timer(self):
        return self.files.timer

    def stop(self):
        self.files.stop()

    def lessThan(self, left, right):
        first, second = self.files.fileInfo(left), self.files.fileInfo(right)
        if first.isDir() != second.isDir():
            return (
                first.isDir() if self.sortOrder() == Qt.SortOrder.AscendingOrder else second.isDir()
            )
        column = self.sortColumn()
        if column == 1:
            a, b = first.size(), second.size()
        elif column == 2:
            a, b = first.suffix().casefold(), second.suffix().casefold()
        elif column == 3:
            a, b = (
                first.lastModified().toMSecsSinceEpoch(),
                second.lastModified().toMSecsSinceEpoch(),
            )
        else:
            a, b = first.fileName().casefold(), second.fileName().casefold()
        return a < b if a != b else first.fileName().casefold() < second.fileName().casefold()
