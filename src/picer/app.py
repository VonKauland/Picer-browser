"""Application startup and a packaged image-decoding smoke test."""

import argparse
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from picer.window import MainWindow


def main() -> int:
    """Launch the image browser or exercise the packaged GUI in CI."""
    parser = argparse.ArgumentParser(description="揽映 Picer 图片浏览器")
    parser.add_argument("image", nargs="?")
    parser.add_argument("--safe-mode", action="store_true", help="本次启动不加载第三方插件")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--plugin-archive", help=argparse.SUPPRESS)
    args = parser.parse_args()
    smoke_test = args.smoke_test
    app = QApplication([sys.argv[0]])
    app.setApplicationName("Picer")
    app.setApplicationDisplayName("揽映")
    app.setStyle("Fusion")
    temporary_plugins = tempfile.TemporaryDirectory() if smoke_test else None
    window = MainWindow(
        plugin_root=Path(temporary_plugins.name) if temporary_plugins else None,
        load_external=not args.safe_mode,
    )
    window.show()

    if smoke_test:

        def verify() -> None:
            try:
                with tempfile.TemporaryDirectory() as folder:
                    image = QImage(80, 60, QImage.Format.Format_RGB32)
                    image.fill(0x3399CC)
                    first, second = Path(folder) / "1.png", Path(folder) / "2.jpg"
                    if args.plugin_archive:
                        plugin_id = window.plugins.install(Path(args.plugin_archive))
                        window.plugins.enable(plugin_id)
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
                    if args.plugin_archive:
                        context = window.plugins.records[plugin_id].context
                        passed = passed and context.get_setting("opened_count") == 2
                        before = window.view.image_item.pixmap().toImage().pixelColor(0, 0)
                        window.plugins.commands[f"{plugin_id}:negative"].trigger()

                        def verify_worker() -> None:
                            if window.plugins.jobs:
                                QTimer.singleShot(25, verify_worker)
                                return
                            after = window.view.image_item.pixmap().toImage().pixelColor(0, 0)
                            colors_ok = all(
                                a == 255 - b
                                for a, b in zip(
                                    (after.red(), after.green(), after.blue()),
                                    (before.red(), before.green(), before.blue()),
                                    strict=True,
                                )
                            )
                            active = window.plugins.records[plugin_id].state == "enabled"
                            window.plugins.disable(plugin_id)
                            cleaned = f"{plugin_id}:negative" not in window.plugins.commands
                            app.exit(0 if passed and colors_ok and active and cleaned else 1)

                        QTimer.singleShot(25, verify_worker)
                    else:
                        app.exit(0 if passed and window.isVisible() else 1)
            except Exception:
                app.exit(1)

        QTimer.singleShot(0, verify)
        QTimer.singleShot(10_000, lambda: app.exit(2))
    elif args.image:
        window.open_image(Path(args.image))

    result = app.exec()
    window.plugins.shutdown()
    if temporary_plugins:
        temporary_plugins.cleanup()
    return result
