"""Application-style editor dock: navigator, presets, independent modifiers, save."""

import copy

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from picer.color_picker import ColorPicker
from picer.editing.controls import CurveEditor, Navigator
from picer.editing.engine import SAVE_FORMATS, defaults
from picer.editing.presets import PresetSettings, add_preset, read_presets
from picer.host_style import mark_host
from picer.plugins.api import PluginError
from picer.ui import RoundedSlider, StyledDialog, Toggle

TITLES = (
    ("crop", "裁剪图像"),
    ("resize", "拉伸图像"),
    ("rotate", "旋转图像"),
    ("mirror", "镜像图像"),
    ("levels", "色阶调整"),
    ("hsl", "色相／饱和度／明度"),
    ("selective", "单色过滤器"),
    ("pixelate", "像素化"),
    ("curves", "曲线修改"),
)


class SaveDialog(StyledDialog):
    def __init__(self, parent, can_overwrite):
        super().__init__("保存修改", parent=parent)
        self.choice = None
        self.resize(430, 200)
        self.body.addWidget(QLabel("是否保存当前图片的修改？"))
        self.body.addWidget(QLabel("保存副本将保留原文件，副本使用 PNG 格式。"))
        row = QHBoxLayout()
        for label, choice in (("取消", None), ("保存覆盖", True), ("保存副本", False)):
            button = QPushButton(label)
            if choice is False:
                button.setObjectName("primaryButton")
            if choice is None:
                button.setDefault(True)
            if choice is True:
                button.setEnabled(can_overwrite)
                if not can_overwrite:
                    button.setToolTip("此格式仅支持保存 PNG 副本")
            button.clicked.connect(lambda _, value=choice: self.choose(value))
            row.addWidget(button)
        self.body.addLayout(row)
        mark_host(self)

    def choose(self, choice):
        self.choice = choice
        self.reject() if choice is None else self.accept()


