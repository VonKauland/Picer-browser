"""Measure the build and prune unused Qt backends and language catalogs.

Picer uses QWidget/QGraphicsView's raster viewport, including glass and SVG
painting through qwindows. Keep the default Windows and offscreen backends,
Chinese/English catalogs, Python, all image codecs and RAW/NumPy/FFmpeg libraries.
"""

from pathlib import Path


def inventory(application: Path) -> dict:
    files = []
    for file in sorted(application.rglob("*")):
        if file.is_file():
            files.append(
                {"path": file.relative_to(application).as_posix(), "bytes": file.stat().st_size}
            )
    return {"bytes": sum(file["bytes"] for file in files), "files": files}


def compact_distribution(application: Path) -> dict:
    if not (application / "Picer.exe").is_file() or not (application / "_internal").is_dir():
        raise ValueError("Refusing to compact an incomplete application")
    before = inventory(application)
    qt = application / "_internal" / "PySide6"
    unused = [qt / "opengl32sw.dll", qt / "plugins" / "platforms" / "qdirect2d.dll"]
    for catalog in sorted((qt / "translations").glob("*.qm")):
        for prefix in ("qtbase_", "qt_help_", "qt_"):
            if catalog.stem.startswith(prefix):
                language = catalog.stem[len(prefix) :].split("_")[0]
                if language not in {"zh", "en"}:
                    unused.append(catalog)
                break
    removed = []
    for file in unused:
        if file.is_file():
            removed.append(
                {"path": file.relative_to(application).as_posix(), "bytes": file.stat().st_size}
            )
            file.unlink()
    after = inventory(application)
    return {
        "before": before,
        "after": after,
        "removed": removed,
        "saved_bytes": before["bytes"] - after["bytes"],
    }
