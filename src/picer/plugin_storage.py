"""Installed plugin disk usage and explicit, confirmed removal."""

import os
import stat

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from picer.bundles import EXAMPLES
from picer.confirmation import confirm
from picer.i18n import plugin_text, tr
from picer.messages import MessageBox
from picer.plugins.api import PluginError
from picer.plugins.tasks import Worker
from picer.ui import Card


def is_external(manager, plugin_id):
    record = manager.records.get(plugin_id)
    return bool(
        record and record.directory is not None and plugin_id not in {e[2] for e in EXAMPLES}
    )


def directory_size(directory, token):
    """Count installed bytes without traversing symlinks or junctions."""
    root = os.lstat(directory)
    if stat.S_ISLNK(root.st_mode) or getattr(root, "st_file_attributes", 0) & 0x400:
        return 0
    total = 0
    pending = [directory]
    while pending:
        token.checkpoint()
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                token.checkpoint()
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    continue
                if stat.S_ISDIR(info.st_mode):
                    pending.append(entry.path)
                elif stat.S_ISREG(info.st_mode):
                    total += info.st_size
    return total


def size_text(size):
    if size < 1024:
        return f"{size} B"
    if size < 1048576:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1048576:.1f} MB"


class PluginStorage(Card):
    def __init__(self, settings):
        super().__init__(tr("插件文件"))
        self.settings, self.manager = settings, settings.manager
        self.rows = {}
        self.jobs = []
        self.generation = 0
        self.total = QLabel()
        self.total.setObjectName("muted")
        self.body.addWidget(self.total)
        self.list = QWidget()
        self.list_layout = QVBoxLayout(self.list)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.body.addWidget(self.list)
        self.refresh()
        self.manager.changed.connect(self.refresh)
        self.destroyed.connect(lambda: [job.token.cancel() for job in self.jobs])

    def refresh(self):
        self.generation += 1
        generation = self.generation
        for job in self.jobs:
            job.token.cancel()
        self.jobs = []
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            item.widget().deleteLater()
        self.rows = {}
        self.sizes = {}
        for plugin_id, record in self.manager.records.items():
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 4, 0, 4)
            name = QLabel(plugin_text(self.manager, plugin_id, record.manifest.name))
            name.setWordWrap(True)
            name.setToolTip(plugin_id)
            layout.addWidget(name, 1)
            kind = QLabel(tr("第三方") if is_external(self.manager, plugin_id) else tr("内置"))
            kind.setObjectName("muted")
            layout.addWidget(kind)
            size = QLabel(tr("统计中…") if record.directory else tr("随应用提供"))
            size.setMinimumWidth(85)
            layout.addWidget(size)
            button = QPushButton(tr("卸载"))
            button.setEnabled(record.directory is not None)
            button.setToolTip(
                tr("内置代码随应用提供，无法单独卸载")
                if not record.directory
                else tr("卸载插件和配置")
            )
            button.clicked.connect(lambda checked=False, key=plugin_id: self.uninstall(key))
            layout.addWidget(button)
            self.list_layout.addWidget(row)
            self.rows[plugin_id] = size
        paths = {
            key: record.directory
            for key, record in self.manager.records.items()
            if record.directory
        }

        def scan(token):
            result = {}
            for key, directory in paths.items():
                token.checkpoint()
                try:
                    result[key] = directory_size(directory, token)
                except OSError:
                    result[key] = None
            return generation, result

        job = Worker(scan)
        self.jobs.append(job)
        job.signals.finished.connect(self.scanned)
        self.total.setText(tr("共 {0} 个插件 · 正在统计独立插件文件").format(len(self.rows)))
        QThreadPool.globalInstance().start(job)

    def scanned(self, payload, error):
        if error or payload[0] != self.generation:
            return
        self.jobs = []
        result = payload[1]
        self.sizes = result
        for key, size in result.items():
            self.rows[key].setText(size_text(size) if size is not None else tr("暂不可读"))
        total = sum(size for size in result.values() if size is not None)
        suffix = tr(" · 部分文件暂不可读") if None in result.values() else ""
        self.total.setText(
            tr("共 {0} 个插件 · 独立文件 {1}{2}").format(len(self.rows), size_text(total), suffix)
        )

    def uninstall(self, plugin_id):
        record = self.manager.records.get(plugin_id)
        if not record or record.directory is None:
            return
        if not confirm(
            self.settings,
            tr("卸载插件？"),
            tr("将卸载「{0}」及其配置。已启用的插件会先停用。").format(record.manifest.name),
            tr("卸载"),
        ):
            return
        try:
            if self.manager._dependents(plugin_id):
                raise PluginError(tr("请先停用依赖此插件的其他插件。"))
            if record.state == "enabled":
                self.manager.disable(plugin_id)
            self.manager.uninstall(plugin_id)
            self.settings.binding_editor.remove_plugin(plugin_id)
        except PluginError as error:
            MessageBox.warning(self.settings, tr("无法卸载"), str(error))
