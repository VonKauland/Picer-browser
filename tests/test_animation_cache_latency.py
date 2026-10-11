"""Animate while cache IO is blocked; prove startup reuse and incremental pruning."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

import picer.animation as animation_module
import picer.cache as cache_module
from picer.animation import AnimationPlayer, FrameSource
from picer.cache import ThumbnailCache
from picer.plugins.tasks import TaskToken
from picer.smoke_samples import make_animation
from picer.window import MainWindow


@pytest.fixture
def host(qtbot, tmp_path):
    window = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(window)
    window.show()
    yield window
    window.close()


@pytest.mark.parametrize("extension", ["gif", "webp"])
def test_animation_and_cached_preview_continue_while_disk_maintenance_blocks(
    host, qtbot, tmp_path, monkeypatch, extension
):
    directory = tmp_path / "animated"
    directory.mkdir()
    path = directory / f"motion.{extension}"
    make_animation(path)
    image = QImage(100, 60, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.blue)
    cached, busy = tmp_path / "cached.png", tmp_path / "busy.png"
    assert image.save(str(cached)) and image.save(str(busy))
    cache = host.thumbnail_cache
    cache.thumbnail(cached, image)
    qtbot.waitUntil(lambda: host.thumbnails.seed_worker is None)
    entered, release = Event(), Event()
    trim = cache._trim_disk

    def blocked_trim():
        entered.set()
        assert release.wait(5)
        trim()

    monkeypatch.setattr(cache, "_trim_disk", blocked_trim)
    with ThreadPoolExecutor(max_workers=1) as pool:
        writing = pool.submit(cache.thumbnail, busy, image)
        try:
            assert entered.wait(3)
            assert not cache.peek(cached).isNull()
            assert not writing.done()
            assert host.open_image(path)
            qtbot.waitUntil(lambda: host.animation.state.active)
            progress = host.plugins.records["example.progress"].instance
            progress.show_preview()
            qtbot.waitUntil(
                lambda: bool(progress.preview.items) and not progress.preview.items[0][2].isNull()
            )
            qtbot.waitUntil(lambda: host.animation.state.frame >= 1)
            assert not writing.done(), "GIF/WebP must play before cache IO is unblocked"
            assert not release.is_set()
        finally:
            release.set()
        assert not writing.result().isNull()


@pytest.mark.parametrize("extension", ["gif", "webp"])
def test_current_animation_uses_playback_first_frame_and_warms_shared_cache(
    host, qtbot, tmp_path, monkeypatch, extension
):
    # Isolate startup: a browser may legitimately have requested a thumbnail
    # before the viewer opens that file. Once decoded, current pixels are shared.
    host.plugins.disable("example.files")
    path = tmp_path / f"motion.{extension}"
    make_animation(path)
    import picer.loading as loading

    original = loading.read_image

    def no_duplicate_qt_decode(candidate, **kwargs):
        assert candidate != path, "Animation startup must reuse its playback decoder"
        return original(candidate, **kwargs)

    monkeypatch.setattr(loading, "read_image", no_duplicate_qt_decode)
    calls = []
    original_thumbnail = cache_module.read_image

    def thumbnail_decode(candidate, **kwargs):
        calls.append(candidate)
        return original_thumbnail(candidate, **kwargs)

    monkeypatch.setattr(cache_module, "read_image", thumbnail_decode)
    assert host.open_image(path)
    qtbot.waitUntil(lambda: host.animation.state.active)
    results = []
    context = host.plugins.records["example.progress"].context
    context.request_thumbnail(path, results.append, edge=80)
    qtbot.waitUntil(lambda: bool(results))
    assert results[0].width() == 80
    assert results[0].pixelColor(0, 0).red() > 240
    assert not calls
    qtbot.waitUntil(
        lambda: host.thumbnails.seed_worker is None and not host.thumbnails.seed_pending
    )
    qtbot.waitUntil(lambda: bool(list(host.thumbnail_cache.directory.glob("*.png"))))
    assert not host.last_error


@pytest.mark.parametrize("extension", ["gif", "webp"])
def test_first_frame_is_not_decoded_twice_when_it_exceeds_frame_cache_budget(
    tmp_path, qapp, monkeypatch, extension
):
    path = tmp_path / f"motion.{extension}"
    make_animation(path)
    monkeypatch.setattr(animation_module, "FRAME_CACHE_BYTES", 1)
    decoded = []
    original = animation_module.pillow_image

    def decode(reader):
        decoded.append(reader.tell())
        return original(reader)

    monkeypatch.setattr(animation_module, "pillow_image", decode)
    source = FrameSource(path)
    preview = source.preview(32, TaskToken())
    assert preview.width() == 32 and preview.text("picer.native_width") == "96"
    assert source.bytes == 0 and not source.cache
    pixels = []
    player = AnimationPlayer()
    player.pixels.connect(pixels.append)
    try:
        player.start(source)
        player.toggle(False)
        assert decoded == [0]
        assert len(pixels) == 1 and pixels[0].width() == 96
        assert source.initial_frame is None
        assert not source.cache and source.bytes == 0
    finally:
        player.shutdown()


def test_cache_eviction_updates_index_without_repeated_directory_scans(tmp_path, qapp, monkeypatch):
    cache = ThumbnailCache(tmp_path / "cache", limit=3)
    original = cache._scan_disk
    scans = []

    def scan():
        scans.append(True)
        original()

    monkeypatch.setattr(cache, "_scan_disk", scan)
    image = QImage(40, 30, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.blue)
    for i in range(12):
        source = tmp_path / f"{i}.png"
        assert image.save(str(source))
        assert not cache.thumbnail(source, image).isNull()
        assert len(list(cache.directory.glob("*.png"))) <= 3
    assert len(scans) == 1
    assert len(cache._disk_entries) == 3
    assert cache._disk_bytes == sum(file.stat().st_size for file in cache.directory.glob("*.png"))
    cache.prune()
    assert len(scans) == 2


@pytest.mark.parametrize("auto_orient", [True, False])
def test_reused_webp_first_frame_preserves_orientation_for_all_frames(tmp_path, qapp, auto_orient):
    from PIL import Image

    path = tmp_path / "rotated.webp"
    exif = Image.Exif()
    exif[274] = 6
    frames = [Image.new("RGB", (96, 64), color) for color in ("red", "green")]
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
        lossless=True,
        exif=exif,
    )
    source = FrameSource(path, auto_orient=auto_orient)
    try:
        preview = source.preview(32, TaskToken())
        expected = (64, 96) if auto_orient else (96, 64)
        assert (
            int(preview.text("picer.native_width")),
            int(preview.text("picer.native_height")),
        ) == expected
        first, _ = source.take_initial()
        second, _ = source.frame(1, TaskToken())
        assert (first.width(), first.height()) == expected
        assert (second.width(), second.height()) == expected
    finally:
        source.close()
