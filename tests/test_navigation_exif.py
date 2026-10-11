"""Real key repeat, progressive requests, and JPEG/RAW camera metadata tables."""

from threading import Event

import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QCursor, QKeyEvent
from PySide6.QtWidgets import QApplication

from picer.exif import sections
from picer.imaging import read_image
from picer.metadata import inspect_image
from picer.settings import ApplicationSettings
from picer.smoke_samples import make_dng
from picer.window import MainWindow


@pytest.fixture
def host(qtbot, tmp_path):
    window = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(window)
    window.show()
    window.activateWindow()
    yield window
    window.close()


def images(tmp_path, count=8, size=(80, 60)):
    paths = [tmp_path / f"{i}.jpg" for i in range(count)]
    for path in paths:
        Image.new("RGB", size, "red").save(path)
    return paths


def test_held_navigation_obeys_ms_setting_and_stops_on_release(host, qtbot, tmp_path):
    paths = images(tmp_path)
    host.open_image(paths[0])
    dialog = ApplicationSettings(host)
    qtbot.addWidget(dialog)
    assert dialog.editors["key_repeat_ms"].suffix() == " ms"
    dialog.editors["key_repeat_ms"].setValue(200)
    dialog.save()
    host.view.setFocus()
    qtbot.keyPress(host.view, Qt.Key.Key_Right)
    assert host.current_path == paths[1] and not host.loader.rapid
    assert host.navigation_keys.delay.isActive()
    qtbot.wait(120)
    assert host.current_path == paths[1]
    qtbot.waitUntil(lambda: host.current_path == paths[2], timeout=1500)
    repeat = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier, "", True
    )
    QApplication.sendEvent(host.view, repeat)
    assert host.current_path == paths[2]
    qtbot.keyRelease(host.view, Qt.Key.Key_Right)
    assert not host.navigation_keys.timer.isActive() and not host.loader.rapid
    qtbot.wait(250)
    assert host.current_path == paths[2]
    state = host.plugins.root
    host.close()
    restarted = MainWindow(plugin_root=state)
    qtbot.addWidget(restarted)
    assert restarted.app_preferences["key_repeat_ms"] == 200
    restarted.close()


def test_text_edit_and_focus_loss_do_not_keep_navigation_running(host, qtbot, tmp_path):
    host.open_image(images(tmp_path)[0])
    dialog = ApplicationSettings(host)
    qtbot.addWidget(dialog)
    dialog.pages.setCurrentIndex(1)
    dialog.show()
    dialog.activateWindow()
    qtbot.wait(30)
    editor = dialog.editors["accent_color"].text
    editor.setFocus()
    editor.setText("#ABCDEF")
    assert QApplication.focusWidget() is editor
    qtbot.keyClick(editor, Qt.Key.Key_Left)
    assert not host.loader.rapid and host.current_path.name == "0.jpg"
    dialog.close()
    host.activateWindow()
    host.view.setFocus()
    qtbot.keyPress(host.view, Qt.Key.Key_Right)
    QApplication.sendEvent(host, QEvent(QEvent.Type.WindowDeactivate))
    assert not host.navigation_keys.timer.isActive() and not host.loader.rapid


def test_rapid_large_images_refine_only_after_release(host, qtbot, tmp_path):
    path = images(tmp_path, 1, (4200, 2800))[0]
    host.loader.set_rapid(True)
    host.open_image(path)
    qtbot.waitUntil(lambda: host.current_path == path)
    assert host.view.image_item.pixmap().width() == 960
    qtbot.wait(240)
    assert host.view.image_item.pixmap().width() == 960
    host.loader.set_rapid(False)
    qtbot.waitUntil(lambda: host.view.image_item.pixmap().width() == 4200)
    host.loader.set_rapid(True)
    host.open_image(path)
    assert host.view.image_item.pixmap().width() == 960
    host.loader.set_rapid(False)


def test_current_preview_is_not_blocked_by_neighbour_prefetch(host, qtbot, tmp_path, monkeypatch):
    paths = images(tmp_path, 4, (3200, 2400))
    started, release = Event(), Event()
    original = read_image

    def slow(path, **options):
        if path == paths[1]:
            started.set()
            assert release.wait(3)
        return original(path, **options)

    host.open_image(paths[0])
    qtbot.waitUntil(lambda: host.current_path == paths[0])
    host.loader.prefetch_timer.stop()
    host.loader.refine.stop()
    monkeypatch.setattr("picer.loading.read_image", slow)
    host.loader.prefetch()
    qtbot.waitUntil(started.is_set)
    try:
        host.open_image(paths[3])
        qtbot.waitUntil(lambda: host.current_path == paths[3])
        assert not release.is_set()
    finally:
        release.set()


