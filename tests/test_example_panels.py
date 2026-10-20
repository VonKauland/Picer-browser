"""Install real example ZIPs and exercise their models, metadata and animations."""

import sys
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
    context.set_setting("photo_sort", "modified")
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
    assert "Test Camera" in plugin.exif_view.text()
    assert not plugin.exif_box.isHidden()
    assert plugin.exif_box.parent() is plugin.panel
    context = window.plugins.records["example.info"].context
    context.set_setting("dimensions", False)
    context.set_setting("histogram", False)
    plugin.apply_settings()
    assert plugin.groups["dimensions"].isHidden()
    assert plugin.groups["histogram"].isHidden()
    assert not plugin.exif_box.isHidden()
    qtbot.mouseClick(plugin.rating, Qt.MouseButton.LeftButton, pos=QPoint(92, 11))
    assert context.image_annotation((pictures / "1.jpg").resolve())["rating"] == 4
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
    qtbot.waitUntil(lambda: not plugin.preview.isVisible())


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
    controller = window.panel_hovers.controllers["example.files"]
    assert not plugin.dock.widget().uses_glass()
    controller.dock.close()
    controller.reveal()
    qtbot.waitUntil(lambda: not window.glass.image.isNull())
    assert window.glass.image.size() == window.size()
    signature = window.glass.captured_signature
    window.glass.invalidate()
    assert not window.glass.timer.isActive()
    controller.pin()
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
    try:
        qtbot.waitUntil(lambda: controller.popup is not None, timeout=1000)
    except Exception:
        from PySide6.QtGui import QCursor

        cursor = QCursor.pos()
        frame = window.window_frame
        if frame.user32:
            import ctypes

            from picer.window_frame import Message, Point, Rect

            native_cursor, native_rect = Point(), Rect()
            get_cursor = frame.user32.GetCursorPos
            get_cursor.argtypes = [ctypes.POINTER(Point)]
            get_cursor.restype = ctypes.c_int
            get_cursor(ctypes.byref(native_cursor))
            frame.user32.GetWindowRect(int(window.winId()), ctypes.byref(native_rect))
            message = Message()
            message.hwnd, message.message = int(window.winId()), 0x0084
            message.lparam = (native_cursor.y & 0xFFFF) << 16 | (native_cursor.x & 0xFFFF)
            hit = frame.native_event(ctypes.addressof(message))
            send = frame.user32.SendMessageW
            send.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_size_t, ctypes.c_ssize_t]
            send.restype = ctypes.c_ssize_t
            native_hit = send(message.hwnd, message.message, 0, message.lparam)
            frame.user32.ScreenToClient(int(window.winId()), ctypes.byref(native_cursor))
            print(
                "Native hover diagnostics:",
                "rect",
                (native_rect.left, native_rect.top, native_rect.right, native_rect.bottom),
                "client cursor",
                (native_cursor.x, native_cursor.y),
                "hit",
                hit,
                "native hit",
                native_hit,
                "style",
                hex(frame.user32.GetWindowLongW(int(window.winId()), -16) & 0xFFFFFFFF),
            )
        print(
            "Hover diagnostics:",
            "window",
            window.geometry(),
            window.frameGeometry(),
            "strip",
            controller.strip.geometry(),
            "strip global",
            controller.strip.mapToGlobal(QPoint(2, 40)),
            "cursor",
            cursor,
            "target",
            QApplication.widgetAt(cursor),
            "client target",
            window.childAt(window.mapFromGlobal(cursor)),
            "DPR",
            window.devicePixelRatioF(),
        )
        raise
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
    qtbot.waitUntil(
        lambda: (restored.height() if area == DOCK_AREAS["bottom"] else restored.width()) == after,
        timeout=2000,
    )
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
    index = plugin.model.index(str(pictures / "1.jpg"))
    image = plugin.model.data(index, Qt.ItemDataRole.DecorationRole).pixmap(32, 32).toImage()
    color = image.pixelColor(image.width() // 2, image.height() // 2)
    assert color.red() > 200 and color.green() < 50 and color.blue() < 50
    option = QStyleOptionViewItem()
    option.state |= QStyle.StateFlag.State_HasFocus
    view.itemDelegate().initStyleOption(option, index)
    assert not option.state & QStyle.StateFlag.State_HasFocus
    assert view.frameShape() == view.Shape.NoFrame
    assert view.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    plugin.quick_actions["tiles" if mode == "list" else "list"].trigger()
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
    qtbot.waitUntil(lambda: not preview.isVisible() and plugin.dock.height() == 72)
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
    assert plugin.exif_view.scroll.horizontalScrollBar().maximum() == 0
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
                assert label.height() >= label.heightForWidth(label.width()), (
                    label.text()[:80],
                    label.minimumSizeHint(),
                    label.sizeHint(),
                    label.fontMetrics().height(),
                    label.heightForWidth(100000),
                )
    if width == 220:
        assert plugin.dock.width() <= 240
    assert not plugin.exif_box.isHidden()
    for expanded in (False, True):
        if expanded:
            plugin.exif_view.button.click()
            qtbot.wait(320)
        button = plugin.exif_view.button
        button_bottom = button.mapTo(plugin.panel, button.rect().bottomLeft()).y()
        switches_top = min(
            switch.mapTo(plugin.panel, QPoint(0, 0)).y()
            for switch in (plugin.focus_switch, plugin.camera_switch)
        )
        assert switches_top - button_bottom >= 10
        assert button.height() >= button.fontMetrics().height() + 8


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
            assert color.blue() <= max(color.red(), color.green()) + 20


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
    ancestor = bar.hidden_parts[-1]
    action = next(action for action in menu.actions() if action.toolTip() == str(ancestor.target))
    action.trigger()
    menu.hide()
    assert bar.text() == str(ancestor.target)
    bar.pathRequested.emit(str(pictures))
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


@pytest.mark.parametrize("mode", ["list", "tiles"])
def test_browser_double_click_parent_backspace_and_side_buttons(
    window, tmp_path, qtbot, pictures, mode
):
    plugin = enable(window, tmp_path, "file_browser")
    plugin.context.set_setting("view", mode)
    plugin.apply_view()
    plugin.open_folder(pictures)
    view = plugin.views.currentWidget()
    qtbot.waitUntil(lambda: view.visualRect(plugin.model.index(str(pictures / "nested"))).isValid())
    pos = view.visualRect(plugin.model.index(str(pictures / "nested"))).center()
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert plugin.location.text() == str(pictures.resolve())
    qtbot.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert plugin.location.text() == str((pictures / "nested").resolve())
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.BackButton)
    assert plugin.location.text() == str(pictures.resolve())
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.ForwardButton)
    assert plugin.location.text() == str((pictures / "nested").resolve())
    qtbot.keyClick(view, Qt.Key.Key_Backspace)
    assert plugin.location.text() == str(pictures.resolve())
    plugin.open_folder(pictures / "nested")
    qtbot.mouseClick(plugin.parent_entry, Qt.MouseButton.LeftButton)
    assert plugin.location.text() == str((pictures / "nested").resolve())
    qtbot.mouseDClick(plugin.parent_entry, Qt.MouseButton.LeftButton)
    assert plugin.location.text() == str(pictures.resolve())
    plugin.location.start_edit()
    plugin.location.editor.setText("abc")
    qtbot.keyClick(plugin.location.editor, Qt.Key.Key_Backspace)
    assert plugin.location.editor.text() == "ab"
    assert plugin.location.text() == str(pictures.resolve())
    plugin.open_folder(Path(pictures.anchor))
    assert plugin.parent_entry.isVisible()
    plugin.go_up()
    assert plugin.location.text() == ""
    assert plugin.parent_entry.isHidden()


