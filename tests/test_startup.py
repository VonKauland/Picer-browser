"""First paint precedes plugin activation and responsive startup image decoding."""

import subprocess
import sys
from threading import Event, get_ident

import pytest
from PIL import Image
from PySide6.QtCore import QTimer

import picer.loading as loading
from picer.startup import AfterFirstPaint, finish_startup
from picer.window import MainWindow


class PaintedWindow(MainWindow):
    paints = 0

    def paintEvent(self, event):
        super().paintEvent(event)
        self.paints += 1


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    result = PaintedWindow(plugin_root=tmp_path / "state", load_examples=False, defer_plugins=True)
    monkeypatch.setattr(result.updates, "start", lambda: None)
    qtbot.addWidget(result)
    yield result
    result.close()


def test_first_paint_before_plugins_and_small_image_decode_stays_responsive(
    window, qtbot, tmp_path, monkeypatch
):
    # Below the small-image threshold, but wider than the 1600px preview lane:
    # startup must retain full pixels and must not decode again for refinement.
    image = tmp_path / "small.png"
    Image.new("RGB", (2000, 600), "red").save(image)
    entered, release = Event(), Event()
    main_thread = get_ident()
    calls, activated, ticks = [], [], []
    decode = loading.read_image
    discover = window.plugins.discover

    def read(path, **kwargs):
        calls.append(path)
        assert get_ident() != main_thread
        entered.set()
        assert release.wait(5)
        return decode(path, **kwargs)

    def discovery():
        assert window.isVisible() and window.paints > 0
        activated.append(True)
        discover()

    monkeypatch.setattr(loading, "read_image", read)
    monkeypatch.setattr(window.plugins, "discover", discovery)
    window.plugins.preferences["ui"]["application"] = {"browse_folder": False}
    AfterFirstPaint(window, lambda: finish_startup(window, image))
    assert not window.plugins._startup_loaded
    assert not activated and not calls
    window.restore_startup(restore_image=False)
    window.show()
    pulse = QTimer(window)
    pulse.setInterval(5)
    pulse.timeout.connect(lambda: ticks.append(True))
    try:
        qtbot.waitUntil(entered.is_set)
        assert window.paints > 0 and activated == [True]
        assert window.current_path is None
        pulse.start()
        qtbot.waitUntil(lambda: len(ticks) >= 3)
        window.update()
        qtbot.waitUntil(lambda: window.paints > 1)
    finally:
        release.set()
        pulse.stop()
    qtbot.waitUntil(lambda: window.current_path == image)
    assert window.view.image_item.pixmap().width() == 2000
    assert not window.loader.refine.isActive()
    assert calls == [image]
    window.plugins.load_startup_plugins()
    assert activated == [True]


@pytest.mark.parametrize("explicit", [False, True])
def test_startup_restores_last_image_but_explicit_file_takes_priority(
    window, qtbot, tmp_path, explicit
):
    last, selected = tmp_path / "last.png", tmp_path / "selected.png"
    for path in (last, selected):
        Image.new("RGB", (80, 60), "blue").save(path)
    window.plugins.preferences["ui"].update(
        last_image=str(last), application={"start": "last", "browse_folder": False}
    )
    window.apply_preferences()
    window.restore_startup(restore_image=False)
    assert window.current_path is None
    AfterFirstPaint(window, lambda: finish_startup(window, selected if explicit else None))
    window.show()
    qtbot.waitUntil(lambda: window.current_path == (selected if explicit else last))
    assert window.paints > 0


def test_close_before_first_paint_cancels_deferred_startup(window, qtbot):
    AfterFirstPaint(window, lambda: finish_startup(window))
    window.close()
    qtbot.wait(20)
    assert window.plugins._closed
    assert not window.plugins._startup_loaded


def test_deferred_safe_mode_never_discovers_or_seeds_plugins(qtbot, tmp_path, monkeypatch):
    window = PaintedWindow(plugin_root=tmp_path / "safe", load_external=False, defer_plugins=True)
    qtbot.addWidget(window)

    def unexpected():
        pytest.fail("Safe mode must not discover external plugins")

    monkeypatch.setattr(window.plugins, "discover", unexpected)
    monkeypatch.setattr(window.updates, "start", lambda: None)
    AfterFirstPaint(window, lambda: finish_startup(window))
    window.show()
    qtbot.waitUntil(lambda: window.plugins._startup_loaded)
    assert set(window.plugins.records) == {"picer.transforms", "picer.mirror", "picer.grayscale"}
    assert all(record.state == "enabled" for record in window.plugins.records.values())
    window.close()


def test_deferred_shipped_panels_receive_initial_image(qtbot, tmp_path, monkeypatch):
    image = tmp_path / "bundled.png"
    Image.new("RGB", (80, 60), "blue").save(image)
    window = PaintedWindow(plugin_root=tmp_path / "bundled-state", defer_plugins=True)
    qtbot.addWidget(window)
    monkeypatch.setattr(window.updates, "start", lambda: None)
    window.plugins.preferences["ui"]["application"] = {"accent_color": "#FFA591"}
    window.apply_preferences()
    AfterFirstPaint(window, lambda: finish_startup(window, image))
    window.show()
    try:
        qtbot.waitUntil(lambda: window.current_path == image)
        info = window.plugins.records["example.info"].instance
        qtbot.waitUntil(lambda: info.metadata is not None)
        assert info.metadata["dimensions"]["宽度"] == "80"
        assert window.skin_colors["accent"] == "#FFA591"
        for plugin in ("example.files", "example.info", "example.progress"):
            assert window.plugins.records[plugin].state == "enabled"
            assert plugin in window.plugins.panels
        for plugin in ("example.images", "example.editor"):
            assert window.plugins.records[plugin].state == "disabled"
        assert window.paints > 0
    finally:
        window.close()


def test_real_entrypoint_paints_before_opening_cli_image(tmp_path):
    image = tmp_path / "cli.png"
    Image.new("RGB", (80, 60), "blue").save(image)
    program = """
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from picer import app
from picer.window import MainWindow

class Window(MainWindow):
    painted = False
    opened = False

    def __init__(self, **kwargs):
        kwargs['load_examples'] = False
        super().__init__(**kwargs)
        self.updates.start = lambda: None

    def paintEvent(self, event):
        super().paintEvent(event)
        self.painted = True

    def open_image(self, path, **kwargs):
        assert self.painted and self.isVisible()
        assert self.plugins._startup_loaded
        assert kwargs['asynchronous'] is True
        self.opened = True
        accepted = super().open_image(path, **kwargs)
        def finished():
            if self.current_path == path:
                QApplication.instance().exit(0)
            else:
                QTimer.singleShot(10, finished)
        QTimer.singleShot(0, finished)
        QTimer.singleShot(10000, lambda: QApplication.instance().exit(3))
        return accepted

app.MainWindow = Window
sys.argv = ['Picer', '--data-dir', sys.argv[1], sys.argv[2]]
raise SystemExit(app.main())
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path / "cli-state"), str(image)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
