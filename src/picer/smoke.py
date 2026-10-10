"""Exercise packaged external examples and their actual Qt widgets in Windows CI."""

import traceback
from pathlib import Path
from time import sleep

from PIL import Image
from PySide6.QtCore import QElapsedTimer, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QCursor, QImage, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu, QPushButton, QStyleOptionSlider

from picer.panels import DOCK_AREAS
from picer.plugins.dialog import PluginDialog
from picer.progress_ring import RING_SIZE
from picer.settings import ApplicationSettings
from picer.smoke_samples import make_animation, make_dng
from picer.ui import RoundedSlider, colors_for


def wait_for(predicate, timeout=3000):
    deadline = QElapsedTimer()
    deadline.start()
    while not predicate() and deadline.elapsed() < timeout:
        QTest.qWait(20)
        # Native Qt waits can repeatedly retain/reacquire Python's GIL on
        # Windows. Yield explicitly so cold decoder imports and Python worker
        # callbacks can progress while this nested smoke loop polls the GUI.
        sleep(0.001)
    assert predicate()


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


def verify_browser(window, browser, folder):
    """Exercise breadcrumb targets and Ctrl-wheel in the actual frozen EXE."""
    child = folder / "child"
    child.mkdir(exist_ok=True)
    sample = QImage(12, 12, QImage.Format.Format_RGB32)
    sample.fill(0x778899)
    assert sample.save(str(child / "sample.png"))
    bar = browser.location
    bar.start_edit()
    bar.editor.setText(str(child))
    QTest.keyClick(bar.editor, Qt.Key.Key_Return)
    assert bar.text() == str(child) and bar.stack.currentWidget() is bar.row
    parent = next(button for button in bar.buttons if button.target == folder)
    if parent.isVisible():
        QTest.mouseClick(parent, Qt.MouseButton.LeftButton)
    else:
        QTest.mouseClick(bar.overflow, Qt.MouseButton.LeftButton)
        menu = bar.findChild(QMenu)
        assert menu and menu.isVisible()
        next(action for action in menu.actions() if action.toolTip() == str(folder)).trigger()
        menu.hide()
    assert bar.text() == str(folder)
    for mode in ("list", "tiles"):
        browser.context.set_setting("view", mode)
        browser.apply_view()
        view = browser.views.currentWidget()
        window.activateWindow()
        view.setFocus()
        QTest.qWait(30)
        assert view.hasFocus()
        wait_for(lambda view=view: view.visualRect(browser.model.index(str(child))).isValid())
        pos = view.visualRect(browser.model.index(str(child))).center()
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=pos)
        assert bar.text() == str(folder)
        QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=pos)
        assert bar.text() == str(child)
        QTest.mouseClick(view.viewport(), Qt.MouseButton.BackButton)
        assert bar.text() == str(folder)
        QTest.mouseClick(view.viewport(), Qt.MouseButton.ForwardButton)
        assert bar.text() == str(child)
        QTest.keyClick(view, Qt.Key.Key_Backspace)
        assert bar.text() == str(folder)
        browser.open_folder(child)
        QTest.mouseClick(browser.parent_entry, Qt.MouseButton.LeftButton)
        assert bar.text() == str(child)
        QTest.mouseDClick(browser.parent_entry, Qt.MouseButton.LeftButton)
        assert bar.text() == str(folder)
        view.setFocus()
        for delta, expected in ((120, 44), (-120, 40)):
            target = view.viewport()
            pos = target.rect().center()
            event = QWheelEvent(
                QPointF(pos),
                QPointF(target.mapToGlobal(pos)),
                QPoint(),
                QPoint(0, delta),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.ControlModifier,
                Qt.ScrollPhase.NoScrollPhase,
                False,
            )
            QApplication.sendEvent(target, event)
            assert browser.tree.iconSize().width() == expected
            assert browser.tiles.iconSize().width() == expected * 2
            assert browser.context.get_setting("icon_size") == expected
            assert bar.text() == str(folder)
    browser.context.set_setting("view", "list")
    browser.apply_view()
    index = browser.model.index(str(child))
    browser.tree.setCurrentIndex(index)
    browser.tree.setFocus()
    QTest.qWait(50)
    row = browser.tree.visualRect(browser.model.index(str(child)))
    assert row.isValid()
    pixels = browser.tree.viewport().grab().toImage()
    for y in range(row.top(), row.bottom() + 1):
        for x in range(browser.tree.indentation()):
            color = pixels.pixelColor(x, y)
            channels = (color.red(), color.green(), color.blue())
            assert min(channels) < 210 and color.blue() <= max(color.red(), color.green()) + 20
    wait_for(lambda: browser.model.rowCount(browser.tree.rootIndex()) == 3)
    assert browser.model.isDir(browser.model.index(0, 0, browser.tree.rootIndex()))
    browser.model.data(browser.model.index(str(child)), Qt.ItemDataRole.DecorationRole)
    wait_for(lambda: browser.model.files.folders.cache.get(str(child)) is True)
    browser.view_button.click()
    QTest.qWait(20)
    assert browser.quick_menu.isVisible()
    pixels = browser.quick_menu.grab().toImage()
    assert pixels.pixelColor(0, 0).alpha() == 0
    browser.quick_actions["favorite"].trigger()
    browser.quick_menu.hide()
    browser.tabs.setCurrentIndex(1)
    assert browser.favorites.count() >= 1
    assert browser.context.get_setting("favorites") == [str(folder)]
    browser.tabs.setCurrentIndex(2)
    assert browser.recent.count() >= 2
    browser.open_folder(Path(folder.anchor))
    QTest.keyClick(browser.tree, Qt.Key.Key_Backspace)
    assert bar.text() == "" and browser.parent_entry.isHidden()
    assert bar.buttons[0].label == "此电脑"
    wait_for(lambda: browser.model.rowCount(browser.tree.rootIndex()) > 0)
    browser.go_back()
    assert bar.text() == str(Path(folder.anchor))
    browser.open_folder(folder)
    browser.sort.setCurrentIndex(browser.sort.findData("modified"))
    browser.set_descending(True)
    browser.open_folder(child)
    wait_for(lambda: browser.model.files.folders.cache.get(str(child)) is True)
    assert browser.current_order() == ("name", False)
    browser.go_up()
    wait_for(
        lambda: browser.model.filePath(browser.tree.currentIndex()) == str(child).replace("\\", "/")
    )
    assert browser.current_order() == ("modified", True)
    print(
        "Browser local favorites/recent history, disk list, per-folder sorting "
        "and return selection; "
        "glass folders, directory ordering, double-click/side-key/Backspace, "
        "breadcrumbs and Ctrl-wheel checks passed"
    )


