"""Native ABI, chord exclusivity, hotplug, capture and persisted command routing."""

import ctypes
from types import SimpleNamespace

import pytest
from PIL import Image
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from picer.gamepad import (
    GamepadMonitor,
    GamepadSample,
    NativeGamepad,
    NativeState,
    XInputBackend,
    activated_bindings,
    normalize_gamepad,
    sample_inputs,
)
from picer.input_bindings import binding_conflict, read_bindings
from picer.settings import ApplicationSettings
from picer.window import MainWindow


class FakeBackend:
    available = True
    guide_supported = True
    message = "模拟 XInput 输入，仅用于自动化验证。"

    def __init__(self):
        self.samples = [GamepadSample(), None, None, None]
        self.reads = []

    def read(self, index):
        self.reads.append(index)
        return self.samples[index]


@pytest.fixture
def host(qtbot, tmp_path, monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr("picer.gamepad.XInputBackend", lambda: backend)
    window = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(window)
    window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    window.inputs.gamepad.timer.stop()
    window.inputs.gamepad.poll()
    yield window, backend
    window.close()


def press(window, backend, sample):
    backend.samples[0] = sample
    window.inputs.gamepad.poll()


def configure(window, values):
    ui = window.plugins.preferences["ui"]
    profile = read_bindings(window)
    for key, bindings in values.items():
        profile[key] = [{"device": "gamepad", "value": value} for value in bindings]
    ui["input_bindings"] = profile
    window.inputs.reload()
    window.inputs.gamepad.timer.stop()
    window.inputs.gamepad.poll()


def images(window, tmp_path):
    paths = [tmp_path / f"{i}.png" for i in range(3)]
    for path in paths:
        Image.new("RGB", (100, 150)).save(path)
    window.open_image(paths[0])
    window.view.setFocus()
    return paths


@pytest.mark.parametrize(
    "value,expected",
    [
        ("A", "A"),
        ("RT+A", "RT+A"),
        ("RT+LB+A", "LB+RT+A"),
        ("RT+LT", "RT+LT"),
        ("RT+RT+A", ""),
        ("A+B", ""),
        ("RT+Bogus", ""),
        ("rt+A", ""),
        ("RT+", ""),
        (None, ""),
    ],
)
def test_normalize_chords(value, expected):
    assert normalize_gamepad(value) == expected


def test_abi_sizes_and_native_reader_guide_fallback(monkeypatch):
    assert ctypes.sizeof(NativeGamepad) == 12
    assert ctypes.sizeof(NativeState) == 16

    class NativeFunction:
        def __init__(self, guide=False):
            self.guide = guide
            self.calls = []

        def __call__(self, index, pointer):
            self.calls.append(index)
            if index != 0:
                return 1167
            state = ctypes.cast(pointer, ctypes.POINTER(NativeState)).contents
            state.gamepad.buttons = 0x1400 if self.guide else 0x1000
            state.gamepad.left_trigger = 88
            state.gamepad.left_x = -23000
            return 0

    standard, extended = NativeFunction(), NativeFunction(True)

    class StandardLibrary:
        XInputGetState = standard

        def __getitem__(self, ordinal):
            raise AttributeError("extended entry point unavailable")

    library = StandardLibrary()
    paths = []

    class Library:
        XInputGetState = standard

        def __getitem__(self, ordinal):
            assert ordinal == 100
            return extended

    def load(path):
        paths.append(path)
        return Library()

    monkeypatch.setattr("picer.gamepad.sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(ctypes, "WinDLL", load, raising=False)
    backend = XInputBackend()
    assert backend.available and backend.guide_supported
    assert paths[0].endswith("System32/xinput1_4.dll") or paths[0].endswith(
        "System32\\xinput1_4.dll"
    )
    assert backend.read(0) == GamepadSample(0x1400, 88, 0, -23000)
    assert backend.read(1) is None
    assert backend.read(-1) is None and backend.read(4) is None
    monkeypatch.setattr(ctypes, "WinDLL", lambda _: library, raising=False)
    backend = XInputBackend()
    assert backend.available and not backend.guide_supported
    assert backend.read(0).buttons == 0x1000
    assert "Guide" not in sample_inputs(GamepadSample(0x1400))


def test_backend_unavailable_is_optional(monkeypatch):
    monkeypatch.setattr("picer.gamepad.sys", SimpleNamespace(platform="linux"))
    assert not XInputBackend().available
    monkeypatch.setattr("picer.gamepad.sys", SimpleNamespace(platform="win32"))

    def missing(_):
        raise OSError("no library")

    monkeypatch.setattr(ctypes, "WinDLL", missing, raising=False)
    backend = XInputBackend()
    assert not backend.available and backend.read(0) is None


def test_trigger_stick_hysteresis_and_guide():
    first = sample_inputs(GamepadSample(0x1400, 41, 0, -19000, 0, 0, 19000), guide_supported=True)
    assert first == {"Guide", "A", "LT", "LSLeft", "RSUp"}
    held = sample_inputs(GamepadSample(0, 22, 0, -13000), first)
    assert held == {"LT", "LSLeft"}
    assert not sample_inputs(GamepadSample(0, 19, 0, -11999), held)
    assert not sample_inputs(GamepadSample(0, 39, 0, 17000))


def test_chord_modifier_exclusivity_and_other_shoulders():
    def binding(value):
        return {"device": "gamepad", "value": value}

    assert binding_conflict(binding("RT"), binding("RT+A"))
    assert binding_conflict(binding("LB+RT+A"), binding("RT"))
    assert not binding_conflict(binding("LB"), binding("RT+A"))
    assert not binding_conflict(binding("RT+A"), binding("RT+B"))
    assert not binding_conflict(binding("A"), binding("RT+A"))
    assert binding_conflict(binding("RT+LB"), binding("LB+RT"))
    values = ["A", "RT+A", "LB", "RT+B", "LB+RT+X"]
    assert list(activated_bindings({"RT"}, set(), values)) == []
    assert list(activated_bindings({"RT", "A"}, {"RT"}, values)) == ["RT+A"]
    assert list(activated_bindings({"A"}, set(), values)) == ["A"]
    assert list(activated_bindings({"RT", "A"}, {"RT", "A"}, values)) == []
    # LB is a modifier in the last chord, so it never also fires standalone.
    assert list(activated_bindings({"LB", "RT", "X"}, {"LB", "RT"}, values)) == ["LB+RT+X"]
    assert list(activated_bindings({"LB"}, set(), ["LB", "RT+A"])) == ["LB"]


def test_monitor_edges_hotplug_reconnect_probe_limit_and_dispose(qtbot):
    backend = FakeBackend()
    backend.samples[0] = GamepadSample(0x1000)
    monitor = GamepadMonitor(backend=backend)
    monitor.timer.stop()
    presses, changes = [], []
    monitor.pressed.connect(lambda i, b: presses.append((i, b)))
    monitor.inputs_changed.connect(lambda i, now, old: changes.append((i, now, old)))
    monitor.poll()
    assert monitor.connected[0] and presses == []
    assert changes[0][1] == changes[0][2]  # Connecting with held keys never fires.
    monitor.poll()
    assert backend.reads.count(1) == 1
    backend.samples[0] = GamepadSample()
    monitor.poll()
    backend.samples[0] = GamepadSample(0x1000)
    monitor.poll()
    monitor.poll()
    assert presses == [(0, "A")]
    backend.samples[0] = None
    monitor.poll()
    backend.samples[0] = GamepadSample(0x1000)
    monitor.next_probe[0] = 0
    monitor.poll()
    assert presses == [(0, "A")]
    monitor.dispose()
    count = len(backend.reads)
    monitor.poll()
    assert not monitor.timer.isActive() and len(backend.reads) == count


def test_runtime_chord_single_press_repeat_focus_and_plugin_revoke(host, qtbot, tmp_path):
    window, backend = host
    paths = images(window, tmp_path)
    configure(window, {"下一张": ["RT+A"], "上一张": ["A"], "example.doublepage:toggle": ["LB"]})
    press(window, backend, GamepadSample(right_trigger=100))
    assert window.current_path == paths[0]
    press(window, backend, GamepadSample(0x1000, right_trigger=100))
    assert window.current_path == paths[1]
    window.inputs.gamepad.poll()
    assert window.current_path == paths[1]
    press(window, backend, GamepadSample())
    press(window, backend, GamepadSample(0x1000))
    assert window.current_path == paths[0]
    window.plugins.disable("example.doublepage")
    press(window, backend, GamepadSample(0x0100))
    assert "example.doublepage:toggle" not in window.plugins.commands
    window.plugins.enable("example.doublepage")
    window.inputs.gamepad.timer.stop()
    window.inputs.gamepad.poll()
    press(window, backend, GamepadSample())
    press(window, backend, GamepadSample(0x0100))
    assert window.plugins.commands["example.doublepage:toggle"].isChecked()
    browser = window.plugins.records["example.files"].instance
    browser.search.setFocus()
    press(window, backend, GamepadSample())
    press(window, backend, GamepadSample(0x1000, right_trigger=100))
    assert window.current_path == paths[0]


def test_editor_capture_chords_click_diagram_and_cancel(host, qtbot, tmp_path):
    window, backend = host
    paths = images(window, tmp_path)
    configure(window, {"下一张": ["RT+A"]})
    settings = ApplicationSettings(window)
    qtbot.addWidget(settings)
    settings.navigation.setCurrentRow(4)
    editor = settings.binding_editor
    assert editor.tabs.count() == 4
    editor.tabs.setCurrentIndex(3)
    settings.show()
    settings.activateWindow()
    qtbot.waitUntil(settings.isActiveWindow)
    page = editor.gamepad_page
    assert window.inputs.gamepad.capture is page
    window.inputs.gamepad.timer.stop()
    window.inputs.gamepad.poll()
    press(window, backend, GamepadSample(0x1000, right_trigger=100))
    assert page.value() == "RT+A", {
        "held": window.inputs.gamepad.held,
        "baseline": window.inputs.gamepad.baseline,
        "subscribed": page.subscribed,
        "dialog_active": settings.isActiveWindow(),
        "active_window": str(QApplication.activeWindow()),
        "popup": str(QApplication.activePopupWidget()),
        "modal": str(QApplication.activeModalWidget()),
    }
    assert window.current_path == paths[0]
    diagram = page.diagram
    scale, x, y = diagram.transform()
    from picer.gamepad_editor import CENTERS

    assert CENTERS["LS"][1] < CENTERS["RS"][1]
    center_x, center_y = CENTERS["Guide"]
    pos = QPointF(x + center_x * scale, y + center_y * scale)
    assert diagram.hit_test(pos) == "Guide"
    qtbot.mouseClick(diagram, Qt.MouseButton.LeftButton, pos=pos.toPoint())
    assert page.button.currentData() == "Guide"
    assert not diagram.grab().toImage().isNull()
    settings.reject()
    assert window.inputs.gamepad.capture is None
    assert ("gamepad", "Guide") not in window.inputs.mapping


def test_shoulder_conflicts_cover_reverse_multiple_and_persist(host, qtbot, monkeypatch):
    window, backend = host
    settings = ApplicationSettings(window)
    qtbot.addWidget(settings)
    editor = settings.binding_editor
    assert all(b["device"] != "gamepad" for entries in editor.profile.values() for b in entries)
    assert editor.assign("上一张", "gamepad", "RT")
    monkeypatch.setattr(
        "picer.binding_editor.QMessageBox.question", lambda *a: QMessageBox.StandardButton.No
    )
    assert not editor.assign("下一张", "gamepad", "RT+A")
    monkeypatch.setattr(
        "picer.binding_editor.QMessageBox.question", lambda *a: QMessageBox.StandardButton.Yes
    )
    assert editor.assign("下一张", "gamepad", "RT+A")
    assert editor.assign("下一张", "gamepad", "RT+B")
    assert editor.assign("上一张", "gamepad", "LB")
    assert {"device": "gamepad", "value": "RT"} not in editor.materialize()["上一张"]
    assert editor.assign("跳转至首图", "gamepad", "RT")
    assert not [b for b in editor.materialize()["下一张"] if b["device"] == "gamepad"]
    assert editor.assign("example.doublepage:toggle", "gamepad", "Guide")
    settings.save()
    root = window.plugins.root
    window.close()
    restarted = MainWindow(plugin_root=root)
    qtbot.addWidget(restarted)
    assert restarted.inputs.mapping[("gamepad", "RT")] == "跳转至首图"
    assert restarted.inputs.mapping[("gamepad", "LB")] == "上一张"
    assert restarted.inputs.mapping[("gamepad", "Guide")] == "example.doublepage:toggle"
    restarted.close()


def test_modal_popup_and_deactivation_never_dispatch(host, qtbot, tmp_path):
    window, backend = host
    paths = images(window, tmp_path)
    configure(window, {"下一张": ["A"]})
    dialog = QMessageBox(window)
    qtbot.addWidget(dialog)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.show()
    qtbot.waitUntil(lambda: QApplication.activeModalWidget() is dialog)
    press(window, backend, GamepadSample(0x1000))
    assert window.current_path == paths[0]
    dialog.close()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    window.inputs.gamepad.poll()
    assert window.current_path == paths[0]
    QApplication.sendEvent(window, QEvent(QEvent.Type.WindowDeactivate))
    window.inputs.gamepad.poll()
    assert window.current_path == paths[0]
    press(window, backend, GamepadSample())
    window.view.setFocus()
    press(window, backend, GamepadSample(0x1000))
    assert window.current_path == paths[1]


def test_native_worker_keeps_gui_responsive_and_rejects_old_generation(qtbot):
    from threading import Event

    entered, release = Event(), Event()
    backend = FakeBackend()
    backend.threaded = True
    original_read = backend.read

    def blocked(index):
        if index == 0:
            entered.set()
            release.wait(3)
        return original_read(index)

    backend.read = blocked
    monitor = GamepadMonitor(backend=backend)
    monitor.timer.stop()
    seen = []
    monitor.pressed.connect(lambda i, key: seen.append(key))
    monitor.poll()
    qtbot.waitUntil(entered.is_set)
    assert monitor.busy
    qtbot.wait(30)  # The GUI continues processing while the native call is blocked.
    monitor.poll()
    assert backend.reads == []  # No second task or queue grows behind the first.
    monitor.rebaseline()
    release.set()
    qtbot.waitUntil(lambda: not monitor.busy)
    assert not monitor.connected[0]  # Stale pre-profile-transition result ignored.
    monitor.poll()
    qtbot.waitUntil(lambda: monitor.connected[0])
    assert seen == []
    backend.samples[0] = GamepadSample(0x1000)
    monitor.poll()
    qtbot.waitUntil(lambda: seen == ["A"])
    monitor.dispose()
    assert not monitor.timer.isActive() and monitor.pool.activeThreadCount() == 0


def test_capture_handles_native_owner_activation_group(host, qtbot, monkeypatch):
    window, backend = host
    settings = ApplicationSettings(window)
    qtbot.addWidget(settings)
    settings.navigation.setCurrentRow(4)
    settings.binding_editor.tabs.setCurrentIndex(3)
    settings.show()
    settings.activateWindow()
    qtbot.waitUntil(settings.isActiveWindow)
    # Windows may report the native owner for an active child dialog group.
    monkeypatch.setattr(QApplication, "activeWindow", lambda: window)
    monitor = window.inputs.gamepad
    monitor.timer.stop()
    monitor.poll()
    press(window, backend, GamepadSample(0x1000, right_trigger=100))
    assert settings.binding_editor.gamepad_page.value() == "RT+A"
    monitor.dispose()
    assert not settings.binding_editor.gamepad_page.subscribed
    settings.reject()


def test_capture_teardown_after_native_monitor_deleted(qtbot):
    from PySide6.QtWidgets import QWidget
    from shiboken6 import delete

    from picer.gamepad_editor import GamepadPage

    monitor = GamepadMonitor(backend=FakeBackend())
    monitor.timer.stop()
    host = QWidget()
    qtbot.addWidget(host)
    host.inputs = SimpleNamespace(gamepad=monitor)
    host.skin_colors = {"accent": "#DFFF45", "text": "#F3F3F0"}
    page = GamepadPage(host)
    qtbot.addWidget(page)
    page.show()
    assert page.subscribed
    monitor.timer.stop()
    delete(monitor)  # Native parent teardown can precede the dialog's Hide event.
    page.hide()
    assert not page.subscribed and not page.connections
