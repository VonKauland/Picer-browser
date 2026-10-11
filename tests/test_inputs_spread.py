"""End-to-end fullscreen, delayed input, two-page and multi-device settings."""

import json
from threading import Event

import pytest
from PIL import Image
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from picer.input_bindings import read_bindings, touch_zone
from picer.settings import ApplicationSettings
from picer.window import MainWindow


@pytest.fixture
def host(qtbot, tmp_path):
    window = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(window)
    window.show()
    window.activateWindow()
    yield window
    window.close()


def pictures(tmp_path, count=5):
    paths = [tmp_path / f"{i:02}.png" for i in range(count)]
    for i, path in enumerate(paths):
        Image.new("RGB", (90, 130), (i * 40, 50, 100)).save(path)
    return paths


def test_function_icons_cover_menus_management_and_slots(host, qtbot):
    from picer.plugins.dialog import PluginDialog

    commands = host.plugins.commands
    assert all(not action.icon().isNull() for action in commands.values())
    keys = ("example.doublepage:toggle", "example.touch:toggle")
    pixels = [commands[key].icon().pixmap(24, 24).toImage() for key in keys]
    assert pixels[0] != pixels[1]
    dialog = PluginDialog(host.plugins, host)
    qtbot.addWidget(dialog)
    for index, key in enumerate(keys, 3):
        action = commands[key]
        host.components.assign(index, key)
        assert host.title_bar.quick_slots[index].icon().cacheKey() == action.icon().cacheKey()
        menu_action = next(
            a for a in host.components.menus["function"].actions() if a.text() == action.text()
        )
        assert menu_action.icon().cacheKey() == action.icon().cacheKey()
        row_index = next(
            i
            for i in range(dialog.list.count())
            if dialog.list.item(i).data(Qt.ItemDataRole.UserRole) == key.split(":")[0]
        )
        row = dialog.list.itemWidget(dialog.list.item(row_index))
        from PySide6.QtWidgets import QLabel

        assert (
            row.findChildren(QLabel)[0].pixmap().toImage() == action.icon().pixmap(26, 26).toImage()
        )
    host.plugins.disable("example.touch")
    assert all(not a.icon().isNull() for a in host.components.menus["function"].actions())


def test_fullscreen_slides_without_reserved_space_and_restores(host, qtbot):
    assert host.title_bar.brand.isHidden()
    host.toggle_fullscreen()
    qtbot.waitUntil(lambda: host.isFullScreen())
    qtbot.wait(100)
    assert host.menuWidget().height() == 0
    assert host.title_bar.y() == -48
    edge = host.fullscreen_chrome.edge
    point = edge.mapToGlobal(QPoint(15, 1))
    from PySide6.QtGui import QCursor

    QCursor.setPos(point)
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(15, 1),
        QPointF(point),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(edge, event)
    qtbot.wait(70)
    assert -48 < host.title_bar.y() < 0
    qtbot.waitUntil(lambda: host.title_bar.y() == 0)
    host.fullscreen_chrome.reveal(False)
    qtbot.waitUntil(lambda: host.title_bar.y() == -48)
    host.exit_fullscreen()
    assert host.title_bar.parentWidget() is host.menuWidget()
    assert host.title_bar.y() == 0 and host.menuWidget().height() == 48


def test_delay_short_tap_no_repeat_and_custom_keyboard_alias(host, qtbot, tmp_path):
    paths = pictures(tmp_path)
    host.open_image(paths[0])
    host.view.setFocus()
    qtbot.keyPress(host.view, Qt.Key.Key_Right)
    assert host.current_path == paths[1]
    qtbot.wait(160)
    assert host.current_path == paths[1] and not host.loader.rapid
    qtbot.keyRelease(host.view, Qt.Key.Key_Right)
    qtbot.wait(1000)
    assert host.current_path == paths[1]
    settings = ApplicationSettings(host)
    qtbot.addWidget(settings)
    settings.editors["key_repeat_delay_ms"].setValue(180)
    settings.editors["key_repeat_ms"].setValue(200)
    assert settings.binding_editor.assign("下一张", "keyboard", "D")
    settings.save()
    host.activateWindow()
    host.view.setFocus()
    qtbot.keyPress(host.view, Qt.Key.Key_D)
    assert host.current_path == paths[2]
    qtbot.wait(80)
    assert host.current_path == paths[2]
    qtbot.waitUntil(lambda: host.current_path == paths[3])
    qtbot.keyRelease(host.view, Qt.Key.Key_D)
    assert not host.loader.rapid and not host.navigation_keys.delay.isActive()


