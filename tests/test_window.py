"""Exercise image decoding, folder browsing and zoom through real Qt widgets."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from windows_tool.window import MainWindow


@pytest.fixture
def images(tmp_path, qapp):
    image = QImage(120, 80, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.blue)
    paths = [tmp_path / "a.png", tmp_path / "b.jpg"]
    for path in paths:
        assert image.save(str(path))
    return paths


@pytest.fixture
def window(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    return window


def test_initial_window(window):
    assert window.isVisible()
    assert window.current_path is None
    assert not window.next_action.isEnabled()
    assert not window.zoom_in_action.isEnabled()


def test_open_image(window, images):
    assert window.open_image(images[0])
    assert window.current_path == images[0]
    assert window.view.image_item.pixmap().width() == 120
    assert "120 × 80" in window.statusBar().currentMessage()
    assert window.next_action.isEnabled()


def test_navigation_wraps(window, images):
    window.open_image(images[0])
    window.next_action.trigger()
    assert window.current_path == images[1]
    window.next_action.trigger()
    assert window.current_path == images[0]
    window.previous_action.trigger()
    assert window.current_path == images[1]


def test_invalid_image_preserves_current(window, images):
    window.open_image(images[0])
    assert not window.open_image(images[0].parent / "missing.png")
    assert window.current_path == images[0]
    assert window.view.image_item.pixmap().width() == 120
    assert "无法打开" in window.statusBar().currentMessage()


def test_navigation_skips_corrupt_image(window, images):
    (images[0].parent / "aa.png").write_bytes(b"not an image")
    window.open_image(images[0])
    window.next_action.trigger()
    assert window.current_path == images[1]


def test_zoom_and_fit(window, images):
    window.open_image(images[0])
    window.actual_action.trigger()
    assert window.view.transform().m11() == 1
    window.zoom_in_action.trigger()
    assert window.view.transform().m11() == pytest.approx(1.25)
    window.zoom_out_action.trigger()
    assert window.view.transform().m11() == pytest.approx(1)
    window.fit_action.trigger()
    assert window.view.fit_mode


def test_file_dialog(window, images, monkeypatch):
    monkeypatch.setattr(
        "windows_tool.window.QFileDialog.getOpenFileName", lambda *args: (str(images[0]), "")
    )
    window.open_action.trigger()
    assert window.current_path == images[0]