def verify_media(window):
    """Exercise wheel-packaged LibRaw/Pillow plus actual animated panel controls."""
    directory = window.paths_layout.cache / "smoke-media"
    directory.mkdir(parents=True, exist_ok=True)
    previous = window.current_path
    progress = window.plugins.records["example.progress"].instance
    for extension in ("gif", "webp"):
        path = directory / f"motion.{extension}"
        make_animation(path)
        assert window.open_image(path)
        wait_for(lambda: window.animation.state.active)
        assert window.animation.state.count == 3
        wait_for(lambda: window.animation.state.frame > 0)
        window.animation.toggle(False)
        progress.playback_slider.setValue(2)
        wait_for(lambda: window.animation.state.duration == 190)
        assert window.view.image_item.pixmap().toImage().pixelColor(30, 30).blue() > 240
        wait_for(lambda: progress.playback_expansion == 1)
        assert not progress.playback.isHidden() and progress.dock.height() == 100
        controller = window.panel_hovers.controllers["example.progress"]
        assert not controller.dock.widget().uses_glass()
        controller.dock.close()
        window.panel_hovers.layout_strips()
        assert controller.strip.isVisible() and controller.strip.width() == RING_SIZE
        assert abs(controller.strip.geometry().center().x() - window.rect().center().x()) <= 1
        pixels = controller.strip.grab().toImage()
        assert pixels.pixelColor(12, 12).alpha() == 0
        assert pixels.pixelColor(12, 6).blue() > 150
        progress.show_preview()
        wait_for(lambda: progress.expansion == 1)
        assert progress.preview.isVisible()
        assert controller.strip.geometry().right() < progress.preview.geometry().left()
        assert (
            abs(controller.strip.geometry().center().y() - progress.preview.geometry().center().y())
            <= 1
        )
        progress.show_preview()
        wait_for(lambda: not progress.preview.isVisible())
        controller.pin()
        progress.playback_button.click()
        assert window.animation.state.playing
        progress.playback_button.click()
        assert not window.animation.state.playing
        assert window.open_image(previous)
        wait_for(lambda: progress.playback_expansion == 0)
        assert progress.playback.isHidden()
        controller.dock.close()
        window.panel_hovers.layout_strips()
        assert controller.strip.grab().toImage().pixelColor(12, 6).alpha() == 0
        controller.pin()
    print(
        "Packaged tiny image/frame rings, thumbnail anchoring and static inner-ring removal passed"
    )
    raw = directory / "synthetic.dng"
    make_dng(raw)
    raw = raw.resolve()
    assert window.open_image(raw)
    try:
        wait_for(lambda: window.current_path == raw, timeout=10_000)
    except AssertionError:
        import faulthandler

        faulthandler.dump_traceback()
        print(
            "RAW load diagnostics",
            {
                "expected": str(raw),
                "current": str(window.current_path),
                "requested": str(window.loader.requested),
                "error": window.last_error,
                "generation": window.loader.generation,
                "jobs": [
                    (lane, worker.token.cancelled)
                    for worker, lane, _ in window.loader.jobs.values()
                ],
                "threads": {
                    name: pool.activeThreadCount() for name, pool in window.loader.pools.items()
                },
            },
            flush=True,
        )
        raise
    wait_for(lambda: window.view.image_item.pixmap().width() == 256, timeout=10_000)
    assert window.open_image(previous)
    print(
        "Packaged LibRaw DNG decode, GIF/WebP playback/seek/pause and animated playback row passed"
    )


