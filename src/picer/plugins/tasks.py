"""Cooperative background work with results delivered to the GUI thread."""

from collections.abc import Callable
from threading import Event

from PySide6.QtCore import QObject, QRunnable, Signal


class TaskCancelled(Exception):
    """A plugin worker observed a cancellation request."""


class TaskToken:
    def __init__(self) -> None:
        self._event = Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def checkpoint(self) -> None:
        if self.cancelled:
            raise TaskCancelled()


class TaskSignals(QObject):
    finished = Signal(object, object)


class Worker(QRunnable):
    def __init__(self, work: Callable[[TaskToken], object]) -> None:
        super().__init__()
        self.work = work
        self.token = TaskToken()
        self.signals = TaskSignals()

    def run(self) -> None:
        result, error = None, None
        try:
            self.token.checkpoint()
            result = self.work(self.token)
            self.token.checkpoint()
        except Exception as caught:
            error = caught
        self.signals.finished.emit(result, error)
