"""Real custom About surface, acrostic, accent artwork and modal close routing."""

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QLabel

from picer import __version__
from picer.about import POEM, PROJECT_URL, AboutDialog, PixelSurface
from picer.window import MainWindow


@pytest.fixture
def host(qtbot, tmp_path):
    window = MainWindow(load_examples=False, plugin_root=tmp_path / "state")
    qtbot.addWidget(window)
    window.show()
    yield window
    window.close()


@pytest.mark.parametrize("accent", ["#E8FF59", "#FF6688"])
def test_about_has_clear_corners_accent_pixels_and_exact_poem(host, qtbot, accent):
    host.app_preferences["accent_color"] = accent
    host.apply_host_style()
    dialog = AboutDialog(host)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(30)
    assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert dialog.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert dialog.close_button.size().toTuple() == (32, 32)
    assert not dialog.close_button.icon().isNull()
    assert dialog.name.text() == "揽映"
    assert __version__ in dialog.version.text()
    assert dialog.poem.accessibleName() == POEM
    assert [len(line.rstrip("，。")) for line in POEM.splitlines()] == [5, 5]
    assert "以插件为核心" not in "".join(label.text() for label in dialog.findChildren(QLabel))
    assert not dialog.artwork.pixmap().isNull()
    image = dialog.grab().toImage()
    ratio = image.devicePixelRatio()
    for x, y in (
        (0, 0),
        (dialog.width() - 1, 0),
        (0, dialog.height() - 1),
        (dialog.width() - 1, dialog.height() - 1),
    ):
        assert image.pixelColor(round(x * ratio), round(y * ratio)).alpha() == 0
    # The unobstructed right-edge pixels should blend toward the chosen accent.
    base = QColor(host.skin_colors["title"])
    colors = [
        image.pixelColor(x, y)
        for y in range(round(90 * ratio), round(230 * ratio))
        for x in range(round(540 * ratio), round(590 * ratio))
    ]
    assert any(c.red() > base.red() + 10 and c != base for c in colors)
    assert f"color:{accent}" in dialog.poem.text()
    dialog.done_button.click()
    assert not dialog.isVisible()


@pytest.mark.parametrize("size", [(560, 340), (600, 360)])
def test_about_layout_and_link_at_larger_font(host, qtbot, monkeypatch, size):
    dialog = AboutDialog(host)
    qtbot.addWidget(dialog)
    dialog.setStyleSheet("QWidget { font-size: 18px; }")
    dialog.resize(*size)
    dialog.show()
    qtbot.wait(30)
    for widget in (
        dialog.artwork,
        dialog.version,
        dialog.poem,
        dialog.done_button,
        dialog.close_button,
    ):
        assert dialog.rect().contains(widget.mapTo(dialog, widget.rect().topLeft()))
        assert dialog.rect().contains(widget.mapTo(dialog, widget.rect().bottomRight()))
    urls = []
    monkeypatch.setattr(
        "picer.about.QDesktopServices.openUrl", lambda url: urls.append(url) or True
    )
    dialog.project_button.click()
    assert urls[0].toString() == PROJECT_URL
    dialog.close_button.click()
    assert not dialog.isVisible()


def test_help_about_opens_custom_dialog_above_settings_and_closes(host):
    settings = host.show_settings()
    opened = []

    def inspect_and_close():
        dialog = QApplication.activeModalWidget()
        try:
            assert isinstance(dialog, AboutDialog)
            assert dialog.parentWidget() is settings
            assert dialog.findChild(PixelSurface) is not None
            opened.append(True)
        finally:
            if dialog:
                dialog.reject()

    QTimer.singleShot(50, inspect_and_close)
    host.show_about()
    assert opened and settings.isVisible()
    settings.reject()