def test_double_pages_pair_navigation_odd_and_disable(host, qtbot, tmp_path):
    paths = pictures(tmp_path)
    host.open_image(paths[0])
    action = host.plugins.commands["example.doublepage:toggle"]
    assert not action.isChecked()
    action.trigger()
    qtbot.waitUntil(host.double_page.second.isVisible)
    assert host.double_page.path == paths[1]
    host.navigate(1)
    qtbot.waitUntil(
        lambda: host.double_page.second.isVisible() and host.double_page.path == paths[3]
    )
    assert host.current_path == paths[2]
    host.navigate(-1)
    assert host.current_path == paths[0]
    host.navigate(1)
    qtbot.waitUntil(
        lambda: host.double_page.path == paths[3] and host.double_page.second.isVisible()
    )
    host.navigate(1)
    assert host.current_path == paths[4] and not host.double_page.second.isVisible()
    host.navigate(-1)
    assert host.current_path == paths[2]
    host.plugins.disable("example.doublepage")
    assert not host.double_page.owners and not host.double_page.second.isVisible()
    host.navigate(1)
    assert host.current_path == paths[3]


def test_double_page_rejects_wide_next_image_and_stale_results(host, qtbot, tmp_path, monkeypatch):
    paths = pictures(tmp_path, 3)
    Image.new("RGB", (1800, 200)).save(paths[1])
    host.open_image(paths[0])
    host.plugins.commands["example.doublepage:toggle"].trigger()
    qtbot.waitUntil(lambda: not host.double_page.jobs)
    assert not host.double_page.second.isVisible()
    host.navigate(1)
    qtbot.waitUntil(lambda: host.current_path == paths[1])
    assert not host.double_page.second.isVisible()
    started, release = Event(), Event()
    from picer.imaging import read_image

    def blocked(path, **kwargs):
        started.set()
        release.wait(2)
        return read_image(path, **kwargs)

    monkeypatch.setattr("picer.spread.read_image", blocked)
    host.open_image(paths[0])
    qtbot.waitUntil(started.is_set)
    host.open_image(paths[2])
    release.set()
    qtbot.waitUntil(lambda: not host.double_page.jobs)
    assert host.current_path == paths[2] and not host.double_page.second.isVisible()


@pytest.mark.parametrize(
    "x,y,zone",
    [
        (0.1, 0.1, "L1"),
        (0.9, 0.1, "R1"),
        (0.1, 0.9, "L2"),
        (0.9, 0.9, "R2"),
        (0.5, 0.1, "Center"),
        (0.5, 0.7, "Center"),
        (0.4, 0.9, "L2"),
        (0.6, 0.9, "R2"),
    ],
)
def test_touch_region_geometry(x, y, zone):
    assert touch_zone(x, y) == zone


def test_multi_device_bindings_conflicts_restart_and_revoke(host, qtbot, tmp_path, monkeypatch):
    paths = pictures(tmp_path)
    host.open_image(paths[0])
    editor = ApplicationSettings(host)
    qtbot.addWidget(editor)
    bindings = editor.binding_editor
    assert bindings.tabs.count() == 3
    assert all(b["device"] != "touch" for values in bindings.profile.values() for b in values)
    assert bindings.assign("下一张", "keyboard", "D")
    assert bindings.assign("下一张", "keyboard", "Ctrl+N")
    assert bindings.assign("下一张", "mouse", "Ctrl+WheelDown")
    assert bindings.assign("下一张", "touch", "R1")
    monkeypatch.setattr(
        "picer.binding_editor.QMessageBox.question", lambda *args: QMessageBox.StandardButton.No
    )
    assert not bindings.assign("上一张", "keyboard", "D")
    monkeypatch.setattr(
        "picer.binding_editor.QMessageBox.question", lambda *args: QMessageBox.StandardButton.Yes
    )
    assert bindings.assign("上一张", "keyboard", "D")
    assert {"device": "keyboard", "value": "D"} not in bindings.materialize()["下一张"]
    assert bindings.assign("example.doublepage:toggle", "keyboard", "Ctrl+Alt+2")
    editor.save()
    assert len(host.next_action.shortcuts()) == 2
    assert host.inputs.dispatch("touch", "R1") and host.current_path == paths[1]
    host.plugins.disable("example.touch")
    assert not host.inputs.dispatch("touch", "R1")
    host.plugins.enable("example.touch")
    assert host.inputs.dispatch("touch", "R1")
    host.plugins.disable("example.doublepage")
    assert not host.inputs.dispatch("keyboard", "Ctrl+Alt+2")
    host.plugins.enable("example.doublepage")
    assert host.plugins.commands["example.doublepage:toggle"].shortcut() == QKeySequence(
        "Ctrl+Alt+2"
    )
    root = host.plugins.root
    host.close()
    restarted = MainWindow(plugin_root=root)
    qtbot.addWidget(restarted)
    assert len(restarted.next_action.shortcuts()) == 2
    assert ("touch", "R1") in restarted.inputs.mapping
    assert restarted.previous_action.shortcuts()[-1] == QKeySequence("D")
    restarted.close()