@pytest.mark.parametrize("column", ["name", "size", "type", "modified"])
@pytest.mark.parametrize("descending", [False, True])
def test_browser_directories_first_for_every_sort(
    window, tmp_path, qtbot, pictures, column, descending
):
    (pictures / "aaa").mkdir()
    plugin = enable(window, tmp_path, "file_browser")
    plugin.context.set_setting("sort", column)
    plugin.context.set_setting("photo_sort", column)
    plugin.context.set_setting("descending", descending)
    plugin.sort_tree()
    plugin.open_folder(pictures)
    # Proxy indexes can be invalidated while the asynchronous filesystem model
    # loads or resorts. Fetch the view's persistent root after each event turn.
    qtbot.waitUntil(lambda: plugin.model.rowCount(plugin.tree.rootIndex()) == 5)
    entries = [
        plugin.model.isDir(plugin.model.index(row, 0, plugin.tree.rootIndex())) for row in range(5)
    ]
    assert entries == [True, True, False, False, False]
    assert plugin.parent_entry.isVisible()


@pytest.mark.parametrize("mode", ["list", "tiles"])
def test_browser_fast_wheel_scrolling_preserves_icon_size(window, tmp_path, qtbot, pictures, mode):
    for number in range(70):
        Image.new("RGB", (8, 8)).save(pictures / f"extra-{number:03}.png")
    plugin = enable(window, tmp_path, "file_browser")
    plugin.context.set_setting("view", mode)
    plugin.apply_view()
    plugin.open_folder(pictures)
    view = plugin.views.currentWidget()
    bar = view.verticalScrollBar()
    qtbot.waitUntil(lambda: bar.maximum() > 400)
    bar.setValue(0)
    wheel(view, -120, Qt.KeyboardModifier.NoModifier)
    assert bar.value() >= 180
    wheel(view, 120, Qt.KeyboardModifier.NoModifier)
    assert bar.value() == 0
    assert plugin.tree.iconSize().width() == 24