def test_ring_rises_with_panel_and_hover_names_current_image(host, qtbot, tmp_path):
    host.open_image(images(tmp_path, 4)[2])
    controller = host.panel_hovers.controllers["example.progress"]
    controller.dock.close()
    host.panel_hovers.layout_strips()
    bottom = controller.strip.y()
    assert "3/4" in controller.strip.toolTip()
    controller.reveal()
    QCursor.setPos(host.mapToGlobal(controller.bounds().center()))
    controller.animation.setCurrentTime(200)
    assert controller.strip.y() < bottom
    controller.animation.setCurrentTime(controller.OPEN_MS)
    assert controller.strip.geometry().bottom() < controller.popup.geometry().top()
    controller.collapse()
    controller.animation.setCurrentTime(controller.CLOSE_MS)
    assert controller.strip.y() == bottom


def camera_exif():
    exif = Image.Exif()
    exif[271], exif[272], exif[315] = "Picer Camera", "Model X", "Photographer"
    exif[34665] = {
        42035: "Lens Maker",
        42036: "24-70 mm",
        33437: IFDRational(28, 10),
        33434: IFDRational(1, 125),
        34855: 200,
        37386: IFDRational(50, 1),
        41989: 75,
        36867: "2026:10:01 20:43:00",
        37385: 9,
        41987: 0,
        36864: b"0231",
    }
    return exif


def test_jpeg_exif_tables_expand_upwards_and_wrap_at_minimum_width(host, qtbot, tmp_path):
    path = tmp_path / "camera.jpg"
    Image.new("RGB", (80, 60)).save(path, exif=camera_exif())
    data = inspect_image(path)
    basic = data["exif_sections"]["基础信息"]
    assert basic["相机型号"] == "Model X"
    assert basic["镜头制造商"] == "Lens Maker" and basic["镜头型号"] == "24-70 mm"
    assert basic["光圈"] == "f/2.8" and basic["曝光时间"] == "1/125 s"
    assert basic["焦距"] == "50 mm" and basic["35mm 焦距"] == "75 mm"
    host.open_image(path)
    plugin = host.plugins.records["example.info"].instance
    qtbot.waitUntil(lambda: plugin.metadata is not None)
    view = plugin.exif_view
    assert not view.expanded and view.details.isHidden()
    old_top = plugin.exif_box.mapTo(host, plugin.exif_box.rect().topLeft()).y()
    qtbot.mouseClick(view.button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: view.fraction == 1)
    assert plugin.exif_box.mapTo(host, plugin.exif_box.rect().topLeft()).y() < old_top
    assert "Photographer" in view.text() and "2.31" in view.text()
    controller = host.panel_hovers.controllers["example.info"]
    controller.resize_extent(220)
    qtbot.wait(80)
    assert view.scroll.horizontalScrollBar().maximum() == 0
    assert view.content.width() <= view.scroll.viewport().width()
    qtbot.mouseClick(view.button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: view.fraction == 0)
    assert view.details.isHidden()


def test_raw_exif_survives_preview_decode_failure_and_reaches_panel(
    host, qtbot, tmp_path, monkeypatch
):
    path = tmp_path / "camera.dng"
    make_dng(path)

    def fail(*args, **kwargs):
        raise ValueError("preview failed")

    with monkeypatch.context() as patch:
        patch.setattr("picer.metadata.read_image", fail)
        data = inspect_image(path)
    assert data["exif_sections"]["基础信息"]["相机制造商"] == "Picer RAW Camera"
    assert data["warnings"] and "preview failed" in data["warnings"][0]
    import rawpy

    def unsupported():
        raise rawpy.LibRawFileUnsupportedError("unsupported RAW variant")

    with monkeypatch.context() as patch:
        patch.setattr(rawpy, "RawPy", unsupported)
        rejected = inspect_image(path)
    assert rejected["exif_sections"]["基础信息"]["相机型号"] == "PicerCamera"
    assert any("unsupported RAW variant" in warning for warning in rejected["warnings"])
    host.open_image(path)
    qtbot.waitUntil(lambda: host.current_path == path)
    plugin = host.plugins.records["example.info"].instance
    qtbot.waitUntil(lambda: plugin.metadata is not None)
    assert not plugin.exif_box.isHidden()
    assert "Picer RAW Camera" in plugin.exif_view.text()


def test_pillow_and_exifread_style_fields_share_formatting():
    from exifread.utils import Ratio

    tags = {
        "EXIF ExposureTime": Ratio(1, 30),
        "EXIF FNumber": Ratio(4, 1),
        "GPS GPSLatitude": [Ratio(30, 1), Ratio(15, 1), Ratio(0, 1)],
        "GPS GPSLatitudeRef": "N",
        "EXIF ExifVersion": b"0231",
    }
    result = sections(tags)
    assert result["基础信息"]["光圈"] == "f/4"
    assert result["基础信息"]["曝光时间"] == "1/30 s"
    assert result["详细信息"]["GPS"]["纬度"] == "30.250000° N"
