"""Staged multi-input settings, with explicit conflict replacement."""

import copy

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
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
from picer.ui import Card


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
        note = QLabel(
            "每个操作可添加多个输入。键盘在窗口内生效；鼠标与触控仅作用于图片画布。触控默认未分配。"
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        body.addWidget(note)
        row = QHBoxLayout()
        left = QVBoxLayout()
        search = QLineEdit()
        search.setPlaceholderText("搜索操作或组件")
        left.addWidget(search)
        self.functions = QListWidget()
        self.functions.setMinimumWidth(160)
        self.functions.setMaximumWidth(230)
        for key, action in self.actions.items():
            item = QListWidgetItem(action.text())
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.functions.addItem(item)
        left.addWidget(self.functions)
        row.addLayout(left)
        card = Card("输入绑定")
        self.tabs = QTabWidget()
        self.tabs.setObjectName("inputTabs")
        self.keyboard_stack = QStackedWidget()
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
        self.tabs.addTab(mouse, "鼠标")
        touch = QWidget()
        touch.setObjectName("bindingPage")
        layout = QVBoxLayout(touch)
        self.touch = QComboBox()
        self.touch.addItems(ZONES)
        layout.addWidget(TouchMap(self.touch, host))
        layout.addWidget(self.touch)
        self.tabs.addTab(touch, "触控")
        card.body.addWidget(self.tabs)
        add = QPushButton("添加绑定")
        add.clicked.connect(self.add_current)
        card.body.addWidget(add)
        self.bindings = QListWidget()
        self.bindings.setMinimumHeight(85)
        self.bindings.setMaximumHeight(115)
        card.body.addWidget(self.bindings)
        remove = QPushButton("移除选中绑定")
        remove.clicked.connect(self.remove_current)
        card.body.addWidget(remove)
        row.addWidget(card, 1)
        body.addLayout(row)
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
        device = ("keyboard", "mouse", "touch")[self.tabs.currentIndex()]
        for binding in self.materialize().get(self.current_key, []):
            if binding["device"] == device:
                item = QListWidgetItem(binding["value"])
                item.setData(Qt.ItemDataRole.UserRole, binding)
                self.bindings.addItem(item)

    def set_profile(self, profile):
        self.profile = copy.deepcopy(profile)
        for key, editor in self.primary_editors.items():
            values = [b["value"] for b in profile.get(key, []) if b["device"] == "keyboard"]
            editor.setKeySequence(QKeySequence(values[0] if values else ""))
        self.show_bindings()

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
            if k != key and binding_conflict(binding, b)
        ]
        owner = conflicts[0][0] if conflicts else None
        if owner is not None:
            label = self.labels.get(owner, owner)
            reply = QMessageBox.question(
                self,
                "快捷键冲突",
                f"{value} 已绑定到「{label}」。是否覆盖原绑定？",
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
        device = ("keyboard", "mouse", "touch")[self.tabs.currentIndex()]
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
                            self, "快捷键冲突", "同一操作中的快捷键不能互为前缀，请修改后保存。"
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
