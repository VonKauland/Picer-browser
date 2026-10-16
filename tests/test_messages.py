"""Real themed prompt routing, safe cancellation and translucent icon rendering."""

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from picer.messages import MessageBox, MessageDialog, frosted_icon
from picer.theme import COLORS
from picer.ui import DialogHeader


@pytest.mark.parametrize("kind", ["question", "warning", "information", "critical"])
def test_prompt_chrome_wrapping_and_transparent_corners(qtbot, kind):
    dialog = MessageDialog(
        None, "快捷键冲突", "<b>纯文字</b> " + "很长的文件路径 " * 20, kind=kind, action="覆盖绑定"
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(20)
    assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert dialog.findChild(DialogHeader)
    assert dialog.message.textFormat() == Qt.TextFormat.PlainText
    assert dialog.message.wordWrap()
    assert dialog.cancel_button.isDefault()
    assert not dialog.confirm_button.isDefault()
    assert dialog.message.geometry().right() < dialog.width()
    assert dialog.grab().toImage().pixelColor(0, 0).alpha() == 0


def test_question_escape_and_explicit_accept_keep_standard_results(qtbot):
    def cancel():
        modal = QApplication.activeModalWidget()
        assert isinstance(modal, MessageDialog)
        assert modal.cancel_button.hasFocus()
        qtbot.keyClick(modal, Qt.Key.Key_Escape)

    QTimer.singleShot(30, cancel)
    assert MessageBox.question(None, "快捷键冲突", "是否覆盖？") == QMessageBox.StandardButton.No
    QTimer.singleShot(30, lambda: QApplication.activeModalWidget().confirm_button.click())
    assert MessageBox.question(None, "快捷键冲突", "是否覆盖？") == QMessageBox.StandardButton.Yes


def test_startup_error_without_host_and_topmost_parent(qtbot):
    QTimer.singleShot(30, lambda: QApplication.activeModalWidget().accept())
    assert (
        MessageBox.critical(None, "无法启动", "不能写入数据目录") == QMessageBox.StandardButton.Ok
    )
    parent = QWidget()
    parent.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
    parent.skin_colors = dict(COLORS, accent="#FF66AA")
    qtbot.addWidget(parent)
    dialog = MessageDialog(parent, "提醒", "信息")
    qtbot.addWidget(dialog)
    assert dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert "#FF66AA" in dialog.styleSheet()


def test_frosted_icons_have_alpha_and_follow_accent():
    images = [
        frosted_icon(kind, "#E8FF59") for kind in ("question", "warning", "information", "critical")
    ]
    assert len({bytes(image.constBits()) for image in images}) == 4
    for image in images:
        assert image.pixelColor(0, 0).alpha() == 0
        assert 0 < image.pixelColor(145, 145).alpha() <= 255
    assert frosted_icon("question", "#FF66AA") != images[0]
