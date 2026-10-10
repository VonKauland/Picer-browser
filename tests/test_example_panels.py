"""Install real example ZIPs and exercise their models, metadata and animations."""

import zipfile
from importlib import import_module
from pathlib import Path, PureWindowsPath

import pytest
from PIL import Image
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QIcon, QPixmap, QWheelEvent
from PySide6.QtWidgets import QApplication, QDockWidget, QMenu

from picer.metadata import inspect_image
from picer.panels import DOCK_AREAS, GlassSurface
from picer.plugins.settings import SettingsDialog
from picer.window import MainWindow

ROOT = Path(__file__).parents[1]


def example(tmp_path, directory):
    archive = tmp_path / f"{directory}.zip"
    with zipfile.ZipFile(archive, "w") as file:
        for source in (ROOT / "examples" / directory).rglob("*"):
            if source.is_file() and "__pycache__" not in source.parts:
                file.write(source, str(source.relative_to(ROOT / "examples" / directory)))
    return archive


@pytest.fixture
def window(qtbot, tmp_path):
    window = MainWindow(load_examples=False, plugin_root=tmp_path / "state")
    qtbot.addWidget(window)
    window.show()
    yield window
    window.plugins.shutdown()


def enable(window, tmp_path, directory):
    plugin_id = window.plugins.install(example(tmp_path, directory))
    window.plugins.enable(plugin_id)
    return window.plugins.records[plugin_id].instance


@pytest.fixture
def pictures(tmp_path):
    folder = tmp_path / "照片"
    folder.mkdir()
    exif = Image.Exif()
    exif[271] = "Test Camera"
    exif[272] = "Camera 2026"
    for name, color in (("1.jpg", "red"), ("2.jpg", "green"), ("3.png", "blue")):
        image = Image.new("RGB", (80, 60), color)
        if name.endswith("jpg"):
            image.save(folder / name, exif=exif)
        else:
            image.save(folder / name)
    (folder / "nested").mkdir()
    Image.new("RGB", (32, 24)).save(folder / "nested" / "child.png")
    return folder


def test_file_browser_home_tree_sort_icons_and_open(window, tmp_path, qtbot, pictures):
    plugin = enable(window, tmp_path, "file_browser")
    context = window.plugins.records["example.files"].context
    context.set_setting("home", str(pictures))
    context.set_setting("icon_size", 48)
    context.set_setting("sort", "modified")
    context.set_setting("descending", True)
    plugin.apply_settings()
    assert window.dockWidgetArea(plugin.dock) == Qt.DockWidgetArea.LeftDockWidgetArea
    assert plugin.tree.iconSize().width() == 48
    assert plugin.tree.header().sortIndicatorSection() == 3
    assert plugin.tree.header().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    qtbot.waitUntil(lambda: plugin.model.index(str(pictures / "1.jpg")).isValid())
    plugin.open_entry(plugin.model.index(str(pictures / "1.jpg")))
    assert window.current_path == (pictures / "1.jpg").resolve()
    plugin.open_folder(str(pictures / "nested"))
    assert plugin.location.text() == str((pictures / "nested").resolve())
    plugin.go_up()
    assert plugin.location.text() == str(pictures.resolve())


def test_settings_apply_atomically_and_restore(window, tmp_path, qtbot, pictures):
    plugin = enable(window, tmp_path, "file_browser")
    dialog = SettingsDialog(window.plugins, "example.files", window)
    qtbot.addWidget(dialog)
    dialog.editors["home"].setText(str(pictures))
    dialog.editors["icon_size"].setValue(40)
    dialog.editors["view"].setCurrentIndex(dialog.editors["view"].findData("tiles"))
    dialog.save()
    assert plugin.location.text() == str(pictures.resolve())
    assert plugin.tree.iconSize().width() == 40
    assert plugin.tiles.iconSize().width() == 80
    assert plugin.views.currentWidget() is plugin.tiles
    root = window.plugins.root
    window.plugins.shutdown()
    restarted = MainWindow(load_examples=False, plugin_root=root)
    qtbot.addWidget(restarted)
    browser = restarted.plugins.records["example.files"].instance
    assert browser.location.text() == str(pictures.resolve())
    assert browser.tree.iconSize().width() == 40
    assert browser.tiles.iconSize().width() == 80
    assert browser.views.currentWidget() is browser.tiles
    restarted.plugins.shutdown()


