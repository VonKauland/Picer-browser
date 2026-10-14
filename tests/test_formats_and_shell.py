"""Real format filtering, context menus and isolated Windows registry integration."""

import copy
import sys
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from PIL import Image
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QContextMenuEvent, QImage
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from picer.formats import valid_formats
from picer.settings_backup import snapshot, validate_backup
from picer.window import MainWindow
from picer.windows_integration import CAPABILITIES, PROG_ID, WindowsIntegration


@pytest.fixture
def host(qtbot, tmp_path):
    window = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(window)
    window.show()
    yield window
    window.close()


def images(tmp_path):
    paths = [tmp_path / "a.png", tmp_path / "b.jpg", tmp_path / "c.png"]
    image = QImage(80, 60, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.green)
    for path in paths:
        assert image.save(str(path))
    return paths


def test_canvas_menu_actions_and_transparency(host, tmp_path, qtbot, monkeypatch):
    paths = images(tmp_path)
    menu = host.image_context_menu()
    assert all(not a.isEnabled() for a in menu.actions()[:3])
    menu.deleteLater()
    host.open_image(paths[0])
    menu = host.image_context_menu()
    assert menu.actions()[0] is host.copy_image_action
    assert menu.actions()[1] is host.copy_action
    menu.actions()[0].trigger()
    assert QApplication.clipboard().image().size() == host.view.image_item.pixmap().size()
    menu.actions()[1].trigger()
    assert QApplication.clipboard().text() == str(paths[0])
    opened = []
    monkeypatch.setattr("picer.window.reveal_file", opened.append)
    menu.actions()[2].trigger()
    assert opened == [paths[0]]
    menu.popup(host.mapToGlobal(QPoint(250, 150)))
    qtbot.waitUntil(menu.isVisible)
    assert menu.grab().toImage().pixelColor(0, 0).alpha() == 0
    assert menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    menu.hide()
    menu.actions()[-1].trigger()
    assert host.isFullScreen()
    host.toggle_fullscreen()
    menu.deleteLater()


def test_canvas_context_event_and_custom_right_binding(host):
    calls = []

    def close_menu():
        menu = QApplication.activePopupWidget()
        if menu:
            calls.append(menu)
            menu.close()

    def send(reason):
        QTimer.singleShot(30, close_menu)
        event = QContextMenuEvent(reason, QPoint(10, 10), host.mapToGlobal(QPoint(10, 10)))
        QApplication.sendEvent(host.view.viewport(), event)

    send(QContextMenuEvent.Reason.Mouse)
    assert len(calls) == 1
    host.inputs.mapping[("mouse", "Right")] = "全屏"
    send(QContextMenuEvent.Reason.Mouse)
    assert len(calls) == 1
    send(QContextMenuEvent.Reason.Keyboard)
    assert len(calls) == 2


def test_format_apply_filters_existing_indexes_browser_and_open(host, tmp_path, qtbot):
    paths = images(tmp_path)
    assert host.open_image(paths[0])
    browser = host.plugins.records["example.files"].instance
    browser.open_folder(tmp_path)
    dialog = host.show_settings()
    selection = dialog.editors["readable_formats"]
    selection.setValue([".png"])
    # Selection is staged until Apply.
    assert ".jpg" in host.supported_suffixes
    dialog.apply()
    qtbot.waitUntil(lambda: host.paths == [paths[0], paths[2]])
    assert host.supported_suffixes == {".png"}
    qtbot.waitUntil(lambda: browser.model.files.nameFilters() == ["*.png"])
    assert not host.open_image(paths[1])
    assert host.current_path == paths[0]
    assert "格式未启用" in host.last_error
    assert host.plugins.records["example.files"].context.readable_suffixes() == {".png"}
    data = validate_backup(snapshot(host), host)
    assert data["application"]["readable_formats"] == [".png"]
    selection.setValue([])
    dialog.apply()
    assert not host.supported_suffixes
    assert not host.open_image(paths[2])
    assert browser.model.files.nameFilters() == ["*.picer-no-enabled-format"]
    selection.setValue(None)
    dialog.apply()
    assert ".jpg" in host.supported_suffixes
    assert host.open_image(paths[1])
    dialog.reject()


def test_format_change_cancels_pending_disabled_pixels(host, tmp_path, qtbot, monkeypatch):
    from picer.imaging import read_image

    first, large = tmp_path / "shown.png", tmp_path / "pending.jpg"
    Image.new("RGB", (80, 60), "blue").save(first)
    Image.new("RGB", (3200, 2400), "red").save(large)
    started, release = Event(), Event()

    def blocked(path, **options):
        if path == large:
            started.set()
            assert release.wait(10)
        return read_image(path, **options)

    monkeypatch.setattr("picer.loading.read_image", blocked)
    try:
        host.open_image(first)
        host.open_image(large)
        qtbot.waitUntil(started.is_set)
        host.plugins.preferences["ui"]["application"] = {"readable_formats": [".png"]}
        host.apply_preferences()
    finally:
        release.set()
    qtbot.waitUntil(lambda: not host.loader.jobs, timeout=10000)
    assert host.current_path == first
    assert host.paths == [first]
    assert host.view.image_item.pixmap().toImage().pixelColor(0, 0).blue() == 255


