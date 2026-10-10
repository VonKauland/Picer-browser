"""Verify real ring rendering, dock material and saved accent behavior."""

import pytest
from PIL import Image
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QCursor, QImage, QPainter
from PySide6.QtWidgets import QPushButton

from picer.preferences import read_preferences
from picer.progress_ring import RING_SIZE, paint_progress
from picer.settings import ApplicationSettings
from picer.smoke_samples import make_animation
from picer.theme import COLORS
from picer.ui import colors_for
from picer.window import MainWindow


@pytest.fixture
def window(qtbot, tmp_path):
    host = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(host)
    host.show()
    yield host
    host.close()


def render_ring(fraction, inner, color=COLORS["accent"]):
    image = QImage(RING_SIZE, RING_SIZE, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint_progress(painter, fraction, inner, color)
    painter.end()
    return image


@pytest.mark.parametrize("fraction", [0, 0.25, 0.5, 1])
def test_ring_has_round_tracks_empty_center_and_only_animation_inner(fraction):
    static = render_ring(fraction, None)
    animated = render_ring(fraction, 1)
    assert static.size().width() == 24
    assert static.pixelColor(0, 0).alpha() == static.pixelColor(12, 12).alpha() == 0
    assert static.pixelColor(12, 6).alpha() == 0
    assert animated.pixelColor(12, 6).alpha() > 150
    assert animated.pixelColor(12, 12).alpha() == 0
    assert static.pixelColor(12, 2).alpha() > 150
    if fraction == 1:
        assert static.pixelColor(12, 22).green() > 200
        assert animated.pixelColor(12, 6).blue() > animated.pixelColor(12, 6).red()


def test_ring_follows_hidden_preview_resize_animation_and_cleanup(window, qtbot, tmp_path):
    for i in range(4):
        Image.new("RGB", (80, 60), "blue").save(tmp_path / f"{i}.png")
    assert window.open_image(tmp_path / "1.png")
    progress = window.plugins.records["example.progress"].instance
    controller = window.panel_hovers.controllers["example.progress"]
    controller.dock.close()
    strip = controller.strip
    assert strip.isVisible() and strip.size().width() == strip.size().height() == RING_SIZE
    assert abs(strip.geometry().center().x() - window.rect().center().x()) <= 1
    assert window.height() - 1 - strip.geometry().bottom() == 6
    progress.show_preview()
    qtbot.waitUntil(lambda: progress.expansion == 1)
    qtbot.waitUntil(
        lambda: controller.dock.property("previewGeometry") == progress.preview.geometry()
    )
    assert strip.geometry().right() < progress.preview.geometry().left()
    assert abs(strip.geometry().center().y() - progress.preview.geometry().center().y()) <= 1
    window.resize(1400, 860)
    qtbot.wait(60)
    assert strip.geometry().right() < progress.preview.geometry().left()
    assert strip.geometry().center().y() == progress.preview.geometry().center().y()
    path = tmp_path / "motion.webp"
    make_animation(path)
    assert window.open_image(path)
    qtbot.waitUntil(lambda: window.animation.state.active)
    window.animation.toggle(False)
    window.animation.seek(2)
    qtbot.waitUntil(lambda: window.animation.state.frame == 2)
    pixels = strip.grab().toImage()
    assert pixels.pixelColor(12, 6).blue() > 150
    progress.show_preview()
    qtbot.waitUntil(lambda: not progress.preview.isVisible())
    assert abs(strip.geometry().center().x() - window.rect().center().x()) <= 1
    qtbot.mouseClick(strip, Qt.MouseButton.LeftButton, pos=QPoint(12, 12))
    assert not controller.dock.isHidden() and strip.isHidden()
    window.plugins.disable("example.progress")
    assert "example.progress" not in window.panel_hovers.controllers


def test_progress_morph_returns_to_ring_after_preview_moves_it(window, qtbot, tmp_path):
    for i in range(2):
        Image.new("RGB", (80, 60), "blue").save(tmp_path / f"{i}.png")
    window.open_image(tmp_path / "0.png")
    progress = window.plugins.records["example.progress"].instance
    controller = window.panel_hovers.controllers["example.progress"]
    controller.dock.close()
    controller.reveal()
    controller.animation.setCurrentTime(controller.OPEN_MS)
    QCursor.setPos(window.mapToGlobal(controller.bounds().center()))
    progress.show_preview()
    qtbot.waitUntil(lambda: progress.expansion == 1)
    ring = controller.strip.geometry()
    assert ring.right() < progress.preview.geometry().left()
    resting = window.panel_hovers.progress_ring_rect(controller, resting=True)
    controller.collapse()
    controller.animation.setCurrentTime(controller.CLOSE_MS - 1)
    assert controller.popup.geometry() == resting
    controller.animation.setCurrentTime(controller.CLOSE_MS)
    assert controller.popup is None and progress.preview.isVisible()


def test_fixed_panels_are_solid_and_hidden_reveals_capture_glass(window, qtbot):
    surface = window.plugins.panels["example.files"].widget()
    assert not surface.uses_glass()
    window.glass.capture()
    assert window.glass.image.isNull() and not window.glass.active()
    image = surface.grab().toImage()
    assert image.pixelColor(5, 100) == QColor("#303032")
    controller = window.panel_hovers.controllers["example.files"]
    controller.dock.close()
    controller.reveal()
    assert controller.popup.uses_glass()
    qtbot.waitUntil(lambda: not window.glass.image.isNull())
    controller.pin()
    assert surface.render_backdrop and not surface.uses_glass()
    assert not window.glass.active()
    window.plugins.preferences["ui"]["application"] = {"glass": False}
    window.apply_preferences()
    controller.dock.close()
    controller.reveal()
    assert not controller.popup.uses_glass()


def test_accent_save_cancel_restart_reset_and_skin_isolation(window, qtbot):
    progress = window.plugins.records["example.progress"].instance
    browser = window.plugins.records["example.files"].instance
    original = browser.panel.property("picerPanelOriginalStyle")
    icon = browser.model.files.folders.icons[0].pixmap(32, 32).toImage()
    dialog = ApplicationSettings(window)
    qtbot.addWidget(dialog)
    dialog.editors["accent_color"].setValue("#91aaff")
    assert window.skin_colors["accent"] == COLORS["accent"]
    dialog.reject()
    assert window.app_preferences["accent_color"] == ""
    dialog = ApplicationSettings(window)
    qtbot.addWidget(dialog)
    dialog.editors["accent_color"].setValue("#91aaff")
    dialog.save()
    assert window.app_preferences["accent_color"] == window.skin_colors["accent"] == "#91AAFF"
    assert colors_for(progress.slider)["accent"] == "#91AAFF"
    assert "#91AAFF" in browser.parent_entry.styleSheet()
    assert browser.context.accent_color() == "#91AAFF"
    assert browser.panel.property("picerPanelOriginalStyle") == original
    assert browser.model.files.folders.icons[0].pixmap(32, 32).toImage() == icon
    window.plugins.enable("example.macos")
    assert window.skin_colors["background"] == "#f5f5f7"
    assert window.skin_colors["accent"] == "#91AAFF"
    assert colors_for(progress.slider)["background"] == COLORS["background"]
    state = window.plugins.root
    window.close()
    restarted = MainWindow(plugin_root=state)
    qtbot.addWidget(restarted)
    assert restarted.app_preferences["accent_color"] == "#91AAFF"
    reset = ApplicationSettings(restarted)
    qtbot.addWidget(reset)
    reset.reset()
    reset.save()
    assert restarted.app_preferences["accent_color"] == ""
    assert restarted.skin_colors["accent"] == COLORS["accent"]
    restarted.close()


@pytest.mark.parametrize("value", ["bad", "#123", "#GG0011", 23, [], "red; background: white"])
def test_invalid_stored_accent_uses_default(window, value):
    window.plugins.preferences["ui"]["application"] = {"accent_color": value}
    assert read_preferences(window.plugins)["accent_color"] == ""


def test_invalid_edited_accent_cannot_save_any_preferences(window, qtbot, monkeypatch):
    dialog = ApplicationSettings(window)
    qtbot.addWidget(dialog)
    dialog.editors["accent_color"].text.setText("#xx0011")
    dialog.editors["zoom_step"].setValue(50)
    warnings = []
    monkeypatch.setattr("picer.settings.QMessageBox.warning", lambda *args: warnings.append(args))
    dialog.save()
    assert warnings and window.view.zoom_step == 25
    assert window.app_preferences["accent_color"] == ""


def test_custom_accent_primary_button_remains_readable(window, qtbot):
    window.plugins.preferences["ui"]["application"] = {"accent_color": "#233B77"}
    window.apply_preferences()
    dialog = ApplicationSettings(window)
    qtbot.addWidget(dialog)
    dialog.show()
    button = dialog.findChild(QPushButton, "primaryButton")
    qtbot.wait(20)
    assert button.palette().color(button.foregroundRole()) == QColor("#F3F3F0")
