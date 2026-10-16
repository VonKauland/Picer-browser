"""Native Windows caption/sizing semantics beneath application-owned chrome."""

import ctypes
import sys

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtWidgets import QAbstractButton, QMenuBar, QWidget


class Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int32), ("y", ctypes.c_int32)]


class Rect(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int32) for name in ("left", "top", "right", "bottom")]


class MinMaxInfo(ctypes.Structure):
    _fields_ = [
        (name, Point) for name in ("reserved", "max_size", "max_position", "min_track", "max_track")
    ]


class MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint32),
        ("monitor", Rect),
        ("work", Rect),
        ("flags", ctypes.c_uint32),
    ]


class Message(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint32),
        ("wparam", ctypes.c_size_t),
        ("lparam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint32),
        ("point", Point),
    ]


def edges_at(x, y, width, height, border=6, corner=12):
    if not 0 <= x < width or not 0 <= y < height:
        return Qt.Edge(0)
    left, right = x < border, x >= width - border
    top, bottom = y < border, y >= height - border
    # Corners provide a slightly larger diagonal target without widening the edges.
    if (x < corner or x >= width - corner) and (y < corner or y >= height - corner):
        left, right = x < corner, x >= width - corner
        top, bottom = y < corner, y >= height - corner
    result = Qt.Edge(0)
    for enabled, edge in (
        (left, Qt.Edge.LeftEdge),
        (right, Qt.Edge.RightEdge),
        (top, Qt.Edge.TopEdge),
        (bottom, Qt.Edge.BottomEdge),
    ):
        if enabled:
            result |= edge
    return result


CURSORS = {
    Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor,
    Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
    Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor,
    Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
    Qt.Edge.LeftEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeFDiagCursor,
    Qt.Edge.RightEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeFDiagCursor,
    Qt.Edge.RightEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeBDiagCursor,
    Qt.Edge.LeftEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeBDiagCursor,
}
HITS = {
    Qt.Edge.LeftEdge: 10,
    Qt.Edge.RightEdge: 11,
    Qt.Edge.TopEdge: 12,
    Qt.Edge.LeftEdge | Qt.Edge.TopEdge: 13,
    Qt.Edge.RightEdge | Qt.Edge.TopEdge: 14,
    Qt.Edge.BottomEdge: 15,
    Qt.Edge.LeftEdge | Qt.Edge.BottomEdge: 16,
    Qt.Edge.RightEdge | Qt.Edge.BottomEdge: 17,
}


class ResizeHandle(QWidget):
    def __init__(self, host, edges):
        super().__init__(host)
        self.host, self.edges, self.drag = host, edges, None
        self.setObjectName("windowResizeHandle")
        self.setStyleSheet("background: transparent; border: none;")
        self.setCursor(CURSORS[edges])
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.host.windowHandle()
            if handle is None or not handle.startSystemResize(self.edges):
                self.drag = event.globalPosition().toPoint(), self.host.geometry()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.drag is None:
            return
        point, rect = self.drag
        delta = event.globalPosition().toPoint() - point
        target = type(rect)(rect)
        if self.edges & Qt.Edge.LeftEdge:
            target.setLeft(
                min(
                    rect.right() - self.host.minimumWidth() + 1,
                    max(rect.right() - self.host.maximumWidth() + 1, rect.left() + delta.x()),
                )
            )
        if self.edges & Qt.Edge.RightEdge:
            target.setWidth(
                max(
                    self.host.minimumWidth(),
                    min(self.host.maximumWidth(), rect.width() + delta.x()),
                )
            )
        if self.edges & Qt.Edge.TopEdge:
            target.setTop(
                min(
                    rect.bottom() - self.host.minimumHeight() + 1,
                    max(rect.bottom() - self.host.maximumHeight() + 1, rect.top() + delta.y()),
                )
            )
        if self.edges & Qt.Edge.BottomEdge:
            target.setHeight(
                max(
                    self.host.minimumHeight(),
                    min(self.host.maximumHeight(), rect.height() + delta.y()),
                )
            )
        self.host.setGeometry(target)
        event.accept()

    def mouseReleaseEvent(self, event):
        self.drag = None
        event.accept()


