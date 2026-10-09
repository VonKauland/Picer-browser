"""Application startup and a packaged image-decoding smoke test."""

import argparse
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QMessageBox

from picer.window import MainWindow


def main() -> int:
    """Launch the image browser or exercise the packaged GUI in CI."""
    parser = argparse.ArgumentParser(description="揽映 Picer 图片浏览器")
    parser.add_argument("image", nargs="?")
    parser.add_argument("--data-dir", type=Path, help="指定插件、缓存、配置与日志目录")
    parser.add_argument("--safe-mode", action="store_true", help="本次启动不加载第三方插件")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--plugin-archive", help=argparse.SUPPRESS)
    args = parser.parse_args()
    smoke_test = args.smoke_test
    app = QApplication([sys.argv[0]])
    app.setApplicationName("Picer")
    app.setApplicationDisplayName("揽映")
    app.setStyle("Fusion")
    temporary_plugins = (
        tempfile.TemporaryDirectory()
        if smoke_test and not getattr(sys, "frozen", False) and args.data_dir is None
        else None
    )
    try:
        window = MainWindow(
            plugin_root=Path(temporary_plugins.name) if temporary_plugins else args.data_dir,
            load_external=not args.safe_mode,
        )
    except OSError as error:
        if not smoke_test:
            QMessageBox.critical(None, "无法创建应用数据目录", str(error))
        if temporary_plugins:
            temporary_plugins.cleanup()
        return 1
    window.show()

    if smoke_test:

        def verify() -> None:
            try:
                with tempfile.TemporaryDirectory() as folder:
                    image = QImage(80, 60, QImage.Format.Format_RGB32)
                    image.fill(0x3399CC)
                    first, second = Path(folder) / "1.png", Path(folder) / "2.jpg"
                    count_before = 0
                    if args.plugin_archive:
                        plugin_id = "example.negative"
                        if plugin_id not in window.plugins.records:
                            window.plugins.install(Path(args.plugin_archive))
                        window.plugins.enable(plugin_id)
                        count_before = window.plugins.records[plugin_id].context.get_setting(
                            "opened_count", 0
                        )
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
                    passed = passed and not window.windowIcon().isNull()
                    passed = passed and window.plugins.state_file.is_file()
                    passed = passed and window.plugins.log_file.is_file()
                    passed = passed and any(window.thumbnail_cache.directory.glob("*.png"))
                    if args.plugin_archive:
                        context = window.plugins.records[plugin_id].context
                        passed = passed and context.get_setting("opened_count") == count_before + 2
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
