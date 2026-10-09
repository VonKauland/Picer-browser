# Repository instructions

- Target Python 3.12 and Windows x64; use PySide6 for the GUI.
- Keep application code in `src/picer`, tests in `tests`, and packaging entry points in `scripts`.
- Install with `python -m pip install -r requirements-dev.txt -e .`.
- Before committing, run `python -m ruff check .`, `python -m ruff format --check .`, and `python -m pytest`.
- In headless Linux, set `QT_QPA_PLATFORM=offscreen` for GUI tests. This does not validate a Windows EXE.
- Build the Windows binary only on Windows using PyInstaller `--onefile --windowed --name Picer --paths src scripts/entrypoint.py`.
- Preserve CI checks on main pushes and pull requests. Upload the EXE only after tests and packaged smoke tests succeed.
- Do not commit virtual environments, caches, build outputs, EXEs, or local secrets.
- Report only checks that actually ran; distinguish Linux checks, Windows CI, and manual desktop validation.

- Keep public plugin SDK compatibility in `src/picer/plugins/api.py` and `docs/plugins.md`; API v1 plugins are trusted in-process Python, not sandboxed.
- Never auto-enable newly installed external plugins. Revoke context, commands, subscriptions and tasks when disabling or failing a plugin.
- Plugin tests must use temporary data directories; never touch the developer's installed plugins or settings.
- Preserve the packaged EXE smoke test that installs and executes the real external example ZIP.
