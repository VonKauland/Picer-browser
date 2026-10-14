"""Real RAW/animated media, latest-wins races, progressive zoom and huge indexes."""

from threading import Event

import pytest
from PIL import Image
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage

from picer.imaging import RAW_SUFFIXES, read_image, supported_suffixes
from picer.metadata import inspect_image
from picer.smoke_samples import make_animation, make_dng, make_stills
from picer.window import MainWindow


@pytest.fixture
def host(qtbot, tmp_path):
    window = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(window)
    window.show()
    yield window
    window.close()


def test_actual_libraw_preview_full_and_metadata(tmp_path, qapp):
    path = tmp_path / "相机.dng"
    make_dng(path)
    preview, full = read_image(path, edge=96), read_image(path)
    assert preview.width() == 96 and full.width() == 256
    assert not full.isNull() and full.pixelColor(200, 200) != full.pixelColor(40, 40)
    metadata = inspect_image(path)
    assert metadata["dimensions"]["宽度"] == "256"
    assert metadata["exif"] and len(metadata["histogram"]) == 3
    assert not metadata["warnings"]
    assert {".cr2", ".cr3", ".nef", ".arw", ".raf", ".dng"} <= RAW_SUFFIXES


def test_available_still_image_codecs_decode(tmp_path, qapp):
    assert {"png", "jpg", "bmp", "webp", "ico", "ppm", "xbm", "xpm", "svg"} <= set(
        make_stills(tmp_path)
    )


@pytest.mark.parametrize("extension", ["gif", "webp"])
def test_animation_play_pause_seek_cleanup_and_panel_motion(host, qtbot, tmp_path, extension):
    path = tmp_path / f"motion.{extension}"
    make_animation(path)
    assert host.open_image(path)
    qtbot.waitUntil(lambda: host.animation.state.active)
    player = host.animation
    plugin = host.plugins.records["example.progress"].instance
    assert player.state.count == 3 and player.state.playing
    qtbot.waitUntil(lambda: player.state.frame > 0)
    player.toggle(False)
    player.seek(2)
    qtbot.waitUntil(lambda: player.state.duration == 190)
    assert host.view.image_item.pixmap().toImage().pixelColor(30, 30).blue() > 240
    qtbot.waitUntil(lambda: plugin.playback_expansion == 1)
    assert plugin.dock.height() == 100 and not plugin.playback.isHidden()
    qtbot.mouseClick(plugin.playback_button, Qt.MouseButton.LeftButton)
    assert player.state.playing
    qtbot.mouseClick(plugin.playback_button, Qt.MouseButton.LeftButton)
    plugin.playback_slider.setValue(0)
    qtbot.waitUntil(lambda: player.state.duration == 80)
    qtbot.wait(150)
    assert player.state.frame == 0 and not player.state.playing
    plugin.show_preview()
    qtbot.waitUntil(lambda: plugin.expansion == 1)
    assert plugin.dock.height() == 80
    still = tmp_path / "still.png"
    Image.new("RGB", (96, 64)).save(still)
    assert host.open_image(still)
    assert not player.state.active
    qtbot.waitUntil(lambda: plugin.playback_expansion == 0)
    assert plugin.dock.height() == 52 and plugin.playback.isHidden()
    assert plugin.preview_open and plugin.preview.isVisible()


def test_large_image_is_background_preview_then_full_without_zoom_jump(host, qtbot, tmp_path):
    path = tmp_path / "large.jpg"
    Image.new("RGB", (4200, 2800), "red").save(path)
    ticks = []
    timer = QTimer(host)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(5)
    assert host.open_image(path)
    assert host.current_path is None
    qtbot.waitUntil(lambda: host.current_path == path)
    assert host.view.image_item.pixmap().width() == 1600
    host.view.actual_size()
    host.view.zoom(1.25)
    visible_width = host.view.image_item.sceneBoundingRect().width() * host.view.transform().m11()
    qtbot.waitUntil(lambda: host.view.image_item.pixmap().width() == 4200)
    assert (
        host.view.image_item.sceneBoundingRect().width() * host.view.transform().m11()
        == pytest.approx(visible_width)
    )
    assert ticks and not host.view.fit_mode


