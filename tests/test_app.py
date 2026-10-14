"""Exercise the application's startup and event loop in a separate process."""

import subprocess
import sys


def test_normal_startup_does_not_import_gui_test_harness():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import picer.app, sys; "
            "assert 'picer.smoke' not in sys.modules; "
            "assert 'PySide6.QtTest' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_application_smoke_test():
    result = subprocess.run(
        [sys.executable, "-m", "picer", "--smoke-test"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
