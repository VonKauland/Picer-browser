"""Staged multi-input settings, with explicit conflict replacement."""

import copy

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from picer.input_bindings import (
    MODIFIERS,
    MOUSE,
    ZONES,
    binding_conflict,
    catalog,
    default_bindings,
    normalize,
    read_bindings,
)
from picer.messages import MessageBox as QMessageBox
from picer.ui import Card

DEVICES = ("keyboard", "mouse", "touch", "gamepad")


class InputTabs(QTabWidget):
    """A bounded viewport; hidden pages cannot impose their form height on every tab."""

    def minimumSizeHint(self):
        return QSize(0, 0)

    def sizeHint(self):
        return QSize(380, 260)

    def addTab(self, page, label):
        viewport = QScrollArea()
        viewport.setWidgetResizable(True)
        viewport.setFrameShape(QScrollArea.Shape.NoFrame)
        viewport.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        viewport.setMinimumSize(0, 0)
        viewport.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        viewport.setWidget(page)
        return super().addTab(viewport, label)


class TouchMap(QWidget):
    def __init__(self, combo, host):
        super().__init__()
        self.combo, self.host = combo, host
        self.setObjectName("touchMap")
        self.setMinimumHeight(145)
        self.setToolTip("L1 / R1 为上半区，L2 / R2 为下半区；Center 为中间上方区域。点击选择区域。")
        combo.currentTextChanged.connect(lambda _: self.update())

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        rects = {
            "L1": (0, 0, w / 3, h / 2),
            "R1": (w * 2 / 3, 0, w / 3, h / 2),
            "L2": (0, h / 2, w / 2, h / 2),
            "R2": (w / 2, h / 2, w / 2, h / 2),
            "Center": (w / 3, 0, w / 3, h * 0.75),
        }
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainterPath

        for key, coords in rects.items():
            rect = QRectF(*coords).adjusted(3, 3, -3, -3)
            selected = key == self.combo.currentText()
            color = QColor(self.host.skin_colors["accent"] if selected else "#626264")
            p.setPen(QPen(color, 1.5))
            fill = QColor(self.host.skin_colors["accent"] if selected else "#303032")
            fill.setAlpha(28 if selected else 255)
            p.setBrush(fill)
            shape = QPainterPath()
            shape.addRoundedRect(rect, 10, 10)
            if key in ("L2", "R2"):
                cut = QPainterPath()
                cut.addRect(QRectF(w / 3, 0, w / 3, h * 0.75 + 3))
                shape = shape.subtracted(cut)
            p.drawPath(shape)
            p.setPen(QColor(self.host.skin_colors["text"]))
            if key in ("L2", "R2"):
                rect.moveBottom(h * 0.94)
                rect.setTop(h * 0.78)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, key)

    def mousePressEvent(self, event):
        from picer.input_bindings import touch_zone

        self.combo.setCurrentText(
            touch_zone(event.position().x() / self.width(), event.position().y() / self.height())
        )


