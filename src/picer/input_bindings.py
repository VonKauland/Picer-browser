"""Persisted, device-specific bindings shared by core and plugin commands."""

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

ZONES = ("L1", "Center", "R1", "L2", "R2")
MOUSE = ("Left", "DoubleLeft", "Middle", "Right", "Back", "Forward", "WheelUp", "WheelDown")
MODIFIERS = (
    "",
    "Ctrl+",
    "Shift+",
    "Alt+",
    "Ctrl+Shift+",
    "Ctrl+Alt+",
    "Shift+Alt+",
    "Ctrl+Shift+Alt+",
)


def touch_zone(x, y):
    if 1 / 3 <= x < 2 / 3 and y < 0.75:
        return "Center"
    return ("L" if x < 0.5 else "R") + ("1" if y < 0.5 else "2")


def normalize(device, value):
    if not isinstance(value, str) or len(value) > 128:
        return ""
    if device == "keyboard":
        sequence = QKeySequence(value, QKeySequence.SequenceFormat.PortableText)
        return sequence.toString(QKeySequence.SequenceFormat.PortableText)
    if device == "mouse" and value in {prefix + button for prefix in MODIFIERS for button in MOUSE}:
        return value
    if device == "touch" and value in ZONES:
        return value
    return ""


def catalog(host):
    return {**host.shortcut_actions, **host.plugins.commands}


def default_bindings(host):
    result = {}
    for key, action in catalog(host).items():
        value = host.default_shortcuts.get(key, action.property("default_shortcut") or "")
        result[key] = [{"device": "keyboard", "value": value}] if value else []
    for key, value in (
        ("放大", "WheelUp"),
        ("缩小", "WheelDown"),
        ("上一张", "Back"),
        ("下一张", "Forward"),
        ("切换图片缩放", "DoubleLeft"),
    ):
        if key in result:
            result[key].append({"device": "mouse", "value": value})
    return result


def read_bindings(host):
    ui = host.plugins.preferences["ui"]
    saved = ui.get("input_bindings")
    defaults = default_bindings(host)
    if not isinstance(saved, dict):
        saved = {}
        legacy = ui.get("shortcuts", {})
        if isinstance(legacy, dict):
            for key, value in legacy.items():
                if key in defaults and isinstance(value, str):
                    defaults[key] = [b for b in defaults[key] if b["device"] != "keyboard"]
                    if value:
                        defaults[key].insert(0, {"device": "keyboard", "value": value})
    result, used = {}, set()
    # Explicit assignments claim inputs before new defaults, preserving updates.
    for key in list(saved)[:512] + [k for k in defaults if k not in saved]:
        entries = saved.get(key, defaults.get(key, []))
        if not isinstance(key, str) or not isinstance(entries, list):
            continue
        result[key] = []
        for entry in entries[:32]:
            if not isinstance(entry, dict):
                continue
            device = entry.get("device")
            value = normalize(device, entry.get("value"))
            token = (device, value)
            if (
                value
                and token not in used
                and not any(
                    binding_conflict({"device": device, "value": value}, {"device": d, "value": v})
                    for d, v in used
                )
            ):
                result[key].append({"device": device, "value": value})
                used.add(token)
    return result


def binding_conflict(first, second):
    if first["device"] != second["device"]:
        return False
    if first["device"] != "keyboard":
        return first["value"] == second["value"]
    a, b = QKeySequence(first["value"]), QKeySequence(second["value"])
    no = QKeySequence.SequenceMatch.NoMatch
    return a.matches(b) != no or b.matches(a) != no


def mouse_value(event, button):
    prefix = ""
    for flag, name in (
        (Qt.KeyboardModifier.ControlModifier, "Ctrl+"),
        (Qt.KeyboardModifier.ShiftModifier, "Shift+"),
        (Qt.KeyboardModifier.AltModifier, "Alt+"),
    ):
        if event.modifiers() & flag:
            prefix += name
    return prefix + button


