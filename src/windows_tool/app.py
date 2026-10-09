"""Application startup and a packaged image-decoding smoke test."""

import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from windows_tool.window import MainWindow


def main() -> int:
    """Launch the image browser or exercise the packaged GUI in CI."""
    smoke_test = "--smoke-test" in sys.argv[1:]
    app = QApplication([sys.argv[0]] if smoke_test else sys.argv)
    app.setApplicationName("映览")
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()

    if smoke_test:

        def verify() -> None:
            try:
                with tempfile.TemporaryDirectory() as folder:
                    image = QImage(80, 60, QImage.Format.Format_RGB32)
                    image.fill(0x3399CC)
                    first, second = Path(folder) / "1.png", Path(folder) / "2.jpg"
                    passed = image.save(str(first)) and image.save(str(second))
                    passed = passed and window.open_image(first)
                    window.next_action.trigger()
                    passed = passed and window.current_path == second.resolve()
                    window.actual_action.trigger()
                    window.zoom_in_action.trigger()
                    passed = passed and window.view.transform().m11() > 1
                    window.rotate_action.trigger()
                    passed = passed and window.view.image_item.pixmap().width() == 60
                    passed = passed and window.title_bar.caption.text() == second.name
                    app.exit(0 if passed and window.isVisible() else 1)
            except Exception:
                app.exit(1)

        QTimer.singleShot(0, verify)
        QTimer.singleShot(10_000, lambda: app.exit(2))
    elif len(sys.argv) > 1:
        window.open_image(Path(sys.argv[1]))

    return app.exec()