class BindingEditor(QWidget):
    def __init__(self, host):
        super().__init__()
        self.host = host
        self.actions = catalog(host)
        self.labels = {key: action.text() for key, action in self.actions.items()}
        self.profile = copy.deepcopy(read_bindings(host))
        self.primary_editors = {}
        self.current_key = None
        body = QVBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        note = QLabel("选择左侧操作，可为键盘、鼠标、触控和手柄添加多个绑定。")
        note.setToolTip(
            "目录键在文件浏览面板内生效；其他键盘操作在窗口内生效。"
            "鼠标与触控作用于图片画布；触控与手柄默认未分配。"
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        body.addWidget(note)
        row = QHBoxLayout()
        function_pane = QWidget()
        function_pane.setMinimumWidth(165)
        function_pane.setMaximumWidth(215)
        left = QVBoxLayout(function_pane)
        left.setContentsMargins(0, 0, 0, 0)
        search = QLineEdit()
        search.setPlaceholderText("搜索操作或组件")
        left.addWidget(search)
        self.functions = QListWidget()
        self.functions.setMinimumSize(0, 0)
        for key, action in self.actions.items():
            item = QListWidgetItem(action.text())
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.functions.addItem(item)
        left.addWidget(self.functions)
        row.addWidget(function_pane)
        card = Card()
        card.body.setContentsMargins(14, 12, 14, 12)
        card.body.setSpacing(10)
        self.tabs = InputTabs()
        self.tabs.setMinimumSize(0, 0)
        self.tabs.setMinimumHeight(90)
        self.tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.tabs.setObjectName("inputTabs")
        self.keyboard_stack = QStackedWidget()
        self.keyboard_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for key in self.actions:
            values = [b["value"] for b in self.profile.get(key, []) if b["device"] == "keyboard"]
            edit = QKeySequenceEdit(QKeySequence(values[0] if values else ""))
            edit.setClearButtonEnabled(True)
            edit.setAccessibleName(self.actions[key].text())
            self.primary_editors[key] = edit
            self.keyboard_stack.addWidget(edit)
            edit.editingFinished.connect(self.show_bindings)
        self.keyboard_add = QKeySequenceEdit()
        self.keyboard_add.setClearButtonEnabled(True)
        self.keyboard_add.setAccessibleName("新增键盘绑定")
        keyboard = QWidget()
        keyboard.setObjectName("bindingPage")
        layout = QVBoxLayout(keyboard)
        layout.addWidget(QLabel("主要快捷键"))
        layout.addWidget(self.keyboard_stack)
        layout.addWidget(QLabel("添加另一个快捷键"))
        layout.addWidget(self.keyboard_add)
        layout.addStretch()
        self.tabs.addTab(keyboard, "键盘")
        mouse = QWidget()
        mouse.setObjectName("bindingPage")
        layout = QVBoxLayout(mouse)
        self.mouse_modifiers, self.mouse = QComboBox(), QComboBox()
        self.mouse_modifiers.addItems(["无修饰键"] + list(MODIFIERS[1:]))
        for value, label in zip(
            MOUSE,
            (
                "左键单击",
                "左键双击",
                "中键",
                "右键",
                "后退侧键",
                "前进侧键",
                "滚轮向上",
                "滚轮向下",
            ),
            strict=True,
        ):
            self.mouse.addItem(label, value)
        layout.addWidget(QLabel("修饰键与鼠标操作"))
        layout.addWidget(self.mouse_modifiers)
        layout.addWidget(self.mouse)
        layout.addStretch()
        self.tabs.addTab(mouse, "鼠标")
        touch = QWidget()
        touch.setObjectName("bindingPage")
        layout = QVBoxLayout(touch)
        self.touch = QComboBox()
        self.touch.addItems(ZONES)
        touch_map = TouchMap(self.touch, host)
        touch_map.setMaximumHeight(220)
        layout.addWidget(touch_map)
        layout.addWidget(self.touch)
        layout.addStretch()
        self.tabs.addTab(touch, "触控")
        from picer.gamepad_editor import GamepadPage

        self.gamepad_page = GamepadPage(host)
        self.tabs.addTab(self.gamepad_page, "手柄")
        card.body.addWidget(self.tabs, 1)
        card.body.addWidget(QLabel("已绑定输入"))
        self.bindings = QListWidget()
        self.bindings.setMinimumHeight(42)
        self.bindings.setMaximumHeight(64)
        self.bindings.currentItemChanged.connect(self.select_binding)
        card.body.addWidget(self.bindings)
        toolbar = QHBoxLayout()
        self.add_button = QPushButton("添加绑定")
        self.add_button.setObjectName("primaryButton")
        self.add_button.clicked.connect(self.add_current)
        self.remove_button = QPushButton("移除选中绑定")
        self.remove_button.clicked.connect(self.remove_current)
        toolbar.addWidget(self.add_button)
        toolbar.addWidget(self.remove_button)
        card.body.addLayout(toolbar)
        row.addWidget(card, 1)
        body.addLayout(row, 1)
        self.functions.currentItemChanged.connect(self.select)
        self.tabs.currentChanged.connect(self.show_bindings)
        search.textChanged.connect(self.filter)
        self.functions.setCurrentRow(0)

    def filter(self, text):
        for i in range(self.functions.count()):
            item = self.functions.item(i)
            item.setHidden(text.casefold() not in item.text().casefold())

    def select(self, item, previous=None):
        if item is None:
            return
        self.current_key = item.data(Qt.ItemDataRole.UserRole)
        self.keyboard_stack.setCurrentWidget(self.primary_editors[self.current_key])
        self.show_bindings()

    def materialize(self):
        result = copy.deepcopy(self.profile)
        for key, editor in self.primary_editors.items():
            entries = result.setdefault(key, [])
            keyboards = [b for b in entries if b["device"] == "keyboard"]
            others = [b for b in entries if b["device"] != "keyboard"]
            value = editor.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
            result[key] = (
                ([{"device": "keyboard", "value": value}] if value else []) + keyboards[1:] + others
            )
        return result

    def show_bindings(self, *_):
        self.bindings.clear()
        if self.current_key is None:
            return
        device = DEVICES[self.tabs.currentIndex()]
        for binding in self.materialize().get(self.current_key, []):
            if binding["device"] == device:
                value = binding["value"]
                if device == "gamepad":
                    from picer.gamepad import GAMEPAD_LABELS

                    value = "+".join(GAMEPAD_LABELS[p] for p in value.split("+"))
                item = QListWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, binding)
                self.bindings.addItem(item)

    def set_profile(self, profile):
        self.profile = copy.deepcopy(profile)
        for key, editor in self.primary_editors.items():
            values = [b["value"] for b in profile.get(key, []) if b["device"] == "keyboard"]
            editor.setKeySequence(QKeySequence(values[0] if values else ""))
        self.show_bindings()

    def select_binding(self, item, previous=None):
        if item is not None:
            binding = item.data(Qt.ItemDataRole.UserRole)
            if binding["device"] == "gamepad":
                self.gamepad_page.set_value(binding["value"])

    def reset(self):
        self.set_profile(default_bindings(self.host))

    def assign(self, key, device, value):
        value = normalize(device, value)
        if not value:
            return False
        profile = self.materialize()
        binding = {"device": device, "value": value}
        if binding in profile.get(key, []):
            return True
        conflicts = [
            (k, b)
            for k, entries in profile.items()
            for b in entries
            if (k != key or device == "gamepad" and b != binding) and binding_conflict(binding, b)
        ]
        owner = conflicts[0][0] if conflicts else None
        if owner is not None:
            label = "、".join(dict.fromkeys(self.labels.get(k, k) for k, _ in conflicts))
            message = f"{value} 与「{label}」的现有绑定冲突。"
            if device == "gamepad":
                from picer.gamepad import SHOULDERS, modifier_shoulders

                if any(
                    value in SHOULDERS
                    and value in modifier_shoulders(b["value"])
                    or b["value"] in SHOULDERS
                    and b["value"] in modifier_shoulders(value)
                    for _, b in conflicts
                ):
                    message += "肩键不能同时作为组合修饰键和单独绑定。"
            reply = QMessageBox.question(
                self,
                "快捷键冲突",
                message + "是否覆盖全部冲突绑定？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return False
            for conflict_owner, conflict in conflicts:
                profile[conflict_owner].remove(conflict)
        if len(profile.setdefault(key, [])) >= 32:
            QMessageBox.warning(self, "绑定数量", "每个操作最多保存 32 个输入绑定。")
            return False
        profile[key].append(binding)
        self.set_profile(profile)
        return True

    def add_current(self):
        device = DEVICES[self.tabs.currentIndex()]
        if device == "gamepad":
            self.assign(self.current_key, device, self.gamepad_page.value())
            return
        value = (
            self.keyboard_add.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
            if device == "keyboard"
            else (
                ""
                if self.mouse_modifiers.currentIndex() == 0
                else self.mouse_modifiers.currentText()
            )
            + self.mouse.currentData()
            if device == "mouse"
            else self.touch.currentText()
        )
        if self.assign(self.current_key, device, value):
            self.keyboard_add.clear()

    def remove_current(self):
        item = self.bindings.currentItem()
        if item:
            profile = self.materialize()
            profile[self.current_key].remove(item.data(Qt.ItemDataRole.UserRole))
            self.set_profile(profile)

    def validated(self):
        profile, claimed = self.materialize(), []
        for key, bindings in profile.items():
            for binding in list(bindings):
                conflicts = [
                    (owner, previous)
                    for owner, previous in claimed
                    if binding_conflict(previous, binding)
                ]
                if conflicts:
                    if all(owner == key for owner, _ in conflicts):
                        if all(previous == binding for _, previous in conflicts):
                            bindings.remove(binding)
                            continue
                        QMessageBox.warning(
                            self, "快捷键冲突", "同一操作中的输入互相冲突，请修改后保存。"
                        )
                        return None
                    label = ", ".join(self.labels.get(owner, owner) for owner, _ in conflicts)
                    answer = QMessageBox.question(
                        self,
                        "快捷键冲突",
                        f"{binding['value']} 与「{label}」冲突。是否覆盖原绑定？",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if answer != QMessageBox.StandardButton.Yes:
                        return None
                    for owner, previous in conflicts:
                        profile[owner].remove(previous)
                        claimed.remove((owner, previous))
                claimed.append((key, binding))
        self.set_profile(profile)
        return profile
