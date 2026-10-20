"""Cancellable navigation through direct sibling image folders only."""

import os
from pathlib import Path

from PySide6.QtGui import QImageReader

from picer.i18n import tr
from picer.imaging import RAW_SUFFIXES


def first_image(directory, suffixes, token):
    try:
        with os.scandir(directory) as entries:
            paths = []
            for entry in entries:
                token.checkpoint()
                if Path(entry.name).suffix.lower() in suffixes and entry.is_file():
                    paths.append(Path(entry.path))
        for path in sorted(paths, key=lambda p: (p.name.casefold(), p.name)):
            token.checkpoint()
            if path.suffix.lower() in RAW_SUFFIXES:
                import rawpy

                try:
                    with rawpy.RawPy() as raw:
                        raw.open_file(str(path))
                    return path
                except (rawpy.LibRawError, OSError):
                    continue
            if QImageReader(str(path)).canRead():
                return path
    except OSError:
        pass
    return None


def sibling_image(current, offset, suffixes, token):
    with os.scandir(current.parent) as entries:
        folders = []
        for entry in entries:
            token.checkpoint()
            if entry.is_dir():
                folders.append(Path(entry.path))
    folders.sort(key=lambda p: (p.name.casefold(), p.name))
    try:
        position = folders.index(current)
    except ValueError:
        return None
    indices = range(position + 1, len(folders)) if offset > 0 else range(position - 1, -1, -1)
    for index in indices:
        token.checkpoint()
        image = first_image(folders[index], suffixes, token)
        if image is not None:
            return image
    return None


class FolderNavigation:
    def __init__(self, host):
        self.host = host
        self.pending = None
        self.serial = 0

    def navigate(self, offset):
        host = self.host
        if host.current_path is None:
            return
        self.serial += 1
        serial, generation = self.serial, host.loader.generation
        current = host.current_path.parent
        if self.pending:
            self.pending.cancel()

        def finish(path, error):
            if serial != self.serial or generation != host.loader.generation:
                return
            self.pending = None
            if error:
                host.notify(tr("无法访问同级文件夹"))
            elif path is None:
                host.notify(
                    tr("已是最后一个图片文件夹") if offset > 0 else tr("已是第一个图片文件夹")
                )
            else:
                if not host.open_image(path):
                    host.notify(tr("图片文件夹中的首图无法读取"))

        self.pending = host.loader.submit(
            "index",
            lambda token: sibling_image(current, offset, host.supported_suffixes, token),
            finish,
        ).token

    def cancel(self):
        self.serial += 1
        if self.pending:
            self.pending.cancel()
            self.pending = None
