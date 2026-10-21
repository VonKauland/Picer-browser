"""Absolute-import entry point for PyInstaller."""

import sys

if len(sys.argv) > 1 and sys.argv[1] == "--shell-thumbnail":
    from picer.shell_thumbnail import main

    try:
        result = main(sys.argv[2:])
    except Exception:
        # No decoder/IO exception may open a windowed-EXE error dialog in Explorer.
        result = 1
    raise SystemExit(result)

from picer.app import main

if __name__ == "__main__":
    raise SystemExit(main())
