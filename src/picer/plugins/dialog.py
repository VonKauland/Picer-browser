"""Desktop plugin management without adding permanent viewer panels."""

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from picer.components import TYPES
from picer.host_style import mark_host
from picer.plugins.api import PluginError

STATES = {"enabled": "已启用", "disabled": "未启用", "error": "已出错", "incompatible": "不兼容"}


class PluginDialog(QDialog):
    def __init__(self, manager, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("揽映 · 插件管理")
        self.resize(720, 480)
        layout = QVBoxLayout(self)
        heading = QLabel("皮肤 · 功能 · 面板")
        heading.setStyleSheet("font-size: 20px; font-weight: 600; padding: 8px 0;")
        layout.addWidget(heading)
        note = QLabel("第三方 Python 插件具有本机程序权限，请仅启用可信来源。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.filter = QComboBox()
        self.filter.addItem("全部组件", "")
        for key, label in TYPES.items():
            self.filter.addItem(label, key)
        self.filter.currentIndexChanged.connect(self.refresh)
        layout.addWidget(self.filter)
        content = QHBoxLayout()
        self.list = QListWidget()
        self.list.setMinimumWidth(240)
        content.addWidget(self.list)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        content.addWidget(self.details, 1)
        layout.addLayout(content, 1)
        buttons = QHBoxLayout()
        for label, callback, name in (
            ("安装/更新 ZIP…", self.install, "install_button"),
            ("启用", self.toggle, "toggle_button"),
            ("设置…", self.settings, "settings_button"),
            ("重载", self.reload, "reload_button"),
            ("卸载", self.uninstall, "uninstall_button"),
            ("打开插件目录", self.open_directory, "directory_button"),
        ):
            button = QPushButton(label)
            button.setStyleSheet("font-size: 13px; padding: 8px 10px; border: 1px solid #42464e;")
            button.clicked.connect(callback)
            setattr(self, name, button)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.list.currentItemChanged.connect(self.selection_changed)
        manager.changed.connect(self.refresh)
        self.refresh()
        mark_host(self)

    def selected_id(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def refresh(self) -> None:
        selected = self.selected_id()
        self.list.clear()
        for plugin_id, record in self.manager.records.items():
            if self.filter.currentData() and record.manifest.type != self.filter.currentData():
                continue
            item = QListWidgetItem(
                f"{record.manifest.name}\n{TYPES[record.manifest.type]} · "
                f"{STATES.get(record.state, record.state)}"
            )
            item.setData(Qt.ItemDataRole.UserRole, plugin_id)
            self.list.addItem(item)
            if selected == plugin_id:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self.selection_changed()

    def selection_changed(self, *_args) -> None:
        plugin_id = self.selected_id()
        record = self.manager.records.get(plugin_id)
        for button in (self.toggle_button, self.reload_button, self.uninstall_button):
            button.setEnabled(record is not None)
        self.settings_button.setEnabled(plugin_id in self.manager.settings_forms)
        if record is None:
            self.details.clear()
            return
        manifest = record.manifest
        self.toggle_button.setText("停用" if record.state == "enabled" else "启用")
        self.toggle_button.setEnabled(record.state != "incompatible")
        self.reload_button.setEnabled(record.state == "enabled")
        self.uninstall_button.setEnabled(record.directory is not None and record.state != "enabled")
        text = (
            f"{manifest.name}\n{manifest.description}\n\n"
            f"ID：{manifest.id}\n版本：{manifest.version}\nAPI：{manifest.api_version}\n"
            f"类型：{TYPES[manifest.type]}{'（旧版兼容，建议迁移）' if manifest.legacy else ''}\n"
            f"作者：{manifest.author or '未填写'}\n"
            f"来源：{record.directory or '内置'}\n"
            f"状态：{STATES.get(record.state, record.state)}\n"
            f"API 权限：{', '.join(manifest.permissions) or '无'}\n"
            f"依赖：{', '.join(manifest.requires) or '无'}\n"
        )
        if record.error:
            text += f"\n错误：{record.error}\n"
        if self.manager.diagnostics:
            text += "\n发现与配置诊断：\n" + "\n".join(self.manager.diagnostics[-10:])
        self.details.setPlainText(text)

    def operation(self, callback) -> None:
        try:
            callback()
        except PluginError as error:
            QMessageBox.warning(self, "插件操作未完成", str(error))
        self.refresh()

    def install(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "安装插件", "", "插件包 (*.zip)")
        if filename:
            self.operation(lambda: self.manager.install(Path(filename), replace_existing=True))

    def toggle(self) -> None:
        plugin_id = self.selected_id()
        if plugin_id:
            record = self.manager.records[plugin_id]
            if record.state == "enabled":
                self.operation(lambda: self.manager.disable(plugin_id))
            else:
                self.operation(lambda: self.manager.enable(plugin_id))

    def settings(self):
        plugin_id = self.selected_id()
        if plugin_id:
            self.operation(lambda: self.manager.show_settings(plugin_id))

    def reload(self) -> None:
        plugin_id = self.selected_id()
        if plugin_id:
            self.operation(lambda: self.manager.reload(plugin_id))

    def uninstall(self) -> None:
        plugin_id = self.selected_id()
        if (
            plugin_id
            and QMessageBox.question(self, "卸载插件", "删除该插件和独立配置？")
            == QMessageBox.StandardButton.Yes
        ):
            self.operation(lambda: self.manager.uninstall(plugin_id))

    def open_directory(self) -> None:
        record = self.manager.records.get(self.selected_id())
        directory = (
            self.manager.paths.skins
            if record and record.manifest.type == "skin"
            else self.manager.directory
        )
        directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))
