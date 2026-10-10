"""Exercise image decoding, folder browsing and zoom through real Qt widgets."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from picer.window import MainWindow


@pytest.fixture
def images(tmp_path, qapp):
    image = QImage(120, 80, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.blue)
    paths = [tmp_path / "a.png", tmp_path / "b.jpg"]
    for path in paths:
        assert image.save(str(path))
    return paths


@pytest.fixture
def window(qtbot, tmp_path):
    window = MainWindow(load_examples=False, plugin_root=tmp_path)
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
    assert window.title_bar.caption.text() == images[0].name
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
    assert "无法打开" in window.last_error


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
        "picer.window.QFileDialog.getOpenFileName", lambda *args: (str(images[0]), "")
    )
    window.open_action.trigger()
    assert window.current_path == images[0]


def test_rotation_does_not_modify_file(window, images):
    before = images[0].read_bytes()
    window.open_image(images[0])
    window.rotate_action.trigger()
    assert window.view.image_item.pixmap().width() == 80
    assert window.view.image_item.pixmap().height() == 120
    assert images[0].read_bytes() == before


def test_single_title_row_and_centered_filename(window, images):
    from PySide6.QtWidgets import QStatusBar, QToolBar

    window.open_image(images[0])
    assert not window.findChildren(QStatusBar)
    assert not window.findChildren(QToolBar)
    assert [a.text() for a in window.title_bar.menu.actions()] == [
        "文件",
        "编辑",
        "视图",
        "插件",
        "帮助",
    ]
    assert abs(window.title_bar.caption.geometry().center().x() - window.title_bar.width() / 2) <= 1


def test_fullscreen_restore(window):
    window.fullscreen_action.trigger()
    assert window.isFullScreen()
    window.exit_fullscreen()
    assert not window.isFullScreen()


def test_copy_path(window, images, qapp):
    window.open_image(images[0])
    window.copy_action.trigger()
    assert qapp.clipboard().text() == str(images[0])


def test_equal_colored_window_controls_and_maximize_restore(window, qtbot):
    controls = window.title_bar.control_buttons
    assert all(button.width() == button.height() == 32 for button in controls.values())
    assert controls["minimize"].x() < controls["maximize"].x() < controls["close"].x()
    for button in controls.values():
        pixels = button.grab().toImage()
        color = button.COLORS[button.objectName()].lower()
        assert any(
            pixels.pixelColor(x, y).name() == color
            for x in range(pixels.width())
            for y in range(pixels.height())
        )
    qtbot.mouseClick(controls["maximize"], Qt.MouseButton.LeftButton)
    assert window.isMaximized()
    qtbot.mouseClick(controls["maximize"], Qt.MouseButton.LeftButton)
    assert not window.isMaximized()
