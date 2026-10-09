# Repository instructions

- Target Python 3.12 and Windows x64; use PySide6 for the GUI.
- Keep application code in `src/picer`, tests in `tests`, and packaging entry points in `scripts`.
- Install with `python -m pip install -r requirements-dev.txt -e .`.
- Before committing, run `python -m ruff check .`, `python -m ruff format --check .`, and `python -m pytest`.
- In headless Linux, set `QT_QPA_PLATFORM=offscreen` for GUI tests. This does not validate a Windows EXE.
- Build the Windows binary only on Windows with `python -m scripts.build_windows` (PyInstaller `--onedir --windowed`).
- Preserve CI checks on main pushes and pull requests. Upload the complete dist/Picer folder only after tests and packaged folder/relocation checks succeed.
- Do not commit virtual environments, caches, build outputs, EXEs, or local secrets.
- Report only checks that actually ran; distinguish Linux checks, Windows CI, and manual desktop validation.

- Keep public plugin SDK compatibility in `src/picer/plugins/api.py` and `docs/plugins.md`; API v1 plugins are trusted in-process Python, not sandboxed.
- Never auto-enable newly installed external plugins. Revoke context, commands, subscriptions and tasks when disabling or failing a plugin.
- Plugin tests must use temporary data directories; never touch the developer's installed plugins or settings.
- Preserve the packaged EXE smoke test that installs and executes the real external example ZIP.

- Resolve resources from the application directory; never derive data paths from cwd. Keep plugins, cache, config and logs separate; preserve user settings during migrations and updates.

- New components must declare type skin/function/panel. Skin packages are declarative resources in skins; functions register exactly one command; panels register exactly one widget and dock only left/right/bottom. Preserve explicit legacy API v1 migration support.
- Revoke quick-slot bindings and docks on cleanup. Keep exactly five top-bar slots and no bottom status bar. Test fullscreen/normal panel visibility transitions and persisted user choices.
