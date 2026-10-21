"""Exercise the complete Windows folder after copying and relocating it."""

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def run_smoke(application: Path, working_directory: Path, images: Path) -> None:
    process = subprocess.Popen(
        [
            str(application / "Picer.exe"),
            "--smoke-test",
            "--plugin-archive",
            str(application / "examples" / "sdk" / "negative-plugin.zip"),
            "--skin-archive",
            str(application / "examples" / "macos-skin.zip"),
            "--panel-archive",
            str(application / "examples" / "info-panel.zip"),
            "--file-panel-archive",
            str(application / "examples" / "file-browser.zip"),
            "--progress-panel-archive",
            str(application / "examples" / "progress-panel.zip"),
            "--smoke-images",
            str(images),
        ],
        cwd=working_directory,
    )
    try:
        code = process.wait(timeout=90)
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False)
        raise RuntimeError("Packaged application smoke test timed out") from None
    for name in ("smoke.log", "plugins.log"):
        log = application / "logs" / name
        if log.is_file() and (code != 0 or name == "smoke.log"):
            # Windows CI may expose a cp1252 console; preserve Chinese paths
            # as escaped text instead of losing the underlying EXE diagnostics.
            content = log.read_text(encoding="utf-8", errors="replace")
            print(content.encode("ascii", errors="backslashreplace").decode("ascii"), flush=True)
    if code != 0:
        raise RuntimeError(f"Packaged application smoke test failed: {code}")


def verify(application: Path) -> None:
    for relative in (
        "Picer.exe",
        "shell/PicerThumbnail.dll",
        "_internal",
        "assets/icons/picer.ico",
        "assets/icons/picer.png",
        "assets/ui/gamepad.png",
        "plugins",
        "cache",
        "config/plugins.json",
        "logs",
        "examples/sdk/negative-plugin.zip",
        "docs/plugins.md",
        "docs/components.md",
        "docs/settings.md",
        "examples/macos-skin.zip",
        "examples/info-panel.zip",
        "examples/file-browser.zip",
        "examples/progress-panel.zip",
        "examples/double-page.zip",
        "examples/touch-support.zip",
        "examples/image-manager.zip",
        "examples/image-editor.zip",
        "plugins/example.images/main.py",
        "plugins/example.editor/main.py",
        "plugins/example.doublepage/main.py",
        "plugins/example.touch/main.py",
        "README.txt",
        "distribution.json",
    ):
        if not (application / relative).exists():
            raise RuntimeError(f"Missing distribution entry: {relative}")
    with tempfile.TemporaryDirectory(prefix="picer-folder-check-") as temporary:
        root = Path(temporary).resolve()
        first = root / "揽映 首次运行"
        unrelated = root / "unrelated-cwd"
        unrelated.mkdir()
        shutil.copytree(application, first)
        from scripts.verify_thumbnail_provider import verify as verify_thumbnail_provider

        verify_thumbnail_provider(first)
        images = root / "测试图片"
        images.mkdir()
        run_smoke(first, unrelated, images)
        state = first / "config" / "plugins.json"
        preferences = json.loads(state.read_text(encoding="utf-8"))
        if preferences["settings"]["example.negative"]["opened_count"] != 4:
            raise RuntimeError("Plugin state was not saved beside the application")
        if not (first / "logs" / "plugins.log").is_file():
            raise RuntimeError("Application logs are missing")
        if not list((first / "cache" / "thumbnails").glob("*.png")):
            raise RuntimeError("Thumbnail cache was not created")
        if not (first / "skins" / "example.macos" / "theme.json").is_file():
            raise RuntimeError("Skin was not installed beside the application")
        if preferences["ui"]["quick_slots"][4] != "example.negative:negative":
            raise RuntimeError("Quick slot assignment was not persisted")
        moved = root / "迁移后的 Picer"
        # Windows can briefly keep the just-executed DLL/EXE open (including
        # Defender scanning) after the process exits. Still require a real rename;
        # a persistent sharing/permission failure must fail the migration check.
        deadline = time.monotonic() + 10
        while True:
            try:
                first.rename(moved)
                break
            except PermissionError as error:
                if getattr(error, "winerror", None) not in {5, 32} or time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        run_smoke(moved, unrelated, images)
        verify_thumbnail_provider(moved)
        preferences = json.loads((moved / "config" / "plugins.json").read_text(encoding="utf-8"))
        if preferences["settings"]["example.negative"]["opened_count"] != 8:
            raise RuntimeError("Plugin configuration did not survive relocation and restart")
        if preferences["ui"]["quick_slots"][4] != "example.negative:negative":
            raise RuntimeError("Quick slot assignment did not survive relocation")
        if preferences["settings"]["example.files"]["home"] != str(images):
            raise RuntimeError("File browser home did not survive relocation")
        if preferences["ui"]["application"]["zoom_step"] != 30:
            raise RuntimeError("Application settings did not survive relocation")
        if preferences["ui"]["application"]["panel_scrollbars"] is not False:
            raise AssertionError("Panel scrollbar preference was not persisted")
        if preferences["ui"]["application"]["reading_direction"] != "ltr":
            raise AssertionError("Reading direction was not persisted")
        if preferences["ui"]["application"]["notification_ms"] != 1500:
            raise RuntimeError("Notification duration did not survive relocation")
        if {"device": "gamepad", "value": "RT+A"} not in preferences["ui"]["input_bindings"][
            "下一张"
        ]:
            raise RuntimeError("Gamepad shoulder chord did not survive relocation")
        print(
            "Folder layout, icons, function/skin/panel components, quick slots, fullscreen, "
            "cache, restart and relocation checks passed"
        )


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("Packaged Windows application checks must run on Windows")
    verify(Path(__file__).resolve().parents[1] / "dist" / "Picer")
