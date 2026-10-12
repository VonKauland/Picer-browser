"""Exercise custom color painting, interaction, bounded layout and save semantics."""

import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QColorDialog

from picer.color_editor import ColorEditor
from picer.color_picker import ColorPicker
from picer.settings import ApplicationSettings
from picer.theme import COLORS
from picer.window import MainWindow


def logical_pixel(image, point):
    scale = image.devicePixelRatio()
    return image.pixelColor(round(point.x() * scale), round(point.y() * scale))


@pytest.fixture
def host(qtbot, tmp_path):
    window = MainWindow(plugin_root=tmp_path / "state", load_examples=False)
    qtbot.addWidget(window)
    window.show()
    yield window
    window.close()


def test_plane_hue_swatches_rgb_and_hex_agree(host, qtbot):
    picker = ColorPicker("#E8FF59", host)
    qtbot.addWidget(picker)
    picker.show()
    qtbot.mouseClick(picker.swatches[3], Qt.MouseButton.LeftButton)
    assert picker.color == QColor("#79B8FF")
    assert picker.hex.text() == "#79B8FF"
    assert [spin.value() for spin in picker.rgb] == [121, 184, 255]
    qtbot.mouseClick(picker.plane, Qt.MouseButton.LeftButton, pos=QPoint(8, 8))
    assert picker.color == QColor("white")
    qtbot.mouseClick(picker.plane, Qt.MouseButton.LeftButton, pos=picker.plane.rect().center())
    qtbot.keyClick(picker.plane, Qt.Key.Key_Right)
    assert picker.plane.saturation > 0.5
    qtbot.mouseClick(picker.hue, Qt.MouseButton.LeftButton, pos=QPoint(8, 14))
    assert picker.hue.value() == 0 and picker.color.red() > picker.color.blue()
    for spin, value in zip(picker.rgb, [10, 20, 30], strict=True):
        spin.setValue(value)
    assert picker.hex.text() == "#0A141E"
    picker.hex.selectAll()
    qtbot.keyClicks(picker.hex, "#91aaff")
    assert picker.color == QColor("#91AAFF")
    assert [spin.value() for spin in picker.rgb] == [145, 170, 255]
    pixels = picker.plane.grab().toImage()
    assert logical_pixel(pixels, QPoint(12, 12)).lightnessF() > 0.9
    assert logical_pixel(pixels, QPoint(12, picker.plane.height() - 12)).lightnessF() < 0.1
    assert picker.grab().toImage().pixelColor(0, 0).alpha() == 0
    assert all(button.size().width() == button.size().height() == 32 for button in picker.swatches)
    pixels = picker.grab().toImage()
    origin = picker.swatches[0].mapTo(picker, QPoint())
    assert logical_pixel(pixels, origin).name().upper() != "#E8FF59"
    assert logical_pixel(pixels, origin + QPoint(16, 16)).name().upper() == "#E8FF59"
    assert not picker.findChildren(QColorDialog)


def test_invalid_hex_blocks_accept_and_grayscale_retains_hue(host, qtbot):
    picker = ColorPicker("#79B8FF", host)
    qtbot.addWidget(picker)
    picker.show()
    hue = picker.hue.value()
    picker.set_color(QColor("black"))
    assert picker.hue.value() == hue
    picker.hex.selectAll()
    qtbot.keyClicks(picker.hex, "#ZZ1234")
    assert not picker.apply.isEnabled() and picker.error.text()
    picker.use_color()
    assert picker.isVisible()
    qtbot.mouseClick(picker.swatches[0], Qt.MouseButton.LeftButton)
    assert picker.apply.isEnabled() and not picker.error.text()
    qtbot.mouseClick(picker.apply, Qt.MouseButton.LeftButton)
    assert picker.selected_value == "#E8FF59" and picker.result() == picker.DialogCode.Accepted


@pytest.mark.parametrize("choice", ["accept", "cancel", "skin"])
def test_editor_opens_app_picker_and_only_commits_accepted_selection(host, qtbot, choice):
    editor = ColorEditor("#123456", host)
    qtbot.addWidget(editor)
    editor.show()
    captured = []

    def interact():
        picker = QApplication.activeModalWidget()
        captured.append(picker)
        assert isinstance(picker, ColorPicker)
        picker.set_color(QColor("#91AAFF"))
        if choice == "accept":
            picker.use_color()
        elif choice == "skin":
            picker.follow_skin()
        else:
            picker.reject()

    QTimer.singleShot(20, interact)
    qtbot.mouseClick(editor.button, Qt.MouseButton.LeftButton)
    assert captured
    assert editor.value() == {"accept": "#91AAFF", "cancel": "#123456", "skin": ""}[choice]
    assert host.skin_colors["accent"] == COLORS["accent"]


def test_picker_selection_still_requires_application_settings_save(host, qtbot):
    settings = ApplicationSettings(host)
    qtbot.addWidget(settings)
    editor = settings.editors["accent_color"]
    QTimer.singleShot(20, lambda: QApplication.activeModalWidget().set_color(QColor("#91AAFF")))
    QTimer.singleShot(40, lambda: QApplication.activeModalWidget().use_color())
    editor.choose()
    assert editor.value() == "#91AAFF" and host.app_preferences["accent_color"] == ""
    settings.save()
    assert host.skin_colors["accent"] == "#91AAFF"


@pytest.mark.parametrize("size,font", [((440, 400), 13), ((500, 590), 13), ((500, 590), 18)])
def test_compact_picker_keeps_actions_visible_without_horizontal_scroll(host, qtbot, size, font):
    picker = ColorPicker("#E8FF59", host)
    qtbot.addWidget(picker)
    custom = picker.font()
    custom.setPixelSize(font)
    picker.setFont(custom)
    picker.setStyleSheet(f"QWidget {{ font-size: {font}px; }}")
    picker.resize(*size)
    picker.show()
    qtbot.wait(30)
    for button in (picker.follow, picker.cancel, picker.apply):
        assert picker.rect().contains(button.mapTo(picker, button.rect().topLeft()))
        assert picker.rect().contains(button.mapTo(picker, button.rect().bottomRight()))
    from PySide6.QtWidgets import QScrollArea

    assert picker.findChild(QScrollArea).horizontalScrollBar().maximum() == 0
