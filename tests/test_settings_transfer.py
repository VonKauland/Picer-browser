"""Real modeless settings, staged import, durable backups and reset confirmation."""

import copy
import json

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QKeySequence
from PySide6.QtWidgets import QApplication

from picer.confirmation import Confirmation
from picer.panels import DOCK_AREAS
from picer.settings_backup import MAX_BYTES, read_backup, snapshot, write_backup
from picer.window import MainWindow


@pytest.fixture
def host(qtbot, tmp_path):
    host = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(host)
    host.show()
    qtbot.wait(30)
    yield host
    host.close()


def test_options_menu_moves_settings_and_keeps_existing_binding_id(host):
    assert [
        action.text() for action in host.options_menu.actions() if not action.isSeparator()
    ] == ["系统设置…", "导出设置…", "导入设置…"]
    actions = host.title_bar.menu.actions()
    edit = actions[1].menu()
    assert host.settings_action not in edit.actions()
    assert host.shortcut_actions["设置…"] is host.settings_action
    assert host.settings_action.shortcut() == QKeySequence("Ctrl+,")


def test_modeless_singleton_apply_stays_open_main_keys_work_and_close_reopens(
    host, qtbot, tmp_path
):
    for name in ("a.png", "b.png"):
        image = QImage(80, 60, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.blue)
        image.save(str(tmp_path / name))
    host.open_image(tmp_path / "a.png")
    dialog = host.show_settings()
    assert host.show_settings() is dialog
    assert not dialog.isModal() and QApplication.activeModalWidget() is None
    assert dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    dialog.editors["zoom_step"].setValue(40)
    qtbot.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)
    assert dialog.isVisible() and host.view.zoom_step == 40
    assert (
        json.loads(host.plugins.state_file.read_text(encoding="utf-8"))["ui"]["application"][
            "zoom_step"
        ]
        == 40
    )
    host.activateWindow()
    host.view.setFocus()
    qtbot.waitUntil(host.isActiveWindow)
    qtbot.keyClick(host.view, Qt.Key.Key_Right)
    assert host.current_path == tmp_path / "b.png" and dialog.isVisible()
    dialog.editors["zoom_step"].setValue(90)
    dialog.reject()
    assert host.settings_dialog is None and host.view.zoom_step == 40
    reopened = host.show_settings()
    assert reopened is not dialog and reopened.editors["zoom_step"].value() == 40
    reopened.editors["zoom_step"].setValue(45)
    reopened.save()
    assert host.settings_dialog is None and host.view.zoom_step == 45


def test_reset_confirmation_cancel_escape_and_accept_only_changes_form(host, qtbot):
    dialog = host.show_settings()
    dialog.editors["zoom_step"].setValue(40)
    seen = []

    def cancel():
        confirmation = QApplication.activeModalWidget()
        try:
            assert isinstance(confirmation, Confirmation)
            seen.append(confirmation.windowTitle())
            assert confirmation.cancel_button.isDefault()
            assert confirmation.grab().toImage().pixelColor(0, 0).alpha() == 0
            qtbot.keyClick(confirmation, Qt.Key.Key_Escape)
            assert not confirmation.isVisible()
        finally:
            if confirmation:
                confirmation.reject()

    QTimer.singleShot(30, cancel)
    dialog.reset()
    assert seen and dialog.editors["zoom_step"].value() == 40
    assert host.view.zoom_step == 25 and not dialog.layout_reset
    QTimer.singleShot(30, lambda: QApplication.activeModalWidget().confirm_button.click())
    dialog.reset()
    assert dialog.editors["zoom_step"].value() == 25 and dialog.layout_reset
    assert host.view.zoom_step == 25
    dialog.reject()
    assert host.view.zoom_step == 25


def test_reset_applies_defaults_even_after_live_main_changes(host, monkeypatch):
    dialog = host.show_settings()
    host.plugins.preferences["ui"]["application"] = {"zoom_step": 40}
    host.apply_preferences()
    monkeypatch.setattr("picer.settings.confirm", lambda *args: True)
    dialog.reset()
    dialog.apply()
    assert host.view.zoom_step == 25 and dialog.isVisible()


def test_untouched_modeless_fields_do_not_revert_main_changes(host):
    dialog = host.show_settings()
    host.toggle_reading_direction()
    controller = host.panel_hovers.controllers["example.files"]
    controller.move_to(DOCK_AREAS["right"])
    host.plugins.enable("example.macos")
    dialog.editors["zoom_step"].setValue(40)
    dialog.apply()
    assert host.app_preferences["reading_direction"] == "rtl"
    assert controller.area == DOCK_AREAS["right"]
    assert host.plugins.records["example.macos"].state == "enabled"
    assert dialog.skin.currentData() == "example.macos"
    assert not dialog.layout_reset