def test_mouse_bindings_canvas_scope_and_modifiers(host, qtbot, tmp_path):
    paths = pictures(tmp_path)
    host.open_image(paths[0])
    settings = ApplicationSettings(host)
    qtbot.addWidget(settings)
    assert settings.binding_editor.assign("下一张", "mouse", "Ctrl+WheelDown")
    settings.save()
    host.activateWindow()
    point = host.view.viewport().rect().center()
    qtbot.mouseClick(host.view.viewport(), Qt.MouseButton.ForwardButton, pos=point)
    assert host.current_path == paths[1]
    wheel = QWheelEvent(
        QPointF(point),
        QPointF(host.view.viewport().mapToGlobal(point)),
        QPoint(),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(host.view.viewport(), wheel)
    assert host.current_path == paths[2]
    qtbot.mouseDClick(host.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert not host.view.fit_mode
    qtbot.mouseDClick(host.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert host.view.fit_mode


def test_legacy_migration_and_invalid_saved_values(tmp_path, qtbot):
    state = tmp_path / "state" / "config"
    state.mkdir(parents=True)
    (state / "plugins.json").write_text(
        json.dumps({"ui": {"shortcuts": {"下一张": "D"}}, "enabled": {}, "settings": {}})
    )
    host = MainWindow(plugin_root=state.parent)
    qtbot.addWidget(host)
    assert host.next_action.shortcut() == QKeySequence("D")
    assert read_bindings(host)["下一张"][0]["value"] == "D"
    host.plugins.preferences["ui"]["input_bindings"] = {
        "下一张": [{"device": "mouse", "value": "bad"}, {"device": "touch", "value": "R1"}],
        "上一张": [{"device": "touch", "value": "R1"}],
    }
    host.inputs.reload()
    assert host.inputs.mapping[("touch", "R1")] == "下一张"
    assert not host.next_action.shortcuts()
    host.close()


def test_os_repeat_does_not_bypass_delay(host, qtbot, tmp_path):
    paths = pictures(tmp_path)
    host.open_image(paths[0])
    host.view.setFocus()
    qtbot.keyPress(host.view, Qt.Key.Key_Right)
    for _ in range(5):
        event = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier, "", True
        )
        QApplication.sendEvent(host.view, event)
    assert host.current_path == paths[1] and not host.loader.rapid
    QApplication.sendEvent(host, QEvent(QEvent.Type.WindowDeactivate))
    assert not host.navigation_keys.delay.isActive()


def test_real_touch_taps_are_unassigned_then_bound(host, qtbot, tmp_path):
    from PySide6.QtTest import QTest

    paths = pictures(tmp_path)
    host.open_image(paths[0])
    qtbot.wait(60)
    viewport = host.view.viewport()
    device = QTest.createTouchDevice()
    point = QPoint(int(viewport.width() * 0.85), int(viewport.height() * 0.2))
    QTest.touchEvent(viewport, device).press(0, point, viewport).commit()
    QTest.touchEvent(viewport, device).release(0, point, viewport).commit()
    qtbot.wait(30)
    assert host.current_path == paths[0] and host.view.fit_mode
    settings = ApplicationSettings(host)
    qtbot.addWidget(settings)
    settings.binding_editor.assign("下一张", "touch", "R1")
    settings.save()
    qtbot.wait(60)
    point = QPoint(int(viewport.width() * 0.85), int(viewport.height() * 0.2))
    QTest.touchEvent(viewport, device).press(0, point, viewport).commit()
    QTest.touchEvent(viewport, device).release(0, point, viewport).commit()
    qtbot.waitUntil(lambda: host.current_path == paths[1])


def test_keyboard_prefix_conflicts_offer_override(host, qtbot, monkeypatch):
    settings = ApplicationSettings(host)
    qtbot.addWidget(settings)
    editor = settings.binding_editor
    assert editor.assign("下一张", "keyboard", "Ctrl+K, Ctrl+N")
    monkeypatch.setattr(
        "picer.binding_editor.QMessageBox.question", lambda *args: QMessageBox.StandardButton.No
    )
    assert not editor.assign("上一张", "keyboard", "Ctrl+K")
    monkeypatch.setattr(
        "picer.binding_editor.QMessageBox.question", lambda *args: QMessageBox.StandardButton.Yes
    )
    assert editor.assign("上一张", "keyboard", "Ctrl+K")
    assert {"device": "keyboard", "value": "Ctrl+K, Ctrl+N"} not in editor.materialize()["下一张"]