def test_glass_folder_classification_watch_and_neutral_icons(window, tmp_path, qtbot, pictures):
    ordinary = pictures / "documents"
    ordinary.mkdir()
    (ordinary / "fake.jpg").write_text("not an image")
    (ordinary / "deep").mkdir()
    Image.new("RGB", (8, 8)).save(ordinary / "deep" / "deep.png")
    plugin = enable(window, tmp_path, "file_browser")
    plugin.open_folder(pictures)
    folders = plugin.model.files.folders
    for path in (ordinary, pictures / "nested"):
        plugin.model.data(plugin.model.index(str(path)), Qt.ItemDataRole.DecorationRole)
    qtbot.waitUntil(
        lambda: all(str(path) in folders.cache for path in (ordinary, pictures / "nested"))
    )
    assert not folders.cache[str(ordinary)] and folders.cache[str(pictures / "nested")]
    image = ordinary / "photo.png"
    Image.new("RGB", (10, 10), "red").save(image)
    qtbot.waitUntil(lambda: folders.cache.get(str(ordinary)) is True)

    def remove_image():
        # Windows denies deletion while a thumbnail worker has the file open.
        try:
            image.unlink()
        except PermissionError:
            return False
        return True

    qtbot.waitUntil(remove_image, timeout=5000)
    qtbot.waitUntil(lambda: folders.cache.get(str(ordinary)) is False)
    for icon in folders.icons:
        normal = icon.pixmap(32, 32, QIcon.Mode.Normal).toImage()
        selected = icon.pixmap(32, 32, QIcon.Mode.Selected).toImage()
        assert normal == selected
        assert normal.pixelColor(0, 0).alpha() == 0
        for x in range(normal.width()):
            for y in range(normal.height()):
                color = normal.pixelColor(x, y)
                assert color.alpha() < 80 or (
                    max(color.red(), color.green(), color.blue())
                    - min(color.red(), color.green(), color.blue())
                    < 12
                )
    window.plugins.disable("example.files")
    assert folders.stopped and not folders.watcher.directories()


def test_preview_motion_intermediate_frames_reversal_and_cleanup(window, tmp_path, qtbot, pictures):
    from PySide6.QtCore import QAbstractAnimation

    plugin = enable(window, tmp_path, "progress_panel")
    window.open_image(pictures / "1.jpg")
    plugin.controls["preview"].click()
    assert plugin.preview_open and plugin.motion.state() == QAbstractAnimation.State.Running
    plugin.motion.setCurrentTime(100)
    assert 0 < plugin.preview.reveal < 1
    assert 52 < plugin.dock.height() < 72
    assert 20 < plugin.controls["next"].height() < 28
    before = plugin.expansion
    plugin.controls["preview"].click()
    assert not plugin.preview_open and plugin.expansion == before
    plugin.motion.setCurrentTime(40)
    assert plugin.expansion < before
    before = plugin.expansion
    plugin.controls["preview"].click()
    assert plugin.preview_open and plugin.expansion == before
    qtbot.waitUntil(lambda: plugin.expansion == 1)
    assert plugin.dock.height() == 52 and plugin.controls["next"].height() == 20
    assert plugin.preview.reveal == 1
    plugin.controls["preview"].click()
    qtbot.waitUntil(lambda: not plugin.preview.isVisible())
    assert plugin.dock.height() == 72 and not plugin.preview.anchor_timer.isActive()
    plugin.controls["preview"].click()
    window.plugins.disable("example.progress")
    assert plugin.motion.state() == QAbstractAnimation.State.Stopped


@pytest.mark.parametrize("mode", ["list", "tiles"])
def test_browser_selection_outline_encloses_whole_item(window, tmp_path, qtbot, pictures, mode):
    plugin = enable(window, tmp_path, "file_browser")
    plugin.context.set_setting("view", mode)
    plugin.apply_view()
    plugin.open_folder(pictures)
    view = plugin.views.currentWidget()
    qtbot.waitUntil(lambda: plugin.model.rowCount(view.rootIndex()) == 4)
    index = plugin.model.index(str(pictures / "nested"))
    view.setCurrentIndex(index)
    qtbot.wait(40)
    row = view.visualRect(plugin.model.index(str(pictures / "nested")))
    image = view.viewport().grab().toImage()
    accent = []
    for x in range(max(0, row.left()), min(image.width(), row.right() + 1)):
        for y in range(max(0, row.top()), min(image.height(), row.bottom() + 1)):
            color = image.pixelColor(x, y)
            if color.red() > 140 and color.green() > 160 and color.blue() < 150:
                accent.append(QPoint(x, y))
    assert accent
    # Border extends to the far edge of the row/tile, beyond the icon.
    assert max(point.x() for point in accent) >= row.right() - 5
    assert min(point.y() for point in accent) <= row.top() + 4


