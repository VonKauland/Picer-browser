"""Notification feedback, lifetime, modal ownership and exact progress seeking."""

import pytest
from PIL import Image
from PySide6.QtCore import QAbstractAnimation, QPoint, Qt
from PySide6.QtWidgets import QDialog

from picer.preferences import read_preferences
from picer.settings import ApplicationSettings
from picer.window import MainWindow


@pytest.fixture
def host(qtbot, tmp_path):
    host = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(host)
    host.show()
    yield host
    host.close()


def test_notification_compact_glass_translation_and_lifetime(host, qtbot):
    bubble = host.notifications
    host.notify("显示双页已开启")
    assert bubble.height() == 32 and bubble.width() < 250
    assert bubble.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert bubble.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert bubble.uses_glass()
    initial_y = bubble.y()
    # Sample the actual timeline deterministically; full-suite/window painting
    # can consume a short fixed wait before Qt delivers the first frame.
    bubble.motion.pause()
    bubble.motion.setCurrentTime(70)
    assert initial_y < bubble.y() < 60
    bubble.motion.resume()
    qtbot.waitUntil(lambda: bubble.phase == "visible")
    assert bubble.y() == 60
    assert abs(bubble.geometry().center().x() - host.rect().center().x()) <= 1
    assert bubble.timer.interval() == 1000
    assert bubble.grab().toImage().pixelColor(0, 0).alpha() <= 4  # Only a faint shadow.
    qtbot.wait(100)
    assert bubble.isVisible()
    qtbot.waitUntil(lambda: bubble.phase == "hidden", timeout=1800)
    assert not bubble.isVisible()


def test_notifications_queue_is_bounded_deduplicated_and_revoked(host, qtbot):
    bubble = host.notifications
    host.notify("第一条")
    for i in range(12):
        host.notify(str(i))
    assert list(bubble.pending) == ["7", "8", "9", "10", "11"]
    host.notify("11")
    assert len(bubble.pending) == 5
    bubble.dispose()
    host.notify("不能重新开启")
    qtbot.wait(200)
    assert not bubble.isVisible() and bubble.motion.state() == QAbstractAnimation.State.Stopped
    assert not bubble.timer.isActive() and not bubble.pending


def test_modal_notification_returns_to_host_before_dialog_deletion(host, qtbot):
    dialog = QDialog(host)
    qtbot.addWidget(dialog)
    dialog.setModal(True)
    dialog.resize(800, 500)
    dialog.show()
    host.notify("组件已安装")
    assert host.notifications.parentWidget() is dialog
    dialog.reject()
    qtbot.wait(20)
    assert host.notifications.parentWidget() is host
    dialog.deleteLater()
    qtbot.wait(20)
    host.notify("第二条")
    assert "第二条" in host.notifications.pending


def test_notification_settings_persist_and_cover_real_feedback(host, qtbot, monkeypatch):
    messages = []
    monkeypatch.setattr(host, "notify", messages.append)
    action = host.plugins.commands["example.doublepage:toggle"]
    action.trigger()
    action.trigger()
    host.plugins.disable("example.touch")
    host.plugins.enable("example.touch")
    host.toggle_fullscreen()
    qtbot.waitUntil(host.isFullScreen)
    host.exit_fullscreen()
    assert messages[:4] == ["显示双页已开启", "显示双页已关闭", "触控支持已停用", "触控支持已启用"]
    assert "已进入全屏" in messages and "已退出全屏" in messages
    settings = ApplicationSettings(host)
    qtbot.addWidget(settings)
    settings.editors["notification_ms"].setValue(2500)
    settings.save()
    assert read_preferences(host.plugins)["notification_ms"] == 2500
    assert "设置已保存" in messages


def test_image_boundary_feedback_and_both_progress_bars_jump(host, tmp_path, qtbot, monkeypatch):
    messages = []
    monkeypatch.setattr(host, "notify", messages.append)
    paths = [tmp_path / f"{i:02}.png" for i in range(8)]
    for i, path in enumerate(paths):
        Image.new("RGB", (80, 100), (i * 20, 40, 60)).save(path)
    assert host.open_image(paths[0])
    qtbot.waitUntil(lambda: host.current_path == paths[0] and len(host.paths) == 8)
    host.app_preferences["wrap"] = False
    host.navigate(-1)
    assert messages[-1] == "已到第一张"
    host.navigate(7)
    qtbot.waitUntil(lambda: host.current_path == paths[-1])
    assert messages[-1] == "已到最后一张"
    progress = host.plugins.records["example.progress"].instance
    slider = progress.slider
    qtbot.mouseClick(
        slider, Qt.MouseButton.LeftButton, pos=QPoint(slider.width() // 2, slider.height() // 2)
    )
    qtbot.waitUntil(lambda: host.current_path in paths[3:5])
    host.navigate(-host.path_positions[host.current_path])
    qtbot.waitUntil(lambda: host.current_path == paths[0])
    assert messages[-1] == "已到第一张"
    animated = tmp_path / "animated.gif"
    frames = [Image.new("RGB", (40, 50), (i * 20, 50, 60)) for i in range(10)]
    frames[0].save(animated, save_all=True, append_images=frames[1:], duration=1000, loop=0)
    assert host.open_image(animated)
    qtbot.waitUntil(lambda: progress.playback_slider.maximum() == 9, timeout=5000)
    qtbot.waitUntil(lambda: progress.playback.isVisible() and progress.playback_expansion == 1.0)
    if host.animation.state.playing:
        host.animation.toggle()
    playback = progress.playback_slider
    qtbot.mouseClick(
        playback,
        Qt.MouseButton.LeftButton,
        pos=QPoint(int(playback.width() * 0.8), playback.height() // 2),
    )
    qtbot.waitUntil(lambda: 7 <= host.animation.state.frame <= 8)
