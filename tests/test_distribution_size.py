"""Compaction preserves every runtime codec, RAW library, asset and user file."""

import hashlib

import pytest

from scripts.distribution_size import compact_distribution, inventory


def test_compaction_preserves_all_other_files_and_is_idempotent(tmp_path):
    files = (
        "Picer.exe",
        "_internal/PySide6/Qt6Gui.dll",
        "_internal/PySide6/plugins/imageformats/qwebp.dll",
        "_internal/PySide6/plugins/imageformats/qtiff.dll",
        "_internal/rawpy/_rawpy.pyd",
        "_internal/numpy.libs/blas.dll",
        "assets/ui/gamepad.png",
        "config/plugins.json",
        "plugins/external/main.py",
        "cache/thumbnails/user.png",
        "_internal/PySide6/opengl32sw.dll",
    )
    for index, name in enumerate(files):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(bytes([index]) * (index + 1) * 13)
    before = inventory(tmp_path)
    hashes = {
        file["path"]: hashlib.sha256((tmp_path / file["path"]).read_bytes()).digest()
        for file in before["files"]
    }
    report = compact_distribution(tmp_path)
    assert report["before"] == before
    assert len(report["removed"]) == 1
    removed = report["removed"][0]
    assert removed["path"] == "_internal/PySide6/opengl32sw.dll"
    assert report["saved_bytes"] == removed["bytes"] > 0
    for file in report["after"]["files"]:
        assert (
            hashlib.sha256((tmp_path / file["path"]).read_bytes()).digest() == hashes[file["path"]]
        )
    assert len(report["after"]["files"]) == len(files) - 1
    repeated = compact_distribution(tmp_path)
    assert repeated["removed"] == [] and repeated["saved_bytes"] == 0
    assert repeated["before"] == repeated["after"] == report["after"]


def test_compaction_refuses_incomplete_directory(tmp_path):
    with pytest.raises(ValueError, match="incomplete"):
        compact_distribution(tmp_path)
