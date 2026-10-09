"""Test real Qt widgets and user interactions."""

from PySide6.QtCore import Qt

from windows_tool.window import MainWindow


def test_initial_window(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    assert window.isVisible()
    assert window.windowTitle() == "WindowsTool"
    assert window.click_count == 0
    assert window.feedback_label.text() == "Ready. Click the button below."


def test_click_feedback(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    for count in range(1, 4):
        qtbot.mouseClick(window.action_button, Qt.MouseButton.LeftButton)
        assert window.click_count == count
        assert window.feedback_label.text() == f"Button clicked {count} time(s)."


def test_keyboard_activation(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.action_button.setFocus()
    qtbot.keyClick(window.action_button, Qt.Key.Key_Space)
    assert window.click_count == 1
