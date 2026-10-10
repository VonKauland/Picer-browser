"""Exercise packaged external examples and their actual Qt widgets in Windows CI."""

import traceback
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QCursor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton, QStyleOptionSlider

from picer.panels import DOCK_AREAS
from picer.plugins.dialog import PluginDialog
from picer.settings import ApplicationSettings
from picer.ui import RoundedSlider


def verify_popups(window, browser):
    """Inspect actual popup windows in the frozen Windows application."""
    for menu in (window.main_menus[3], window.components.menus["function"]):
        menu.popup(window.mapToGlobal(QPoint(100, 100)))
        QTest.qWait(20)
        assert menu.isVisible()
        pixels = menu.grab().toImage()
        assert pixels.pixelColor(0, 0).alpha() == 0
        assert pixels.pixelColor(pixels.width() - 1, pixels.height() - 1).alpha() == 0
        assert menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        menu.hide()
    browser.sort.showPopup()
    QTest.qWait(20)
    popup = browser.sort.view().window()
    pixels = popup.grab().toImage()
    assert pixels.pixelColor(0, 0).alpha() == 0
    assert pixels.pixelColor(pixels.width() - 1, pixels.height() - 1).alpha() == 0
    QTest.keyClick(browser.sort.view(), Qt.Key.Key_Escape)
    assert not popup.isVisible()