class WindowFrame(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.closed = False
        self.handles = {edges: ResizeHandle(host, edges) for edges in CURSORS}
        self.user32 = None
        if sys.platform == "win32":
            self.user32 = ctypes.WinDLL("user32", use_last_error=True)
            for name, result, args in (
                ("GetWindowLongW", ctypes.c_int32, [ctypes.c_void_p, ctypes.c_int32]),
                (
                    "SetWindowLongW",
                    ctypes.c_int32,
                    [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32],
                ),
                (
                    "SetWindowPos",
                    ctypes.c_int,
                    [
                        ctypes.c_void_p,
                        ctypes.c_void_p,
                        ctypes.c_int,
                        ctypes.c_int,
                        ctypes.c_int,
                        ctypes.c_int,
                        ctypes.c_uint,
                    ],
                ),
                ("GetWindowRect", ctypes.c_int, [ctypes.c_void_p, ctypes.POINTER(Rect)]),
                ("ScreenToClient", ctypes.c_int, [ctypes.c_void_p, ctypes.POINTER(Point)]),
                ("MonitorFromWindow", ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_uint]),
                ("GetMonitorInfoW", ctypes.c_int, [ctypes.c_void_p, ctypes.POINTER(MonitorInfo)]),
            ):
                function = getattr(self.user32, name)
                function.restype, function.argtypes = result, args
        self.refresh = QTimer(self)
        self.refresh.setSingleShot(True)
        self.refresh.timeout.connect(self.sync)
        host.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() in {
            QEvent.Type.Show,
            QEvent.Type.Resize,
            QEvent.Type.WindowStateChange,
            QEvent.Type.WinIdChange,
        }:
            self.refresh.start(0)
        return False

    def sync(self):
        host = self.host
        normal = not host.isMaximized() and not host.isFullScreen()
        w, h, b, c = host.width(), host.height(), 6, 12
        rectangles = {
            10: (0, c, b, max(0, h - 2 * c)),
            11: (w - b, c, b, max(0, h - 2 * c)),
            12: (c, 0, max(0, w - 2 * c), b),
            15: (c, h - b, max(0, w - 2 * c), b),
            13: (0, 0, c, c),
            14: (w - c, 0, c, c),
            16: (0, h - c, c, c),
            17: (w - c, h - c, c, c),
        }
        for edges, handle in self.handles.items():
            handle.setGeometry(*rectangles[HITS[edges]])
            handle.setVisible(normal and host.isVisible())
            if normal:
                handle.raise_()
            else:
                handle.drag = None
        # Existing narrow reveal strips intentionally overlap the outer sizing band.
        # Keep them above the fallback handles, without moving or widening either UI.
        for control in self.edge_controls():
            control.raise_()
        if self.user32 and host.isVisible() and not host.isFullScreen():
            hwnd = int(host.winId())
            old = self.user32.GetWindowLongW(hwnd, -16)
            # WS_OVERLAPPEDWINDOW enables OS sizing, caption dragging/Aero Snap and
            # native maximize/restore. NCCALCSIZE below keeps our own title bar.
            style = (old | 0x00CF0000) & ~0x80000000
            if style != old:
                self.user32.SetWindowLongW(hwnd, -16, style)
                self.user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0027)

    def edge_controls(self):
        collection = getattr(self.host, "panel_hovers", None)
        for controller in collection.controllers.values() if collection else ():
            for control in (controller.strip, controller.indicator):
                if control is not None and control.isVisible():
                    yield control

    def edge_control_at(self, point):
        return any(
            control.rect().contains(control.mapFrom(self.host, point))
            for control in self.edge_controls()
        )

    def caption_at(self, point):
        bar = self.host.title_bar
        local = bar.mapFrom(self.host, point)
        if self.host.isFullScreen() or not bar.isVisible() or not bar.rect().contains(local):
            return False
        child = bar.childAt(local)
        while child and child is not bar:
            if isinstance(child, (QAbstractButton, QMenuBar)):
                return False
            child = child.parentWidget()
        return True

    def native_event(self, address):
        if self.closed or not self.user32 or not address:
            return None
        message = Message.from_address(int(address))
        if message.message == 0x0083:  # WM_NCCALCSIZE: all pixels belong to our client chrome.
            return 0
        if self.host.isFullScreen():
            return None
        if message.message == 0x0024 and message.lparam:  # WM_GETMINMAXINFO
            monitor = self.user32.MonitorFromWindow(message.hwnd, 2)
            info = MonitorInfo()
            info.size = ctypes.sizeof(info)
            if monitor and self.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                limits = MinMaxInfo.from_address(message.lparam)
                limits.max_position = Point(
                    info.work.left - info.monitor.left, info.work.top - info.monitor.top
                )
                limits.max_size = Point(
                    info.work.right - info.work.left, info.work.bottom - info.work.top
                )
                scale = self.host.devicePixelRatioF()
                limits.min_track = Point(
                    round(self.host.minimumWidth() * scale),
                    round(self.host.minimumHeight() * scale),
                )
                return 0
        if message.message == 0x0084:  # WM_NCHITTEST uses signed physical desktop coordinates.
            x = ctypes.c_int16(message.lparam & 0xFFFF).value
            y = ctypes.c_int16((message.lparam >> 16) & 0xFFFF).value
            point = Point(x, y)
            client = None
            if self.user32.ScreenToClient(message.hwnd, ctypes.byref(point)):
                scale = self.host.devicePixelRatioF()
                client = QPoint(round(point.x / scale), round(point.y / scale))
                if self.edge_control_at(client):
                    return 1  # HTCLIENT: side reveal strips keep their original hover/pin input.
            rect = Rect()
            if not self.host.isMaximized() and self.user32.GetWindowRect(
                message.hwnd, ctypes.byref(rect)
            ):
                scale = self.host.devicePixelRatioF()
                edges = edges_at(
                    x - rect.left,
                    y - rect.top,
                    rect.right - rect.left,
                    rect.bottom - rect.top,
                    round(6 * scale),
                    round(12 * scale),
                )
                if edges:
                    return HITS[edges]
            if client is not None and self.caption_at(client):
                return 2  # HTCAPTION: Windows owns drag, double-click and top-edge snap.
        return None

    def dispose(self):
        self.closed = True
        self.refresh.stop()
        self.host.removeEventFilter(self)