class InputBindings(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.touch_owners = host.touch_owners
        self.touch_start = None
        self.mouse_start = None
        self.double = False
        self.pending = QTimer(self)
        self.pending.setSingleShot(True)
        self.pending.timeout.connect(lambda: self.dispatch("mouse", self.pending_value))
        self.host.view.viewport().setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
        QApplication.instance().installEventFilter(self)
        self.reload()

    def reload(self):
        self.profile = read_bindings(self.host)
        self.mapping = {}
        for key, action in catalog(self.host).items():
            bindings = self.profile.get(key, [])
            action.setShortcuts(
                [QKeySequence(b["value"]) for b in bindings if b["device"] == "keyboard"]
            )
            for binding in bindings:
                self.mapping[(binding["device"], binding["value"])] = key

    def dispatch(self, device, value):
        if device == "touch" and not self.touch_owners:
            return False
        key = self.mapping.get((device, value))
        action = catalog(self.host).get(key)
        if action is not None and action.isEnabled():
            action.trigger()
            return True
        return False

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind in (QEvent.Type.ApplicationDeactivate, QEvent.Type.WindowDeactivate):
            self.pending.stop()
            self.touch_start = self.mouse_start = None
        if (
            obj is not self.host.view.viewport()
            or QApplication.activePopupWidget()
            or QApplication.activeModalWidget()
        ):
            return False
        if kind in (
            QEvent.Type.TouchBegin,
            QEvent.Type.TouchUpdate,
            QEvent.Type.TouchEnd,
            QEvent.Type.TouchCancel,
        ):
            if not self.touch_owners:
                return False
            points = event.points()
            if kind == QEvent.Type.TouchBegin and len(points) == 1:
                self.touch_start = points[0].position()
            elif kind == QEvent.Type.TouchUpdate and (
                len(points) != 1
                or self.touch_start is not None
                and (points[0].position() - self.touch_start).manhattanLength()
                > QApplication.startDragDistance()
            ):
                self.touch_start = None
            elif kind == QEvent.Type.TouchEnd:
                if self.touch_start is not None:
                    p = self.touch_start
                    self.dispatch("touch", touch_zone(p.x() / obj.width(), p.y() / obj.height()))
                self.touch_start = None
            elif kind == QEvent.Type.TouchCancel:
                self.touch_start = None
            event.accept()
            return True
        if kind == QEvent.Type.Wheel:
            value = mouse_value(event, "WheelUp" if event.angleDelta().y() > 0 else "WheelDown")
            if event.angleDelta().y():
                self.dispatch("mouse", value)
            event.accept()
            return True
        names = {
            Qt.MouseButton.LeftButton: "Left",
            Qt.MouseButton.MiddleButton: "Middle",
            Qt.MouseButton.RightButton: "Right",
            Qt.MouseButton.BackButton: "Back",
            Qt.MouseButton.ForwardButton: "Forward",
        }
        if kind == QEvent.Type.MouseButtonDblClick:
            if event.button() == Qt.MouseButton.LeftButton:
                self.pending.stop()
                self.double = True
                self.dispatch("mouse", mouse_value(event, "DoubleLeft"))
                return True
        if kind == QEvent.Type.MouseButtonPress:
            self.double = False
            self.mouse_start = event.position()
        elif kind == QEvent.Type.MouseMove and self.mouse_start is not None:
            if (
                event.position() - self.mouse_start
            ).manhattanLength() > QApplication.startDragDistance():
                self.mouse_start = None
        elif kind == QEvent.Type.MouseButtonRelease:
            start, self.mouse_start = self.mouse_start, None
            if self.double:
                self.double = False
                return True
            value = mouse_value(event, names.get(event.button(), ""))
            if start is not None and ("mouse", value) in self.mapping:
                if (
                    event.button() == Qt.MouseButton.LeftButton
                    and ("mouse", mouse_value(event, "DoubleLeft")) in self.mapping
                ):
                    self.pending_value = value
                    self.pending.start(QApplication.doubleClickInterval())
                else:
                    self.dispatch("mouse", value)
                return True
        return False

    def dispose(self):
        self.pending.stop()
        self.touch_owners.clear()
        QApplication.instance().removeEventFilter(self)