class EditingPanel(QWidget):
    def __init__(self, context):
        super().__init__()
        self.context = context
        self.session = context.create_editing_session()
        self.editors, self.switches, self.parameters, self.headers = {}, {}, {}, {}
        self.syncing = False
        self.last_path = None
        self.setMinimumWidth(235)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 8)
        layout.setSpacing(5)
        self.navigator = Navigator(self.session)
        layout.addWidget(self.navigator)
        zoom = QHBoxLayout()
        self.zoom = RoundedSlider()
        self.zoom.setRange(-30, 40)
        self.zoom.setValue(0)
        self.zoom.setAccessibleName("导航器缩放")
        self.zoom.valueChanged.connect(self.set_zoom)
        zoom.addWidget(self.zoom, 1)
        self.button(zoom, "适应", self.session.host.view.fit_image)
        self.button(zoom, "100%", self.session.host.view.actual_size)
        layout.addLayout(zoom)
        presets = QHBoxLayout()
        self.presets = QComboBox()
        self.presets.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.presets.setAccessibleName("编辑预设")
        self.presets.activated.connect(self.use_preset)
        presets.addWidget(self.presets, 1)
        self.add_preset_button = self.button(presets, "+", self.new_preset)
        self.add_preset_button.setFixedWidth(30)
        self.add_preset_button.setToolTip("新增预设")
        layout.addLayout(presets)
        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        self.stack = QVBoxLayout(content)
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.stack.setSpacing(6)
        self.scroll.setWidget(content)
        layout.addWidget(self.scroll, 1)
        for key, title in TITLES:
            self.section(key, title)
        self.stack.addStretch()
        footer = QHBoxLayout()
        self.status = QLabel("临时预览")
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        footer.addWidget(self.status, 1)
        self.save_button = self.button(footer, "保存", self.confirm_save)
        self.save_button.setObjectName("primaryButton")
        layout.addLayout(footer)
        self.session.changed.connect(self.sync)
        self.session.picked.connect(lambda hue: self.modify("selective", "hue", hue))
        self.session.cropped.connect(self.crop_selected)
        self.reload_presets()
        self.sync()
        context.add_settings_page(lambda parent: PresetSettings(self, parent))
        context.subscribe("appearance.changed", lambda _: self.sync())

    @staticmethod
    def button(layout, text, callback):
        button = QPushButton(text)
        button.setStyleSheet("padding: 5px 8px; min-height: 20px; border-radius: 8px;")
        button.clicked.connect(lambda _: callback())
        layout.addWidget(button)
        return button

    def section(self, key, title):
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(4, 4, 4, 4)
        column.setSpacing(7)
        row = QHBoxLayout()
        header = QPushButton("› " + title)
        header.setStyleSheet(
            "text-align: left; padding: 5px 0; border: none; background: transparent;"
        )
        header.clicked.connect(lambda _: self.switches[key].toggle())
        self.headers[key] = header
        row.addWidget(header, 1)
        switch = Toggle()
        switch.setAccessibleName("启用" + title)
        switch.toggled.connect(lambda enabled: self.modify(key, "enabled", enabled))
        self.switches[key] = switch
        row.addWidget(switch)
        column.addLayout(row)
        params = QWidget()
        body = QVBoxLayout(params)
        body.setContentsMargins(0, 0, 0, 3)
        body.setSpacing(7)
        self.parameters[key] = params
        column.addWidget(params)
        getattr(self, "build_" + key)(body)
        reset = QHBoxLayout()
        reset.addStretch()
        self.button(reset, "重置", lambda: self.reset(key))
        body.addLayout(reset)
        self.stack.addWidget(box)

    def number(self, body, key, field, label, low, high, value=0, decimals=0, slider=False):
        row = QHBoxLayout()
        text = QLabel(label)
        text.setWordWrap(True)
        row.addWidget(text, 1)
        edit = QDoubleSpinBox() if decimals else QSpinBox()
        if decimals:
            edit.setDecimals(decimals)
            edit.setSingleStep(0.1 if field == "angle" else 0.01)
        edit.setRange(low, high)
        edit.setValue(value)
        edit.setFixedWidth(78 if decimals else 72)
        edit.setAccessibleName(label)
        if slider:
            control = RoundedSlider()
            control.setRange(int(low), int(high))
            control.setAccessibleName(label)
            control.valueChanged.connect(edit.setValue)
            edit.valueChanged.connect(lambda n: control.setValue(round(n)))
            row.addWidget(control, 2)
            self.editors[(key, field, "slider")] = control
        edit.valueChanged.connect(lambda n: self.modify(key, field, n))
        row.addWidget(edit)
        self.editors[(key, field)] = edit
        body.addLayout(row)
        return edit

    def choice(self, body, key, field, label, choices):
        row = QHBoxLayout()
        row.addWidget(QLabel(label), 1)
        edit = QComboBox()
        for value, text in choices:
            edit.addItem(text, value)
        edit.currentIndexChanged.connect(lambda _: self.modify(key, field, edit.currentData()))
        row.addWidget(edit)
        body.addLayout(row)
        self.editors[(key, field)] = edit
        return edit

    def check(self, body, key, field, label):
        row = QHBoxLayout()
        row.addWidget(QLabel(label), 1)
        edit = Toggle()
        edit.setAccessibleName(label)
        edit.toggled.connect(lambda value: self.modify(key, field, value))
        row.addWidget(edit)
        body.addLayout(row)
        self.editors[(key, field)] = edit

    def build_crop(self, body):
        self.aspect = QComboBox()
        for label in ("自由", "原始", "1:1", "4:3", "16:9"):
            self.aspect.addItem(label)
        self.aspect.currentIndexChanged.connect(self.apply_aspect)
        body.addWidget(self.aspect)
        for field, title in (("x", "X"), ("y", "Y"), ("w", "宽"), ("h", "高")):
            self.number(body, "crop", field, title, 0 if field in {"x", "y"} else 1, 30000)
        row = QHBoxLayout()
        self.button(row, "画布框选", lambda: self.session.begin_tool("crop"))
        body.addLayout(row)

    def build_resize(self, body):
        self.number(body, "resize", "width", "宽", 1, 30000, 1920)
        self.number(body, "resize", "height", "高", 1, 30000, 1280)
        self.check(body, "resize", "linked", "保持比例")
        self.choice(
            body,
            "resize",
            "method",
            "插值",
            (("lanczos", "高质量"), ("bicubic", "双三次"), ("nearest", "邻近像素")),
        )

    def build_rotate(self, body):
        self.number(body, "rotate", "angle", "角度", -180, 180, decimals=1, slider=True)
        row = QHBoxLayout()
        for label, angle in (("↶ 90°", -90), ("↷ 90°", 90), ("180°", 180)):
            self.button(row, label, lambda a=angle: self.modify("rotate", "angle", a))
        body.addLayout(row)

    def build_mirror(self, body):
        self.check(body, "mirror", "horizontal", "水平镜像")
        self.check(body, "mirror", "vertical", "垂直镜像")

    def build_levels(self, body):
        self.choice(
            body, "levels", "channel", "通道", tuple((v, v) for v in ("RGB", "R", "G", "B"))
        )
        self.histogram = CurveEditor(editable=False)
        body.addWidget(self.histogram)
        for field, label, low, high, value, decimals in (
            ("black", "黑场", 0, 254, 0, 0),
            ("mid", "中间调", 0.1, 10, 1, 2),
            ("white", "白场", 1, 255, 255, 0),
            ("out_black", "输出黑场", 0, 255, 0, 0),
            ("out_white", "输出白场", 0, 255, 255, 0),
        ):
            self.number(
                body, "levels", field, label, low, high, value, decimals, slider=not decimals
            )
        row = QHBoxLayout()
        self.button(row, "自动", self.auto_levels)
        body.addLayout(row)

    def build_hsl(self, body):
        for field, label, limit in (
            ("hue", "色相", 180),
            ("saturation", "饱和度", 100),
            ("lightness", "明度", 100),
        ):
            self.number(body, "hsl", field, label, -limit, limit, slider=True)

    def build_selective(self, body):
        row = QHBoxLayout()
        row.addWidget(QLabel("保留颜色"), 1)
        self.color = self.button(row, "", self.choose_color)
        self.color.setFixedWidth(35)
        self.color.setAccessibleName("选择保留颜色")
        self.button(row, "取色", lambda: self.session.begin_tool("pick"))
        body.addLayout(row)
        self.number(body, "selective", "hue", "色相", 0, 359, 120, slider=True)
        self.number(body, "selective", "range", "色域范围 ±°", 0, 180, 25, slider=True)
        self.number(body, "selective", "softness", "过渡柔和度 %", 0, 100, 20, slider=True)

    def build_pixelate(self, body):
        self.number(body, "pixelate", "size", "区块大小 px", 1, 512, 16, slider=True)
        row = QHBoxLayout()
        for size in (4, 8, 16, 32):
            self.button(row, str(size), lambda value=size: self.modify("pixelate", "size", value))
        body.addLayout(row)

    def build_curves(self, body):
        self.choice(
            body, "curves", "channel", "通道", tuple((v, v) for v in ("RGB", "R", "G", "B"))
        )
        self.curve = CurveEditor()
        self.curve.changed.connect(self.curve_changed)
        body.addWidget(self.curve)
        values = QHBoxLayout()
        self.curve_x, self.curve_y = QSpinBox(), QSpinBox()
        for title, edit in (("输入", self.curve_x), ("输出", self.curve_y)):
            values.addWidget(QLabel(title))
            edit.setRange(0, 255)
            edit.setFixedWidth(70)
            edit.setAccessibleName("曲线" + title)
            edit.valueChanged.connect(self.edit_curve_value)
            values.addWidget(edit)
        body.addLayout(values)
        self.curve_values = QLabel("单击添加节点 · Delete 删除节点")
        self.curve_values.setWordWrap(True)
        body.addWidget(self.curve_values)
        row = QHBoxLayout()
        self.button(row, "线性", self.linear_curve)
        body.addLayout(row)

    def modify(self, key, field, value):
        if self.syncing:
            return
        state = copy.deepcopy(self.session.state)
        if key == "crop" and field != "enabled":
            w, h = self.session.native
            if not w or not h:
                return
            value /= w if field in {"x", "w"} else h
            if field in {"x", "y"}:
                extent = "w" if field == "x" else "h"
                value = min(value, 1 - state[key][extent])
            else:
                value = min(value, 1 - state[key]["x" if field == "w" else "y"])
        if key == "resize" and field in {"width", "height"} and state[key]["linked"]:
            other = "height" if field == "width" else "width"
            state[key][other] = max(
                1, min(30000, round(value * state[key][other] / state[key][field]))
            )
        state[key][field] = value
        if key == "levels":
            if field == "black":
                state[key]["white"] = max(value + 1, state[key]["white"])
            if field == "white":
                state[key]["black"] = min(value - 1, state[key]["black"])
        try:
            self.session.set_state(state)
            if key != "curves" or field != "channel":
                self.presets.setCurrentIndex(0)
        except ValueError as error:
            self.context.notify(str(error))
            self.sync()

    def sync(self):
        self.syncing = True
        state = self.session.state
        if self.session.path != self.last_path:
            self.last_path = self.session.path
            self.presets.setCurrentIndex(0)
            self.aspect.setCurrentIndex(0)
            self.curve.selected = None
        for key, title in TITLES:
            enabled = state[key]["enabled"]
            with QSignalBlocker(self.switches[key]):
                self.switches[key].setChecked(enabled)
            self.parameters[key].setVisible(enabled)
            self.headers[key].setText(("⌄ " if enabled else "› ") + title)
        for (key, field, *extra), editor in self.editors.items():
            value = state[key][field]
            if key == "crop":
                w, h = self.session.native
                value = round(value * (w if field in {"x", "w"} else h))
                if field in {"w", "h"}:
                    value = max(1, value)
            with QSignalBlocker(editor):
                if isinstance(editor, QComboBox):
                    editor.setCurrentIndex(editor.findData(value))
                elif isinstance(editor, Toggle):
                    editor.setChecked(value)
                else:
                    editor.setValue(round(value) if extra else value)
        self.curve.nodes = copy.deepcopy(state["curves"]["points"][state["curves"]["channel"]])
        self.curve.update()
        color = QColor.fromHsv(state["selective"]["hue"], 220, 230).name()
        self.color.setStyleSheet(f"background: {color}; border-radius: 5px; min-height: 20px;")
        if self.session.source is not None:
            hist = self.session.source.convert("L").resize((256, 160)).histogram()
            self.histogram.histogram = self.curve.histogram = hist
            self.histogram.update()
        ready = self.session.source is not None
        self.scroll.setEnabled(ready and not self.session.saving)
        self.presets.setEnabled(ready and not self.session.saving)
        self.add_preset_button.setEnabled(ready and not self.session.saving)
        self.save_button.setEnabled(
            ready
            and not self.session.error
            and not self.session.busy
            and not self.session.saving
            and any(row["enabled"] for row in state.values())
        )
        self.status.setText(
            self.session.error
            or (
                "正在保存…"
                if self.session.saving
                else "正在预览…"
                if self.session.busy
                else "临时预览 · 尚未保存"
                if self.session.applied
                else "开启修改器开始编辑"
            )
        )
        self.navigator.update()
        self.syncing = False

    def set_zoom(self, value):
        view = self.session.host.view
        target = 2 ** (value / 10)
        current = view.transform().m11()
        if current:
            view.zoom(target / current)

    def reset(self, key):
        state = copy.deepcopy(self.session.state)
        enabled = state[key]["enabled"]
        state[key] = defaults(self.session.native if all(self.session.native) else (1920, 1280))[
            key
        ]
        state[key]["enabled"] = enabled
        self.session.set_state(state)

    def apply_aspect(self):
        if self.syncing or not all(self.session.native):
            return
        value = self.aspect.currentText()
        if value == "自由":
            return
        w, h = self.session.native
        ratio = w / h if value == "原始" else int(value.split(":")[0]) / int(value.split(":")[1])
        state = copy.deepcopy(self.session.state)
        c = state["crop"]
        width, height = c["w"] * w, c["h"] * h
        if width / height > ratio:
            width = height * ratio
        else:
            height = width / ratio
        c.update(w=width / w, h=height / h)
        self.session.set_state(state)

    def crop_selected(self, crop):
        state = copy.deepcopy(self.session.state)
        state["crop"].update(crop, enabled=True)
        self.session.set_state(state)
        self.apply_aspect()

    def choose_color(self):
        initial = QColor.fromHsv(self.session.state["selective"]["hue"], 255, 255)
        picker = ColorPicker(
            initial.name(), self, title="选择保留颜色", subtitle="指定需要保留的色域"
        )
        picker.follow.hide()
        try:
            if picker.exec() and picker.selected_value:
                self.modify("selective", "hue", max(0, QColor(picker.selected_value).hsvHue()))
        finally:
            picker.deleteLater()

    def curve_changed(self, nodes):
        state = copy.deepcopy(self.session.state)
        state["curves"]["points"][state["curves"]["channel"]] = nodes
        self.session.set_state(state)
        n = self.curve.selected
        if n is not None and n < len(nodes):
            for edit, value in ((self.curve_x, nodes[n][0]), (self.curve_y, nodes[n][1])):
                with QSignalBlocker(edit):
                    edit.setValue(round(value))

    def edit_curve_value(self):
        self.curve.set_selected(self.curve_x.value(), self.curve_y.value())

    def linear_curve(self):
        state = copy.deepcopy(self.session.state)
        state["curves"]["points"][state["curves"]["channel"]] = [[0, 0], [255, 255]]
        self.session.set_state(state)

    def auto_levels(self):
        source = self.session.source
        if source:
            hist = source.convert("L").histogram()
            values = [n for n, count in enumerate(hist) if count]
            if values and values[-1] > values[0]:
                state = copy.deepcopy(self.session.state)
                state["levels"].update(black=values[0], white=values[-1])
                self.session.set_state(state)

    def reload_presets(self):
        self.entries = read_presets(self.context)
        with QSignalBlocker(self.presets):
            self.presets.clear()
            self.presets.addItem("自定义")
            self.presets.addItems([row["name"] for row in self.entries])

    def use_preset(self, index):
        if index > 0:
            self.session.set_state(self.entries[index - 1]["state"])

    def new_preset(self):
        if add_preset(self, self.entries, self.session.state):
            try:
                self.context.set_setting("presets", self.entries)
            except PluginError as error:
                self.context.notify(str(error))
            self.reload_presets()
            self.presets.setCurrentIndex(len(self.entries))

    def confirm_save(self):
        if not self.save_button.isEnabled():
            return
        dialog = SaveDialog(self, self.session.path.suffix.lower() in SAVE_FORMATS)
        try:
            if dialog.exec() and dialog.choice is not None:
                self.session.save(dialog.choice)
        finally:
            dialog.deleteLater()

    def shutdown(self):
        self.navigator.timer.stop()