def test_image_metadata_exif_histogram_and_visibility(window, tmp_path, qtbot, pictures):
    plugin = enable(window, tmp_path, "info_panel")
    window.open_image(pictures / "1.jpg")
    qtbot.waitUntil(lambda: plugin.metadata is not None)
    assert plugin.metadata["dimensions"]["宽度"] == "80"
    assert sum(plugin.histogram.channels[0]) == 80 * 60
    assert "Test Camera" in plugin.exif_text.toPlainText()
    assert not plugin.exif_box.isHidden()
    assert plugin.exif_box.parent() is plugin.panel
    context = window.plugins.records["example.info"].context
    context.set_setting("dimensions", False)
    context.set_setting("histogram", False)
    plugin.apply_settings()
    assert plugin.groups["dimensions"].isHidden()
    assert plugin.groups["histogram"].isHidden()
    assert not plugin.exif_box.isHidden()
    plugin.rating.setCurrentIndex(4)
    assert context.get_setting("ratings")[str((pictures / "1.jpg").resolve())] == 4
    assert Image.open(pictures / "1.jpg").getexif().get(18246) is None
    window.open_image(pictures / "3.png")
    qtbot.waitUntil(lambda: plugin.metadata is not None)
    assert plugin.exif_box.isHidden()


def test_metadata_failure_and_sample_bounds(tmp_path):
    path = tmp_path / "large.png"
    Image.new("RGB", (1600, 1200), "red").save(path)
    data = inspect_image(path)
    assert data["dimensions"]["宽度"] == "1600"
    assert data["sample_size"] == (1024, 768)
    assert len(data["histogram"]) == 3
    path.write_text("broken image")
    data = inspect_image(path)
    assert data["warnings"]
    assert data["exif"] == {}


def test_progress_seek_navigation_rotation_and_slideshow(window, tmp_path, qtbot, pictures):
    plugin = enable(window, tmp_path, "progress_panel")
    window.open_image(pictures / "1.jpg")
    assert plugin.count.text() == "1/3"
    plugin.controls["next"].click()
    assert plugin.count.text() == "2/3"
    plugin.controls["previous"].click()
    assert plugin.count.text() == "1/3"
    plugin.slider.setValue(2)
    assert window.current_path.name == "3.png"
    plugin.controls["rotate"].click()
    assert window.view.image_item.pixmap().width() == 60
    plugin.timer.setInterval(35)
    plugin.controls["slideshow"].click()
    qtbot.waitUntil(lambda: window.current_path.name == "1.jpg")
    plugin.controls["slideshow"].click()
    assert not plugin.timer.isActive()
    window.plugins.disable("example.progress")
    assert not plugin.timer.isActive()


def test_preview_size_count_and_selection(window, tmp_path, qtbot, pictures):
    plugin = enable(window, tmp_path, "progress_panel")
    window.open_image(pictures / "1.jpg")
    context = window.plugins.records["example.progress"].context
    context.set_setting("thumbnail_size", 64)
    context.set_setting("thumbnail_count", 3)
    plugin.show_preview()
    qtbot.waitUntil(lambda: len(plugin.preview.items) == 3)
    assert plugin.preview.thumbnail_size == 64
    assert plugin.preview.width() == plugin.dock.width()
    qtbot.mouseClick(
        plugin.preview,
        Qt.MouseButton.LeftButton,
        pos=plugin.preview.tile_rect(2).center().toPoint(),
    )
    assert window.current_path.name == "3.png"
    assert plugin.preview.isVisible()
    plugin.controls["preview"].click()
    assert not plugin.preview.isVisible()


def test_macos_host_skin_keeps_plugin_styles_and_icons(window, tmp_path, pictures):
    plugin = enable(window, tmp_path, "file_browser")
    style = plugin.panel.styleSheet()
    icon = QIcon(QPixmap(12, 12))
    # External icons are not recolored when assigned to a quick slot.
    enable_id = window.plugins.install(example(tmp_path, "negative_plugin"))
    window.plugins.enable(enable_id)
    external = window.plugins.commands["example.negative:negative"]
    external.setIcon(icon)
    window.components.assign(4, "example.negative:negative")
    cache_key = external.icon().cacheKey()
    skin_id = window.plugins.install(example(tmp_path, "macos_skin"))
    window.plugins.enable(skin_id)
    assert window.chrome_style == "macos"
    assert window.title_bar.controls.parent() is window.title_bar.right
    assert window.title_bar.control_buttons["close"].width() == 32
    assert plugin.panel.styleSheet() == style
    assert external.icon().cacheKey() == cache_key
    assert not plugin.panel.property("picerHost")
    window.plugins.disable(skin_id)
    assert window.title_bar.controls.parent() is window.title_bar.right
    assert window.title_bar.control_buttons["close"].width() == 32