def test_network_locations_add_search_remove_and_restart(window, tmp_path, qtbot, monkeypatch):
    plugin = enable(window, tmp_path, "file_browser")
    module = import_module(plugin.__class__.__module__.rsplit(".", 1)[0] + ".network")
    plugin.search.setText("之前的目录搜索")
    plugin.tabs.setCurrentIndex(3)
    assert plugin.model.search_text == ""
    assert plugin.pages.currentWidget() is plugin.network
    qtbot.waitUntil(lambda: plugin.network.add_button.height() == 32)
    assert plugin.location.virtual_label == "网络位置"
    assert plugin.search.placeholderText() == "搜索网络位置"
    assert not plugin.random_button.isEnabled()
    assert plugin.network.empty.isVisible()
    for invalid in (
        "",
        "C:\\Photos",
        "https://NAS/photos",
        r"\\?\C:\Photos",
        "\\\\NAS\\Photos\nX",
    ):
        with pytest.raises(ValueError):
            module.normalize_path(invalid)
    assert module.normalize_path("//NAS/Photos/旅行") == r"\\NAS\Photos\旅行"
    assert module.normalize_path(r"\\192.168.0.20") == r"\\192.168.0.20"
    for invalid in (None, {}, [{"name": "无效", "path": "C:/local"}], [None]):
        plugin.context.set_setting("network_locations", invalid)
        assert module.saved_locations(plugin.context) == []
    plugin.context.set_setting("network_locations", [])

    def submit(dialog):
        dialog.path.setText(r"\\NAS\Photos")
        dialog.name.setText("家庭 NAS")
        assert dialog.confirm.isEnabled()
        dialog.confirm.click()
        return dialog.result()

    monkeypatch.setattr(module.LocationDialog, "exec", submit)
    plugin.network.add_button.click()
    entries = module.saved_locations(plugin.context)
    assert len(entries) == 1 and entries[0]["name"] == "家庭 NAS"
    item = plugin.network.list.item(0)
    assert item.icon().cacheKey() == plugin.network.folder_icon.cacheKey()
    assert item.icon().cacheKey() != plugin.model.files.folders.icons[0].cacheKey()
    globe = item.icon().pixmap(128, 128).toImage()
    assert any(globe.pixelColor(x, y).alpha() > 100 for x in range(38, 117) for y in range(5, 14))
    assert all(globe.pixelColor(x, 0).alpha() == 0 for x in range(128))
    assert all(globe.pixelColor(127, y).alpha() == 0 for y in range(128))
    dialog = module.LocationDialog(entries, plugin.panel)
    qtbot.addWidget(dialog)
    dialog.path.setText("//nas/photos/")
    assert not dialog.confirm.isEnabled() and "已添加" in dialog.error.text()
    large = [{"name": "位置", "path": "\\\\nas\\share\\" + "a" * 1800 + str(i)} for i in range(40)]
    full = module.LocationDialog(large, plugin.panel)
    qtbot.addWidget(full)
    full.path.setText(r"\\other\photos")
    assert not full.confirm.isEnabled() and "列表已满" in full.error.text()
    monkeypatch.setattr(module.LocationDialog, "exec", lambda dialog: 0)
    plugin.network.add_button.click()
    assert module.saved_locations(plugin.context) == entries
    plugin.search.setText("没有匹配")
    assert plugin.network.list.item(0).isHidden()
    plugin.search.setText("nas")
    assert not plugin.network.list.item(0).isHidden()
    # Rendering saved locations never probes the server, including when offline.
    with monkeypatch.context() as patch:
        patch.setattr(module, "Path", lambda path: pytest.fail("Unexpected network IO"))
        plugin.network.reload()
        plugin.network.list.viewport().grab()
    root = window.plugins.root
    window.plugins.shutdown()
    restarted = MainWindow(load_examples=False, plugin_root=root)
    qtbot.addWidget(restarted)
    browser = restarted.plugins.records["example.files"].instance
    assert module.saved_locations(browser.context) == entries
    browser.tabs.setCurrentIndex(3)
    browser.network.remove(entries[0]["path"])
    assert browser.network.list.count() == 0
    assert module.saved_locations(browser.context) == []
    restarted.plugins.shutdown()


