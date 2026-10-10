"""Application startup and a packaged image-decoding smoke test."""

import argparse
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from picer.smoke import run as run_smoke
from picer.window import MainWindow


def main() -> int:
    """Launch the image browser or exercise the packaged GUI in CI."""
    parser = argparse.ArgumentParser(description="揽映 Picer 图片浏览器")
    parser.add_argument("image", nargs="?")
    parser.add_argument("--data-dir", type=Path, help="指定插件、缓存、配置与日志目录")
    parser.add_argument("--safe-mode", action="store_true", help="本次启动不加载第三方插件")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--plugin-archive", help=argparse.SUPPRESS)
    parser.add_argument("--skin-archive", help=argparse.SUPPRESS)
    parser.add_argument("--panel-archive", help=argparse.SUPPRESS)
    parser.add_argument("--file-panel-archive", help=argparse.SUPPRESS)
    parser.add_argument("--progress-panel-archive", help=argparse.SUPPRESS)
    parser.add_argument("--smoke-images", type=Path, help=argparse.SUPPRESS)
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
    if not smoke_test:
        window.restore_startup(restore_image=not bool(args.image))
    window.show()

    temporary_images = (
        tempfile.TemporaryDirectory() if smoke_test and args.smoke_images is None else None
    )
    if smoke_test:
        folder = Path(temporary_images.name) if temporary_images else args.smoke_images
        QTimer.singleShot(0, lambda: run_smoke(window, args, folder, app.exit))
        QTimer.singleShot(20_000, lambda: app.exit(2))
    elif args.image:
        window.open_image(Path(args.image))

    if smoke_test and getattr(sys, "frozen", False):
        # A --windowed EXE has no stdout/stderr. Keep actual smoke diagnostics
        # in the copied distribution so its parent CI process can report failures.
        with (window.plugins.paths.logs / "smoke.log").open(
            "w", encoding="utf-8", buffering=1
        ) as log:
            with redirect_stdout(log), redirect_stderr(log):
                result = app.exec()
    else:
        result = app.exec()
    window.plugins.shutdown()
    if temporary_plugins:
        temporary_plugins.cleanup()
    if temporary_images:
        temporary_images.cleanup()
    return result
