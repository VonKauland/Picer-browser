"""PSD merged-only reads, consistent panel geometry and native file drag contracts."""

from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QDrag, QMouseEvent
from PySide6.QtWidgets import QApplication, QTabBar

from picer.imaging import read_image, supported_suffixes
from picer.metadata import inspect_image
from picer.panels import PANEL_BOTTOM_GAP
from picer.plugins.tasks import TaskCancelled, TaskToken
from picer.smoke_samples import make_psd
from picer.window import MainWindow


@pytest.mark.parametrize("depth", [8, 16, 32])
@pytest.mark.parametrize("compression", [0, 1, 2, 3])
def test_psd_merged_pixels_and_no_layer_metadata(tmp_path, qapp, depth, compression):
    path = make_psd(tmp_path / "preview.psd", depth=depth, compression=compression)
    image = read_image(path)
    assert image.width() == 40 and image.height() == 24
    assert image.pixelColor(0, 0).red() == pytest.approx(90, abs=1)
    assert image.pixelColor(15, 9).blue() == pytest.approx(215, abs=1)
    assert read_image(path, edge=20).width() == 20
    info = inspect_image(path)
    assert info["dimensions"]["位深"] == str(depth)
    assert "图层" not in str(info) and not info["warnings"]
    assert ".psd" in supported_suffixes()


def test_psd_skips_layer_area_and_handles_cancel_and_damage(tmp_path, qapp):
    path = make_psd(tmp_path / "large.psd", layer_bytes=32 * 1048576, compression=3)
    assert read_image(path, edge=20).width() == 20
    token = TaskToken()
    token.cancel()
    with pytest.raises(TaskCancelled):
        read_image(path, token=token)
    data = path.read_bytes()[:26]
    path.write_bytes(data)
    with pytest.raises(ValueError):
        read_image(path)
    assert inspect_image(path)["warnings"]


@pytest.fixture
def host(qtbot, tmp_path):
    window = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(window)
    window.show()
    yield window
    window.close()


@pytest.mark.parametrize("state", ["normal", "maximized", "fullscreen"])
def test_uniform_gap_with_stacks_and_autohide(host, qtbot, state):
    host.plugins.enable("example.editor")
    host.plugins.enable("example.images")
    if state == "maximized":
        host.showMaximized()
    elif state == "fullscreen":
        host.enter_fullscreen()
    qtbot.wait(70)
    controllers = host.panel_hovers.controllers
    for key in ("example.files", "example.info", "example.editor", "example.images"):
        controller = controllers[key]
        controller.pin()
        controller.dock.raise_()
        qtbot.wait(20)
        assert host.height() - 1 - controller.dock.geometry().bottom() == PANEL_BOTTOM_GAP
        controller.dock.close()
        controller.reveal()
        qtbot.waitUntil(lambda controller=controller: controller.progress == 1)
        assert host.height() - 1 - controller.popup.geometry().bottom() == PANEL_BOTTOM_GAP
        controller.pin()
    progress = controllers["example.progress"]
    progress.pin()
    assert host.height() - 1 - progress.dock.geometry().bottom() == PANEL_BOTTOM_GAP
    assert all(
        bar.sizeHint().height() == 0 for bar in host.findChildren(QTabBar) if bar.parent() is host
    )


def perform_drag(qtbot, view, index):
    view.scrollTo(index)
    rect = view.visualRect(index)
    point = rect.center()
    qtbot.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    target = QPointF(point.x() + QApplication.startDragDistance() + 5, point.y())
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        target,
        QPointF(view.viewport().mapToGlobal(target.toPoint())),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(view.viewport(), event)
    qtbot.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=point)


def test_both_browser_views_and_manager_export_only_image_files(host, qtbot, tmp_path, monkeypatch):
    folder = tmp_path / "相册 with spaces"
    folder.mkdir()
    photo = folder / "照片.png"
    Image.new("RGB", (40, 24)).save(photo)
    other = folder / "another.jpg"
    Image.new("RGB", (40, 24)).save(other)
    child = folder / "folder.png"
    child.mkdir()
    video = folder / "movie.mp4"
    video.write_bytes(b"not decoded here")
    assert host.open_image(photo)
    qtbot.waitUntil(lambda: host.current_path == photo)
    files = host.plugins.records["example.files"].instance
    files.context.set_setting("home", str(folder))
    files.apply_settings()
    qtbot.waitUntil(lambda: files.model.index(str(other)).isValid())
    calls = []

    def export(drag, actions, default):
        mime = drag.mimeData()
        assert not mime.hasImage()  # Original file URLs, never bitmap/temp-file export.
        assert actions == default == Qt.DropAction.CopyAction
        calls.append([Path(url.toLocalFile()) for url in mime.urls()])
        assert (
            bytes(mime.data('application/x-qt-windows-mime;value="Preferred DropEffect"'))
            == b"\x01\0\0\0"
        )
        return Qt.DropAction.CopyAction

    monkeypatch.setattr(QDrag, "exec", export)
    for index, view in enumerate((files.tree, files.tiles)):
        files.views.setCurrentIndex(index)
        qtbot.wait(30)
        perform_drag(qtbot, view, files.model.index(str(other)))
        assert calls[-1] == [other]
        count = len(calls)
        perform_drag(qtbot, view, files.model.index(str(child)))
        assert len(calls) == count
        assert files.file_drags[index].mime_data(video) is None
    assert host.current_path == photo
    host.plugins.enable("example.images")
    manager = host.plugins.records["example.images"].instance
    qtbot.waitUntil(lambda: manager.model.rowCount() == 2)
    manager.dock.raise_()
    qtbot.wait(30)
    index = manager.model.index(manager.model.positions[str(other)])
    perform_drag(qtbot, manager.grid, index)
    assert calls[-1] == [other]
    assert photo.is_file() and other.is_file() and child.is_dir()
    host.plugins.disable("example.images")
    assert manager.file_drag.mime_data(other) is None