def test_network_connect_is_background_bounded_and_ignores_stale_results(
    window,
    tmp_path,
    qtbot,
    monkeypatch,
    pictures,
):
    from threading import Event, get_ident

    plugin = enable(window, tmp_path, "file_browser")
    module = import_module(plugin.__class__.__module__.rsplit(".", 1)[0] + ".network")
    started, release = Event(), Event()
    threads = []

    class OfflinePath:
        def __init__(self, path):
            pass

        def is_dir(self):
            threads.append(get_ident())
            started.set()
            assert release.wait(5)
            return False

    monkeypatch.setattr(module, "Path", OfflinePath)
    plugin.tabs.setCurrentIndex(3)
    plugin.open_folder(r"\\NAS\Photos")
    try:
        qtbot.waitUntil(started.is_set)
        assert plugin.network.busy
        assert threads == [threads[0]] and threads[0] != get_ident()
        plugin.network.timeout.timeout.emit()
        assert "超时" in plugin.note.text()
        plugin.open_folder(r"\\NAS\Other")
        assert len(threads) == 1  # no unbounded jobs behind a stalled server
        plugin.open_folder(pictures)
        assert plugin.location.text() == str(pictures.resolve())
        release.set()
        qtbot.waitUntil(lambda: not plugin.network.busy)
        assert plugin.location.text() == str(pictures.resolve())
        assert plugin.note.text() == ""  # stale failure cannot replace local feedback
    finally:
        release.set()


@pytest.mark.parametrize("readable", [True, False])
def test_network_open_result_routes_validated_path_only(
    window,
    tmp_path,
    qtbot,
    monkeypatch,
    readable,
):
    from types import SimpleNamespace

    plugin = enable(window, tmp_path, "file_browser")
    module = import_module(plugin.__class__.__module__.rsplit(".", 1)[0] + ".network")
    monkeypatch.setattr(module, "Path", lambda path: SimpleNamespace(is_dir=lambda: readable))
    calls = []
    original = plugin.open_folder

    def capture(path, **kwargs):
        if kwargs.get("_network_ready"):
            calls.append((path, kwargs))
            return True
        return original(path, **kwargs)

    monkeypatch.setattr(plugin, "open_folder", capture)
    plugin.tabs.setCurrentIndex(3)
    plugin.open_folder(r"\\NAS\Photos")
    qtbot.waitUntil(lambda: not plugin.network.busy)
    assert not plugin.network.timeout.isActive()
    if readable:
        assert len(calls) == 1 and calls[0][1]["_network_ready"]
        assert calls[0][0] == module.normalize_path(r"\\NAS\Photos")
    else:
        assert not calls and "无法访问" in plugin.note.text()


def test_network_task_capacity_failure_keeps_browser_available(window, tmp_path, monkeypatch):
    from picer.plugins import PluginError

    plugin = enable(window, tmp_path, "file_browser")

    def full(*args, **kwargs):
        raise PluginError("full")

    with monkeypatch.context() as patch:
        patch.setattr(plugin.context, "run_task", full)
        plugin.open_folder(r"\\NAS\Photos")
    assert not plugin.network.busy and not plugin.network.timeout.isActive()
    assert "繁忙" in plugin.note.text()


def test_network_server_root_lists_shares_and_goes_up(window, tmp_path, qtbot, monkeypatch):
    plugin = enable(window, tmp_path, "file_browser")
    module = import_module(plugin.__class__.__module__.rsplit(".", 1)[0] + ".network")
    server = r"\\192.168.0.20"
    plugin.context.set_setting("network_locations", [{"name": "NAS", "path": server}])
    monkeypatch.setattr(
        module,
        "list_shares",
        lambda path, token: [
            {"name": "Photos", "path": path + r"\Photos"},
        ],
    )
    plugin.tabs.setCurrentIndex(3)
    plugin.open_selected()  # no selection is harmless
    plugin.open_folder(server)
    qtbot.waitUntil(lambda: plugin.network.server == server)
    assert plugin.location.virtual_label == server
    assert plugin.network.list.item(0).text() == "Photos"
    assert not plugin.network.add_button.isVisible()
    plugin.go_up()
    assert plugin.network.server is None
    assert plugin.network.list.item(0).text() == "NAS"
    assert plugin.network.add_button.isVisible()
    calls = []
    plugin.tabs.setCurrentIndex(0)
    plugin.location.setText(server + r"\Photos")
    monkeypatch.setattr(plugin, "open_folder", calls.append)
    plugin.go_up()
    assert calls == [server]


@pytest.mark.skipif(sys.platform != "win32", reason="Native NetShareEnum requires Windows")
def test_native_nas_share_enumeration_abi(window, tmp_path):
    from picer.plugins.tasks import TaskToken

    plugin = enable(window, tmp_path, "file_browser")
    module = import_module(plugin.__class__.__module__.rsplit(".", 1)[0] + ".shares")
    try:
        rows = module.list_shares(r"\\localhost", TaskToken())
    except OSError as error:
        assert "Windows 错误" in str(error)  # local sharing may be disabled on the runner
    else:
        assert all(row["path"].startswith("\\\\localhost" + "\\") for row in rows)


