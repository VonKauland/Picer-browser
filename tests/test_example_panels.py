"""Install real example ZIPs and exercise their models, metadata and animations."""

import zipfile
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QDockWidget

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
    dialog.save()
    assert plugin.location.text() == str(pictures.resolve())
    assert plugin.tree.iconSize().width() == 40
    root = window.plugins.root
    window.plugins.shutdown()
    restarted = MainWindow(load_examples=False, plugin_root=root)
    qtbot.addWidget(restarted)
    browser = restarted.plugins.records["example.files"].instance
    assert browser.location.text() == str(pictures.resolve())
    assert browser.tree.iconSize().width() == 40
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
