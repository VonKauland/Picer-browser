"""Exercise the application's startup and event loop in a separate process."""

import subprocess
import sys


def test_application_smoke_test():
    result = subprocess.run(
        [sys.executable, "-m", "windows_tool", "--smoke-test"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
