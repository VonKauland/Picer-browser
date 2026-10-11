"""Optional Windows XInput reader and bounded, edge-triggered Qt polling."""

import ctypes
import os
import sys
import time
import weakref
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal

BUTTON_MASKS = {
    "DpadUp": 0x0001,
    "DpadDown": 0x0002,
    "DpadLeft": 0x0004,
    "DpadRight": 0x0008,
    "Start": 0x0010,
    "Back": 0x0020,
    "LS": 0x0040,
    "RS": 0x0080,
    "LB": 0x0100,
    "RB": 0x0200,
    "Guide": 0x0400,
    "A": 0x1000,
    "B": 0x2000,
    "X": 0x4000,
    "Y": 0x8000,
}
GAMEPAD_LABELS = {
    "A": "A",
    "B": "B",
    "X": "X",
    "Y": "Y",
    "LB": "LB",
    "RB": "RB",
    "LT": "LT",
    "RT": "RT",
    "Back": "视图键",
    "Start": "菜单键",
    "Guide": "引导键",
    "LS": "左摇杆按下",
    "RS": "右摇杆按下",
    "DpadUp": "方向键 ↑",
    "DpadDown": "方向键 ↓",
    "DpadLeft": "方向键 ←",
    "DpadRight": "方向键 →",
    "LSUp": "左摇杆 ↑",
    "LSDown": "左摇杆 ↓",
    "LSLeft": "左摇杆 ←",
    "LSRight": "左摇杆 →",
    "RSUp": "右摇杆 ↑",
    "RSDown": "右摇杆 ↓",
    "RSLeft": "右摇杆 ←",
    "RSRight": "右摇杆 →",
}
SHOULDERS = ("LB", "RB", "LT", "RT")


def normalize_gamepad(value):
    if not isinstance(value, str):
        return ""
    parts = value.split("+")
    if not parts or len(parts) > 5 or len(set(parts)) != len(parts):
        return ""
    if any(part not in GAMEPAD_LABELS for part in parts):
        return ""
    if any(part not in SHOULDERS for part in parts[:-1]):
        return ""
    ordered = [part for part in SHOULDERS if part in parts[:-1]]
    return "+".join(ordered + [parts[-1]])


def modifier_shoulders(value):
    parts = value.split("+")
    return set(parts[:-1]) if len(parts) > 1 else set()


def gamepad_conflict(first, second):
    if set(first.split("+")) == set(second.split("+")):
        return True
    return (
        "+" not in first
        and first in modifier_shoulders(second)
        or "+" not in second
        and second in modifier_shoulders(first)
    )


def activated_bindings(current, previous, values):
    """Recognize chords once; used modifiers never fire a standalone command."""
    modifiers = set().union(*(modifier_shoulders(value) for value in values))
    active = current & modifiers
    for value in values:
        parts = frozenset(value.split("+"))
        if parts <= current and not parts <= previous:
            if active == parts & modifiers and not (len(parts) == 1 and parts & modifiers):
                yield value


class NativeGamepad(ctypes.Structure):
    _fields_ = [
        ("buttons", ctypes.c_uint16),
        ("left_trigger", ctypes.c_uint8),
        ("right_trigger", ctypes.c_uint8),
        ("left_x", ctypes.c_int16),
        ("left_y", ctypes.c_int16),
        ("right_x", ctypes.c_int16),
        ("right_y", ctypes.c_int16),
    ]


class NativeState(ctypes.Structure):
    _fields_ = [("packet", ctypes.c_uint32), ("gamepad", NativeGamepad)]


@dataclass(frozen=True)
class GamepadSample:
    buttons: int = 0
    left_trigger: int = 0
    right_trigger: int = 0
    left_x: int = 0
    left_y: int = 0
    right_x: int = 0
    right_y: int = 0


def sample_inputs(sample, previous=frozenset(), *, guide_supported=False):
    """Use hysteresis so noisy triggers/sticks do not repeatedly fire commands."""
    result = {
        key
        for key, mask in BUTTON_MASKS.items()
        if sample.buttons & mask and (key != "Guide" or guide_supported)
    }
    for key, value in (("LT", sample.left_trigger), ("RT", sample.right_trigger)):
        if value >= (20 if key in previous else 40):
            result.add(key)
    for stick, x, y in (
        ("LS", sample.left_x, sample.left_y),
        ("RS", sample.right_x, sample.right_y),
    ):
        for direction, value in (("Left", -x), ("Right", x), ("Up", y), ("Down", -y)):
            key = stick + direction
            if value >= (12000 if key in previous else 18000):
                result.add(key)
    return frozenset(result)