@pytest.mark.parametrize(
    "area",
    [
        Qt.DockWidgetArea.LeftDockWidgetArea,
        Qt.DockWidgetArea.RightDockWidgetArea,
        Qt.DockWidgetArea.BottomDockWidgetArea,
    ],
)
def test_hidden_strip_morph_reverses_and_cleans_up(window, tmp_path, qtbot, area):
    plugin = enable(window, tmp_path, "file_browser")
    window.addDockWidget(area, plugin.dock)
    plugin.dock.close()
    controller = window.panel_hovers.controllers["example.files"]
    assert controller.strip.isVisible()
    assert min(controller.strip.width(), controller.strip.height()) == 5
    controller.reveal()
    qtbot.waitUntil(lambda: controller.progress >= 1, timeout=1500)
    assert plugin.dock.isHidden()
    assert controller.popup is not None
    assert window.plugins.preferences["ui"]["panels"]["example.files"] is False
    controller.collapse()
    qtbot.waitUntil(lambda: controller.popup is None, timeout=1500)
    assert isinstance(plugin.dock.widget(), GlassSurface)
    controller.reveal()
    qtbot.wait(80)
    controller.collapse()
    controller.reveal()  # Mid-transition reversal starts from the current shape.
    qtbot.wait(80)
    window.plugins.disable("example.files")
    assert "example.files" not in window.panel_hovers.controllers
    qtbot.wait(1)
    assert not window.findChildren(QDockWidget)


def test_glass_backdrop_cached_and_fullscreen_hover_restored(window, tmp_path, qtbot, pictures):
    plugin = enable(window, tmp_path, "file_browser")
    window.open_image(pictures / "1.jpg")
    qtbot.waitUntil(lambda: not window.glass.image.isNull())
    assert window.glass.image.size() == window.size()
    signature = window.glass.captured_signature
    window.glass.invalidate()
    assert not window.glass.timer.isActive()
    window.toggle_fullscreen()
    controller = window.panel_hovers.controllers["example.files"]
    assert plugin.dock.isHidden()
    assert controller.strip.isVisible()
    controller.reveal()
    qtbot.wait(80)
    window.exit_fullscreen()
    assert controller.popup is None
    assert not plugin.dock.isHidden()
    assert signature is not None


def test_actual_hover_enter_leave_and_dialog_hold(window, tmp_path, qtbot):
    from PySide6.QtCore import QPoint

    plugin = enable(window, tmp_path, "file_browser")
    plugin.dock.close()
    controller = window.panel_hovers.controllers["example.files"]
    qtbot.mouseMove(controller.strip, QPoint(2, 40))
    qtbot.waitUntil(lambda: controller.popup is not None, timeout=1000)
    qtbot.wait(450)
    dialog = SettingsDialog(window.plugins, "example.files", window)
    qtbot.addWidget(dialog)
    dialog.setModal(True)
    dialog.show()
    qtbot.mouseMove(window, QPoint(window.width() - 60, 90))
    controller.schedule_collapse()
    qtbot.wait(350)
    assert controller.popup is not None
    dialog.reject()
    qtbot.waitUntil(lambda: controller.popup is None, timeout=2000)
    assert plugin.dock.isHidden()
    assert window.plugins.preferences["ui"]["panels"]["example.files"] is False


def test_invalid_settings_schema_and_disabled_settings_removed(window, tmp_path):
    from picer.plugins import PluginError, SettingField

    plugin = enable(window, tmp_path, "file_browser")
    window.plugins.settings_forms.pop("example.files")
    context = window.plugins.records["example.files"].context
    with pytest.raises(PluginError, match="整数设置"):
        context.add_settings((SettingField("size", "Size", "int", True),), lambda: None)
    with pytest.raises(PluginError, match="选择设置"):
        context.add_settings(
            (SettingField("sort", "Sort", "choice", "bad", choices=(("name", "名称"),)),),
            lambda: None,
        )
    context.add_settings(plugin.fields, plugin.apply_settings)
    window.plugins.disable("example.files")
    assert "example.files" not in window.plugins.settings_forms
    with pytest.raises(PluginError, match="停用"):
        context.show_settings()


