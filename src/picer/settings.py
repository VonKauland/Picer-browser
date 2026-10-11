"""Application settings, distinct from component settings in plugin management."""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from picer.color_editor import ColorEditor
from picer.host_style import mark_host
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
        self.resize(1000, 780)
        self.setMinimumSize(860, 620)
        content = QHBoxLayout()
        self.navigation = QListWidget()
        self.navigation.setFixedWidth(180)
        self.navigation.setSpacing(6)
        self.pages = QStackedWidget()
        for label, icon, builder in (
            ("常规", "settings", self.general_page),
            ("外观", "skin", self.appearance_page),
            ("图片浏览", "photo", self.browsing_page),
            ("面板与布局", "panel", self.panels_page),
            ("快捷键", "keyboard", self.shortcuts_page),
            ("缓存与存储", "storage", self.storage_page),
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
        footer = QHBoxLayout()
        reset = QPushButton("恢复默认")
        reset.setObjectName("quietButton")
        reset.clicked.connect(self.reset)
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
        self.preference(card, "focus_image", "打开图片后聚焦画布")
        layout.addWidget(card)
        card = Card("文件关联")
        button = QPushButton("打开 Windows 默认应用设置")
        button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("ms-settings:defaultapps")))
        card.body.addWidget(button)
        note = QLabel("在 Windows 设置中选择揽映作为默认图片浏览器。")
        note.setObjectName("muted")
        note.setWordWrap(True)
        card.body.addWidget(note)
        layout.addWidget(card)

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
        card = Card("动画与反馈")
        label = QLabel("面板悬停展开与收回沿用当前动效。")
        label.setObjectName("muted")
        label.setWordWrap(True)
        card.body.addWidget(label)
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
        note = QLabel("旋转只修改预览，不改写原图。")
        note.setObjectName("muted")
        card.body.addWidget(note)
        layout.addWidget(card)

    def panels_page(self, layout):
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
        note = QLabel(
            "固定 / 自动隐藏仅通过面板三点条与指示条切换。全屏默认隐藏；"
            "侧边面板可左右换边，底部仅放进度面板。"
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        card.body.addWidget(note)
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
        layout.addWidget(self.binding_editor)

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
        self.layout_reset = True
        defaults = {"example.files": "left", "example.info": "right", "example.progress": "bottom"}
        for key, area in self.panel_editors.items():
            if key in defaults:
                area.setCurrentIndex(area.findData(DOCK_AREAS[defaults[key]]))

    def reset(self):
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
        self.reset_layout()

    def save(self):
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
        skin = self.skin.currentData()
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
            controller.move_to(area.currentData())
            if self.layout_reset:
                controller.extents = {"width": 320, "height": 180}
                controller.restore_size()
                controller.remember_layout()
        self.manager._save()
        self.host.apply_preferences()
        self.accept()
