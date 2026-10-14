"""Real shared decoding, durable cache, progressive delivery and unrestricted browsing."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from PIL import Image
from PySide6.QtCore import QPoint, Qt

import picer.cache as cache_module
from picer.cache import ThumbnailCache
from picer.window import MainWindow


@pytest.fixture
def host(qtbot, tmp_path):
    window = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(window)
    window.show()
    yield window
    window.close()


def test_concurrent_sizes_share_decode_disk_reload_and_invalidate(tmp_path, monkeypatch, qapp):
    path = tmp_path / "photo.png"
    Image.new("RGB", (600, 400), "red").save(path)
    real_read = cache_module.read_image
    entered, release = Event(), Event()
    calls = []

    def decode(path, **kwargs):
        calls.append(path)
        entered.set()
        assert release.wait(3)
        return real_read(path, **kwargs)

    monkeypatch.setattr(cache_module, "read_image", decode)
    cache = ThumbnailCache(tmp_path / "cache")
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cache.read, path, edge=80)
        assert entered.wait(3)
        second = pool.submit(cache.read, path, edge=128)
        release.set()
        assert first.result().width() == 80
        assert second.result().width() == 128
    assert len(calls) == 1
    assert len(list(cache.directory.glob("*.png"))) == 1
    reopened = ThumbnailCache(tmp_path / "cache")
    assert reopened.read(path, edge=200).pixelColor(0, 0).red() == 255
    assert len(calls) == 1
    Image.new("RGB", (601, 400), "blue").save(path)
    assert reopened.read(path).pixelColor(0, 0).blue() == 255
    assert len(calls) == 2
    reopened.clear()
    assert reopened.peek(path) is None
    assert not list(cache.directory.glob("*.png"))


def test_cache_clear_during_decode_does_not_repopulate(tmp_path, monkeypatch, qapp):
    path = tmp_path / "picture.png"
    Image.new("RGB", (200, 100), "red").save(path)
    entered, release = Event(), Event()
    real_read = cache_module.read_image

    def decode(path, **kwargs):
        entered.set()
        assert release.wait(3)
        return real_read(path, **kwargs)

    monkeypatch.setattr(cache_module, "read_image", decode)
    cache = ThumbnailCache(tmp_path / "cache")
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(cache.read, path)
        assert entered.wait(3)
        cache.clear()
        release.set()
        assert not pending.result().isNull()
    assert not cache.memory
    assert not list(cache.directory.glob("*.png"))


def test_two_plugin_contexts_share_pixels_and_revoke_delivery(
    host, qtbot, tmp_path, monkeypatch, qapp
):
    path = tmp_path / "isolated.png"
    Image.new("RGB", (300, 200), "blue").save(path)
    files = host.plugins.records["example.files"].context
    progress = host.plugins.records["example.progress"].context
    real_read = cache_module.read_image
    calls = []

    def decode(path, **kwargs):
        calls.append(path)
        return real_read(path, **kwargs)

    monkeypatch.setattr(cache_module, "read_image", decode)
    results = []
    files.request_thumbnail(path, lambda image: results.append(image), edge=128)
    progress.request_thumbnail(path, lambda image: results.append(image), edge=80)
    qtbot.waitUntil(lambda: len(results) == 2)
    assert sorted(image.width() for image in results) == [80, 128]
    assert len(calls) == 1
    delivered = []
    token = progress.request_thumbnail(path, delivered.append)
    host.plugins.disable("example.progress")
    qtbot.wait(50)
    assert token.cancelled and not delivered
    assert len(calls) == 1


def test_preview_displays_fast_tile_without_waiting_for_slow_tile(
    host, qtbot, tmp_path, monkeypatch
):
    folder = tmp_path / "photos"
    folder.mkdir()
    for i in range(6):
        Image.new("RGB", (100, 60), "blue").save(folder / f"{i}.png")
    assert host.open_image(folder / "0.png")
    release, entered = Event(), Event()
    read = host.thumbnail_cache.read

    def slow(path, **kwargs):
        if path.name == "1.png":
            entered.set()
            assert release.wait(5)
        return read(path, **kwargs)

    monkeypatch.setattr(host.thumbnail_cache, "read", slow)
    progress = host.plugins.records["example.progress"].instance
    try:
        progress.show_preview()
        qtbot.waitUntil(entered.is_set)
        qtbot.waitUntil(
            lambda: any(i == 0 and not image.isNull() for i, _, image in progress.preview.items)
        )
        assert any(i == 1 and image.isNull() for i, _, image in progress.preview.items)
        assert progress.preview.isVisible()
    finally:
        release.set()
    qtbot.waitUntil(lambda: not host.thumbnails.running and not host.thumbnails.pending)


def test_preview_browses_past_legacy_count_limit_with_bounded_work(host, qtbot, tmp_path):
    folder = tmp_path / "many"
    folder.mkdir()
    for i in range(160):
        Image.new("RGB", (16, 16), "red").save(folder / f"{i:03}.png")
    assert host.open_image(folder / "000.png")
    qtbot.waitUntil(lambda: len(host.paths) == 160)
    progress = host.plugins.records["example.progress"].instance
    progress.context.set_setting("thumbnail_count", 3)  # Old persisted limits are ignored.
    assert "thumbnail_count" not in {field.key for field in progress.fields}
    progress.show_preview()
    progress.preview.move_center(159)
    assert progress.preview.center_index == 159
    qtbot.waitUntil(
        lambda: any(i == 159 and not image.isNull() for i, _, image in progress.preview.items)
    )
    assert len(progress.preview.items) < 20
    assert len(progress.preview_tokens) < 20
    qtbot.keyClick(progress.preview, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: host.current_path.name == "159.png")


def test_accent_controls_fullscreen_and_coexisting_bottom_indicator(host, qtbot, tmp_path):
    host.plugins.preferences["ui"]["application"] = {"accent_color": "#FFA591"}
    host.apply_preferences()
    controls = host.title_bar.control_buttons
    assert list(controls) == ["fullscreen", "minimize", "maximize", "close"]
    assert all(
        button.size().width() == button.size().height() == 32 for button in controls.values()
    )
    for button in controls.values():
        pixels = button.grab().toImage()
        assert any(
            pixels.pixelColor(x, y).name().lower() == "#ffa591"
            for x in range(32)
            for y in range(32)
        )
    qtbot.mouseClick(controls["fullscreen"], Qt.MouseButton.LeftButton)
    assert host.isFullScreen()
    qtbot.mouseClick(controls["fullscreen"], Qt.MouseButton.LeftButton)
    assert not host.isFullScreen()
    controller = host.panel_hovers.controllers["example.progress"]
    controller.dock.close()
    assert controller.strip.isVisible() and controller.indicator.isVisible()
    assert controller.indicator.width() == 84 and controller.indicator.height() == 5
    assert controller.strip.geometry().bottom() < controller.indicator.geometry().top()
    qtbot.mouseClick(controller.indicator, Qt.MouseButton.LeftButton, pos=QPoint(40, 2))
    assert not controller.dock.isHidden()
    assert controller.strip.isHidden() and controller.indicator.isHidden()
    controller.dock.close()
    assert controller.indicator.isVisible() and controller.strip.isVisible()
    host.plugins.disable("example.progress")
    assert controller.indicator.isHidden() and controller.strip.isHidden()


def test_slow_cache_write_does_not_block_full_resolution_refinement(
    host, qtbot, tmp_path, monkeypatch
):
    path = tmp_path / "large.jpg"
    Image.new("RGB", (3000, 1800), "blue").save(path, quality=95)
    entered, release = Event(), Event()
    store = host.thumbnail_cache.thumbnail

    def blocked_write(path, image):
        entered.set()
        assert release.wait(5)
        return store(path, image)

    monkeypatch.setattr(host.thumbnail_cache, "thumbnail", blocked_write)
    host.loader.set_rapid(True)
    try:
        assert host.open_image(path)
        qtbot.waitUntil(entered.is_set)
        assert host.view.image_item.pixmap().width() == 960
        host.loader.set_rapid(False)
        qtbot.waitUntil(lambda: host.view.image_item.pixmap().width() == 3000)
        assert not release.is_set()
    finally:
        release.set()
    qtbot.waitUntil(lambda: host.thumbnails.seed_worker is None)
