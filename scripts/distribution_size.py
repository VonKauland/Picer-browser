"""Measure the build and remove only the unused bundled software OpenGL fallback.

Picer uses QWidget/QGraphicsView's raster viewport, including glass and SVG
painting. Qt's PyInstaller hook nevertheless collects a 19.7 MiB Mesa fallback
for OpenGL widgets. Keep Python, Qt, all image codecs and RAW/NumPy libraries.
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
    unused = application / "_internal" / "PySide6" / "opengl32sw.dll"
    removed = []
    if unused.is_file():
        removed.append(
            {"path": unused.relative_to(application).as_posix(), "bytes": unused.stat().st_size}
        )
        unused.unlink()
    after = inventory(application)
    return {
        "before": before,
        "after": after,
        "removed": removed,
        "saved_bytes": before["bytes"] - after["bytes"],
    }