def test_roundtrip_stages_then_applies_bindings_skin_layout_slots_and_restarts(
    host, tmp_path, qtbot
):
    dialog = host.show_settings()
    dialog.editors["accent_color"].setValue("#91AAFF")
    assert dialog.binding_editor.assign("下一张", "gamepad", "RT+A")
    assert dialog.binding_editor.assign("上一张", "mouse", "Ctrl+Back")
    assert dialog.binding_editor.assign("上一张", "touch", "L1")
    dialog.apply()
    controller = host.panel_hovers.controllers["example.files"]
    controller.move_to(DOCK_AREAS["right"])
    controller.resize_extent(350)
    controller.dock.close()
    host.components.assign(4, "example.doublepage:toggle")
    host.plugins.enable("example.macos")
    expected = snapshot(host)
    path = tmp_path / "设置备份.json"
    write_backup(path, host)
    assert read_backup(path, host) == expected
    assert set(json.loads(path.read_text(encoding="utf-8"))) == set(expected)
    # Imports do not write or apply anything until the user applies the form.
    host.components.default_skin()
    controller.move_to(DOCK_AREAS["left"])
    controller.pin()
    host.plugins.preferences["ui"]["application"] = {"accent_color": "#FFAA00"}
    host.apply_preferences()
    before = copy.deepcopy(host.plugins.preferences)
    before_file = host.plugins.state_file.read_bytes()
    dialog.load_backup(read_backup(path, host))
    assert (
        host.plugins.preferences == before and host.plugins.state_file.read_bytes() == before_file
    )
    assert host.app_preferences["accent_color"] == "#FFAA00"
    dialog.apply()
    assert dialog.isVisible() and host.app_preferences["accent_color"] == "#91AAFF"
    assert host.inputs.mapping[("gamepad", "RT+A")] == "下一张"
    assert host.inputs.mapping[("touch", "L1")] == "上一张"
    assert controller.area == DOCK_AREAS["right"] and controller.dock.isHidden()
    assert host.components.assignments()[4] == "example.doublepage:toggle"
    assert host.plugins.records["example.macos"].state == "enabled"
    assert host.plugins.preferences["enabled"] == {**before["enabled"], "example.macos": True}
    root = host.plugins.root
    host.close()
    restarted = MainWindow(plugin_root=root)
    qtbot.addWidget(restarted)
    assert restarted.app_preferences["accent_color"] == "#91AAFF"
    assert restarted.inputs.mapping[("gamepad", "RT+A")] == "下一张"
    assert restarted.plugins.panels["example.files"].isHidden()
    assert restarted.panel_hovers.controllers["example.files"].area == DOCK_AREAS["right"]
    restarted.close()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(version=True),
        lambda d: d.update(format="other"),
        lambda d: d["application"].update(zoom_step=True),
        lambda d: d["application"].update(accent_color="red"),
        lambda d: d["application"].update(cache_mb=100000),
        lambda d: d.update(skin="example.files"),
        lambda d: d.update(quick_slots=["x"]),
        lambda d: d["panels"]["example.files"].update(area="bottom"),
        lambda d: d.update(
            input_bindings={
                "a": [{"device": "keyboard", "value": "Ctrl+K"}],
                "b": [{"device": "keyboard", "value": "Ctrl+K, Ctrl+C"}],
            }
        ),
        lambda d: d.update(
            input_bindings={
                "a": [{"device": "gamepad", "value": "RT+A"}],
                "b": [{"device": "gamepad", "value": "RT"}],
            }
        ),
    ],
)
def test_invalid_backups_leave_state_and_form_unchanged(host, mutation):
    data = snapshot(host)
    mutation(data)
    before = copy.deepcopy(host.plugins.preferences)
    dialog = host.show_settings()
    dialog.editors["zoom_step"].setValue(40)
    with pytest.raises(ValueError):
        dialog.load_backup(data)
    assert dialog.editors["zoom_step"].value() == 40 and host.plugins.preferences == before


@pytest.mark.parametrize(
    "content", [b'{"format":1,"format":2}', b'{"format":NaN}', b"\xff", b"{bad"]
)
def test_bad_file_is_rejected(host, tmp_path, content):
    path = tmp_path / "bad.json"
    path.write_bytes(content)
    with pytest.raises(ValueError):
        read_backup(path, host)


def test_oversize_and_active_config_overwrite_rejected(host, tmp_path):
    path = tmp_path / "large.json"
    with path.open("wb") as file:
        file.truncate(MAX_BYTES + 1)
    with pytest.raises(ValueError):
        read_backup(path, host)
    before = host.plugins.state_file.read_bytes()
    with pytest.raises(ValueError):
        write_backup(host.plugins.state_file, host)
    assert host.plugins.state_file.read_bytes() == before


def test_file_menu_export_import_cancel_error_and_staged_success(host, tmp_path, monkeypatch):
    path = tmp_path / "backup.json"
    monkeypatch.setattr("picer.window.QFileDialog.getSaveFileName", lambda *args: (str(path), ""))
    host.export_settings()
    assert path.is_file()
    warnings = []
    monkeypatch.setattr("picer.window.QMessageBox.warning", lambda *args: warnings.append(args))
    monkeypatch.setattr("picer.window.QFileDialog.getOpenFileName", lambda *args: ("", ""))
    host.import_settings()
    assert host.settings_dialog is None
    monkeypatch.setattr("picer.window.QFileDialog.getOpenFileName", lambda *args: (str(path), ""))
    host.import_settings()
    assert host.settings_dialog.pending_backup and not warnings
    host.settings_dialog.reject()
    path.write_text("not json")
    host.import_settings()
    assert warnings and host.settings_dialog is None


def test_export_failure_preserves_existing_backup(host, tmp_path, monkeypatch):
    path = tmp_path / "backup.json"
    path.write_text("existing")
    from pathlib import Path

    def fail(*args):
        raise OSError("unwritable")

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError):
        write_backup(path, host)
    assert path.read_text() == "existing"
