"""Frameless chrome delegates Windows caption/sizing to the operating system."""

import ctypes
import sys

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage

from picer.window import MainWindow
from picer.window_frame import CURSORS, HITS, Message, MinMaxInfo, edges_at


@pytest.fixture
def window(qtbot, tmp_path):
    host = MainWindow(plugin_root=tmp_path / "state", load_examples=False)
    qtbot.addWidget(host)
    host.show()
    qtbot.wait(30)
    yield host
    host.close()


@pytest.mark.parametrize(
    "point,edges",
    [
        ((0, 200), Qt.Edge.LeftEdge),
        ((999, 200), Qt.Edge.RightEdge),
        ((300, 0), Qt.Edge.TopEdge),
        ((300, 599), Qt.Edge.BottomEdge),
        ((0, 0), Qt.Edge.LeftEdge | Qt.Edge.TopEdge),
        ((999, 0), Qt.Edge.RightEdge | Qt.Edge.TopEdge),
        ((0, 599), Qt.Edge.LeftEdge | Qt.Edge.BottomEdge),
        ((999, 599), Qt.Edge.RightEdge | Qt.Edge.BottomEdge),
        ((10, 10), Qt.Edge.LeftEdge | Qt.Edge.TopEdge),
        ((30, 30), Qt.Edge(0)),
        ((-1, 0), Qt.Edge(0)),
    ],
)
def test_border_hit_regions_and_cursors(point, edges):
    assert edges_at(*point, 1000, 600) == edges
    if edges:
        assert edges in CURSORS and 10 <= HITS[edges] <= 17
    assert edges_at(8, 300, 2000, 1200, 12, 24) == Qt.Edge.LeftEdge


def test_maximize_restore_icon_and_title_double_click(window, qtbot):
    bar = window.title_bar
    button = bar.control_buttons["maximize"]
    assert button.toolTip() == "最大化"
    normal = button.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    # Caption center is draggable; menu, quick slots and controls remain client input.
    center = QPoint(bar.width() // 2, 24)
    assert window.window_frame.caption_at(bar.mapTo(window, center))
    assert not window.window_frame.caption_at(button.mapTo(window, button.rect().center()))
    assert not window.window_frame.caption_at(bar.menu.mapTo(window, bar.menu.rect().center()))
    qtbot.mouseDClick(bar, Qt.MouseButton.LeftButton, pos=center)
    qtbot.waitUntil(window.isMaximized)
    qtbot.wait(30)
    assert button.toolTip() == button.accessibleName() == "还原"
    restored_icon = button.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    assert bytes(normal.constBits()) != bytes(restored_icon.constBits())
    assert all(not handle.isVisible() for handle in window.window_frame.handles.values())
    button.click()
    qtbot.waitUntil(lambda: not window.isMaximized())
    qtbot.wait(30)
    assert button.toolTip() == "最大化"
    assert all(handle.isVisible() for handle in window.window_frame.handles.values())
    for edge, handle in window.window_frame.handles.items():
        assert handle.cursor().shape() == CURSORS[edge]
    window.toggle_fullscreen()
    qtbot.wait(30)
    assert all(not handle.isVisible() for handle in window.window_frame.handles.values())
    window.toggle_fullscreen()


def test_resize_handle_fallback_preserves_opposite_corner_and_minimum(window, qtbot, monkeypatch):
    frame = window.window_frame
    # Force the platform-independent fallback while checking the same anchored geometry.
    handle = frame.handles[Qt.Edge.LeftEdge | Qt.Edge.TopEdge]
    fake = type("Handle", (), {"startSystemResize": lambda self, edges: False})()
    monkeypatch.setattr(window, "windowHandle", lambda: fake)
    before = window.geometry()
    qtbot.mousePress(handle, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
    qtbot.mouseMove(handle, QPoint(42, 32))
    qtbot.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
    after = window.geometry()
    assert after.right() == before.right() and after.bottom() == before.bottom()
    assert after.width() < before.width() and after.height() < before.height()
    assert after.width() >= window.minimumWidth() and after.height() >= window.minimumHeight()


@pytest.mark.skipif(sys.platform != "win32", reason="Real HWND styles/hit tests require Windows")
def test_windows_real_hwnd_caption_edges_and_native_maximize(window, qtbot):
    frame = window.window_frame
    hwnd = int(window.winId())
    style = frame.user32.GetWindowLongW(hwnd, -16)
    assert style & 0x00040000 and style & 0x00010000  # thick frame + maximize box
    from picer.window_frame import Point, Rect

    rect = Rect()
    assert frame.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    msg = Message()
    msg.hwnd, msg.message = hwnd, 0x0084
    for x, y, expected in (
        (rect.left + 1, rect.top + 1, 13),
        (rect.right - 1, rect.bottom - 1, 17),
    ):
        msg.lparam = (y & 0xFFFF) << 16 | (x & 0xFFFF)
        assert frame.native_event(ctypes.addressof(msg)) == expected
    caption = window.title_bar.mapTo(window, QPoint(window.title_bar.width() // 2, 24))
    physical = Point(
        round(caption.x() * window.devicePixelRatioF()),
        round(caption.y() * window.devicePixelRatioF()),
    )
    client_to_screen = frame.user32.ClientToScreen
    client_to_screen.argtypes = [ctypes.c_void_p, ctypes.POINTER(Point)]
    client_to_screen.restype = ctypes.c_int
    assert client_to_screen(hwnd, ctypes.byref(physical))
    msg.lparam = (physical.y & 0xFFFF) << 16 | (physical.x & 0xFFFF)
    assert frame.native_event(ctypes.addressof(msg)) == 2
    limits = MinMaxInfo()
    msg.message, msg.lparam = 0x0024, ctypes.addressof(limits)
    assert frame.native_event(ctypes.addressof(msg)) == 0
    assert limits.max_size.x > 0 and limits.max_size.y > 0
    send = frame.user32.SendMessageW
    send.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_size_t, ctypes.c_ssize_t]
    send.restype = ctypes.c_ssize_t
    send(hwnd, 0x0112, 0xF030, 0)  # WM_SYSCOMMAND / SC_MAXIMIZE
    qtbot.waitUntil(window.isMaximized)
    assert window.title_bar.control_buttons["maximize"].toolTip() == "还原"
    send(hwnd, 0x0112, 0xF120, 0)  # SC_RESTORE
    qtbot.waitUntil(lambda: not window.isMaximized())