def run(window, args, folder, done):
    try:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        first, second = folder / "1.png", folder / "2.jpg"
        image = QImage(80, 60, QImage.Format.Format_RGB32)
        image.fill(0x3399CC)
        assert image.save(str(first))
        exif = Image.Exif()
        exif[271] = "Picer Test Camera"
        exif[272] = "Frozen EXIF Test"
        Image.new("RGB", (80, 60), (51, 153, 204)).save(second, exif=exif)
        if window.plugins.get_setting("example.negative", "opened_count", 0) == 0:
            assert window.plugins.records["example.macos"].state == "disabled"
            assert all(not dock.isHidden() for dock in window.plugins.panels.values())
        assert all(
            not action.text().startswith("显示：")
            for action in window.components.menus["panel"].actions()
        )
        bottom = window.panel_hovers.controllers["example.progress"]
        assert bottom.dock.width() == window.width() // 3
        assert bottom.area == DOCK_AREAS["bottom"]
        for key in ("example.files", "example.info"):
            dock = window.plugins.panels[key]
            assert not (dock.allowedAreas() & DOCK_AREAS["bottom"])
            assert window.height() - 1 - dock.geometry().bottom() <= 1
        archives = (
            (args.plugin_archive, "example.negative"),
            (args.skin_archive, "example.macos"),
            (args.panel_archive, "example.info"),
            (args.file_panel_archive, "example.files"),
            (args.progress_panel_archive, "example.progress"),
        )
        for archive, plugin_id in archives:
            if archive:
                if plugin_id not in window.plugins.records:
                    assert window.plugins.install(Path(archive)) == plugin_id
                window.plugins.enable(plugin_id)
        negative = window.plugins.records.get("example.negative")
        count_before = negative.context.get_setting("opened_count", 0) if negative else 0
        if args.skin_archive:
            assert window.chrome_style == "macos"
            assert window.title_bar.controls.parent() is window.title_bar.right
        assert all(
            button.size().width() == button.size().height() == 32
            for button in window.title_bar.control_buttons.values()
        )
        assert all(dock.titleBarWidget().height() == 0 for dock in window.plugins.panels.values())
        for plugin_id in ("example.files", "example.info", "example.progress"):
            record = window.plugins.records.get(plugin_id)
            if record:
                assert all(
                    "设置" not in button.text() + button.toolTip() + button.accessibleName()
                    for button in record.instance.panel.findChildren(QPushButton)
                )
        if args.file_panel_archive:
            browser_record = window.plugins.records["example.files"]
            browser = browser_record.instance
            if count_before:
                assert browser_record.context.get_setting("home") == str(folder)
                assert browser_record.context.get_setting("icon_size") == 40
            management = PluginDialog(
                window.plugins, window, selected_id="example.files", open_settings=True
            )
            assert management.pages.currentIndex() == 1
            management.settings_form.editors["home"].setText(str(folder))
            management.settings_form.editors["icon_size"].setValue(40)
            management.save_settings()
            assert management.summary.text() == "设置已保存"
            management.close()
            management.deleteLater()
            assert browser.location.text() == str(folder.resolve())
            assert browser.tree.iconSize().width() == 40
            if count_before:
                assert window.app_preferences["zoom_step"] == 30
            application_settings = ApplicationSettings(window)
            assert application_settings.pages.count() == 6
            assert isinstance(application_settings.editors["glass_strength"], RoundedSlider)
            application_settings.editors["zoom_step"].setValue(30)
            application_settings.save()
            assert window.view.zoom_step == 30
            application_settings.deleteLater()
            verify_popups(window, browser)
        progress = (
            window.plugins.records["example.progress"].instance
            if args.progress_panel_archive
            else None
        )
        assert window.open_image(first)
        if progress:
            assert isinstance(progress.slider, RoundedSlider)
            progress.controls["next"].click()
        else:
            window.next_action.trigger()
        assert window.current_path == second.resolve()
        opened = 2
        if progress:
            assert progress.count.text() == "2/2"

            def drag_to(index):
                option = QStyleOptionSlider()
                progress.slider.initStyleOption(option)
                start = progress.slider.handle_rect(option).center().toPoint()
                option.sliderPosition = index
                target = progress.slider.handle_rect(option).center().toPoint()
                QTest.mousePress(progress.slider, Qt.MouseButton.LeftButton, pos=start)
                QTest.mouseMove(progress.slider, target)
                assert progress.slider.isSliderDown()
                assert window.current_path == window.paths[index]
                QTest.mouseRelease(progress.slider, Qt.MouseButton.LeftButton, pos=target)

            drag_to(0)
            assert window.current_path == first.resolve()
            drag_to(1)
            assert window.current_path == second.resolve()
            opened += 2
            settings = window.plugins.records["example.progress"].context
            if count_before:
                assert settings.get_setting("thumbnail_size") == 80
            management = PluginDialog(
                window.plugins, window, selected_id="example.progress", open_settings=True
            )
            management.settings_form.editors["thumbnail_size"].setValue(80)
            management.settings_form.editors["thumbnail_count"].setValue(3)
            management.save_settings()
            assert management.summary.text() == "设置已保存"
            management.close()
            management.deleteLater()
            progress.controls["slideshow"].click()
            assert progress.timer.isActive()
            progress.controls["slideshow"].click()
            assert not progress.timer.isActive()
        window.actual_action.trigger()
        window.zoom_in_action.trigger()
        assert window.view.transform().m11() > 1
        window.rotate_action.trigger()
        assert window.view.image_item.pixmap().width() == 60
        if progress:
            progress.controls["rotate"].click()
            assert window.view.image_item.pixmap().width() == 80
        assert window.title_bar.caption.text() == second.name
        assert not window.windowIcon().isNull()
        assert window.plugins.state_file.is_file() and window.plugins.log_file.is_file()
        assert any(window.thumbnail_cache.directory.glob("*.png"))
        assert len(window.title_bar.quick_slots) == 5
        window.toggle_fullscreen()
        assert all(dock.isHidden() for dock in window.plugins.panels.values())
        window.exit_fullscreen()
        assert all(not dock.isHidden() for dock in window.plugins.panels.values())

        def guarded(callback):
            try:
                callback()
            except Exception:
                traceback.print_exc()
                done(1)

        def metadata_ready():
            if window.plugins.jobs:
                QTimer.singleShot(25, lambda: guarded(metadata_ready))
                return
            if args.panel_archive:
                info = window.plugins.records["example.info"].instance
                if info.metadata is None:
                    QTimer.singleShot(25, lambda: guarded(metadata_ready))
                    return
                assert info.metadata is not None
                assert info.metadata["dimensions"]["宽度"] == "80"
                assert "Picer Test Camera" in info.exif_text.toPlainText()
                assert not info.exif_box.isHidden()
                assert len(info.histogram.channels) == 3
                window.panel_hovers.controllers["example.info"].resize_extent(220)
                QTest.qWait(50)
                assert info.scroll.widget().width() <= info.scroll.viewport().width()
                assert info.scroll.horizontalScrollBar().maximum() == 0
                assert info.exif_text.horizontalScrollBar().maximum() == 0
            if args.file_panel_archive:
                index = browser.model.index(str(first))
                browser.model.data(index, Qt.ItemDataRole.DecorationRole)
                if not any(key[0] == str(first) for key in browser.model.cache):
                    QTimer.singleShot(25, lambda: guarded(metadata_ready))
                    return
                thumbnail = (
                    browser.model.data(index, Qt.ItemDataRole.DecorationRole)
                    .pixmap(32, 32)
                    .toImage()
                )
                assert (
                    thumbnail.pixelColor(thumbnail.width() // 2, thumbnail.height() // 2).blue()
                    > 150
                )
                browser.view_button.click()
                assert browser.views.currentWidget() is browser.tiles
                browser.view_button.click()
                assert browser.views.currentWidget() is browser.tree
            if progress:
                progress.show_preview()
                QTimer.singleShot(25, lambda: guarded(preview_ready))
            else:
                invert()

        def preview_ready():
            if window.plugins.jobs:
                QTimer.singleShot(25, lambda: guarded(preview_ready))
                return
            assert len(progress.preview.items) == 2, (
                len(progress.preview.items),
                progress.preview.isVisible(),
                progress.dock.isHidden(),
                progress.controls["previous"].height(),
            )
            assert progress.preview.thumbnail_size == 80
            assert progress.preview.width() == progress.dock.width()
            assert progress.controls["previous"].height() == 20
            assert progress.dock.height() < 65
            pixels = progress.preview.grab().toImage()
            assert pixels.pixelColor(pixels.width() // 2, 0).alpha() == 0
            assert pixels.pixelColor(0, pixels.height() // 2).alpha() == 0
            QTest.mouseClick(window.view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(30, 30))
            assert progress.preview.isVisible()
            progress.dock.close()
            controller = window.panel_hovers.controllers["example.progress"]
            controller.collapse(immediate=True)
            progress.preview.reposition()
            assert progress.preview.isVisible()
            assert progress.preview.geometry().bottom() == window.height() - 9
            controller.pin()
            progress.controls["preview"].click()
            assert not progress.preview.isVisible()
            invert()

        def invert():
            if negative:
                assert negative.context.get_setting("opened_count") == count_before + opened
                if count_before:
                    assert window.components.assignments()[4] == "example.negative:negative"
                window.components.assign(4, "example.negative:negative")
                before = window.view.image_item.pixmap().toImage().pixelColor(0, 0)
                window.title_bar.quick_slots[4].click()
                QTimer.singleShot(25, lambda: guarded(lambda: inversion_ready(before)))
            else:
                hover()

        def inversion_ready(before):
            if window.plugins.jobs:
                QTimer.singleShot(25, lambda: guarded(lambda: inversion_ready(before)))
                return
            after = window.view.image_item.pixmap().toImage().pixelColor(0, 0)
            assert (after.red(), after.green(), after.blue()) == (
                255 - before.red(),
                255 - before.green(),
                255 - before.blue(),
            )
            assert negative.state == "enabled"
            window.plugins.disable("example.negative")
            assert window.title_bar.quick_slots[4].defaultAction() is None
            hover()

        def hover():
            if not args.file_panel_archive:
                done(0)
                return
            controller = window.panel_hovers.controllers["example.files"]
            controller.dock.close()
            assert controller.strip.isVisible()
            assert min(controller.strip.width(), controller.strip.height()) == 5
            QCursor.setPos(window.mapToGlobal(controller.bounds().center()))
            controller.reveal()
            QTimer.singleShot(550, lambda: guarded(lambda: expanded(controller)))

        def expanded(controller):
            assert controller.popup is not None and controller.progress >= 0.99
            assert controller.dock.isHidden()
            controller.collapse()
            QTimer.singleShot(400, lambda: guarded(lambda: collapsed(controller)))

        def collapsed(controller):
            assert controller.popup is None and controller.dock.widget() is not None
            # Drag the hidden strip using actual mouse events, then click it during reveal to pin.
            strip = controller.strip
            QTest.mousePress(strip, Qt.MouseButton.LeftButton, pos=strip.rect().center())
            target = QPoint(window.width() - 5, window.height() // 2)
            QTest.mouseMove(strip, strip.mapFrom(window, target))
            QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, pos=strip.mapFrom(window, target))
            assert controller.area == DOCK_AREAS["right"]
            assert controller.dock.isHidden()
            assert window.plugins.preferences["ui"]["panels"]["example.files"] is False
            controller.reveal()
            QTest.mouseClick(strip, Qt.MouseButton.LeftButton, pos=strip.rect().center())
            assert not controller.dock.isHidden() and controller.popup is None
            assert window.plugins.preferences["ui"]["panels"]["example.files"] is True
            controller.move_to(DOCK_AREAS["left"])
            QTest.qWait(50)
            grip = controller.dock.widget().grip
            start = grip.rect().center()
            before_width = controller.dock.width()
            QTest.mousePress(grip, Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(grip, start + QPoint(50, 0))
            QTest.mouseRelease(grip, Qt.MouseButton.LeftButton, pos=grip.rect().center())
            QTest.qWait(50)
            assert controller.dock.width() >= before_width + 40
            assert (
                window.plugins.preferences["ui"]["panel_layouts"]["example.files"]["area"] == "left"
            )
            assert not window.glass.image.isNull()
            print(
                "Packaged examples: file tree, settings, metadata/EXIF, histogram, progress, "
                "thumbnails, embedded/app settings, transparent popups/rounded sliders, "
                "macOS isolation, glass, hover morph, "
                "hidden-strip drag/pin and grips passed"
            )
            done(0)

        QTimer.singleShot(25, lambda: guarded(metadata_ready))
    except Exception:
        traceback.print_exc()
        done(1)
