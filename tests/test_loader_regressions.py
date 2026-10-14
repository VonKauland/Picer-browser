"""Queue pressure and settings changes during real background image work."""

import os
from pathlib import Path
from threading import Event

import pytest
from PIL import Image

from picer.imaging import read_image
from picer.window import MainWindow


@pytest.fixture
def host(qtbot, tmp_path):
    window = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(window)
    window.show()
    yield window
    window.close()


def prepare_neighbours(host, tmp_path, count=3):
    for name in ("a", "b", "c")[:count]:
        Image.new("RGB", (80, 60), "blue").save(tmp_path / f"{name}.jpg")
    assert host.open_image(tmp_path / "b.jpg")
    host.loader.prefetch_timer.stop()
    host.loader.clear_cache()


@pytest.mark.parametrize("count", [2, 3])
def test_neighbour_prefetch_stays_bounded_while_decoder_is_busy(
    host, tmp_path, qtbot, monkeypatch, count
):
    prepare_neighbours(host, tmp_path, count)
    entered, release = Event(), Event()
    calls = []

    def blocked(path, **options):
        calls.append(path)
        entered.set()
        assert release.wait(10)
        return read_image(path, **options)

    monkeypatch.setattr("picer.loading.read_image", blocked)
    try:
        host.loader.prefetch()
        qtbot.waitUntil(entered.is_set)
        for _ in range(40):
            host.loader.prefetch()
        assert sum(lane == "prefetch" for _, lane, _ in host.loader.jobs.values()) <= 2
    finally:
        release.set()
    qtbot.waitUntil(lambda: not host.loader.jobs, timeout=10000)
    qtbot.wait(50)
    assert len(calls) == count - 1 and len(set(calls)) == count - 1


def test_clear_cache_does_not_get_undone_by_inflight_prefetch(host, tmp_path, qtbot, monkeypatch):
    prepare_neighbours(host, tmp_path)
    entered, release = Event(), Event()

    def blocked(path, **options):
        entered.set()
        assert release.wait(10)
        return read_image(path, **options)

    monkeypatch.setattr("picer.loading.read_image", blocked)
    try:
        host.loader.prefetch()
        qtbot.waitUntil(entered.is_set)
        host.loader.clear_cache()
    finally:
        release.set()
    qtbot.waitUntil(lambda: not host.loader.jobs, timeout=10000)
    assert not host.loader.cache and host.loader.cache_bytes == 0
    assert host.current_path == tmp_path / "b.jpg"
    assert not host.view.image_item.pixmap().isNull()


def test_changing_formats_discards_pending_folder_open_without_false_failure(
    host, tmp_path, qtbot, monkeypatch
):
    existing = tmp_path / "existing.jpg"
    Image.new("RGB", (80, 60), "blue").save(existing)
    assert host.open_image(existing)
    folder = tmp_path / "new"
    folder.mkdir()
    Image.new("RGB", (80, 60), "red").save(folder / "a.png")
    Image.new("RGB", (80, 60), "green").save(folder / "b.jpg")
    entered, release = Event(), Event()
    original = os.scandir
    failures = []

    def blocked(directory):
        if Path(directory) == folder:
            entered.set()
            assert release.wait(10)
        return original(directory)

    monkeypatch.setattr("picer.loading.os.scandir", blocked)
    monkeypatch.setattr(host, "loading_failed", lambda *args: failures.append(args))
    try:
        host.loader.open_folder(folder)
        qtbot.waitUntil(entered.is_set)
        host.plugins.preferences["ui"]["application"] = {"readable_formats": [".jpg"]}
        host.apply_preferences()
    finally:
        release.set()
    qtbot.waitUntil(lambda: not host.loader.jobs, timeout=10000)
    assert not failures
    assert host.current_path == existing and folder not in host.loader.directories
    host.loader.open_folder(folder)
    qtbot.waitUntil(lambda: host.current_path == folder / "b.jpg")
    assert host.paths == [folder / "b.jpg"]