def test_format_change_discards_inflight_directory_scan(host, tmp_path, qtbot, monkeypatch):
    import os

    paths = images(tmp_path)
    host.open_image(paths[0])
    original, started, release = os.scandir, Event(), Event()
    first_call = True

    def blocked(directory):
        nonlocal first_call
        if Path(directory) == tmp_path and first_call:
            first_call = False
            started.set()
            assert release.wait(10)
        return original(directory)

    monkeypatch.setattr("picer.loading.os.scandir", blocked)
    try:
        host.loader.index_directory(tmp_path, force=True)
        qtbot.waitUntil(started.is_set)
        host.plugins.preferences["ui"]["application"] = {"readable_formats": [".png"]}
        host.apply_preferences()
    finally:
        release.set()
    qtbot.waitUntil(lambda: not host.loader.jobs, timeout=10000)
    assert host.paths == [paths[0], paths[2]]
    assert host.loader.directories[tmp_path] == [paths[0], paths[2]]


@pytest.mark.parametrize("value", [".png", [".PNG"], ["png"], [".png", ".png"], [1], [".a\\shell"]])
def test_backup_rejects_invalid_formats(host, value):
    assert not valid_formats(value)
    data = copy.deepcopy(snapshot(host))
    data["application"]["readable_formats"] = value
    with pytest.raises(ValueError, match="readable_formats"):
        validate_backup(data, host)


def test_explorer_launch_preserves_filename_as_argument(tmp_path, monkeypatch):
    from picer import windows_integration as integration

    image = tmp_path / "照片, with spaces & (1).png"
    image.touch()
    calls = []
    monkeypatch.setattr(integration.sys, "platform", "win32")
    monkeypatch.setattr(integration.subprocess, "Popen", lambda args: calls.append(args))
    integration.reveal_file(image)
    assert calls[0][1:] == ["/select,", str(image.resolve())]
    assert Path(calls[0][0]).name == "explorer.exe"


def test_default_apps_link(monkeypatch):
    from picer import windows_integration as integration

    urls = []
    monkeypatch.setattr(
        integration.QDesktopServices, "openUrl", lambda url: urls.append(url) or True
    )
    integration.open_default_apps()
    assert urls[0].toString() == "ms-settings:defaultapps?registeredAppUser=Picer"
    monkeypatch.setattr(integration.QDesktopServices, "openUrl", lambda url: False)
    with pytest.raises(OSError, match="默认应用"):
        integration.open_default_apps()


def test_registration_buttons_use_applied_formats_and_report_errors(host, monkeypatch):
    from picer import format_settings

    calls = []

    class Integration:
        def register_viewer(self, formats):
            calls.append(("viewer", formats))

        def register_context_menu(self, formats):
            calls.append(("context", formats))

        def remove_context_menu(self):
            calls.append(("remove",))

    monkeypatch.setattr(format_settings, "WindowsIntegration", Integration)
    monkeypatch.setattr(format_settings, "open_default_apps", lambda: calls.append(("defaults",)))
    dialog = host.show_settings()
    buttons = {b.text(): b for b in dialog.findChildren(QPushButton)}
    selection = dialog.editors["readable_formats"]
    selection.setValue([".png"])
    buttons["注册 Windows 右键菜单"].clicked.emit()
    assert not calls
    assert any("尚未应用" in label.text() for label in dialog.findChildren(QLabel))
    dialog.apply()
    buttons["注册 Windows 右键菜单"].clicked.emit()
    buttons["设为 Windows 默认图片浏览器…"].clicked.emit()
    buttons["移除 Windows 右键菜单"].clicked.emit()
    assert calls == [("context", {".png"}), ("viewer", {".png"}), ("defaults",), ("remove",)]

    def unavailable():
        raise OSError("注册权限不足")

    monkeypatch.setattr(format_settings, "WindowsIntegration", unavailable)
    buttons["注册 Windows 右键菜单"].clicked.emit()
    assert any("注册权限不足" in label.text() for label in dialog.findChildren(QLabel))
    dialog.reject()


@pytest.mark.skipif(sys.platform != "win32", reason="Actual HKCU registry requires Windows")
def test_native_windows_registration_isolated_and_reversible(tmp_path):
    import winreg

    executable = tmp_path / "揽映 path with spaces.exe"
    executable.touch()
    root = r"Software\PicerIntegrationTests" + "\\" + uuid4().hex
    service = WindowsIntegration(executable, root=root)
    classes = r"Software\Classes"
    service.write(classes + r"\.png", "", "OtherViewer.Image")
    service.write(
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.png\UserChoice",
        "ProgId",
        "OtherViewer.Image",
    )
    try:
        service.register_viewer([".png", ".jpg"])
        assert service.read(CAPABILITIES + r"\FileAssociations", ".png") == PROG_ID
        assert (
            service.read(classes + "\\" + PROG_ID + r"\shell\open\command", "")
            == f'"{executable}" "%1"'
        )
        assert service.read(classes + r"\.png", "") == "OtherViewer.Image"
        assert (
            service.read(
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.png\UserChoice",
                "ProgId",
            )
            == "OtherViewer.Image"
        )
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, service.path(classes + r"\.png\OpenWithProgids")
        ) as handle:
            value, kind = winreg.QueryValueEx(handle, PROG_ID)
            assert kind == winreg.REG_NONE and value in (None, b"")
        service.register_context_menu([".png", ".jpg"])
        assert service.read(service.menu_key(".png") + r"\command", "") == service.command
        service.register_context_menu([".png"])
        assert service.read(service.menu_key(".jpg"), "") is None
        service.register_viewer([".png"])
        assert service.read(classes + r"\.jpg\OpenWithProgids", PROG_ID) is None
        service.remove_context_menu()
        assert service.read(service.menu_key(".png"), "") is None
        with pytest.raises(ValueError):
            service.register_context_menu([])
    finally:
        service.delete("")
    with pytest.raises(FileNotFoundError):
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, root)
