"""Direct half-star and color persistence, fixed below independently expanding EXIF."""

import pytest
from PIL import Image
from PySide6.QtCore import QPoint, Qt

from picer.window import MainWindow


@pytest.fixture
def info(qtbot, tmp_path):
    host = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(host)
    host.show()
    path = tmp_path / "photo.jpg"
    exif = Image.Exif()
    exif[271], exif[272] = "Camera Maker", "Camera Model"
    Image.new("RGB", (80, 60), "gray").save(path, exif=exif)
    host.open_image(path)
    plugin = host.plugins.records["example.info"].instance
    qtbot.waitUntil(lambda: plugin.metadata is not None)
    yield host, plugin, str(path.resolve())
    host.plugins.shutdown()


def test_all_half_stars_and_explicit_clear(info, qtbot):
    host, plugin, path = info
    for half in range(1, 11):
        qtbot.mouseClick(
            plugin.rating, Qt.MouseButton.LeftButton, pos=QPoint(34 + int((half - 0.5) * 7.5), 17)
        )
        assert plugin.context.get_setting("ratings")[path] == half / 2
    qtbot.mouseClick(plugin.rating, Qt.MouseButton.LeftButton, pos=QPoint(106, 17))
    assert plugin.context.get_setting("ratings")[path] == 0
    host.panel_hovers.controllers["example.info"].resize_extent(220)
    qtbot.wait(30)
    assert plugin.rating.width() <= plugin.panel.width()
    assert plugin.scroll.horizontalScrollBar().maximum() == 0


def test_categories_plain_centers_restore_without_overwriting_ratings(info, qtbot):
    host, plugin, path = info
    qtbot.mouseClick(plugin.rating, Qt.MouseButton.LeftButton, pos=QPoint(82, 17))
    assert plugin.context.get_setting("ratings")[path] == 3.5
    qtbot.mouseClick(plugin.rating, Qt.MouseButton.LeftButton, pos=QPoint(118, 47))
    assert plugin.context.get_setting("color_labels")[path] == "blue"
    image = plugin.rating.grab().toImage()
    assert image.pixelColor(118, 47).name().lower() == "#488fff"
    host.plugins.disable("example.info")
    host.plugins.enable("example.info")
    restored = host.plugins.records["example.info"].instance
    qtbot.waitUntil(lambda: restored.metadata is not None)
    assert restored.rating.value == 3.5 and restored.rating.category == "blue"
    qtbot.mouseClick(restored.rating, Qt.MouseButton.LeftButton, pos=QPoint(118, 47))
    assert path not in restored.context.get_setting("color_labels")
    assert restored.context.get_setting("ratings")[path] == 3.5


def test_footer_stays_at_bottom_with_exif_expanded_and_scrolled(info, qtbot):
    _, plugin, _ = info
    footer = plugin.rating
    bottom = footer.mapTo(plugin.panel, footer.rect().bottomLeft()).y()
    assert bottom == plugin.panel.height() - 1
    qtbot.mouseClick(plugin.exif_view.button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: plugin.exif_view.fraction == 1)
    plugin.scroll.verticalScrollBar().setValue(plugin.scroll.verticalScrollBar().maximum())
    assert footer.mapTo(plugin.panel, footer.rect().bottomLeft()).y() == bottom
    assert plugin.exif_box.geometry().bottom() < footer.geometry().top()
