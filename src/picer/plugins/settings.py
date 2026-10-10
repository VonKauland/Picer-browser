"""Declarative per-component settings, validated before a single atomic commit."""

from dataclasses import dataclass
from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from picer.host_style import mark_host
from picer.ui import Card, StyledDialog, Toggle, form_row, ui_icon


@dataclass(frozen=True)
class SettingField:
    key: str
    label: str
    kind: str
    default: Any
    minimum: int = 0
    maximum: int = 100
    choices: tuple[tuple[str, str], ...] = ()

    def validate(self, value):
        if self.kind == "bool":
            return value if type(value) is bool else self.default
        if self.kind == "int":
            return (
                max(self.minimum, min(self.maximum, value)) if type(value) is int else self.default
            )
        if self.kind == "choice":
            return value if value in tuple(key for key, _ in self.choices) else self.default
        return value if isinstance(value, str) else self.default


class SettingsForm(QWidget):
    """The same validated editor works embedded in management or in the legacy dialog."""

    def __init__(self, manager, plugin_id, parent=None):
        super().__init__(parent)
        self.manager, self.plugin_id = manager, plugin_id
        self.fields, self.callback = manager.settings_forms[plugin_id]
        self.editors = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        groups = {
            "example.files": (("首页", {"home"}), ("浏览", {"icon_size", "sort", "descending"})),
            "example.info": (("显示内容", {field.key for field in self.fields}),),
            "example.progress": (
                ("缩略预览", {"thumbnail_size", "thumbnail_count"}),
                ("幻灯片", {"interval"}),
            ),
        }.get(plugin_id, (("组件选项", {field.key for field in self.fields}),))
        used = set()
        for title, keys in (*groups, ("其他选项", {field.key for field in self.fields})):
            fields = [field for field in self.fields if field.key in keys and field.key not in used]
            if not fields:
                continue
            card = Card(title)
            for field in fields:
                used.add(field.key)
                value = field.validate(manager.get_setting(plugin_id, field.key, field.default))
                if field.kind == "bool":
                    editor = Toggle()
                    editor.setChecked(value)
                elif field.kind == "int":
                    editor = QSpinBox()
                    editor.setRange(field.minimum, field.maximum)
                    editor.setValue(value)
                    editor.setFixedWidth(120)
                    if field.key in {"icon_size", "thumbnail_size"}:
                        editor.setSuffix(" px")
                    elif field.key == "interval":
                        editor.setSuffix(" 秒")
                    elif field.key == "thumbnail_count":
                        editor.setSuffix(" 张")
                elif field.kind == "choice":
                    editor = QComboBox()
                    for key, label in field.choices:
                        editor.addItem(label, key)
                    editor.setCurrentIndex(editor.findData(value))
                    editor.setMinimumWidth(120)
                else:
                    editor = QLineEdit(value)
                editor.setAccessibleName(field.label)
                self.editors[field.key] = editor
                if field.kind == "path":
                    card.body.addWidget(QLabel(field.label))
                    row = QHBoxLayout()
                    row.addWidget(editor, 1)
                    browse = QPushButton()
                    browse.setIcon(ui_icon("folder", manager.host.skin_colors["text"]))
                    browse.setObjectName("circleButton")
                    browse.setFixedSize(36, 36)
                    browse.setToolTip("选择文件夹")
                    browse.clicked.connect(lambda _, edit=editor: self.choose_directory(edit))
                    row.addWidget(browse)
                    card.body.addLayout(row)
                else:
                    card.body.addLayout(form_row(field.label, editor))
            layout.addWidget(card)
        if plugin_id == "example.info":
            note = QLabel("读取到相机 EXIF 时，固定显示在面板底部。")
            note.setObjectName("muted")
            note.setWordWrap(True)
            layout.addWidget(note)
        self.dock_combo = None
        controller = manager.host.panel_hovers.controllers.get(plugin_id)
        if controller:
            from picer.panels import DOCK_AREAS

            card = Card("面板位置")
            self.dock_combo = QComboBox()
            for name, label in (("left", "左侧"), ("right", "右侧"), ("bottom", "底部")):
                self.dock_combo.addItem(label, DOCK_AREAS[name])
            self.dock_combo.setCurrentIndex(self.dock_combo.findData(controller.area))
            card.body.addLayout(form_row("停靠位置", self.dock_combo))
            layout.addWidget(card)
        layout.addStretch()
        mark_host(self)

    def choose_directory(self, editor):
        path = QFileDialog.getExistingDirectory(self, "选择首页路径", editor.text())
        if path:
            editor.setText(path)

    def reset(self):
        for field in self.fields:
            editor = self.editors[field.key]
            if field.kind == "bool":
                editor.setChecked(field.default)
            elif field.kind == "int":
                editor.setValue(field.default)
            elif field.kind == "choice":
                editor.setCurrentIndex(editor.findData(field.default))
            else:
                editor.setText(field.default)

    def save(self):
        from pathlib import Path

        from picer.plugins.api import PluginError

        if self.plugin_id not in self.manager.settings_forms:
            return False
        values = {}
        for field in self.fields:
            editor = self.editors[field.key]
            value = (
                editor.isChecked()
                if field.kind == "bool"
                else editor.value()
                if field.kind == "int"
                else editor.currentData()
                if field.kind == "choice"
                else editor.text()
            )
            if field.kind == "path" and value and not Path(value).expanduser().is_dir():
                QMessageBox.warning(self, "设置未保存", "首页路径必须是存在的文件夹。")
                return False
            values[field.key] = field.validate(value)
        try:
            self.manager.set_settings(self.plugin_id, values)
            self.manager._invoke(self.plugin_id, self.callback)
            record = self.manager.records.get(self.plugin_id)
            if record is None or record.state != "enabled":
                raise PluginError(record.error if record else "组件已移除")
            if self.dock_combo:
                controller = self.manager.host.panel_hovers.controllers.get(self.plugin_id)
                if controller:
                    controller.move_to(self.dock_combo.currentData())
        except PluginError as error:
            QMessageBox.warning(self, "设置未保存", str(error))
            return False
        return True


class SettingsDialog(StyledDialog):
    """Compatibility dialog for SDK users; manager uses the embedded SettingsForm."""

    def __init__(self, manager, plugin_id, parent=None):
        super().__init__(manager.records[plugin_id].manifest.name + " · 设置", parent=parent)
        self.manager, self.plugin_id = manager, plugin_id
        self.resize(560, 640)
        self.form = SettingsForm(manager, plugin_id)
        self.editors = self.form.editors
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.form)
        self.body.addWidget(scroll, 1)
        footer = QHBoxLayout()
        reset = QPushButton("恢复默认")
        reset.setObjectName("quietButton")
        reset.clicked.connect(self.form.reset)
        footer.addWidget(reset)
        footer.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        save = QPushButton("保存更改")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save)
        footer.addWidget(save)
        self.body.addLayout(footer)
        mark_host(self)
        manager.changed.connect(self.check_active)

    def check_active(self):
        if self.plugin_id not in self.manager.settings_forms:
            self.reject()

    def save(self):
        if self.form.save():
            self.accept()