def test_old_background_pixels_cannot_overwrite_new_image(host, qtbot, tmp_path, monkeypatch):
    first, second = tmp_path / "a.jpg", tmp_path / "b.png"
    Image.new("RGB", (3200, 2400), "red").save(first)
    Image.new("RGB", (80, 60), "blue").save(second)
    started, release = Event(), Event()
    original = read_image

    def slow(path, **options):
        if path == first:
            started.set()
            assert release.wait(3)
        return original(path, **options)

    monkeypatch.setattr("picer.loading.read_image", slow)
    try:
        assert host.open_image(first)
        qtbot.waitUntil(started.is_set)
        assert host.open_image(second)
    finally:
        release.set()
    qtbot.waitUntil(lambda: not host.loader.jobs)
    assert host.current_path == second
    assert host.view.image_item.pixmap().width() == 80
    assert host.view.image_item.pixmap().toImage().pixelColor(0, 0).blue() == 255


def test_index_reused_for_twenty_thousand_files_and_invalidation(
    host, qtbot, tmp_path, monkeypatch
):
    import os

    directory = tmp_path / "many"
    directory.mkdir()
    first = directory / "00000.png"
    Image.new("RGB", (80, 60)).save(first)
    real_scan = os.scandir
    calls = []

    class Entries:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def __iter__(self):
            from types import SimpleNamespace

            return iter(
                SimpleNamespace(
                    name=f"{i:05}.png", path=str(directory / f"{i:05}.png"), is_file=lambda: True
                )
                for i in range(20_000)
            )

    def scan(path):
        if str(path) == str(directory):
            calls.append(1)
            return Entries()
        return real_scan(path)

    monkeypatch.setattr("picer.loading.os.scandir", scan)
    host.open_image(first)
    qtbot.waitUntil(lambda: len(host.paths) == 20_000)
    initial = len(calls)
    positions = host.path_positions
    snapshot = host.image_path_snapshot
    for _ in range(30):
        assert host.open_image(first)
    assert len(calls) == initial
    assert host.path_positions is positions and host.image_path_snapshot is snapshot
    context = host.plugins.records["example.progress"].context
    assert context.image_paths() is snapshot and context.image_index() == 0
    assert len(host.loader.jobs) <= 5
    host.loader.invalidate_directory(str(directory))
    qtbot.waitUntil(lambda: len(calls) > initial)


def test_unified_browser_raw_thumbnails(host, qtbot, tmp_path):
    path = tmp_path / "photo.dng"
    make_dng(path)
    browser = host.plugins.records["example.files"].instance
    assert set(browser.model.files.nameFilters()) == {
        f"*{suffix}" for suffix in supported_suffixes()
    }
    browser.open_folder(tmp_path)
    qtbot.waitUntil(lambda: browser.model.index(str(path)).isValid())
    index = browser.model.index(str(path))
    browser.model.data(index, Qt.ItemDataRole.DecorationRole)
    qtbot.waitUntil(lambda: any(key[0] == str(path) for key in browser.model.cache))
    icon = next(value for key, value in browser.model.cache.items() if key[0] == str(path))
    assert not icon.isNull()


def test_preview_and_frame_caches_obey_byte_limits(host, qapp):
    loader = host.loader
    loader.cache_limit = 5000
    for i in range(10):
        image = QImage(32, 32, QImage.Format.Format_RGB32)
        loader.remember((i,), image)
    assert loader.cache_bytes <= 5000 and len(loader.cache) == 1


def test_async_unreadable_raw_is_skipped_and_cannot_loop(host, qtbot, tmp_path):
    first, last = tmp_path / "a.png", tmp_path / "c.png"
    Image.new("RGB", (80, 60), "red").save(first)
    Image.new("RGB", (80, 60), "blue").save(last)
    (tmp_path / "b.dng").write_bytes(b"not a raw file")
    assert host.open_image(first)
    host.navigate(1)
    qtbot.waitUntil(lambda: host.current_path == last)
    last.unlink()
    host.loader.invalidate_directory(str(tmp_path))
    qtbot.waitUntil(
        lambda: tmp_path in host.loader.directories
        and last not in host.loader.directories[tmp_path]
    )
    host.open_image(first)
    host.navigate(1)
    qtbot.waitUntil(lambda: not host.loader.jobs)
    assert host.current_path == first and host.navigation_request is None


