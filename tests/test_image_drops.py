"""Send complete Qt drag sequences to the real image canvas, not its parent."""

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QImage
from PySide6.QtWidgets import QApplication

from picer.window import MainWindow


@pytest.fixture
def host(qtbot, tmp_path):
    window = MainWindow(plugin_root=tmp_path / "state", load_examples=False)
    qtbot.addWidget(window)
    window.show()
    yield window
    window.close()


def drag_sequence(target, urls):
    mime = QMimeData()
    mime.setUrls(urls)
    actions = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction
    button, modifier = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    events = (
        QDragEnterEvent(QPoint(20, 20), actions, mime, button, modifier),
        QDragMoveEvent(QPoint(30, 30), actions, mime, button, modifier),
        QDropEvent(QPointF(30, 30), actions, mime, button, modifier),
    )
    for event in events:
        QApplication.sendEvent(target, event)
    return events


def make_image(path, color):
    image = QImage(80, 60, QImage.Format.Format_RGB32)
    image.fill(color)
    assert image.save(str(path))
    return path


@pytest.mark.parametrize("state", ["empty", "opened", "fullscreen", "chrome", "view"])
def test_drop_opens_on_canvas_and_retains_source(host, tmp_path, qtbot, state):
    previous = make_image(tmp_path / "previous.jpg", Qt.GlobalColor.red)
    path = make_image(tmp_path / "图片 空格.PNG", Qt.GlobalColor.blue)
    before = path.read_bytes()
    if state != "empty":
        host.open_image(previous)
    if state == "fullscreen":
        host.fullscreen_action.trigger()
    target = {"chrome": host, "view": host.view}.get(state, host.view.viewport())
    events = drag_sequence(target, [QUrl.fromLocalFile(str(path))])
    assert all(event.isAccepted() for event in events)
    assert all(event.dropAction() == Qt.DropAction.CopyAction for event in events)
    qtbot.waitUntil(lambda: host.current_path == path)
    assert host.view.image_item.pixmap().toImage().pixelColor(10, 10).blue() == 255
    assert path.read_bytes() == before


@pytest.mark.parametrize("url", ["https://example.com/photo.png", "file:///missing.txt"])
def test_non_image_or_remote_drops_do_not_open_or_warn(host, url, monkeypatch):
    warnings = []
    monkeypatch.setattr("picer.drops.QMessageBox.warning", lambda *args: warnings.append(args))
    events = drag_sequence(host.view.viewport(), [QUrl(url)])
    assert not events[0].isAccepted() and not events[1].isAccepted()
    assert host.current_path is None and not warnings


def test_corrupt_drop_preserves_image_and_can_skip_to_valid_candidate(host, tmp_path, monkeypatch):
    good = make_image(tmp_path / "good.png", Qt.GlobalColor.blue)
    host.open_image(good)
    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"invalid pixels")
    warnings = []
    monkeypatch.setattr("picer.drops.QMessageBox.warning", lambda *args: warnings.append(args))
    drag_sequence(host.view.viewport(), [QUrl.fromLocalFile(str(corrupt))])
    assert len(warnings) == 1 and host.current_path == good
    other = make_image(tmp_path / "other.jpg", Qt.GlobalColor.red)
    events = drag_sequence(
        host.view.viewport(), [QUrl.fromLocalFile(str(corrupt)), QUrl.fromLocalFile(str(other))]
    )
    assert all(event.isAccepted() for event in events)
    assert host.current_path == other and len(warnings) == 1


@pytest.mark.parametrize("extension", ["gif", "webp"])
def test_animated_drop_uses_existing_background_loader(host, tmp_path, qtbot, extension):
    from picer.smoke_samples import make_animation

    path = tmp_path / f"motion.{extension}"
    make_animation(path)
    assert all(
        event.isAccepted()
        for event in drag_sequence(host.view.viewport(), [QUrl.fromLocalFile(str(path))])
    )
    qtbot.waitUntil(lambda: host.current_path == path and host.animation.state.active)
