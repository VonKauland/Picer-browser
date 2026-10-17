"""Application settings, distinct from component settings in plugin management."""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from picer.color_editor import ColorEditor
from picer.confirmation import confirm
from picer.host_style import mark_host
from picer.messages import MessageBox as QMessageBox
from picer.panels import DOCK_AREAS
from picer.plugins.api import PluginError
from picer.preferences import DEFAULTS, read_preferences
from picer.ui import Card, RoundedSlider, StyledDialog, Toggle, form_row, ui_icon


class ApplicationSettings(StyledDialog):
    def __init__(self, window):
        super().__init__("设置", "", window)
        self.host, self.manager = window, window.plugins
        self.values = read_preferences(self.manager)
        self.editors, self.shortcut_editors, self.panel_editors = {}, {}, {}
        self.layout_reset = False
        self.pending_backup = None
        self.reset_pending = False
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumSize(760, 500)
        available = self.screen().availableGeometry().size()
        self.resize(min(960, available.width() - 24), min(720, available.height() - 24))
        content = QHBoxLayout()
        self.navigation = QListWidget()
        self.navigation.setFixedWidth(150)
        self.navigation.setSpacing(6)
        self.pages = QStackedWidget()
        for label, icon, builder in (
            ("常规", "settings", self.general_page),
            ("外观", "skin", self.appearance_page),
            ("图片浏览", "photo", self.browsing_page),
            ("面板与布局", "panel", self.panels_page),
            ("快捷键", "keyboard", self.shortcuts_page),
            ("缓存与存储", "storage", self.storage_page),
            ("格式设置", "photo", self.formats_page),
        ):
            from PySide6.QtWidgets import QListWidgetItem

            self.navigation.addItem(
                QListWidgetItem(ui_icon(icon, self.host.skin_colors["text"]), label)
            )
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setSpacing(18)
            title = QLabel(label)
            title.setObjectName("dialogHeading")
            layout.addWidget(title)
            builder(layout)
            if builder == self.shortcuts_page:
                layout.setSpacing(10)
                self.pages.addWidget(page)
                continue
            layout.addStretch()
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self.pages.addWidget(scroll)
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.setCurrentRow(1)
        content.addWidget(self.navigation)
        content.addWidget(self.pages, 1)
        self.body.addLayout(content, 1)
        self.skin_baseline = self.skin.currentData()
        self.panel_baseline = {key: area.currentData() for key, area in self.panel_editors.items()}
        footer = QHBoxLayout()
        reset = QPushButton("恢复默认")
        reset.setObjectName("quietButton")
        reset.clicked.connect(self.reset)
        footer.addWidget(reset)
        footer.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        self.apply_button = QPushButton("应用")
        self.apply_button.clicked.connect(self.apply)
        footer.addWidget(self.apply_button)
        save = QPushButton("保存更改")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save)
        footer.addWidget(save)
        self.body.addLayout(footer)
        mark_host(self)

    def preference(self, card, key, label, choices=None):
        value = self.values[key]
        if type(DEFAULTS[key]) is bool:
            editor = Toggle()
            editor.setChecked(value)
        elif choices:
            editor = QComboBox()
            for data, text in choices:
                editor.addItem(text, data)
            editor.setCurrentIndex(editor.findData(value))
        else:
            editor = QSpinBox()
            from picer.preferences import RANGES

            editor.setRange(*RANGES[key])
            editor.setValue(value)
            editor.setFixedWidth(130)
            editor.setSuffix(" MB" if key == "cache_mb" else " %")
        self.editors[key] = editor
        card.body.addLayout(form_row(label, editor))
        return editor

    def general_page(self, layout):
        card = Card("启动")
        self.preference(
            card, "start", "启动页面", (("empty", "空白首页"), ("last", "上次浏览的图片"))
        )
        self.preference(card, "remember_window", "记住窗口位置与大小")
        layout.addWidget(card)
        card = Card("操作反馈")
        self.preference(card, "tooltips", "显示操作提示")
        duration = self.preference(card, "notification_ms", "通知气泡显示时长")
        duration.setSuffix(" ms")
        self.preference(card, "focus_image", "打开图片后聚焦画布")
        layout.addWidget(card)

    def formats_page(self, layout):
        from picer.format_settings import build_format_page

        build_format_page(self, layout)

    def appearance_page(self, layout):
        card = Card("主题")
        self.skin = QComboBox()
        self.skin.addItem("默认深色 · Charcoal / Lime", "")
        current = ""
        for key, record in self.manager.records.items():
            if record.manifest.type == "skin":
                self.skin.addItem(record.manifest.name, key)
                if record.state == "enabled":
                    current = key
        self.skin.setCurrentIndex(self.skin.findData(current))
        card.body.addLayout(form_row("当前皮肤", self.skin))
        button = QPushButton("管理皮肤")
        button.clicked.connect(self.host.show_plugins)
        card.body.addWidget(button)
        layout.addWidget(card)
        card = Card("强调色")
        accent = ColorEditor(self.values["accent_color"])
        self.editors["accent_color"] = accent
        card.body.addLayout(form_row("界面强调色", accent))
        note = QLabel(
            "输入 #RRGGBB 或选择颜色，留空跟随皮肤。保存后应用；恢复默认可清除自定义颜色。"
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        card.body.addWidget(note)
        layout.addWidget(card)
        card = Card("界面")
        self.preference(card, "density", "界面密度", (("standard", "标准"), ("compact", "紧凑")))
        self.preference(card, "glass", "自动隐藏面板使用毛玻璃")
        slider = RoundedSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(self.values["glass_strength"])
        slider.setMinimumWidth(200)
        self.editors["glass_strength"] = slider
        card.body.addLayout(form_row("毛玻璃层次", slider))
        card.body.addLayout(form_row("文件名", QLabel("始终居中")))
        layout.addWidget(card)

    def browsing_page(self, layout):
        card = Card("打开图片")
        self.preference(
            card, "default_scale", "默认显示", (("fit", "适应窗口"), ("actual", "原始大小"))
        )
        self.preference(card, "auto_orient", "自动纠正 EXIF 方向")
        layout.addWidget(card)
        card = Card("导航")
        self.preference(card, "browse_folder", "浏览当前文件夹")
        self.preference(card, "wrap", "到末尾循环浏览")
        self.preference(
            card,
            "reading_direction",
            "浏览方向",
            (("ltr", "从左到右"), ("rtl", "从右到左")),
        )
        delay = self.preference(card, "key_repeat_delay_ms", "长按开始连击的延迟")
        delay.setSuffix(" ms")
        repeat = self.preference(card, "key_repeat_ms", "长按方向键切换间隔")
        repeat.setSuffix(" ms")
        note = QLabel(
            "30–2000 毫秒，默认 120 毫秒。值越大切换越慢；长按期间暂停原图精修，松开后恢复。"
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        card.body.addWidget(note)
        layout.addWidget(card)
        card = Card("缩放")
        self.preference(card, "zoom_step", "滚轮缩放步长")
        self.preference(
            card,
            "double_click",
            "双击图片",
            (("toggle", "适应 / 原始大小切换"), ("fit", "适应窗口"), ("actual", "原始大小")),
        )
        layout.addWidget(card)

    def panels_page(self, layout):
        card = Card("滚动条")
        self.preference(card, "panel_scrollbars", "显示所有面板的滚动条")
        note = QLabel("隐藏后仍可使用滚轮、触控板和键盘滚动；不会启用面板原本禁用的横向滚动条。")
        note.setWordWrap(True)
        note.setObjectName("muted")
        card.body.addWidget(note)
        layout.addWidget(card)
        card = Card("面板停靠位置")
        for plugin_id, controller in self.host.panel_hovers.controllers.items():
            row = QHBoxLayout()
            row.addWidget(QLabel(controller.dock.windowTitle()), 1)
            area = QComboBox()
            for key, label in (("left", "左侧"), ("right", "右侧"), ("bottom", "底部")):
                if controller.dock.allowedAreas() & DOCK_AREAS[key]:
                    area.addItem(label, DOCK_AREAS[key])
            area.setCurrentIndex(area.findData(controller.area))
            row.addWidget(area)
            self.panel_editors[plugin_id] = area
            card.body.addLayout(row)
        if not self.panel_editors:
            card.body.addWidget(QLabel("启用面板组件后，可在这里调整停靠位置。"))
        reset = QPushButton("重置布局")
        reset.clicked.connect(self.reset_layout)
        card.body.addWidget(reset)
        layout.addWidget(card)
        note = QLabel("面板内容设置统一位于：插件管理 → 选中组件 → 设置。")
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)

    def shortcuts_page(self, layout):
        from picer.binding_editor import BindingEditor

        self.binding_editor = BindingEditor(self.host)
        self.shortcut_editors = self.binding_editor.primary_editors
        layout.addWidget(self.binding_editor, 1)

    def storage_page(self, layout):
        card = Card("应用数据")
        path = QLineEdit(str(self.manager.paths.root))
        path.setReadOnly(True)
        card.body.addWidget(path)
        button = QPushButton("打开数据目录")
        button.clicked.connect(self.host.open_data_directory)
        card.body.addWidget(button)
        layout.addWidget(card)
        card = Card("图片缓存")
        self.cache_label = QLabel()
        self.refresh_cache_size()
        card.body.addWidget(self.cache_label)
        self.preference(card, "cache_mb", "缓存空间上限")
        button = QPushButton("清理图片缓存")
        button.clicked.connect(self.clear_cache)
        card.body.addWidget(button)
        layout.addWidget(card)
        from picer.plugin_storage import PluginStorage

        self.plugin_storage = PluginStorage(self)
        layout.addWidget(self.plugin_storage)
        card = Card("日志")
        button = QPushButton("打开日志目录")
        button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.manager.paths.logs)))
        )
        card.body.addWidget(button)
        note = QLabel(
            self.manager.paths.notice
            or "便携目录中的配置随软件保留，目录不可写时使用本地应用数据目录。"
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        card.body.addWidget(note)
        layout.addWidget(card)

    def refresh_cache_size(self):
        try:
            size = sum(
                file.stat().st_size for file in self.host.thumbnail_cache.directory.glob("*.png")
            )
            self.cache_label.setText(f"已使用 {size / 1048576:.1f} MB")
        except OSError:
            self.cache_label.setText("缓存大小暂不可读")

    def clear_cache(self):
        self.host.clear_thumbnail_cache()
        self.refresh_cache_size()

    def reset_layout(self):
        if confirm(
            self, "恢复默认布局？", "面板停靠位置与尺寸将恢复默认。点击应用或保存更改后生效。"
        ):
            self._reset_layout()

    def _reset_layout(self):
        self.layout_reset = True
        defaults = {"example.files": "left", "example.info": "right", "example.progress": "bottom"}
        for key, area in self.panel_editors.items():
            if key in defaults:
                area.setCurrentIndex(area.findData(DOCK_AREAS[defaults[key]]))

    def reset(self):
        if not confirm(
            self,
            "恢复默认设置？",
            "外观、浏览行为、输入绑定和面板布局将恢复默认。"
            "点击应用或保存更改后生效；取消会保留当前表单。",
        ):
            return
        self.pending_backup = None
        self.reset_pending = True
        for key, editor in self.editors.items():
            value = DEFAULTS[key]
            if isinstance(editor, Toggle):
                editor.setChecked(value)
            elif isinstance(editor, QComboBox):
                editor.setCurrentIndex(editor.findData(value))
            else:
                editor.setValue(value)
        self.skin.setCurrentIndex(0)
        self.binding_editor.reset()
        self._reset_layout()

    def save(self):
        self.apply(close=True)

    def load_backup(self, data):
        from picer.settings_backup import validate_backup

        data = validate_backup(data, self.host)
        for key, editor in self.editors.items():
            value = data["application"][key]
            if isinstance(editor, Toggle):
                editor.setChecked(value)
            elif isinstance(editor, QComboBox):
                editor.setCurrentIndex(editor.findData(value))
            else:
                editor.setValue(value)
        if data["skin"] and self.skin.findData(data["skin"]) < 0:
            record = self.manager.records[data["skin"]]
            self.skin.addItem(record.manifest.name, data["skin"])
        self.skin.setCurrentIndex(self.skin.findData(data["skin"]))
        self.binding_editor.set_profile(data["input_bindings"])
        for key, area in self.panel_editors.items():
            if key in data["panels"]:
                area.setCurrentIndex(area.findData(DOCK_AREAS[data["panels"][key]["area"]]))
        self.pending_backup = data
        self.reset_pending = False
        self.layout_reset = False

    def apply(self, *, close=False):
        bindings = self.binding_editor.validated()
        if bindings is None:
            return
        shortcuts = {
            key: next((b["value"] for b in bindings.get(key, []) if b["device"] == "keyboard"), "")
            for key in self.host.shortcut_actions
        }
        try:
            values = {}
            for key, editor in self.editors.items():
                values[key] = (
                    editor.isChecked()
                    if isinstance(editor, Toggle)
                    else editor.currentData()
                    if isinstance(editor, QComboBox)
                    else editor.value()
                )
        except ValueError as error:
            QMessageBox.warning(self, "设置未保存", str(error))
            return
        # A modeless window can coexist with reading-direction/skin/layout changes
        # made in the main window. Untouched fields must not revert those changes.
        if not self.pending_backup and not self.reset_pending:
            current = read_preferences(self.manager)
            values = {k: current[k] if v == self.values[k] else v for k, v in values.items()}
        skin = self.skin.currentData()
        if skin == self.skin_baseline and not self.pending_backup and not self.reset_pending:
            skin = next(
                (
                    key
                    for key, r in self.manager.records.items()
                    if r.manifest.type == "skin" and r.state == "enabled"
                ),
                "",
            )
        try:
            if skin:
                if skin not in self.manager.records:
                    raise PluginError("该皮肤已移除，请重新打开设置。")
                self.manager.enable(skin)
            else:
                self.host.components.default_skin()
        except PluginError as error:
            QMessageBox.warning(self, "设置未保存", str(error))
            return
        ui = self.manager.preferences["ui"]
        ui["application"], ui["shortcuts"] = values, shortcuts
        ui["input_bindings"] = bindings
        if not isinstance(ui.get("panels"), dict):
            ui["panels"] = {}
        for key, area in self.panel_editors.items():
            controller = self.host.panel_hovers.controllers.get(key)
            if not controller:
                continue
            if (
                self.layout_reset
                or self.pending_backup
                or area.currentData() != self.panel_baseline[key]
            ):
                controller.move_to(area.currentData())
            if self.layout_reset:
                controller.extents = {"width": 320, "height": 180}
                controller.restore_size()
                controller.remember_layout()
        if self.pending_backup:
            data = self.pending_backup
            if not isinstance(ui.get("panel_layouts"), dict):
                ui["panel_layouts"] = {}
            ui["quick_slots"] = data["quick_slots"].copy()
            self.host.panel_hovers.close_all()
            transition = self.manager._panel_transition
            self.manager._panel_transition = True
            try:
                for key, layout in data["panels"].items():
                    ui.setdefault("panel_layouts", {})[key] = {
                        name: layout[name] for name in ("area", "width", "height")
                    }
                    if "order" in layout:
                        ui["panel_layouts"][key]["order"] = layout["order"]
                    ui["panels"][key] = layout["fixed"]
                    controller = self.host.panel_hovers.controllers.get(key)
                    if controller:
                        controller.move_to(DOCK_AREAS[layout["area"]])
                        controller.order = layout.get("order", controller.order)
                        controller.extents = {name: layout[name] for name in ("width", "height")}
                        controller.dock.setVisible(not self.manager._fullscreen and layout["fixed"])
                        controller.restore_size()
                        controller.remember_layout()
            finally:
                self.manager._panel_transition = transition
            self.host.panel_hovers.normalize_sides()
            self.host.panel_hovers.layout_strips()
            self.host.components.refresh_slots()
        self.manager._save()
        self.host.apply_preferences()
        for index, name in enumerate(("settings", "skin", "photo", "panel", "keyboard", "storage")):
            self.navigation.item(index).setIcon(ui_icon(name, self.host.skin_colors["text"]))
        for button in self.findChildren(QPushButton):
            if button.accessibleName() == "关闭窗口":
                button.setIcon(ui_icon("close", self.host.skin_colors["text"]))
        self.values = values.copy()
        self.pending_backup = None
        self.reset_pending = False
        self.layout_reset = False
        self.skin_baseline = skin
        if skin and self.skin.findData(skin) < 0:
            self.skin.addItem(self.manager.records[skin].manifest.name, skin)
        self.skin.setCurrentIndex(self.skin.findData(skin))
        for key, area in self.panel_editors.items():
            controller = self.host.panel_hovers.controllers.get(key)
            if controller:
                area.setCurrentIndex(area.findData(controller.area))
                self.panel_baseline[key] = controller.area
        for key, editor in self.editors.items():
            if isinstance(editor, Toggle):
                editor.setChecked(values[key])
            elif isinstance(editor, QComboBox):
                editor.setCurrentIndex(editor.findData(values[key]))
            else:
                editor.setValue(values[key])
        if close:
            self.accept()
        self.host.notify("设置已保存" if close else "设置已应用")