class XInputBackend:
    threaded = True

    def __init__(self):
        self.available = False
        self.guide_supported = False
        self.dll = self.reader = None
        self.message = "手柄输入仅在 Windows 上可用；仍可设置并保存绑定。"
        if sys.platform != "win32":
            return
        system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
        for name in ("xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll"):
            try:
                # Absolute system path: never load a similarly named DLL from a plugin/cwd.
                dll = ctypes.WinDLL(str(system / name))
                reader = dll.XInputGetState
                reader.argtypes = [ctypes.c_uint32, ctypes.POINTER(NativeState)]
                reader.restype = ctypes.c_uint32
            except (OSError, AttributeError):
                continue
            try:
                # Optional extended entry point exposes the otherwise omitted guide bit.
                extended = dll[100]
                extended.argtypes = reader.argtypes
                extended.restype = reader.restype
            except (AttributeError, OSError):
                extended = None
            self.dll, self.reader = dll, reader
            self.extended = extended
            self.guide_supported = extended is not None
            self.available = True
            self.message = "支持 XInput 手柄，连接后按下按钮可识别。"
            break
        if not self.available:
            self.message = "Windows XInput 不可用；仍可设置并保存绑定。"

    def read(self, index):
        if not self.available or index not in range(4):
            return None
        state = NativeState()
        try:
            code = (self.extended or self.reader)(index, ctypes.byref(state))
            if code != 0 and self.extended is not None:
                code = self.reader(index, ctypes.byref(state))
            if code != 0:
                return None
        except (OSError, ctypes.ArgumentError):
            return None
        pad = state.gamepad
        return GamepadSample(*(getattr(pad, name) for name, _ in NativeGamepad._fields_))


class PollSignals(QObject):
    ready = Signal(int, object)


class PollTask(QRunnable):
    def __init__(self, backend, indices, generation, signals):
        super().__init__()
        self.backend, self.indices = backend, indices
        self.generation, self.signals = generation, signals

    def run(self):
        samples = {}
        for index in self.indices:
            try:
                samples[index] = self.backend.read(index)
            except (OSError, ctypes.ArgumentError):
                samples[index] = None
        self.signals.ready.emit(self.generation, samples)


class GamepadMonitor(QObject):
    pressed = Signal(int, str)
    buttons_changed = Signal(int, object)
    inputs_changed = Signal(int, object, object)
    status_changed = Signal()

    def __init__(self, parent=None, backend=None):
        super().__init__(parent)
        self.backend = backend if backend is not None else XInputBackend()
        self.connected = [False] * 4
        self.held = [frozenset() for _ in range(4)]
        self.next_probe = [0.0] * 4
        self.baseline = [True] * 4
        self._capture = None
        self.interested = False
        self.disposed = False
        self.generation = 0
        self.busy = False
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.signals = PollSignals(self)
        self.signals.ready.connect(self.complete, Qt.ConnectionType.QueuedConnection)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.poll)
        self.refresh_interval()

    @property
    def capture(self):
        widget = self._capture() if self._capture else None
        try:
            return widget if widget is not None and widget.isVisible() else None
        except RuntimeError:
            return None

    def set_capture(self, widget):
        self._capture = weakref.ref(widget) if widget is not None else None
        self.rebaseline()
        self.refresh_interval()

    def release_capture(self, widget):
        if self._capture is not None and self._capture() is widget:
            self.set_capture(None)

    def set_interest(self, interested):
        self.interested = interested
        self.rebaseline()
        self.refresh_interval()

    def rebaseline(self):
        self.generation += 1
        self.baseline = [True] * 4
        self.next_probe = [0.0] * 4

    def refresh_interval(self):
        if not self.disposed and self.backend.available:
            self.timer.start(16 if self.interested or self.capture is not None else 250)
        else:
            self.timer.stop()

    def poll(self):
        if self.disposed or self.busy:
            return
        now = time.monotonic()
        indices = [i for i in range(4) if self.connected[i] or now >= self.next_probe[i]]
        if not indices:
            return
        for index in indices:
            self.next_probe[index] = now + 1
        if getattr(self.backend, "threaded", False):
            self.busy = True
            self.pool.start(PollTask(self.backend, indices, self.generation, self.signals))
        else:
            self.apply_samples({index: self.backend.read(index) for index in indices})

    def complete(self, generation, samples):
        self.busy = False
        if not self.disposed and generation == self.generation:
            self.apply_samples(samples)

    def apply_samples(self, samples):
        for index in range(4):
            if index not in samples:
                continue
            sample = samples[index]
            connected = sample is not None
            previous = self.held[index]
            current = (
                sample_inputs(sample, previous, guide_supported=self.backend.guide_supported)
                if connected
                else frozenset()
            )
            changed = connected != self.connected[index]
            first = self.baseline[index] or changed
            self.connected[index], self.held[index] = connected, current
            self.baseline[index] = not connected
            if changed:
                self.status_changed.emit()
            if current != previous or changed:
                self.buttons_changed.emit(index, current)
                self.inputs_changed.emit(index, current, current if first else previous)
            if not first:
                for key in (*SHOULDERS, *(key for key in GAMEPAD_LABELS if key not in SHOULDERS)):
                    if key in current - previous:
                        self.pressed.emit(index, key)

    def dispose(self):
        self.disposed = True
        self.timer.stop()
        self._capture = None
        self.held = [frozenset() for _ in range(4)]
        # Keep the signal owner alive until the single native reader returns.
        self.pool.waitForDone()
