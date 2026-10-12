"""Modeless settings only capture the controller while their page has focus."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from picer.window import MainWindow


def test_inactive_settings_capture_does_not_block_main_gamepad(qtbot, tmp_path):
    host = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(host)
    host.show()
    host.inputs.gamepad.timer.stop()
    dialog = host.show_settings()
    dialog.navigation.setCurrentRow(4)
    dialog.binding_editor.tabs.setCurrentIndex(3)
    page = dialog.binding_editor.gamepad_page
    qtbot.waitUntil(lambda: host.inputs.gamepad.capture is page)
    calls = []
    host.inputs.dispatch = lambda device, value: calls.append((device, value))
    host.inputs.mapping[("gamepad", "A")] = "下一张"
    dialog.activateWindow()
    qtbot.waitUntil(dialog.isActiveWindow)
    host.inputs.gamepad_changed(0, frozenset({"A"}), frozenset())
    assert not calls
    host.activateWindow()
    host.view.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(host.isActiveWindow)
    qtbot.waitUntil(lambda: not dialog.isActiveWindow())
    assert QApplication.activeModalWidget() is None
    host.inputs.gamepad_changed(0, frozenset({"A"}), frozenset())
    assert calls == [("gamepad", "A")]
    host.close()
    assert host.settings_dialog is None and host.inputs.gamepad.capture is None
