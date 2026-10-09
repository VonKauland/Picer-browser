"""Portable paths, resource packaging and real thumbnail storage."""

import json
import struct
import sys
import zipfile
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from picer.cache import ThumbnailCache
from picer.paths import AppPaths
from scripts.build_windows import prepare_distribution
from scripts.prepare_assets import prepare_icons


@pytest.fixture
def frozen_app(tmp_path, monkeypatch):
    application = tmp_path / "应用 Picer"
    application.mkdir()
    (application / "Picer.exe").touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(application / "Picer.exe"))
    return application


def test_frozen_paths_follow_executable_not_cwd(frozen_app, tmp_path, monkeypatch):
    unrelated = tmp_path / "working"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    paths = AppPaths.resolve()
    assert paths.root == frozen_app
    assert paths.assets == frozen_app / "assets"
    assert paths.plugins.is_dir()
    assert paths.config.is_dir()
    assert paths.logs.is_dir()
    assert paths.cache.is_dir()
    assert not list(unrelated.iterdir())


def test_unwritable_frozen_directory_falls_back(frozen_app, tmp_path, monkeypatch):
    user_root = tmp_path / "user-data"
    monkeypatch.setattr("picer.paths.QStandardPaths.writableLocation", lambda _: str(user_root))
    initialize = AppPaths.initialize

    def fail_only_application(self):
        if self.root == frozen_app:
            raise PermissionError("read only")
        initialize(self)

    monkeypatch.setattr(AppPaths, "initialize", fail_only_application)
    paths = AppPaths.resolve()
    assert paths.root == user_root
    assert paths.assets == frozen_app / "assets"
    assert "不可写" in paths.notice


def test_explicit_unwritable_data_directory_is_not_silently_replaced(tmp_path, monkeypatch):
    def fail(self):
        raise PermissionError("read only")

    monkeypatch.setattr(AppPaths, "initialize", fail)
    with pytest.raises(PermissionError):
        AppPaths.resolve(tmp_path / "explicit")


def test_legacy_state_migration_preserves_backup_and_existing_new_config(tmp_path):
    legacy = tmp_path / "plugins.json"
    legacy.write_text('{"enabled": {"example.plugin": true}}', encoding="utf-8")
    (tmp_path / "plugins.log").write_text("old logs", encoding="utf-8")
    paths = AppPaths.resolve(tmp_path)
    assert (paths.config / "plugins.json").read_text() == legacy.read_text()
    assert (paths.logs / "plugins.log").read_text() == "old logs"
    assert legacy.exists()
    (paths.config / "plugins.json").write_text("new", encoding="utf-8")
    paths.migrate_legacy()
    assert (paths.config / "plugins.json").read_text() == "new"


def test_thumbnail_cache_hits_invalidates_and_is_bounded(tmp_path, qapp):
    cache = ThumbnailCache(tmp_path / "cache", limit=2)
    image = QImage(500, 300, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.red)
    path = tmp_path / "source.png"
    assert image.save(str(path))
    thumbnail = cache.thumbnail(path, image)
    assert thumbnail.width() == 256
    assert len(list(cache.directory.glob("*.png"))) == 1
    # A deliberately different supplied image proves the existing disk cache is read.
    different = image.copy()
    different.fill(Qt.GlobalColor.blue)
    assert cache.thumbnail(path, different).pixelColor(0, 0).red() == 255
    path.write_bytes(b"different size and content")
    assert cache.thumbnail(path, different).pixelColor(0, 0).blue() == 255
    second = tmp_path / "second.png"
    assert image.save(str(second))
    cache.thumbnail(second, image)
    assert len(list(cache.directory.glob("*.png"))) == 2
    cache.clear()
    assert not list(cache.directory.glob("*.png"))
    assert path.exists()


def test_failed_cache_storage_does_not_break_thumbnail(tmp_path, qapp):
    image = QImage(400, 200, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.green)
    path = tmp_path / "original.png"
    assert image.save(str(path))
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    thumbnail = ThumbnailCache(blocked).thumbnail(path, image)
    assert not thumbnail.isNull()
    assert thumbnail.width() == 256


def test_icon_generation_and_distribution_assets(tmp_path, qapp):
    source = Path(__file__).parents[1] / "src" / "picer" / "assets" / "icons" / "picer.svg"
    assets = tmp_path / "rendered"
    prepare_icons(source, assets / "icons")
    assert not QImage(str(assets / "icons" / "picer.png")).isNull()
    assert struct.unpack("<HHH", (assets / "icons" / "picer.ico").read_bytes()[:6]) == (0, 1, 7)
    application = tmp_path / "Picer"
    application.mkdir()
    (application / "Picer.exe").touch()  # This test checks layout; it never executes a fake binary.
    (application / "_internal").mkdir()
    prepare_distribution(application, assets, version="0.4.0")
    assert (application / "plugins" / ".keep").is_file()
    assert (application / "logs" / ".keep").is_file()
    assert (application / "cache" / ".keep").is_file()
    assert (application / "assets" / "icons" / "picer.ico").is_file()
    assert (
        json.loads((application / "distribution.json").read_text(encoding="utf-8"))["mode"]
        == "portable-folder"
    )
    with zipfile.ZipFile(application / "examples" / "negative-plugin.zip") as archive:
        assert set(archive.namelist()) == {"manifest.json", "main.py"}
    config = application / "config" / "plugins.json"
    config.write_text("custom settings", encoding="utf-8")
    prepare_distribution(application, assets, version="0.4.0")
    assert config.read_text() == "custom settings"