def drag_to(qtbot, widget, destination, modifier=Qt.KeyboardModifier.NoModifier):
    qtbot.mousePress(widget, Qt.MouseButton.LeftButton, modifier, pos=widget.rect().center())
    qtbot.mouseMove(widget, widget.mapFromGlobal(destination))
    qtbot.mouseRelease(
        widget, Qt.MouseButton.LeftButton, modifier, pos=widget.mapFromGlobal(destination)
    )


@pytest.mark.parametrize("area", [DOCK_AREAS["left"], DOCK_AREAS["right"]])
def test_internal_grip_resizes_without_title_or_separator(window, tmp_path, qtbot, area):
    plugin = enable(window, tmp_path, "file_browser")
    controller = window.panel_hovers.controllers["example.files"]
    controller.move_to(area)
    qtbot.wait(50)
    dock, surface = plugin.dock, plugin.dock.widget()
    assert dock.titleBarWidget().height() == 0
    assert surface.geometry() == dock.rect()
    grip = surface.grip
    if area == DOCK_AREAS["bottom"]:
        assert abs(grip.geometry().center().x() - surface.rect().center().x()) <= 1
        before = dock.height()
        delta = QPoint(0, -55)
    else:
        assert abs(grip.geometry().center().y() - surface.rect().center().y()) <= 1
        before = dock.width()
        delta = QPoint(55 if area == DOCK_AREAS["left"] else -55, 0)
    destination = grip.mapToGlobal(grip.rect().center()) + delta
    drag_to(qtbot, grip, destination)
    qtbot.wait(50)
    after = dock.height() if area == DOCK_AREAS["bottom"] else dock.width()
    assert after >= before + 40
    assert controller.current_extent() == after
    assert window.plugins.preferences["ui"]["panel_layouts"]["example.files"]["area"] == next(
        name for name, value in DOCK_AREAS.items() if value == area
    )
    window.plugins.shutdown()
    restarted = MainWindow(load_examples=False, plugin_root=window.plugins.root)
    qtbot.addWidget(restarted)
    restarted.show()
    qtbot.wait(50)
    restored = restarted.plugins.panels["example.files"]
    assert restarted.dockWidgetArea(restored) == area
    assert (restored.height() if area == DOCK_AREAS["bottom"] else restored.width()) == after
    restarted.plugins.shutdown()


@pytest.mark.parametrize("settle_ms", [60, 500])
def test_click_hidden_strip_pins_during_or_after_animation(window, tmp_path, qtbot, settle_ms):
    plugin = enable(window, tmp_path, "file_browser")
    plugin.dock.close()
    controller = window.panel_hovers.controllers["example.files"]
    surface = plugin.dock.widget()
    controller.reveal()
    qtbot.wait(settle_ms)
    qtbot.mouseClick(
        controller.strip, Qt.MouseButton.LeftButton, pos=controller.strip.rect().center()
    )
    assert not plugin.dock.isHidden()
    assert not controller.strip.isVisible()
    assert controller.popup is None
    assert plugin.dock.widget() is surface
    assert surface.parent() is plugin.dock and surface.render_backdrop
    assert window.plugins.preferences["ui"]["panels"]["example.files"] is True
    qtbot.wait(500)
    assert not plugin.dock.isHidden()  # No pending collapse may undo a pin.