def run(window, args, folder, done):
    try:
        # Windows TEMP can contain 8.3 aliases (RUNNER~1); the Qt model and
        # viewer use resolved paths, so compare the same canonical directory.
        folder = Path(folder).resolve()
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
                    if button is not getattr(record.instance, "view_button", None)
                )
        if args.file_panel_archive:
            browser_record = window.plugins.records["example.files"]
            browser = browser_record.instance
            if count_before:
                assert browser_record.context.get_setting("home") == str(folder)
                assert browser_record.context.get_setting("icon_size") == 40
                assert browser_record.context.get_setting("favorites") == [str(folder)]
                assert str(folder / "child") in browser_record.context.get_setting("recent_folders")
                assert browser_record.context.get_setting("folder_orders")[str(folder)] == {
                    "sort": "modified",
                    "descending": True,
                }
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
                assert window.app_preferences["accent_color"] == "#FFA591"
            application_settings = ApplicationSettings(window)
            assert application_settings.pages.count() == 6
            assert isinstance(application_settings.editors["glass_strength"], RoundedSlider)
            application_settings.editors["zoom_step"].setValue(30)
            application_settings.editors["accent_color"].setValue("#ffa591")
            application_settings.save()
            assert window.view.zoom_step == 30
            assert window.skin_colors["accent"] == "#FFA591"
            assert colors_for(browser.tree)["accent"] == "#FFA591"
            assert window.skin_colors["background"] != colors_for(browser.tree)["background"]
            assert "#FFA591" in browser.parent_entry.styleSheet()
            print("Packaged custom accent save/restart and macOS plugin isolation passed")
            application_settings.deleteLater()
            verify_popups(window, browser)
            verify_browser(window, browser, folder)
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
        wait_for(lambda: any(window.thumbnail_cache.directory.glob("*.png")))
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
                print(
                    "Waiting for tasks",
                    [(job.plugin_id, job.token.cancelled) for job in window.plugins.jobs.values()],
                    flush=True,
                )
                QTimer.singleShot(25, lambda: guarded(metadata_ready))
                return
            if args.panel_archive:
                info = window.plugins.records["example.info"].instance
                if info.metadata is None:
                    print(
                        "Waiting for image metadata",
                        window.plugins.records["example.info"].state,
                        info.read_timer.isActive(),
                        flush=True,
                    )
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
                if not any(Path(key[0]) == first for key in browser.model.cache):
                    print(
                        "Waiting for file thumbnail",
                        str(first),
                        index.isValid(),
                        browser.model.busy,
                        tuple(browser.model.pending),
                        tuple(browser.model.cache),
                        flush=True,
                    )
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
                browser.quick_actions["tiles"].trigger()
                assert browser.views.currentWidget() is browser.tiles
                browser.quick_actions["list"].trigger()
                assert browser.views.currentWidget() is browser.tree
            if progress:
                progress.show_preview()
                QTimer.singleShot(25, lambda: guarded(preview_ready))
            else:
                invert()

        def preview_ready():
            if window.plugins.jobs or progress.expansion < 1:
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
            wait_for(lambda: not progress.preview.isVisible())
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
                verify_media(window)
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
            assert controller.popup.uses_glass() and window.glass.active()
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
            assert not controller.dock.widget().uses_glass()
            assert not window.glass.active()
            print(
                "Packaged examples: file tree, settings, metadata/EXIF, histogram, progress, "
                "thumbnails, embedded/app settings, transparent popups/rounded sliders, "
                "macOS isolation, glass, hover morph, "
                "hidden-strip drag/pin and grips passed"
            )
            verify_media(window)
            done(0)

        QTimer.singleShot(25, lambda: guarded(metadata_ready))
    except Exception:
        traceback.print_exc()
        done(1)
