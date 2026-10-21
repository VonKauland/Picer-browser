"""Run expensive startup only after the real main window has painted once."""

from PySide6.QtCore import QEvent, QObject, QTimer


class AfterFirstPaint(QObject):
    def __init__(self, window, callback):
        super().__init__(window)
        self.window = window
        self.callback = callback
        self.scheduled = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.run)
        window.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Close:
            self.cancel()
        elif event.type() == QEvent.Type.Paint and not self.scheduled and self.callback:
            self.scheduled = True
            # The timer fires after this paint event and its child paints return.
            # A zero-delay timer scheduled before show() can precede first paint.
            self.timer.start(0)
        return False

    def cancel(self):
        self.timer.stop()
        self.callback = None
        self.window.removeEventFilter(self)

    def run(self):
        callback = self.callback
        self.cancel()
        if callback:
            callback()


def finish_startup(window, image=None):
    if window.plugins._closed:
        return
    window.plugins.load_startup_plugins()
    window.apply_preferences()
    if image is not None:
        window.open_image(image, asynchronous=True)
    else:
        window.restore_startup(restore_geometry=False, asynchronous=True)
    window.updates.start()