def test_animation_detected_by_content_rotation_and_reversal(host, qtbot, tmp_path):
    original = tmp_path / "motion.gif"
    make_animation(original)
    renamed = tmp_path / "renamed.png"
    original.rename(renamed)
    assert host.open_image(renamed)
    qtbot.waitUntil(lambda: host.animation.state.active)
    progress = host.plugins.records["example.progress"].instance
    qtbot.waitUntil(lambda: 0.05 < progress.playback_expansion < 0.95)
    host.rotate_image()
    assert host.animation.state.active and host.animation.state.playing
    host.animation.seek(2)
    qtbot.waitUntil(lambda: host.view.image_item.pixmap().width() == 64)
    assert host.view.image_item.pixmap().height() == 96
    still = tmp_path / "still.png"
    Image.new("RGB", (80, 60)).save(still)
    host.open_image(still)
    qtbot.waitUntil(lambda: 0 < progress.playback_expansion < 1)
    host.open_image(renamed)
    qtbot.waitUntil(lambda: host.animation.state.active)
    qtbot.waitUntil(lambda: progress.playback_expansion == 1)
    assert progress.dock.height() == 100
    host.plugins.disable("example.progress")
    assert progress.playback_motion.state() == progress.playback_motion.State.Stopped


def test_raw_embedded_preview_avoids_sensor_unpack(tmp_path, qapp, monkeypatch):
    from io import BytesIO
    from types import SimpleNamespace

    buffer = BytesIO()
    Image.new("RGB", (160, 100), "red").save(buffer, format="JPEG")

    class EmbeddedRaw:
        sizes = SimpleNamespace(width=6000, height=4000)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def open_file(self, path):
            pass

        def extract_thumb(self):
            import rawpy

            return SimpleNamespace(format=rawpy.ThumbFormat.JPEG, data=buffer.getvalue())

        def postprocess(self, **options):
            raise AssertionError("embedded previews must not unpack/demosaic sensor data")

    monkeypatch.setattr("rawpy.RawPy", EmbeddedRaw)
    image = read_image(tmp_path / "camera.nef", edge=128)
    assert image.width() == 128 and image.pixelColor(0, 0).red() > 240
    assert image.text("picer.native_width") == "6000"


def test_frame_cache_bounded_and_finite_loop_stops(host, qtbot, tmp_path):
    from picer.animation import FrameSource
    from picer.plugins.tasks import TaskToken

    path = tmp_path / "once.gif"
    frames = [Image.new("RGB", (96, 64), (i * 10, 255 - i * 10, 100)) for i in range(20)]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=10)
    source = FrameSource(path)
    for index in range(source.count):
        source.frame(index, TaskToken())
    assert len(source.cache) <= 12 and source.bytes <= 64 * 1048576
    source.close()
    host.open_image(path)
    qtbot.waitUntil(lambda: host.animation.state.active)
    qtbot.waitUntil(lambda: not host.animation.state.playing, timeout=5000)
    assert host.animation.state.frame == 19


def test_bad_background_image_preserves_existing_animation(host, qtbot, tmp_path, monkeypatch):
    path = tmp_path / "motion.gif"
    make_animation(path)
    host.open_image(path)
    qtbot.waitUntil(lambda: host.animation.state.active)
    other = tmp_path / "bad.jpg"
    Image.new("RGB", (3200, 2400), "red").save(other)

    def fail(*args, **kwargs):
        raise ValueError("unreadable pixels")

    monkeypatch.setattr("picer.loading.read_image", fail)
    assert host.open_image(other)
    qtbot.waitUntil(lambda: "unreadable pixels" in host.last_error)
    assert host.current_path == path and host.animation.state.active
    assert host.animation.state.playing
