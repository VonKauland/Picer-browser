"""Searchable component management, with settings edited in the same page."""

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTabBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from picer.components import TYPES, component_icon
from picer.host_style import mark_host
from picer.messages import MessageBox as QMessageBox
from picer.plugins.api import PluginError
from picer.plugins.settings import SettingsForm
from picer.ui import Card, StyledDialog, Toggle, ui_icon

STATES = {"enabled": "已启用", "disabled": "已停用", "error": "已出错", "incompatible": "不兼容"}


class PluginDialog(StyledDialog):
    def __init__(self, manager, parent=None, *, selected_id=None, open_settings=False):
        super().__init__("插件管理", "管理皮肤、功能与面板", parent)
        self.manager = manager
        self.resize(1100, 760)
        self.setMinimumSize(940, 600)
        self.form_id, self.settings_form = None, None
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索组件")
        self.search.addAction(
            ui_icon("search", manager.host.skin_colors["text"]),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self.search.textChanged.connect(self.refresh)
        top.addWidget(self.search, 1)
        self.status_filter = QComboBox()
        for label, value in (
            ("全部状态", ""),
            ("已启用", "enabled"),
            ("已停用", "disabled"),
            ("有问题", "problem"),
        ):
            self.status_filter.addItem(label, value)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        top.addWidget(self.status_filter)
        self.install_button = QPushButton("安装组件")
        self.install_button.setIcon(ui_icon("install", manager.host.skin_colors["title"]))
        self.install_button.setObjectName("primaryButton")
        self.install_button.clicked.connect(self.install)
        top.addWidget(self.install_button)
        self.body.addLayout(top)
        self.filter = QComboBox(self)  # Retain the existing filter API for extensions/tests.
        self.filter.hide()
        self.filter.addItem("全部组件", "")
        self.type_tabs = QTabBar()
        self.type_tabs.setDrawBase(False)
        self.type_tabs.addTab("全部")
        for key, label in TYPES.items():
            self.filter.addItem(label, key)
            self.type_tabs.addTab(label)
        self.type_tabs.currentChanged.connect(self.filter.setCurrentIndex)
        self.filter.currentIndexChanged.connect(self.type_tabs.setCurrentIndex)
        self.filter.currentIndexChanged.connect(self.refresh)
        self.body.addWidget(self.type_tabs)
        content = QHBoxLayout()
        content.setSpacing(18)
        self.list = QListWidget()
        self.list.setMinimumWidth(380)
        self.list.setSpacing(6)
        self.list.currentItemChanged.connect(self.selection_changed)
        content.addWidget(self.list, 5)
        right = QVBoxLayout()
        self.page_tabs = QTabBar()
        self.page_tabs.setDrawBase(False)
        self.page_tabs.addTab("概览")
        self.page_tabs.addTab("设置")
        self.page_tabs.currentChanged.connect(self.show_page)
        right.addWidget(self.page_tabs)
        self.pages = QStackedWidget()
        self.overview = Card()
        self.detail_title = QLabel()
        self.detail_title.setObjectName("dialogHeading")
        self.detail_title.setWordWrap(True)
        self.overview.body.addWidget(self.detail_title)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.overview.body.addWidget(self.details, 1)
        self.overview_buttons = QHBoxLayout()
        for label, callback, name in (
            ("启用", self.toggle, "toggle_button"),
            ("设置…", self.settings, "settings_button"),
            ("重新加载", self.reload, "reload_button"),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            setattr(self, name, button)
            self.overview_buttons.addWidget(button)
        self.overview.body.addLayout(self.overview_buttons)
        self.directory_button = QPushButton("打开组件目录")
        self.directory_button.setIcon(ui_icon("folder", manager.host.skin_colors["text"]))
        self.directory_button.clicked.connect(self.open_directory)
        self.overview.body.addWidget(self.directory_button)
        self.uninstall_button = QPushButton("卸载组件")
        self.uninstall_button.setObjectName("dangerButton")
        self.uninstall_button.clicked.connect(self.uninstall)
        self.overview.body.addWidget(self.uninstall_button)
        self.pages.addWidget(self.overview)
        self.settings_page = QWidget()
        self.settings_layout = QVBoxLayout(self.settings_page)
        self.settings_layout.setContentsMargins(0, 0, 0, 0)
        self.pages.addWidget(self.settings_page)
        right.addWidget(self.pages, 1)
        content.addLayout(right, 5)
        self.body.addLayout(content, 1)
        footer = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        footer.addWidget(self.summary, 1)
        logs = QPushButton("查看日志")
        logs.setObjectName("quietButton")
        logs.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(manager.paths.logs)))
        )
        footer.addWidget(logs)
        self.body.addLayout(footer)
        manager.changed.connect(self.refresh)
        self.refresh()
        if selected_id:
            self.select(selected_id)
        if open_settings:
            self.settings()
        mark_host(self)

    def selected_id(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def select(self, plugin_id):
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == plugin_id:
                self.list.setCurrentItem(item)
                return

    def refresh(self, *_args):
        selected = self.selected_id()
        self.list.blockSignals(True)
        self.list.clear()
        query, state = self.search.text().strip().casefold(), self.status_filter.currentData()
        for plugin_id, record in self.manager.records.items():
            manifest = record.manifest
            if self.filter.currentData() and manifest.type != self.filter.currentData():
                continue
            if (
                query
                and query not in f"{manifest.name} {plugin_id} {manifest.description}".casefold()
            ):
                continue
            if state and (
                record.state not in {"error", "incompatible"}
                if state == "problem"
                else record.state != state
            ):
                continue
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, plugin_id)
            item.setSizeHint(QSize(360, 72))
            self.list.addItem(item)
            row = QWidget()
            row.setObjectName("componentRow")
            layout = QHBoxLayout(row)
            layout.setContentsMargins(12, 8, 12, 8)
            glyph = QLabel()
            icon = (
                component_icon(self.manager, plugin_id)
                if manifest.type == "function"
                else ui_icon(manifest.type, self.manager.host.skin_colors["text"])
            )
            glyph.setPixmap(icon.pixmap(26, 26))
            layout.addWidget(glyph)
            name = QLabel(manifest.name)
            name.setToolTip(manifest.name)
            name.setMinimumWidth(90)
            name.setWordWrap(True)
            layout.addWidget(name, 1)
            kind = QLabel(TYPES[manifest.type])
            kind.setObjectName("typePill")
            kind.setFixedSize(48, 24)
            kind.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(kind)
            toggle = Toggle()
            toggle.setAccessibleName(manifest.name + " · 启停")
            toggle.setChecked(record.state == "enabled")
            toggle.setEnabled(record.state != "incompatible")
            toggle.clicked.connect(lambda _, key=plugin_id: self.toggle_id(key))
            layout.addWidget(toggle)
            more = QPushButton()
            more.setIcon(ui_icon("more", self.manager.host.skin_colors["text"]))
            more.setObjectName("circleButton")
            more.setFixedSize(32, 32)
            more.setToolTip("组件操作")
            more.clicked.connect(lambda _, key=plugin_id, widget=more: self.row_menu(key, widget))
            layout.addWidget(more)
            self.list.setItemWidget(item, row)
            if selected == plugin_id:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        enabled = sum(record.state == "enabled" for record in self.manager.records.values())
        self.summary.setText(
            f"已启用 {enabled} 个组件" if self.list.count() else "没有找到组件 · 换个关键词试试"
        )
        if self.manager.diagnostics:
            self.summary.setText(self.summary.text() + f" · {len(self.manager.diagnostics)} 条诊断")
            self.summary.setToolTip("\n".join(self.manager.diagnostics))
        self.selection_changed()
        mark_host(self)

    def selection_changed(self, *_args):
        plugin_id = self.selected_id()
        record = self.manager.records.get(plugin_id)
        for button in (self.toggle_button, self.reload_button, self.uninstall_button):
            button.setEnabled(record is not None)
        available = plugin_id in self.manager.settings_forms
        self.settings_button.setEnabled(available)
        self.page_tabs.setTabEnabled(1, available)
        if plugin_id != self.form_id or not available:
            self.page_tabs.setCurrentIndex(0)
            self.clear_form()
        if record is None:
            self.detail_title.setText("没有找到组件")
            self.details.clear()
            return
        manifest = record.manifest
        self.detail_title.setText(manifest.name)
        self.toggle_button.setText("停用" if record.state == "enabled" else "启用")
        self.toggle_button.setEnabled(record.state != "incompatible")
        self.reload_button.setEnabled(record.state == "enabled")
        self.uninstall_button.setEnabled(record.directory is not None and record.state != "enabled")
        self.details.setPlainText(
            f"{manifest.description}\n\n状态：{STATES.get(record.state, record.state)}\n"
            f"版本：{manifest.version}\n类型：{TYPES[manifest.type]}\n"
            f"来源：{'本地组件' if record.directory else '内置'}\n"
            f"作者：{manifest.author or '未填写'}\nAPI：{manifest.api_version}\n"
            f"ID：{manifest.id}\n权限：{', '.join(manifest.permissions) or '无'}\n"
            f"依赖：{', '.join(manifest.requires) or '无'}\n"
            + (f"\n错误：{record.error}" if record.error else "")
            + ("\n\n第三方 Python 组件在本机运行，请仅启用可信来源。" if record.directory else "")
        )

    def clear_form(self):
        while self.settings_layout.count():
            item = self.settings_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.form_id, self.settings_form = None, None

    def show_page(self, index):
        if index == 1:
            plugin_id = self.selected_id()
            if plugin_id not in self.manager.settings_forms:
                self.page_tabs.setCurrentIndex(0)
                return
            if self.form_id != plugin_id:
                self.clear_form()
                self.form_id = plugin_id
                self.settings_form = SettingsForm(self.manager, plugin_id)
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setWidget(self.settings_form)
                self.settings_layout.addWidget(scroll, 1)
                footer = QWidget()
                row = QHBoxLayout(footer)
                row.setContentsMargins(0, 8, 0, 0)
                reset = QPushButton("恢复默认")
                reset.setObjectName("quietButton")
                reset.clicked.connect(self.settings_form.reset)
                row.addWidget(reset)
                row.addStretch()
                cancel = QPushButton("取消")
                cancel.clicked.connect(self.cancel_settings)
                row.addWidget(cancel)
                save = QPushButton("保存更改")
                save.setObjectName("primaryButton")
                save.clicked.connect(self.save_settings)
                row.addWidget(save)
                self.settings_layout.addWidget(footer)
                mark_host(self)
        self.pages.setCurrentIndex(index)

    def settings(self):
        self.page_tabs.setCurrentIndex(1)

    def cancel_settings(self):
        self.page_tabs.setCurrentIndex(0)
        self.clear_form()

    def save_settings(self):
        if self.settings_form and self.settings_form.save():
            self.summary.setText("设置已保存")

    def operation(self, callback):
        try:
            callback()
        except PluginError as error:
            QMessageBox.warning(self, "插件操作未完成", str(error))
        self.refresh()

    def install(self):
        filename, _ = QFileDialog.getOpenFileName(self, "安装组件", "", "组件包 (*.zip)")
        if filename:
            self.operation(lambda: self.manager.install(Path(filename), replace_existing=True))

    def toggle_id(self, plugin_id):
        self.select(plugin_id)
        self.toggle()

    def toggle(self):
        plugin_id = self.selected_id()
        if plugin_id:
            record = self.manager.records[plugin_id]
            self.operation(
                lambda: self.manager.disable(plugin_id)
                if record.state == "enabled"
                else self.manager.enable(plugin_id)
            )

    def reload(self):
        plugin_id = self.selected_id()
        if plugin_id:
            self.operation(lambda: self.manager.reload(plugin_id))

    def uninstall(self):
        plugin_id = self.selected_id()
        if (
            plugin_id
            and QMessageBox.question(self, "卸载组件", "卸载后可重新安装。删除该组件和配置？")
            == QMessageBox.StandardButton.Yes
        ):
            self.operation(lambda: self.manager.uninstall(plugin_id))

    def open_directory(self):
        record = self.manager.records.get(self.selected_id())
        directory = record.directory if record and record.directory else self.manager.directory
        directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    def row_menu(self, plugin_id, widget):
        self.select(plugin_id)
        menu = QMenu(self)
        settings = menu.addAction("设置…", self.settings)
        settings.setEnabled(plugin_id in self.manager.settings_forms)
        reload = menu.addAction("重新加载", self.reload)
        reload.setEnabled(self.manager.records[plugin_id].state == "enabled")
        menu.addAction(self.toggle_button.text(), self.toggle)
        uninstall = menu.addAction("卸载组件", self.uninstall)
        uninstall.setEnabled(self.uninstall_button.isEnabled())
        mark_host(menu)
        menu.exec(widget.mapToGlobal(widget.rect().bottomLeft()))
        menu.deleteLater()