def test_plugin_dialog_surfaces_are_opaque_and_accent_bordered(window, tmp_path, qtbot):
    from PySide6.QtGui import QColor

    from picer.editing.panel import SaveDialog

    plugin = enable(window, tmp_path, "file_browser")
    module = import_module(plugin.__class__.__module__.rsplit(".", 1)[0] + ".network")
    window.app_preferences["accent_color"] = "#6699CC"
    for dialog in (SaveDialog(plugin.panel, True), module.LocationDialog([], plugin.panel)):
        qtbot.addWidget(dialog)
        dialog.show()
        qtbot.wait(20)
        pixels = dialog.grab().toImage()
        assert pixels.pixelColor(0, 0).alpha() == 0
        assert pixels.pixelColor(5, dialog.height() // 2) == QColor("#242426")
        border = pixels.pixelColor(dialog.width() // 2, dialog.height() - 1)
        expected = QColor("#6699CC").darker(230)
        assert border.alpha() == 255
        assert abs(border.red() - expected.red()) < 4
        dialog.hide()


def test_focus_overlay_toggle_geometry_and_revocation(window, tmp_path, qtbot, pictures):
    from picer.metadata import inspect_image

    files = enable(window, tmp_path, "file_browser")
    path = pictures / "1.jpg"
    window.open_image(path)
    qtbot.waitUntil(lambda: window.current_path == path)
    boxes = {"boxes": [(0.1, 0.2, 0.2, 0.1)], "orientation": 1}
    files.context.show_focus_points(boxes)
    overlay = window.focus_points.item
    assert overlay.isVisible() and overlay.parentItem() is window.view.image_item
    rect = overlay.path().boundingRect()
    assert rect.center().x() == pytest.approx(16)
    assert rect.width() == pytest.approx(16 / 3)
    window.rotate_image()
    assert overlay.path().boundingRect().center().x() == pytest.approx(45)
    assert overlay.path().boundingRect().center().y() == pytest.approx(16)
    window.plugins.disable("example.files")
    assert not overlay.isVisible()
    info = enable(window, tmp_path, "info_panel")
    info.read_timer.stop()
    if info.token:
        info.token.cancel()
    data = inspect_image(path)
    data["focus_points"] = boxes
    info.show_metadata(data)
    info.focus_switch.setChecked(True)
    assert overlay.isVisible()
    info.focus_switch.setChecked(False)
    assert not overlay.isVisible()
    assert info.context.get_setting("show_focus_points") is False


def test_network_double_click_enter_failure_and_disable(window, tmp_path, qtbot, monkeypatch):
    plugin = enable(window, tmp_path, "file_browser")
    module = import_module(plugin.__class__.__module__.rsplit(".", 1)[0] + ".network")
    path = module.normalize_path(r"\\NAS\Photos")
    plugin.context.set_setting("network_locations", [{"name": "照片", "path": path}])
    plugin.tabs.setCurrentIndex(3)
    calls = []
    monkeypatch.setattr(plugin.network, "open_path", lambda *args: calls.append(args))
    rect = plugin.network.list.visualItemRect(plugin.network.list.item(0))
    qtbot.mouseClick(plugin.network.list.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    assert not calls
    qtbot.mouseDClick(plugin.network.list.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    assert calls[0][0] == path
    plugin.open_selected()
    assert len(calls) == 2
    plugin.network.timeout.start()
    window.plugins.disable("example.files")
    assert not plugin.network.timeout.isActive()


def test_browser_quick_menu_places_and_restart(window, tmp_path, qtbot, pictures):
    plugin = enable(window, tmp_path, "file_browser")
    plugin.context.set_setting("home", str(pictures))
    plugin.open_folder(pictures)
    assert [plugin.tabs.tabText(i) for i in range(4)] == ["", "", "", ""]
    assert [plugin.tabs.tabToolTip(i) for i in range(4)] == [
        "文件",
        "快速访问",
        "历史记录",
        "网络位置",
    ]
    assert all(not plugin.tabs.tabIcon(i).isNull() for i in range(4))
    assert plugin.tabs.tabSizeHint(0).width() == 36
    qtbot.mouseClick(plugin.view_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(plugin.quick_menu.isVisible)
    assert [
        None if action.isSeparator() else action.text() for action in plugin.quick_menu.actions()
    ] == ["平铺视图", "列表视图", None, "刷新", None, "正序排列", "倒序排列", None, "加入快速访问"]
    pixels = plugin.quick_menu.grab().toImage()
    assert pixels.pixelColor(0, 0).alpha() == 0
    assert pixels.pixelColor(pixels.width() - 1, pixels.height() - 1).alpha() == 0
    plugin.quick_actions["favorite"].trigger()
    plugin.add_favorite()
    assert plugin.context.get_setting("favorites") == [str(pictures.resolve())]
    plugin.quick_menu.hide()
    plugin.open_folder(pictures / "nested")
    plugin.tabs.setCurrentIndex(1)
    assert plugin.pages.currentWidget() is plugin.favorites
    item = plugin.favorites.item(0)
    pos = plugin.favorites.visualItemRect(item).center()
    qtbot.mouseClick(plugin.favorites.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert plugin.location.text() == str((pictures / "nested").resolve())
    qtbot.mouseDClick(plugin.favorites.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert plugin.location.text() == str(pictures.resolve())
    plugin.tabs.setCurrentIndex(2)
    assert plugin.pages.currentWidget() is plugin.recent
    assert plugin.recent.item(0).data(Qt.ItemDataRole.UserRole) == str(pictures.resolve())
    saved_recent = plugin.context.get_setting("recent_folders")
    plugin.open_folder(tmp_path / "missing")
    assert plugin.context.get_setting("recent_folders") == saved_recent
    root = window.plugins.root
    window.plugins.shutdown()
    restarted = MainWindow(load_examples=False, plugin_root=root)
    qtbot.addWidget(restarted)
    browser = restarted.plugins.records["example.files"].instance
    assert browser.context.get_setting("favorites") == [str(pictures.resolve())]
    assert str((pictures / "nested").resolve()) in browser.context.get_setting("recent_folders")
    browser.favorites.remove_path(str(pictures.resolve()))
    browser.recent.clear_history()
    assert browser.favorites.count() == browser.recent.count() == 0
    restarted.plugins.shutdown()


@pytest.mark.parametrize("mode", ["list", "tiles"])
def test_browser_disk_list_double_click_and_history(window, tmp_path, qtbot, pictures, mode):
    plugin = enable(window, tmp_path, "file_browser")
    plugin.set_view(mode)
    drive = Path(pictures.anchor)
    plugin.open_folder(drive)
    plugin.go_up()
    assert plugin.location.text() == ""
    assert plugin.location.buttons[0].label == "此电脑"
    assert plugin.parent_entry.isHidden()
    plugin.sync_quick_menu()
    assert not plugin.quick_actions["favorite"].isEnabled()
    view = plugin.views.currentWidget()
    qtbot.waitUntil(lambda: view.visualRect(plugin.model.index(str(drive))).isValid())
    pos = view.visualRect(plugin.model.index(str(drive))).center()
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert plugin.location.text() == ""
    qtbot.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert plugin.location.text() == str(drive)
    plugin.go_back()
    assert plugin.location.text() == ""
    plugin.go_forward()
    assert plugin.location.text() == str(drive)


@pytest.mark.parametrize("mode", ["list", "tiles"])
@pytest.mark.parametrize("descending", [False, True])
def test_browser_return_selection_scrolls_to_top(window, tmp_path, qtbot, mode, descending):
    folder = tmp_path / "many-folders"
    folder.mkdir()
    for number in range(90):
        (folder / f"folder-{number:03}").mkdir()
    exited = folder / "folder-045"
    plugin = enable(window, tmp_path, "file_browser")
    plugin.set_view(mode)
    plugin.open_folder(folder)
    plugin.set_descending(descending)
    plugin.open_folder(exited)
    plugin.go_up()
    view = plugin.views.currentWidget()
    qtbot.waitUntil(
        lambda: view.currentIndex().isValid()
        and Path(plugin.model.filePath(view.currentIndex())) == exited
    )
    qtbot.waitUntil(lambda: abs(view.visualRect(plugin.model.index(str(exited))).top()) <= 4)
    assert plugin.model.isDir(view.currentIndex())
    assert plugin.tree.header().sortIndicatorOrder() == (
        Qt.SortOrder.DescendingOrder if descending else Qt.SortOrder.AscendingOrder
    )


def test_browser_folder_sort_defaults_isolation_and_persistence(window, tmp_path, qtbot, pictures):
    ordinary = tmp_path / "ordinary"
    ordinary.mkdir()
    plugin = enable(window, tmp_path, "file_browser")
    plugin.context.set_setting("sort", "modified")
    plugin.open_folder(ordinary)
    qtbot.waitUntil(lambda: str(ordinary) in plugin.model.files.folders.cache)
    assert plugin.current_order() == ("modified", False)
    plugin.sort.setCurrentIndex(plugin.sort.findData("size"))
    plugin.set_descending(True)
    plugin.open_folder(pictures)
    qtbot.waitUntil(lambda: plugin.model.files.folders.cache.get(str(pictures)) is True)
    assert plugin.current_order() == ("name", False)
    plugin.context.set_setting("photo_sort", "type")
    plugin.sort_tree()
    assert plugin.current_order() == ("type", False)
    plugin.open_folder(ordinary)
    assert plugin.current_order() == ("size", True)
    plugin.open_folder(pictures / "nested")
    qtbot.waitUntil(lambda: plugin.model.files.folders.cache.get(str(pictures / "nested")) is True)
    assert plugin.current_order() == ("type", False)
    plugin.context.set_setting("home", str(ordinary))
    root = window.plugins.root
    window.plugins.shutdown()
    restarted = MainWindow(load_examples=False, plugin_root=root)
    qtbot.addWidget(restarted)
    browser = restarted.plugins.records["example.files"].instance
    assert browser.current_order() == ("size", True)
    restarted.plugins.shutdown()


def test_browser_refresh_reloads_image_and_stops_old_jobs(window, tmp_path, qtbot, pictures):
    plugin = enable(window, tmp_path, "file_browser")
    plugin.open_folder(pictures)
    path = pictures / "1.jpg"
    qtbot.waitUntil(lambda: plugin.model.index(str(path)).isValid())
    plugin.model.data(plugin.model.index(str(path)), Qt.ItemDataRole.DecorationRole)
    qtbot.waitUntil(lambda: any(Path(key[0]) == path for key in plugin.model.cache))
    old = plugin.model
    Image.new("RGB", (80, 60), "blue").save(path)
    plugin.quick_actions["refresh"].trigger()
    assert old.stopped and old.files.folders.stopped
    qtbot.waitUntil(lambda: plugin.model.index(str(path)).isValid())
    plugin.model.data(plugin.model.index(str(path)), Qt.ItemDataRole.DecorationRole)
    qtbot.waitUntil(lambda: any(Path(key[0]) == path for key in plugin.model.cache))
    icon = plugin.model.data(plugin.model.index(str(path)), Qt.ItemDataRole.DecorationRole)
    image = icon.pixmap(32, 32).toImage()
    assert image.pixelColor(image.width() // 2, image.height() // 2).blue() > 200


@pytest.mark.parametrize("mode", ["list", "tiles"])
def test_folder_first_photo_preview_shared_cache_and_live_updates(
    window, tmp_path, qtbot, pictures, mode, monkeypatch
):
    album = pictures / "album"
    album.mkdir()
    (album / "00-broken.jpg").write_text("broken")
    Image.new("RGB", (32, 24), "green").save(album / "z-last.png")
    first = album / "A-first.png"
    Image.new("RGB", (32, 24), "red").save(first)
    plugin = enable(window, tmp_path, "file_browser")
    plugin.context.set_setting("view", mode)
    plugin.apply_view()
    folders = plugin.model.files.folders
    probed = []
    can_read = folders.can_read

    def probe(source, token):
        if Path(source).parent == album:
            probed.append(Path(source).name)
        return can_read(source, token)

    monkeypatch.setattr(folders, "can_read", probe)
    plugin.open_folder(pictures)
    path = str(album)
    folders.icon(path)
    qtbot.waitUntil(lambda: path in folders.previews)
    assert folders.sources[path] == str(first)
    assert set(probed) == {"00-broken.jpg", "A-first.png"}
    pixels = folders.icon(path).pixmap(128, 128).toImage()
    assert pixels.pixelColor(80, 46).red() > 230
    assert pixels.pixelColor(80, 46).green() < 30
    # The photo is smaller than the front-facing sleeve and biased to its right.
    left = pixels.pixelColor(34, 46)
    assert abs(left.red() - left.green()) < 12
    assert pixels.pixelColor(0, 0).alpha() == 0
    assert folders.icon(path).pixmap(128, 128, QIcon.Mode.Selected).toImage() == pixels
    assert not window.thumbnail_cache.peek(first).isNull()
    assert window.thumbnail_cache.peek(first).pixelColor(0, 0).red() > 230
    # Updating the existing first photo (not a directory membership change)
    # must refresh its shared thumbnail and the composite folder icon.
    Image.new("RGB", (48, 32), "blue").save(first)
    qtbot.waitUntil(
        lambda: path in folders.previews
        and folders.icon(path).pixmap(128, 128).toImage().pixelColor(80, 46).blue() > 230
    )
    earlier = album / "01-new.png"
    Image.new("RGB", (32, 24), "yellow").save(earlier)
    qtbot.waitUntil(lambda: folders.sources.get(path) == str(earlier))
    qtbot.waitUntil(
        lambda: folders.icon(path).pixmap(128, 128).toImage().pixelColor(80, 46).green() > 230
    )
    earlier.unlink()
    qtbot.waitUntil(lambda: folders.sources.get(path) == str(first))
    qtbot.waitUntil(
        lambda: folders.icon(path).pixmap(128, 128).toImage().pixelColor(80, 46).blue() > 230
    )
    window.plugins.disable("example.files")
    assert folders.stopped and not folders.preview_tokens
    assert not folders.watcher.files() and not folders.watcher.directories()
