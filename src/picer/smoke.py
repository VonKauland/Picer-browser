"""Exercise packaged external examples and their actual Qt widgets in Windows CI."""

import traceback
from pathlib import Path
from threading import Event, Thread
from time import sleep

from PIL import Image
from PySide6.QtCore import QElapsedTimer, QMimeData, QPoint, QPointF, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QIcon,
    QImage,
    QWheelEvent,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame, QMenu, QPushButton, QStyleOptionSlider

from picer.color_picker import ColorPicker
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


def verify_image_drop(window, path):
    """Exercise the frozen Qt viewport's complete drag/drop route."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    before = path.read_bytes()
    for event in (
        QDragEnterEvent(
            QPoint(20, 20),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
        QDragMoveEvent(
            QPoint(30, 30),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
        QDropEvent(
            QPointF(30, 30),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    ):
        QApplication.sendEvent(window.view.viewport(), event)
        assert event.isAccepted() and event.dropAction() == Qt.DropAction.CopyAction
    wait_for(lambda: window.current_path == path.resolve())
    assert window.view.image_item.pixmap().toImage().pixelColor(10, 10).blue() == 204
    assert path.read_bytes() == before
    print("Packaged viewport enter/move/drop opens image and preserves source passed")


def verify_color_picker(settings):
    editor = settings.editors["accent_color"]
    previous = editor.value()
    seen = []

    def interact():
        try:
            picker = QApplication.activeModalWidget()
            assert isinstance(picker, ColorPicker)
            QTest.mouseClick(picker.swatches[3], Qt.MouseButton.LeftButton)
            assert picker.hex.text() == "#79B8FF"
            picker.set_color(QColor("#FFA591"))
            assert [spin.value() for spin in picker.rgb] == [255, 165, 145]
            assert picker.grab().toImage().pixelColor(0, 0).alpha() == 0
            pixels = picker.grab().toImage()
            origin = picker.swatches[0].mapTo(picker, QPoint())
            scale = pixels.devicePixelRatio()
            corner = pixels.pixelColor(round(origin.x() * scale), round(origin.y() * scale))
            center = pixels.pixelColor(
                round((origin.x() + 16) * scale), round((origin.y() + 16) * scale)
            )
            assert corner.name().upper() != "#E8FF59"
            assert center.name().upper() == "#E8FF59"
            QTest.mouseClick(picker.apply, Qt.MouseButton.LeftButton)
            seen.append(True)
        except Exception:
            traceback.print_exc()
            if QApplication.activeModalWidget():
                QApplication.activeModalWidget().reject()

    QTimer.singleShot(50, interact)
    editor.choose()
    assert seen and editor.value() == "#FFA591"
    assert settings.host.app_preferences["accent_color"] == previous
    print("Packaged custom rounded HSV picker, swatches, RGB/HEX and explicit save passed")


def verify_system_settings(window):
    """Exercise topmost modeless apply/reset/import in the real frozen application."""
    from picer.confirmation import Confirmation
    from picer.settings_backup import read_backup, snapshot, write_backup

    assert [a.text() for a in window.title_bar.menu.actions()] == [
        "文件",
        "编辑",
        "视图",
        "插件",
        "选项",
        "帮助",
    ]
    assert window.settings_action not in window.main_menus[1].actions()
    saved = snapshot(window)
    path = window.paths_layout.cache / "settings-smoke.json"
    write_backup(path, window)
    assert read_backup(path, window) == saved
    dialog = window.show_settings()
    assert window.show_settings() is dialog and not dialog.isModal()
    assert dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert QApplication.activeModalWidget() is None
    dialog.editors["zoom_step"].setValue(45)
    QTest.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)
    assert dialog.isVisible() and window.view.zoom_step == 45
    before = window.current_path
    window.activateWindow()
    window.view.setFocus()
    wait_for(window.isActiveWindow)
    QTest.keyClick(window.view, Qt.Key.Key_Right)
    assert window.current_path != before and dialog.isVisible()
    dialog.editors["zoom_step"].setValue(60)
    cancelled = []

    def cancel_reset():
        confirmation = QApplication.activeModalWidget()
        try:
            assert isinstance(confirmation, Confirmation)
            assert confirmation.cancel_button.isDefault()
            assert confirmation.grab().toImage().pixelColor(0, 0).alpha() == 0
            cancelled.append(True)
        finally:
            if confirmation:
                confirmation.reject()

    QTimer.singleShot(50, cancel_reset)
    dialog.reset()
    assert cancelled and dialog.editors["zoom_step"].value() == 60
    dialog.load_backup(read_backup(path, window))
    assert window.view.zoom_step == 45
    dialog.apply()
    assert dialog.isVisible() and window.view.zoom_step == saved["application"]["zoom_step"]
    assert snapshot(window) == saved
    dialog.reject()
    assert window.settings_dialog is None
    window.activateWindow()
    window.view.setFocus()
    print(
        "Packaged Options menu, topmost modeless main-key routing, Apply persistence, "
        "reset cancellation and JSON settings roundtrip passed"
    )
    verify_formats_and_shell(window)


def verify_formats_and_shell(window):
    """Check frozen capability filtering and actual isolated HKCU registrations."""
    import sys
    from uuid import uuid4

    from picer.windows_integration import CAPABILITIES, PROG_ID, WindowsIntegration

    menu = window.image_context_menu()
    assert menu.actions()[0] is window.copy_image_action
    menu.actions()[1].trigger()
    assert QApplication.clipboard().text() == str(window.current_path)
    menu.popup(window.mapToGlobal(QPoint(250, 100)))
    QTest.qWait(20)
    assert menu.grab().toImage().pixelColor(0, 0).alpha() == 0
    menu.hide()
    menu.deleteLater()
    dialog = window.show_settings()
    dialog.navigation.setCurrentRow(6)
    selection = dialog.editors["readable_formats"]
    saved = selection.value()
    selection.setValue([".png"])
    dialog.apply()
    assert window.supported_suffixes == {".png"}
    assert not window.open_image(window.paths_layout.cache / "disabled.jpg")
    assert "格式未启用" in window.last_error
    selection.setValue(saved)
    dialog.apply()
    dialog.reject()
    if sys.platform == "win32":
        executable = Path(sys.executable).resolve()
        root = r"Software\PicerIntegrationTests" + "\\" + uuid4().hex
        service = WindowsIntegration(executable, root=root)
        try:
            service.register_viewer([".png", ".jpg", ".dng"])
            service.register_context_menu([".png", ".jpg", ".dng"])
            command = f'"{executable}" "%1"'
            assert service.read(service.menu_key(".png") + r"\command", "") == command
            assert service.read(CAPABILITIES + r"\FileAssociations", ".dng") == PROG_ID
            assert service.read(r"Software\Classes\Picer.Image\shell\open\command", "") == command
            service.register_context_menu([".png"])
            assert service.read(service.menu_key(".jpg"), "") is None
            service.remove_context_menu()
            assert service.read(service.menu_key(".png"), "") is None
        finally:
            service.delete("")
        print("Packaged EXE per-user native registry commands and cleanup passed (isolated HKCU)")
    print("Packaged image context menu and live format filtering passed")
    from picer.about import POEM, AboutDialog

    checked = []

    def close_about():
        dialog = QApplication.activeModalWidget()
        try:
            assert isinstance(dialog, AboutDialog)
            assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
            assert dialog.poem.accessibleName() == POEM
            assert "Windows x64" in dialog.version.text() if sys.platform == "win32" else True
            assert dialog.close_button.size().width() == 32
            assert dialog.grab().toImage().pixelColor(0, 0).alpha() == 0
            checked.append(True)
        finally:
            if dialog:
                dialog.done_button.click()

    QTimer.singleShot(50, close_about)
    window.show_about()
    assert checked
    print("Packaged custom About title bar, transparent corners, accent pixels and acrostic passed")


def verify_popups(window, browser):
    """Inspect actual popup windows in the frozen Windows application."""
    dialog = window.show_settings()
    dialog.navigation.setCurrentRow(1)
    combo = dialog.editors["density"]
    combo.showPopup()
    QTest.qWait(30)
    popup = combo.view().window()
    assert popup.frameShape() == QFrame.Shape.NoFrame
    pixels = popup.grab().toImage()
    ratio = pixels.devicePixelRatio()
    for x, y in (
        (0, 0),
        (popup.width() - 1, 0),
        (0, popup.height() - 1),
        (popup.width() - 1, popup.height() - 1),
    ):
        assert pixels.pixelColor(round(x * ratio), round(y * ratio)).alpha() == 0
    combo.hidePopup()
    dialog.navigation.setCurrentRow(4)
    tabs = dialog.binding_editor.tabs.tabBar()
    QTest.mouseMove(tabs, tabs.tabRect(3).center())
    QTest.qWait(30)
    image = dialog.grab().toImage()
    for corner in (tabs.tabRect(3).topLeft(), tabs.tabRect(3).topRight()):
        point = tabs.mapTo(dialog, corner)
        assert image.pixelColor(
            round(point.x() * image.devicePixelRatio()), round(point.y() * image.devicePixelRatio())
        ) == QColor(window.skin_colors["menu"])
    dialog.reject()
    print("Packaged real settings dropdown native-frame removal and transparent tab backing passed")
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
    folders = browser.model.files.folders
    wait_for(lambda: str(child) in folders.previews)
    source = Path(folders.sources[str(child)])
    assert source.parent == child and not window.thumbnail_cache.peek(source).isNull()
    normal = folders.icon(str(child)).pixmap(128, 128).toImage()
    assert normal.pixelColor(0, 0).alpha() == 0
    assert normal == folders.icon(str(child)).pixmap(128, 128, QIcon.Mode.Selected).toImage()
    print("Packaged frontal frosted folder first-photo card and shared cache passed")
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


def verify_shared_thumbnails(window, folder):
    import picer.cache as cache_module
    from picer.cache import ThumbnailCache

    source = folder.parent / "缩略图共享缓存检查.png"
    if not source.exists():
        image = QImage(320, 200, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.blue)
        assert image.save(str(source))
    original = cache_module.read_image
    decoded = []

    def read(path, **kwargs):
        if Path(path) == source:
            decoded.append(path)
        return original(path, **kwargs)

    cache_module.read_image = read
    try:
        results = []
        for plugin_id, edge in (("example.files", 128), ("example.progress", 80)):
            window.plugins.records[plugin_id].context.request_thumbnail(
                source, results.append, edge=edge
            )
        wait_for(lambda: len(results) == 2)
        assert sorted(image.width() for image in results) == [80, 128]
        assert all(image.pixelColor(10, 10).blue() == 255 for image in results)
        assert len(decoded) <= 1
        before = len(decoded)
        reopened = ThumbnailCache(window.paths_layout.cache)
        assert reopened.read(source, edge=80).pixelColor(10, 10).blue() == 255
        assert len(decoded) == before
        canceled = []
        token = window.plugins.records["example.progress"].context.request_thumbnail(
            source, canceled.append
        )
        token.cancel()
        wait_for(lambda: token.finished)
        assert not canceled
        print("Packaged shared thumbnail decode, disk reuse and cancellation passed")
    finally:
        cache_module.read_image = original


def verify_held_keys(window):
    previous = window.current_path
    window.activateWindow()
    window.view.setFocus()
    wait_for(window.isActiveWindow)
    QTest.keyPress(window.view, Qt.Key.Key_Right)
    try:
        assert not window.loader.rapid and window.current_path != previous
        assert window.navigation_keys.delay.isActive()
        wait_for(lambda: window.loader.rapid)
        wait_for(lambda: window.current_path == previous)
    finally:
        QTest.keyRelease(window.view, Qt.Key.Key_Right)
    assert not window.navigation_keys.timer.isActive() and not window.loader.rapid
    QTest.qWait(window.app_preferences["key_repeat_ms"] + 40)
    assert window.current_path == previous
    print("Packaged held-key millisecond interval, release and saved repeat setting passed")


def open_animation_with_cache_io_blocked(window, path):
    entered, release = Event(), Event()

    def disk_maintenance():
        with window.thumbnail_cache._disk_lock:
            entered.set()
            release.wait(10)

    thread = Thread(target=disk_maintenance)
    thread.start()
    try:
        assert entered.wait(3)
        assert window.open_image(path)
        wait_for(lambda: window.animation.state.active)
        wait_for(lambda: window.animation.state.frame > 0)
        assert not release.is_set() and thread.is_alive()
        images = []
        window.plugins.records["example.progress"].context.request_thumbnail(path, images.append)
        wait_for(lambda: bool(images))
        assert not images[0].isNull() and thread.is_alive()
        print(
            f"Packaged {path.suffix} startup, frames and shared thumbnail "
            "with blocked cache IO passed"
        )
    finally:
        release.set()
        thread.join(5)


def verify_media(window):
    """Exercise wheel-packaged LibRaw/Pillow plus actual animated panel controls."""
    verify_held_keys(window)
    directory = window.paths_layout.cache / "smoke-media"
    directory.mkdir(parents=True, exist_ok=True)
    previous = window.current_path
    progress = window.plugins.records["example.progress"].instance
    for extension in ("gif", "webp"):
        path = directory / f"motion.{extension}"
        make_animation(path)
        open_animation_with_cache_io_blocked(window, path)
        assert window.animation.state.count == 3
        wait_for(lambda: window.animation.state.frame > 0)
        window.animation.toggle(False)
        wait_for(lambda: progress.playback_expansion == 1)
        progress.playback_slider.setValue(0)
        slider = progress.playback_slider
        QTest.mouseClick(
            slider, Qt.MouseButton.LeftButton, pos=QPoint(slider.width() // 2, slider.height() // 2)
        )
        assert window.animation.state.frame == 1
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
        assert controller.indicator.isVisible() and controller.indicator.size().height() == 5
        assert controller.strip.geometry().bottom() < controller.indicator.geometry().top()
        assert abs(controller.strip.geometry().center().x() - window.rect().center().x()) <= 1
        assert f"/{len(window.paths)}" in controller.strip.toolTip()
        old_top = controller.strip.y()
        controller.reveal()
        controller.animation.setCurrentTime(controller.OPEN_MS)
        assert controller.strip.y() < old_top
        assert controller.strip.geometry().bottom() < controller.popup.geometry().top()
        controller.collapse(immediate=True)
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
    info = window.plugins.records["example.info"].instance
    wait_for(
        lambda: info.metadata is not None and info.metadata["path"] == str(raw), timeout=10_000
    )
    assert info.metadata["exif_sections"]["基础信息"]["相机制造商"] == "Picer RAW Camera"
    assert not info.exif_box.isHidden() and "Picer RAW Camera" in info.exif_view.text()
    print("Packaged RAW EXIF camera table passed")
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
        assert list(window.title_bar.control_buttons) == [
            "fullscreen",
            "minimize",
            "maximize",
            "close",
        ]
        window.title_bar.control_buttons["fullscreen"].click()
        assert window.isFullScreen()
        window.title_bar.control_buttons["fullscreen"].click()
        assert not window.isFullScreen()
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
                assert window.app_preferences["key_repeat_ms"] == 160
            application_settings = ApplicationSettings(window)
            assert application_settings.pages.count() == 7
            assert isinstance(application_settings.editors["glass_strength"], RoundedSlider)
            application_settings.editors["zoom_step"].setValue(30)
            application_settings.editors["key_repeat_ms"].setValue(160)
            verify_color_picker(application_settings)
            application_settings.save()
            assert window.view.zoom_step == 30
            assert window.app_preferences["key_repeat_ms"] == 160
            assert window.skin_colors["accent"] == "#FFA591"
            assert colors_for(browser.tree)["accent"] == "#FFA591"
            assert window.skin_colors["background"] != colors_for(browser.tree)["background"]
            assert "#FFA591" in browser.parent_entry.styleSheet()
            print("Packaged custom accent save/restart and macOS plugin isolation passed")
            application_settings.deleteLater()
            verify_popups(window, browser)
            verify_browser(window, browser, folder)
            if args.progress_panel_archive:
                verify_shared_thumbnails(window, folder)
        progress = (
            window.plugins.records["example.progress"].instance
            if args.progress_panel_archive
            else None
        )
        verify_image_drop(window, first)
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
            assert "thumbnail_count" not in management.settings_form.editors
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
                assert "Picer Test Camera" in info.exif_view.text()
                assert not info.exif_box.isHidden()
                assert len(info.histogram.channels) == 3
                assert not info.exif_view.details.isVisible()
                before_height = info.exif_view.height()
                info.exif_view.button.click()
                wait_for(lambda: info.exif_view.fraction == 1)
                assert info.exif_view.height() > before_height
                assert "相机制造商" in info.exif_view.text()
                info.exif_view.button.click()
                wait_for(lambda: info.exif_view.fraction == 0)
                window.panel_hovers.controllers["example.info"].resize_extent(220)
                QTest.qWait(50)
                assert info.scroll.widget().width() <= info.scroll.viewport().width()
                assert info.scroll.horizontalScrollBar().maximum() == 0
                assert info.exif_view.scroll.horizontalScrollBar().maximum() == 0
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
            if (
                window.plugins.jobs
                or progress.expansion < 1
                or not progress.preview.items
                or any(image.isNull() for _, _, image in progress.preview.items)
            ):
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
                verify_input_features(window)
                verify_system_settings(window)
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
            verify_input_features(window)
            verify_system_settings(window)
            done(0)

        QTimer.singleShot(25, lambda: guarded(metadata_ready))
    except Exception:
        traceback.print_exc()
        done(1)


def verify_input_features(window):
    """Execute the new controls and packaged preinstalled functions in the EXE."""
    assert window.title_bar.brand.isHidden()
    assert all(not action.icon().isNull() for action in window.plugins.commands.values())
    app_icon = window.windowIcon().pixmap(256, 256).toImage()
    assert app_icon.pixelColor(0, 0).alpha() == 0
    assert app_icon.pixelColor(128, 128).alpha() > 200
    assert any(0 < app_icon.pixelColor(128, y).alpha() < 180 for y in range(32))
    icons = [
        window.plugins.commands[key].icon().pixmap(24, 24).toImage()
        for key in ("example.doublepage:toggle", "example.touch:toggle")
    ]
    assert icons[0] != icons[1] and all(not icon.isNull() for icon in icons)
    assert all(not a.icon().isNull() for a in window.components.menus["function"].actions())
    for key in ("example.doublepage", "example.touch"):
        assert window.plugins.records[key].state == "enabled"
    directory = window.paths_layout.cache / "smoke-spread"
    directory.mkdir(exist_ok=True)
    paths = [directory / f"{i:02}.png" for i in range(5)]
    for i, path in enumerate(paths):
        image = QImage(90, 130, QImage.Format.Format_RGB32)
        image.fill(0x334455 + i * 0x110000)
        assert image.save(str(path))
    assert window.open_image(paths[0])
    wait_for(lambda: window.current_path == paths[0])
    double = window.plugins.commands["example.doublepage:toggle"]
    if not double.isChecked():
        double.trigger()
    wait_for(window.double_page.second.isVisible)
    assert window.double_page.path == paths[1]
    window.navigate(1)
    wait_for(lambda: window.double_page.path == paths[3] and window.double_page.second.isVisible())
    assert window.current_path == paths[2]
    window.navigate(-1)
    assert window.current_path == paths[0]
    double.trigger()
    assert not window.double_page.second.isVisible()
    settings = ApplicationSettings(window)
    editor = settings.binding_editor
    assert editor.tabs.count() == 4
    assert editor.assign("下一张", "keyboard", "Ctrl+Alt+N")
    settings.editors["key_repeat_delay_ms"].setValue(300)
    settings.editors["notification_ms"].setValue(1500)
    assert editor.assign("下一张", "mouse", "Ctrl+Forward")
    assert editor.assign("下一张", "touch", "R1")
    settings.save()
    assert len(window.next_action.shortcuts()) >= 2
    assert window.inputs.dispatch("touch", "R1")
    assert window.current_path == paths[1]
    # Qt routes synthetic touch through native screen coordinates. Keep the
    # target on-screen even on small/offscreen CI displays.
    available = window.screen().availableGeometry()
    window.move(available.topLeft())
    window.resize(
        max(window.minimumWidth(), min(800, available.width())), min(600, available.height())
    )
    window.activateWindow()
    window.view.setFocus()
    QTest.qWait(80)
    device = QTest.createTouchDevice()
    viewport = window.view.viewport()
    point = QPoint(int(viewport.width() * 0.85), int(viewport.height() * 0.2))
    QTest.touchEvent(viewport, device).press(0, point, viewport).commit()
    QTest.touchEvent(viewport, device).release(0, point, viewport).commit()
    wait_for(lambda: window.current_path == paths[2])
    touch = window.plugins.commands["example.touch:toggle"]
    touch.trigger()
    assert not window.inputs.dispatch("touch", "R1")
    touch.trigger()
    window.toggle_fullscreen()
    wait_for(window.isFullScreen)
    QTest.qWait(100)
    assert window.menuWidget().height() == 0 and window.title_bar.y() == -48
    edge = window.fullscreen_chrome.edge
    QTest.mouseMove(edge, QPoint(10, 1))
    wait_for(lambda: window.title_bar.y() == 0)
    window.fullscreen_chrome.reveal(False)
    wait_for(lambda: window.title_bar.y() == -48)
    window.exit_fullscreen()
    assert window.menuWidget().height() == 48 and window.title_bar.y() == 0
    print(
        "Packaged transparent glowing app/function icons, icon-only chrome, "
        "fullscreen slide, two-page plugin and multi-input bindings passed"
    )
    verify_notifications_and_click_seek(window, paths)
    verify_browser_commands(window, paths)
    verify_gamepad(window, paths)


def verify_gamepad(window, paths):
    """Load the real system backend; simulate input without assuming CI has hardware."""
    import sys
    from types import SimpleNamespace

    from picer.gamepad import GamepadSample, XInputBackend
    from picer.input_bindings import binding_conflict

    native = XInputBackend()
    if sys.platform == "win32":
        assert native.available, native.message
        # Exercises native DLL lookup/calling convention even with no attached controller.
        for index in range(4):
            native.read(index)
    assert binding_conflict(
        {"device": "gamepad", "value": "RT"},
        {"device": "gamepad", "value": "RT+A"},
    )
    assert not binding_conflict(
        {"device": "gamepad", "value": "LB"},
        {"device": "gamepad", "value": "RT+A"},
    )
    monitor = window.inputs.gamepad
    monitor.timer.stop()
    wait_for(lambda: not monitor.busy)
    real_backend = monitor.backend
    samples = [GamepadSample(), None, None, None]
    monitor.backend = SimpleNamespace(
        available=True,
        guide_supported=True,
        message="自动检查：模拟手柄输入。",
        read=lambda index: samples[index],
    )
    try:
        monitor.rebaseline()
        monitor.timer.stop()
        monitor.poll()
        window.open_image(paths[0])
        settings = ApplicationSettings(window)
        settings.navigation.setCurrentRow(4)
        editor = settings.binding_editor
        editor.tabs.setCurrentIndex(3)
        settings.show()
        settings.activateWindow()
        wait_for(settings.isActiveWindow)
        assert monitor.capture is editor.gamepad_page
        assert not editor.gamepad_page.diagram.artwork.isNull()
        assert editor.gamepad_page.diagram.artwork.toImage().pixelColor(0, 0).alpha() == 0
        for index in range(4):
            editor.tabs.setCurrentIndex(index)
            QTest.qWait(20)
            for control in (editor.bindings, editor.add_button, editor.remove_button):
                center = control.mapTo(settings, control.rect().center())
                assert settings.rect().contains(center)
        editor.tabs.setCurrentIndex(3)
        monitor.timer.stop()
        monitor.poll()
        samples[0] = GamepadSample(0x1000, right_trigger=100)
        monitor.poll()
        assert editor.gamepad_page.value() == "RT+A", {
            "held": monitor.held,
            "baseline": monitor.baseline,
            "subscribed": editor.gamepad_page.subscribed,
            "dialog_active": settings.isActiveWindow(),
            "active_window": str(QApplication.activeWindow()),
            "popup": str(QApplication.activePopupWidget()),
            "modal": str(QApplication.activeModalWidget()),
        }
        assert window.current_path == paths[0]
        assert not editor.gamepad_page.diagram.grab().isNull()
        assert editor.assign("下一张", "gamepad", "RT+A")
        assert editor.assign("上一张", "gamepad", "LB")
        assert editor.assign("复制当前图片", "gamepad", "Guide")
        settings.save()
        assert monitor.capture is None
        window.activateWindow()
        window.view.setFocus()
        wait_for(window.isActiveWindow)
        monitor.timer.stop()
        samples[0] = GamepadSample()
        monitor.poll()
        samples[0] = GamepadSample(right_trigger=100)
        monitor.poll()
        assert window.current_path == paths[0]
        samples[0] = GamepadSample(0x1000, right_trigger=100)
        monitor.poll()
        assert window.current_path == paths[1]
        monitor.poll()
        assert window.current_path == paths[1]
        samples[0] = GamepadSample()
        monitor.poll()
        samples[0] = GamepadSample(0x0100)
        monitor.poll()
        assert window.current_path == paths[0]
        print(
            "Packaged XInput native backend, unbranded asymmetric diagram, isolated capture, "
            "simulated shoulder chords/edge routing and persisted gamepad bindings passed; "
            "physical controller not tested"
        )
    finally:
        monitor.backend = real_backend
        monitor.rebaseline()
        monitor.refresh_interval()


def verify_browser_commands(window, paths):
    """Exercise configurable browser operations in the packaged EXE and on restart."""
    from PySide6.QtWidgets import QApplication

    from picer.input_bindings import default_bindings

    defaults = default_bindings(window)
    assert defaults["复制当前图片"] == [{"device": "keyboard", "value": "Ctrl+C"}]
    assert not defaults["启用全屏"] and not defaults["退出全屏"]
    siblings = window.paths_layout.cache / "smoke-folder-navigation"
    sibling_paths = [siblings / name / "image.png" for name in ("A", "B")]
    for path in sibling_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        assert window.view.image_item.pixmap().toImage().save(str(path))
    browser = window.plugins.records["example.files"].instance
    original_folder = browser.location.text()
    assert window.open_image(sibling_paths[0])
    window.next_folder_action.trigger()
    wait_for(lambda: window.current_path == sibling_paths[1])
    assert browser.location.text() == original_folder
    window.next_folder_action.trigger()
    wait_for(lambda: window.folder_navigation.pending is None)
    assert window.current_path == sibling_paths[1]
    window.previous_folder_action.trigger()
    wait_for(lambda: window.current_path == sibling_paths[0])
    assert window.open_image(paths[0])
    window.first_action.trigger()
    assert window.current_path == paths[0]
    window.last_action.trigger()
    assert window.current_path == paths[-1]
    window.copy_image_action.trigger()
    assert QApplication.clipboard().image().width() == 90
    window.shortcut_actions["切换浏览方向"].trigger()
    assert window.app_preferences["reading_direction"] == "rtl"
    window.previous_action.trigger()
    assert window.current_path == paths[0]
    window.shortcut_actions["切换浏览方向"].trigger()
    progress = window.plugins.records["example.progress"].instance
    window.shortcut_actions["播放幻灯片"].trigger()
    assert progress.timer.isActive()
    window.shortcut_actions["停止幻灯片"].trigger()
    assert not progress.timer.isActive()
    browser = window.plugins.records["example.files"].instance
    child = paths[0].parent / "child"
    child.mkdir(exist_ok=True)
    browser.open_folder(str(paths[0].parent))
    wait_for(lambda: browser.model.rowCount(browser.tree.rootIndex()) == len(paths) + 1)
    browser.search.setText(paths[2].name)
    assert browser.model.rowCount(browser.tree.rootIndex()) == 1
    browser.random_button.click()
    assert Path(browser.model.filePath(browser.tree.currentIndex())) == child
    assert browser.location.text() == str(paths[0].parent)
    window.first_action.trigger()
    wait_for(lambda: Path(browser.model.filePath(browser.tree.currentIndex())) == paths[0])
    window.next_action.trigger()
    wait_for(lambda: Path(browser.model.filePath(browser.tree.currentIndex())) == paths[1])
    favorites = browser.context.get_setting("favorites", [])
    window.shortcut_actions["将当前文件夹加入快速访问"].trigger()
    assert str(paths[0].parent) in browser.context.get_setting("favorites", [])
    browser.context.set_setting("favorites", favorites)
    browser.favorites.reload()
    browser.open_folder(str(child))
    window.next_action.trigger()
    assert browser.location.text() == str(child)
    window.shortcut_actions["打开父级文件夹"].trigger()
    wait_for(lambda: Path(browser.model.filePath(browser.tree.currentIndex())) == child)
    window.shortcut_actions["打开选中文件夹"].trigger()
    assert browser.location.text() == str(child)
    settings = ApplicationSettings(window)
    settings.editors["panel_scrollbars"].setChecked(False)
    settings.save()
    assert browser.tree.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    info = window.plugins.records["example.info"].instance
    assert info.scroll.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    print(
        "Packaged sibling folder navigation/boundaries, pixel clipboard, first/last, "
        "slideshow, reading direction, local search, "
        "random folder selection, browser keyboard operations and synchronized selection, "
        "persisted panel scrollbar preference passed"
    )


def verify_notifications_and_click_seek(window, paths):
    """Exercise actual click-through notifications and image seeking in the EXE."""
    bubble = window.notifications
    bubble.pending.clear()
    bubble.dismiss()
    wait_for(lambda: bubble.phase == "hidden")
    assert window.app_preferences["notification_ms"] == 1500
    window.app_preferences["notification_ms"] = 250
    window.notify("纯文字操作提示")
    wait_for(lambda: bubble.phase == "visible")
    assert bubble.height() == 32 and bubble.width() < 250
    assert bubble.snapshot.size() == bubble.size()
    assert bubble.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert bubble.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert bubble.grab().toImage().pixelColor(0, 0).alpha() <= 4
    assert bubble.timer.interval() == 250
    wait_for(lambda: bubble.phase == "hidden")
    window.app_preferences["notification_ms"] = 1500
    window.panel_hovers.controllers["example.progress"].pin()
    assert window.open_image(paths[0])
    wait_for(lambda: window.current_path == paths[0])
    slider = window.plugins.records["example.progress"].instance.slider
    QTest.mouseClick(
        slider, Qt.MouseButton.LeftButton, pos=QPoint(slider.width() // 2, slider.height() // 2)
    )
    wait_for(lambda: window.current_path == paths[2])
    print(
        "Packaged text-only frosted notifications, duration "
        "and exact image/frame click seeking passed"
    )