@pytest.mark.parametrize("area", ["right", "left"])
def test_hidden_strip_drag_relocates_and_persists(window, tmp_path, qtbot, area):
    plugin = enable(window, tmp_path, "file_browser")
    controller = window.panel_hovers.controllers["example.files"]
    controller.move_to(DOCK_AREAS["left" if area == "right" else "right"])
    plugin.dock.close()
    controller.reveal()
    qtbot.wait(80)
    targets = {
        "left": QPoint(4, window.height() // 2),
        "right": QPoint(window.width() - 5, window.height() // 2),
        "bottom": QPoint(window.width() // 2, window.height() - 5),
    }
    drag_to(qtbot, controller.strip, window.mapToGlobal(targets[area]))
    qtbot.wait(50)
    assert window.dockWidgetArea(plugin.dock) == DOCK_AREAS[area]
    assert plugin.dock.isHidden() and controller.strip.isVisible()
    assert controller.popup is None and not window.panel_hovers.drop_hint.isVisible()
    assert controller.strip.width() == (84 if area == "bottom" else 5)
    assert controller.strip.height() == (5 if area == "bottom" else 84)
    assert window.plugins.preferences["ui"]["panels"]["example.files"] is False
    window.plugins.shutdown()
    restarted = MainWindow(load_examples=False, plugin_root=window.plugins.root)
    qtbot.addWidget(restarted)
    restarted.show()
    restored = restarted.plugins.panels["example.files"]
    assert restarted.dockWidgetArea(restored) == DOCK_AREAS[area]
    assert restored.isHidden()
    restarted.plugins.shutdown()


def test_invalid_drop_cancels_and_fullscreen_pin_keeps_normal_preference(window, tmp_path, qtbot):
    plugin = enable(window, tmp_path, "file_browser")
    plugin.dock.close()
    controller = window.panel_hovers.controllers["example.files"]
    drag_to(qtbot, controller.strip, window.mapToGlobal(window.rect().center()))
    assert controller.area == DOCK_AREAS["left"] and plugin.dock.isHidden()
    assert controller.popup is None and not controller.moving
    window.toggle_fullscreen()
    controller.reveal()
    qtbot.mouseClick(
        controller.strip, Qt.MouseButton.LeftButton, pos=controller.strip.rect().center()
    )
    assert not plugin.dock.isHidden()
    assert window.plugins.preferences["ui"]["panels"]["example.files"] is False
    window.exit_fullscreen()
    assert plugin.dock.isHidden()


def test_shift_grip_moves_visible_panel_and_unload_cleans_drag_hint(window, tmp_path, qtbot):
    plugin = enable(window, tmp_path, "file_browser")
    qtbot.wait(50)
    controller = window.panel_hovers.controllers["example.files"]
    grip = plugin.dock.widget().grip
    destination = window.mapToGlobal(QPoint(window.width() - 5, window.height() // 2))
    drag_to(qtbot, grip, destination, Qt.KeyboardModifier.ShiftModifier)
    assert controller.area == DOCK_AREAS["right"] and not plugin.dock.isHidden()
    controller.begin_move()
    controller.update_move(destination)
    assert window.panel_hovers.drop_hint.isVisible()
    window.plugins.disable("example.files")
    assert not window.panel_hovers.drop_hint.isVisible()
    assert "example.files" not in window.panel_hovers.controllers


@pytest.mark.parametrize("mode", ["list", "tiles"])
def test_browser_photo_previews_and_frame_free_selection(window, tmp_path, qtbot, pictures, mode):
    from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

    plugin = enable(window, tmp_path, "file_browser")
    plugin.context.set_setting("home", str(pictures))
    plugin.context.set_setting("view", mode)
    plugin.apply_settings()
    view = plugin.views.currentWidget()
    assert view is (plugin.tree if mode == "list" else plugin.tiles)
    qtbot.waitUntil(lambda: plugin.model.index(str(pictures / "1.jpg")).isValid())
    index = plugin.model.index(str(pictures / "1.jpg"))
    view.setCurrentIndex(index)
    view.setFocus()
    # Request and inspect the actual decoded decoration, rather than a generic file icon.
    plugin.model.data(index, Qt.ItemDataRole.DecorationRole)
    qtbot.waitUntil(lambda: any(Path(key[0]) == pictures / "1.jpg" for key in plugin.model.cache))
    image = plugin.model.data(index, Qt.ItemDataRole.DecorationRole).pixmap(32, 32).toImage()
    color = image.pixelColor(image.width() // 2, image.height() // 2)
    assert color.red() > 200 and color.green() < 50 and color.blue() < 50
    option = QStyleOptionViewItem()
    option.state |= QStyle.StateFlag.State_HasFocus
    view.itemDelegate().initStyleOption(option, index)
    assert not option.state & QStyle.StateFlag.State_HasFocus
    assert view.frameShape() == view.Shape.NoFrame
    assert view.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    plugin.view_button.click()
    assert plugin.context.get_setting("view") == ("tiles" if mode == "list" else "list")
    # Tile navigation and the list's hierarchical root use the same filesystem model.
    plugin.context.set_setting("view", "tiles")
    plugin.apply_view()
    plugin.open_entry(plugin.model.index(str(pictures / "nested")))
    assert plugin.location.text() == str((pictures / "nested").resolve())
    plugin.go_up()
    assert plugin.tiles.rootIndex() == plugin.tree.rootIndex()
    window.plugins.disable("example.files")
    assert plugin.model.stopped and not plugin.model.timer.isActive()


def test_progress_drag_changes_image_before_release(window, tmp_path, qtbot, pictures):
    from PySide6.QtWidgets import QStyleOptionSlider

    plugin = enable(window, tmp_path, "progress_panel")
    window.open_image(pictures / "1.jpg")
    option = QStyleOptionSlider()
    plugin.slider.initStyleOption(option)
    start = plugin.slider.handle_rect(option).center().toPoint()
    qtbot.mousePress(plugin.slider, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(plugin.slider, QPoint(plugin.slider.width() - 8, start.y()))
    assert plugin.slider.isSliderDown()
    assert window.current_path.name == "3.png"
    assert plugin.count.text() == "3/3"
    qtbot.mouseRelease(
        plugin.slider, Qt.MouseButton.LeftButton, pos=QPoint(plugin.slider.width() - 8, start.y())
    )
    assert window.current_path.name == "3.png"


def test_preview_remains_until_button_toggle_and_docks_down(window, tmp_path, qtbot, pictures):
    plugin = enable(window, tmp_path, "progress_panel")
    window.open_image(pictures / "1.jpg")
    plugin.controls["preview"].click()
    qtbot.waitUntil(lambda: len(plugin.preview.items) == 3)
    preview = plugin.preview
    qtbot.mouseClick(window.view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(40, 40))
    assert preview.isVisible()
    plugin.controls["next"].click()
    qtbot.waitUntil(lambda: preview.center_index == 1 and len(preview.items) == 3)
    assert preview.isVisible()
    plugin.dock.close()
    qtbot.waitUntil(lambda: preview.geometry().bottom() == window.height() - 9)
    assert preview.isVisible()
    controller = window.panel_hovers.controllers["example.progress"]
    controller.reveal()
    qtbot.wait(460)
    assert preview.isVisible() and controller.popup is not None
    assert abs(preview.geometry().bottom() - (controller.popup.geometry().top() - 9)) <= 1
    controller.collapse()
    qtbot.waitUntil(
        lambda: controller.popup is None and preview.geometry().bottom() == window.height() - 9
    )
    assert preview.isVisible() and preview.geometry().bottom() == window.height() - 9
    window.resize(1300, 840)
    qtbot.waitUntil(lambda: preview.width() == window.width() // 3)
    assert preview.geometry().bottom() == window.height() - 9
    controller.pin()
    plugin.controls["preview"].click()
    assert not preview.isVisible() and plugin.dock.height() == 72
    assert not preview.anchor_timer.isActive()


@pytest.mark.parametrize("width", [220, 260, 380])
def test_information_resizes_long_fields_without_horizontal_overflow(
    window, tmp_path, qtbot, pictures, width
):
    from PySide6.QtWidgets import QFormLayout, QLabel

    plugin = enable(window, tmp_path, "info_panel")
    window.open_image(pictures / "1.jpg")
    qtbot.waitUntil(lambda: plugin.metadata is not None)
    data = dict(plugin.metadata)
    data["file"] = {
        "路径": "C:/" + "long_directory/" * 25 + "照片.jpg",
        "名称": "longfilename" * 20,
    }
    data["extra"] = {"VeryLongMetadataLabel" * 8: "metadata" * 70}
    data["exif"] = {"相机": "CameraModel" * 30}
    plugin.show_metadata(data)
    controller = window.panel_hovers.controllers["example.info"]
    controller.resize_extent(width)
    qtbot.wait(80)
    viewport = plugin.scroll.viewport()
    assert plugin.scroll.widget().width() <= viewport.width()
    assert plugin.scroll.horizontalScrollBar().maximum() == 0
    assert plugin.exif_text.horizontalScrollBar().maximum() == 0
    for table in plugin.tables.values():
        expected = (
            QFormLayout.RowWrapPolicy.WrapAllRows
            if viewport.width() < 320
            else QFormLayout.RowWrapPolicy.DontWrapRows
        )
        assert table.rowWrapPolicy() == expected
        for row in range(table.rowCount()):
            for role in (QFormLayout.ItemRole.LabelRole, QFormLayout.ItemRole.FieldRole):
                label = table.itemAt(row, role).widget()
                assert isinstance(label, QLabel) and label.wordWrap()
                assert label.width() <= viewport.width()
                assert label.height() >= label.heightForWidth(label.width())
    if width == 220:
        assert plugin.dock.width() <= 240
    assert not plugin.exif_box.isHidden()


def test_browser_branch_gutter_and_scrollbar_have_no_white_frames(
    window, tmp_path, qtbot, pictures
):
    for index in range(50):
        Image.new("RGB", (16, 16), "red").save(pictures / f"extra-{index:02d}.png")
    plugin = enable(window, tmp_path, "file_browser")
    plugin.context.set_setting("home", str(pictures))
    plugin.apply_settings()
    qtbot.waitUntil(lambda: plugin.tree.verticalScrollBar().maximum() > 0)
    index = plugin.model.index(str(pictures / "1.jpg"))
    plugin.tree.setCurrentIndex(index)
    plugin.tree.setFocus()
    qtbot.wait(40)
    row = plugin.tree.visualRect(index)
    pixels = plugin.tree.viewport().grab().toImage()
    # The branch gutter sits before the image icon/text and must remain dark,
    # including the selected/focused row on Windows' native Qt style.
    for y in range(max(0, row.top()), min(pixels.height(), row.bottom() + 1)):
        for x in range(min(12, pixels.width())):
            color = pixels.pixelColor(x, y)
            assert min(color.red(), color.green(), color.blue()) < 210
    bar = plugin.tree.verticalScrollBar().grab().toImage()
    for x in range(bar.width()):
        for y in range(bar.height()):
            color = bar.pixelColor(x, y)
            assert min(color.red(), color.green(), color.blue()) < 210


@pytest.mark.parametrize("expanded", [False, True])
def test_selected_folder_branch_has_no_blue_or_white_edges(
    window, tmp_path, qtbot, pictures, expanded
):
    plugin = enable(window, tmp_path, "file_browser")
    plugin.open_folder(pictures)
    index = plugin.model.index(str(pictures / "nested"))
    qtbot.waitUntil(lambda: plugin.tree.visualRect(index).isValid())
    plugin.tree.setExpanded(index, expanded)
    plugin.tree.setCurrentIndex(index)
    window.activateWindow()
    plugin.tree.setFocus()
    row = plugin.tree.visualRect(index)
    qtbot.mouseMove(plugin.tree.viewport(), QPoint(8, row.center().y()))
    qtbot.wait(250)  # Wait for Qt's tree expansion animation.
    image = plugin.tree.viewport().grab().toImage()
    for y in range(row.top(), row.bottom() + 1):
        for x in range(plugin.tree.indentation()):
            color = image.pixelColor(x, y)
            channels = (color.red(), color.green(), color.blue())
            assert min(channels) < 210
            assert max(channels) - min(channels) < 30


def wheel(view, delta, modifiers=Qt.KeyboardModifier.ControlModifier, pixels=0):
    target = view.viewport()
    pos = target.rect().center()
    event = QWheelEvent(
        QPointF(pos),
        QPointF(target.mapToGlobal(pos)),
        QPoint(0, pixels),
        QPoint(0, delta),
        Qt.MouseButton.NoButton,
        modifiers,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(target, event)


@pytest.mark.parametrize("mode", ["list", "tiles"])
def test_browser_ctrl_wheel_sizes_limits_and_navigation(window, tmp_path, qtbot, pictures, mode):
    plugin = enable(window, tmp_path, "file_browser")
    plugin.context.set_setting("view", mode)
    plugin.apply_view()
    plugin.open_folder(pictures / "nested")
    view = plugin.views.currentWidget()
    window.activateWindow()
    view.setFocus()
    qtbot.waitUntil(view.hasFocus)
    wheel(view, 60)
    assert plugin.tree.iconSize().width() == 24
    wheel(view, 60)
    assert plugin.tree.iconSize().width() == 28
    assert plugin.tiles.iconSize().width() == 56
    assert plugin.context.get_setting("icon_size") == 28
    wheel(view, -240)
    assert plugin.tree.iconSize().width() == 20
    wheel(view, -1200)
    assert plugin.tree.iconSize().width() == 16
    wheel(view, 2400)
    assert plugin.tree.iconSize().width() == 64
    wheel(view, 120)
    assert plugin.tree.iconSize().width() == 64
    wheel(view, 0, pixels=-30)
    assert plugin.tree.iconSize().width() == 60
    wheel(view, 120, Qt.KeyboardModifier.NoModifier)
    assert plugin.tree.iconSize().width() == 60
    assert plugin.location.text() == str((pictures / "nested").resolve())
    window.view.setFocus()
    qtbot.waitUntil(window.view.hasFocus)
    wheel(view, 120)
    assert plugin.tree.iconSize().width() == 60


def test_breadcrumb_navigation_editing_overflow_and_long_names(window, tmp_path, qtbot, pictures):
    plugin = enable(window, tmp_path, "file_browser")
    long_folder = pictures / ("长文件夹名称" * 8)
    long_folder.mkdir()
    plugin.open_folder(long_folder)
    bar = plugin.location
    qtbot.waitUntil(lambda: bar.buttons[-1].isVisible())
    assert bar.buttons[-1].text() != bar.buttons[-1].label
    assert "…" in bar.buttons[-1].text()
    assert bar.buttons[-1].toolTip() == str(long_folder.resolve())
    for button in (bar.buttons[0], bar.buttons[-1], bar.edit):
        assert bar.row.rect().contains(button.geometry())
    assert bar.buttons[0].isVisible()  # Drive/root always stays available.
    assert bar.hidden_parts and bar.overflow.isVisible()
    qtbot.mouseClick(bar.overflow, Qt.MouseButton.LeftButton)
    menu = bar.findChild(QMenu)
    assert menu is not None and menu.isVisible()
    pixels = menu.grab().toImage()
    assert pixels.pixelColor(0, 0).alpha() == 0
    assert pixels.pixelColor(pixels.width() - 1, pixels.height() - 1).alpha() == 0
    ancestor = next(button for button in bar.hidden_parts if button.target == pictures.resolve())
    action = next(action for action in menu.actions() if action.toolTip() == str(ancestor.target))
    action.trigger()
    menu.hide()
    assert bar.text() == str(pictures.resolve())
    bar.start_edit()
    assert bar.editor.text() == str(pictures.resolve())
    bar.editor.setText(str(pictures / "nested"))
    qtbot.keyClick(bar.editor, Qt.Key.Key_Return)
    assert bar.text() == str((pictures / "nested").resolve())
    assert bar.stack.currentWidget() is bar.row
    bar.start_edit()
    bar.editor.setText("invalid")
    qtbot.keyClick(bar.editor, Qt.Key.Key_Escape)
    assert bar.text() == str((pictures / "nested").resolve())
    assert bar.stack.currentWidget() is bar.row
    parent = next(button for button in bar.buttons if button.target == pictures.resolve())
    parent.click()
    assert bar.text() == str(pictures.resolve())
    bar.start_edit()
    bar.editor.setText(str(tmp_path / "missing"))
    qtbot.keyClick(bar.editor, Qt.Key.Key_Return)
    assert bar.text() == str(pictures.resolve()) and plugin.note.text()
    qtbot.keyClick(bar.editor, Qt.Key.Key_Escape)
    bar.row.setFocus()
    qtbot.keyClick(bar.row, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
    assert bar.stack.currentWidget() is bar.editor


@pytest.mark.parametrize(
    "path", [PureWindowsPath("C:/Users/user/Pictures"), PureWindowsPath("//server/share/photos")]
)
def test_breadcrumb_windows_drive_and_unc_targets(window, tmp_path, path):
    plugin = enable(window, tmp_path, "file_browser")
    parts = import_module(type(plugin.location).__module__).path_parts(path)
    assert parts[0][1] == PureWindowsPath(path.anchor)
    assert parts[0][0] == path.anchor.rstrip("\\/")
    assert parts[-1][1] == path
    assert all(target == parts[index + 1][1].parent for index, (_, target) in enumerate(parts[:-1]))


def test_persistent_preview_discards_other_folder_tiles(window, tmp_path, qtbot, pictures):
    plugin = enable(window, tmp_path, "progress_panel")
    window.open_image(pictures / "1.jpg")
    plugin.controls["preview"].click()
    qtbot.waitUntil(lambda: len(plugin.preview.items) == 3)
    old_position = plugin.preview.tile_rect(2).center().toPoint()
    folder = tmp_path / "另一组"
    folder.mkdir()
    target = folder / "only.png"
    Image.new("RGB", (30, 20), "orange").save(target)
    window.open_image(target)
    assert plugin.preview.isVisible() and not plugin.preview.items
    qtbot.mouseClick(plugin.preview, Qt.MouseButton.LeftButton, pos=old_position)
    assert window.current_path == target.resolve()
    qtbot.waitUntil(lambda: len(plugin.preview.items) == 1)
    assert plugin.preview.items[0][1] == str(target.resolve())
    assert window.plugins.records["example.progress"].state == "enabled"
