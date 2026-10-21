"""Visited browser thumbnails survive long scrolls without unbounded retention."""

from types import SimpleNamespace

import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

import picer.cache as cache_module
from examples.file_browser.thumbnails import PhotoModel
from picer.cache import ThumbnailCache
from picer.plugins.tasks import TaskToken
from picer.thumbnails import ThumbnailService


@pytest.fixture
def model(qapp):
    requests = []

    def request(path, callback, **kwargs):
        token = TaskToken()
        requests.append((token, callback))
        return token

    result = PhotoModel(SimpleNamespace(request_thumbnail=request), None)
    result.requests = requests
    yield result
    result.stop()
    result.deleteLater()


def pixels(width=128, height=80):
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.red)
    return image


def file_key(model, path):
    index = model.index(str(path))
    info = model.fileInfo(index)
    return str(path), info.lastModified().toMSecsSinceEpoch(), info.size()


def test_scroll_beyond_256_returns_icons_without_new_shared_requests(
    model, tmp_path, qtbot, monkeypatch
):
    folder = tmp_path / "photos"
    folder.mkdir()
    paths = [folder / f"{i:03}.png" for i in range(320)]
    for path in paths:
        Image.new("RGB", (128, 80), "red").save(path)
    cache = ThumbnailCache(tmp_path / "cache")
    service = ThumbnailService(cache)
    requests, decodes = [], []
    read = cache_module.read_image

    def decode(path, **kwargs):
        decodes.append(path)
        return read(path, **kwargs)

    def request(path, callback, **kwargs):
        requests.append(path)
        return service.request(path, callback, **kwargs)

    monkeypatch.setattr(cache_module, "read_image", decode)
    model.context = SimpleNamespace(request_thumbnail=request)
    root = model.setRootPath(str(folder))
    qtbot.waitUntil(lambda: model.rowCount(root) == len(paths))
    try:
        # Simulate successive viewport ranges without loading the whole folder
        # up front; the shared master cache is smaller than this browsing pass.
        for offset in range(0, len(paths), 40):
            batch = paths[offset : offset + 40]
            for path in batch:
                model.data(model.index(str(path)), Qt.ItemDataRole.DecorationRole)
            qtbot.waitUntil(
                lambda batch=batch: all(file_key(model, path) in model.cache for path in batch)
            )
        assert len(requests) == len(decodes) == len(paths)
        assert len(cache.memory) < len(paths)
        # Even after host memory eviction, previously visited rows paint
        # immediately instead of flashing placeholders and scheduling more IO.
        for path in reversed(paths):
            key = file_key(model, path)
            icon = model.data(model.index(str(path)), Qt.ItemDataRole.DecorationRole)
            assert icon.cacheKey() == model.cache[key].cacheKey()
            assert icon.pixmap(128, 128).toImage().pixelColor(0, 0).red() == 255
        assert len(requests) == len(decodes) == len(paths)
        assert not model.pending and not model.tokens
        assert 0 < model.cache_bytes <= model.CACHE_BYTE_LIMIT
    finally:
        model.stop()
        service.shutdown()


def test_pixel_budget_evicts_least_recently_used_not_recently_revisited(model, tmp_path):
    paths = [tmp_path / f"{i}.png" for i in range(3)]
    for path in paths:
        Image.new("RGB", (20, 10), "red").save(path)
    model.setRootPath(str(tmp_path))
    keys = [file_key(model, path) for path in paths]
    image = pixels()
    model.remember(keys[0], image)
    cost = model.cache_bytes
    model.CACHE_BYTE_LIMIT = cost * 2
    model.remember(keys[1], image)
    model.data(model.index(str(paths[0])), Qt.ItemDataRole.DecorationRole)
    model.remember(keys[2], image)
    assert keys[0] in model.cache and keys[2] in model.cache
    assert keys[1] not in model.cache
    assert model.cache_bytes == cost * 2
    assert len(model.cache_sizes) == len(model.cache_paths) == 2


def test_entry_limit_bounds_empty_icons_too(model):
    model.CACHE_ENTRY_LIMIT = 3
    for i in range(10):
        model.remember((f"{i}.png", 0, 0), QImage())
    assert [key[0] for key in model.cache] == ["7.png", "8.png", "9.png"]
    assert model.cache_bytes == 3 * 512
    assert len(model.cache_sizes) == len(model.cache_paths) == 3


def test_modified_file_replaces_old_version_and_budget(model):
    old, current = ("photo.png", 1, 50), ("photo.png", 2, 70)
    model.remember(old, pixels())
    model.remember(current, pixels(64, 40))
    assert list(model.cache) == [current]
    assert model.cache_bytes == 512 + 64 * 40 * 4
    assert model.cache_paths == {"photo.png": current}
    model.remember(current, pixels())
    assert model.cache_bytes == 512 + 128 * 80 * 4


def test_disable_releases_icons_and_rejects_late_results(model):
    model.remember(("cached.png", 0, 0), pixels())
    model.pending[("pending.png", 0, 0)] = None
    model.load_batch()
    token, callback = model.requests[0]
    model.stop()
    assert token.cancelled
    callback(pixels())
    assert not model.cache and not model.cache_sizes and not model.cache_paths
    assert not model.pending and not model.tokens
    assert model.cache_bytes == 0
