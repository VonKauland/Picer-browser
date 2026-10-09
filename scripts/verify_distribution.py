"""Exercise the complete Windows folder after copying and relocating it."""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run_smoke(application: Path, working_directory: Path) -> None:
    process = subprocess.Popen(
        [
            str(application / "Picer.exe"),
            "--smoke-test",
            "--plugin-archive",
            str(application / "examples" / "negative-plugin.zip"),
        ],
        cwd=working_directory,
    )
    try:
        code = process.wait(timeout=60)
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False)
        raise RuntimeError("Packaged application smoke test timed out") from None
    if code != 0:
        raise RuntimeError(f"Packaged application smoke test failed: {code}")


def verify(application: Path) -> None:
    for relative in (
        "Picer.exe",
        "_internal",
        "assets/icons/picer.ico",
        "assets/icons/picer.png",
        "plugins",
        "cache",
        "config/plugins.json",
        "logs",
        "examples/negative-plugin.zip",
        "docs/plugins.md",
        "README.txt",
        "distribution.json",
    ):
        if not (application / relative).exists():
            raise RuntimeError(f"Missing distribution entry: {relative}")
    with tempfile.TemporaryDirectory(prefix="picer-folder-check-") as temporary:
        root = Path(temporary)
        first = root / "揽映 首次运行"
        unrelated = root / "unrelated-cwd"
        unrelated.mkdir()
        shutil.copytree(application, first)
        run_smoke(first, unrelated)
        state = first / "config" / "plugins.json"
        preferences = json.loads(state.read_text(encoding="utf-8"))
        if preferences["settings"]["example.negative"]["opened_count"] != 2:
            raise RuntimeError("Plugin state was not saved beside the application")
        if not (first / "logs" / "plugins.log").is_file():
            raise RuntimeError("Application logs are missing")
        if not list((first / "cache" / "thumbnails").glob("*.png")):
            raise RuntimeError("Thumbnail cache was not created")
        moved = root / "迁移后的 Picer"
        first.rename(moved)
        run_smoke(moved, unrelated)
        preferences = json.loads((moved / "config" / "plugins.json").read_text(encoding="utf-8"))
        if preferences["settings"]["example.negative"]["opened_count"] != 4:
            raise RuntimeError("Plugin configuration did not survive relocation and restart")
        print("Folder layout, icons, external plugin, cache, restart and relocation checks passed")


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("Packaged Windows application checks must run on Windows")
    verify(Path(__file__).resolve().parents[1] / "dist" / "Picer")
