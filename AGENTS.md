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
- Never auto-enable user-installed external plugins. The user-authorized shipped examples are provisioned by the trusted application catalog: panels/functions on, skins off; preserve later user choices and explicit uninstalls. Revoke context, commands, subscriptions and tasks when disabling or failing a plugin.
- Plugin tests must use temporary data directories; never touch the developer's installed plugins or settings.
- Preserve the packaged EXE smoke test that installs and executes the real external example ZIP.

- Resolve resources from the application directory; never derive data paths from cwd. Keep plugins, cache, config and logs separate; preserve user settings during migrations and updates.

- New components must declare type skin/function/panel. Skin packages are declarative resources in skins; functions register exactly one command; panels register exactly one widget and dock only left/right, except a declared progress role restricted to bottom; allow at most one bottom progress overlay. Preserve explicit legacy API v1 migration support.
- Revoke quick-slot bindings and docks on cleanup. Keep exactly five top-bar slots and no bottom status bar. Test fullscreen/normal panel visibility transitions and persisted user choices.

- Scope skins to host widgets only; preserve external plugin QIcon and content styles. Fixed panels use opaque charcoal shells; only auto-hide reveals use shared glass backdrops; hover reveals must preserve hidden preferences and restore widget ownership on cleanup.
- Keep four primary example ZIPs (file browser, image info, progress, macOS skin) plus the SDK negative regression ZIP. EXE checks must read actual JPEG EXIF and exercise hover animation and persistent example settings.
- Keep default UI charcoal with a distinct lime accent; appearance settings may override the accent, and shared controls/opt-in example plugins must follow it without rewriting external QIcon or original content styles. Default example panels have no component-configuration buttons; edit component settings inline in Plugin Management. The file browser quick-settings menu is authorized for daily browsing actions. Application preferences belong in Edit → Settings.
- Preserve panel motion: 420 ms OutBack (overshoot 0.55) expansion, 300 ms InOutCubic collapse, 220 ms leave delay and continuous reversal. Visual restyling must not change these animations.
- Popup menus and comboboxes must have transparent rounded corners and no native white frame. Use RoundedSlider for default progress/settings sliders; render tests must check both orientations, inverted appearance and range endpoints while retaining Qt input behavior.

- Bottom progress uses a centered one-third-width overlay and must not reserve a dock row. Side docks reach the bottom. Expose fixed/auto-hide only on grips and indicator strips. Transparent preview thumbnails retain configurable size and unrestricted total folder browsing, individual shadows, edge feathering and no scrollbar.

- File browser: neutral frosted folder icons classify direct decodable images asynchronously; keep cache/watches bounded and stop them on disable. Selected row/tile outlines encompass the whole background, never tint folder icons. Keep parent entry pinned first, directories before files in every sort direction, single-click selection and double-click folder entry. Side keys navigate history; Backspace goes up but must keep text editing intact.
- Preview reveal/compact motion shares one reversible timeline (280 ms OutCubic open, 220 ms InOutCubic close). Keep independent preview docking and existing edge-hover motion; verify intermediate frames, reversal and cleanup.

- File browser locations: Picer-only favorites and recent folders persist separately from session back/forward navigation, each bounded to 64 entries. Drive roots go up to the virtual disk list. Returning to a parent selects the exited directory and scrolls to the top. Keep folder-specific sort overrides bounded to 128 entries; normal/image-containing folder defaults are separate plugin settings, classified asynchronously without recursive scans.

- Hidden bottom progress uses a tiny transparent 24px ring (20px outer diameter); image position is the accent outer ring, animated frame position a silver inner ring. With independent thumbnails open, anchor it to their left; preserve hover/click pin controls and all motion timings.

- Held image navigation uses the saved millisecond interval, ignores OS repeats and stops on release/deactivation or editing focus. Rapid mode pauses full refinement and prefers 960px previews; use a separate bounded neighbour prefetch pool and keep stale-result/cancellation rules.
- EXIF tables stay bottom-anchored with wrapping columns and upward details expansion. Preserve original metadata SDK fields; parse RAW camera tags independently of pixel/histogram decoding and never invent missing camera/lens values.

- All thumbnails use the host ThumbnailService/ThumbnailCache via request_thumbnail; keep a shared 256px oriented master, coalesced decode, memory/disk limits, per-consumer cancellation and plugin revocation. Preview virtualizes visible neighbours without imposing a total image count cap; old thumbnail_count values are ignored. Window controls remain 32px and share the effective user accent; fullscreen precedes minimize/maximize/close.
- The hidden bottom progress ring coexists with its original 84x5 indicator; keep both hover/pin entry points, avoid overlap, clean up both and preserve existing animation timings.
