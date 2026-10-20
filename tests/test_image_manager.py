"""Opt-in image management, shared durable marks and bounded shared thumbnails."""

import pytest
from PIL import Image
from PySide6.QtCore import QPoint, Qt
from pytestqt.exceptions import TimeoutError as QtTimeoutError

from picer.annotations import AnnotationStore
from picer.plugins.api import PluginError
from picer.window import MainWindow


def test_annotation_migration_and_durable_history(tmp_path):
    path = tmp_path / "photo.jpg"
    db = tmp_path / "annotations.sqlite3"
    legacy = {"ratings": {str(path): 4}, "color_labels": {str(path): "blue"}}
    store = AnnotationStore(db, legacy)
    assert store.snapshot()[str(path)] == {"rating": 4, "color": "blue"}
    store.set(path, rating=3.5)
    for n in range(260):
        store.set(tmp_path / f"{n}.png", color="red")
    restarted = AnnotationStore(db, legacy)
    assert restarted.snapshot()[str(path)]["rating"] == 3.5
    assert len(restarted.snapshot()) == 261
    detached = restarted.snapshot()
    detached[str(path)]["color"] = "purple"
    assert restarted.snapshot()[str(path)]["color"] == "blue"
    for invalid in (-0.5, 5.5, 0.3, float("nan")):
        with pytest.raises(ValueError):
            restarted.set(path, rating=invalid)


@pytest.fixture
def host(qtbot, tmp_path, request):
    window = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(window)
    window.resize(1200, 800)
    window.show()
    folder = tmp_path / "album"
    folder.mkdir()
    for n in range(getattr(request, "param", 8)):
        Image.new("RGB", (40, 30), (n * 20, 40, 80)).save(folder / f"{n}.png")
    (folder / "folder.png").mkdir()
    (folder / "ignored.txt").write_text("not an image")
    window.open_image(folder / "0.png")
    yield window, folder
    window.plugins.shutdown()


def enable(host, qtbot):
    window, folder = host
    assert window.plugins.records["example.images"].state == "disabled"
    window.plugins.enable("example.images")
    panel = window.plugins.records["example.images"].instance
    qtbot.waitUntil(lambda: panel.model.rowCount() == 8, timeout=5000)
    return window, folder, panel


def test_default_off_right_only_images_and_visible_shared_thumbnails(host, qtbot):
    window, folder, panel = enable(host, qtbot)
    assert window.dockWidgetArea(panel.dock) == Qt.DockWidgetArea.RightDockWidgetArea
    assert panel.size.value() == 100
    window.panel_hovers.controllers["example.images"].resize_extent(310)
    window.panel_hovers.controllers["example.images"].pin()
    qtbot.wait(100)
    first, second, third = [panel.grid.visualRect(panel.model.index(n)) for n in range(3)]
    assert second.top() == first.top() and third.top() > first.top(), (
        panel.grid.size(),
        panel.grid.viewport().size(),
        panel.grid.gridSize(),
        panel.grid.verticalScrollBar().sizeHint(),
    )
    assert all(path.parent == folder and path.suffix == ".png" for path in panel.model.paths)
    qtbot.waitUntil(
        lambda: bool(panel.pixels) or window.plugins.records["example.images"].state != "enabled",
        timeout=5000,
    )
    assert panel.pixels, window.plugins.records["example.images"].error
    assert len(panel.pixels) <= 96 and len(panel.requests) <= 80
    assert len(panel.watcher.files()) <= 80
    assert panel.grid.horizontalScrollBar().maximum() == 0
    width = panel.grid.gridSize().width()
    panel.size.setValue(200)
    qtbot.wait(60)
    assert panel.grid.gridSize().width() > width
    panel.search.setText("2")
    qtbot.waitUntil(lambda: panel.model.rowCount() == 1)
    panel.open_index(panel.model.index(0))
    assert window.current_path == folder / "2.png"
    old_context = window.plugins.records["example.images"].context
    with pytest.raises(PluginError):
        old_context.set_image_annotation(folder / "2.png", rating=2)
    window.plugins.disable("example.images")
    assert not panel.active and not panel.requests
    assert not panel.watcher.files() and not panel.watcher.directories()
    with pytest.raises(PluginError):
        old_context.image_annotations()


def test_rating_color_filters_counts_and_realtime_sync(host, qtbot):
    window, folder, panel = enable(host, qtbot)
    context = window.plugins.records["example.info"].context
    original = (folder / "0.png").read_bytes()
    context.set_image_annotation(folder / "0.png", rating=3.5, color="blue")
    context.set_image_annotation(folder / "1.png", rating=3, color="blue")
    context.set_image_annotation(folder / "2.png", rating=4, color="red")
    qtbot.waitUntil(lambda: panel.notes.get(str(folder / "0.png"), {}).get("rating") == 3.5)
    panel.filter_menu()
    popup = panel.popup
    assert popup.rating_counts[3.5] == 1 and popup.color_counts["blue"] == 2
    # Half of the last star on the fourth row selects 3.5 without extra controls.
    qtbot.mouseClick(popup.ratings[4], Qt.MouseButton.LeftButton, pos=QPoint(87, 13))
    assert popup.state["rating"] == 3.5
    popup.compare("ge")
    assert popup.color_counts["blue"] == 1 and popup.color_counts["red"] == 1
    popup.colors[4].click()
    assert popup.colors[4].grab().toImage().pixelColor(16, 13).name() == "#488fff"
    popup.apply()
    qtbot.waitUntil(lambda: panel.model.paths == [folder / "0.png"])
    context.set_image_annotation(folder / "0.png", color="red")
    qtbot.waitUntil(lambda: panel.model.rowCount() == 0)
    assert (folder / "0.png").read_bytes() == original


def test_device_scope_known_only_and_local_directory_follow(host, qtbot, tmp_path):
    window, folder, panel = enable(host, qtbot)
    second = tmp_path / "other"
    second.mkdir()
    marked, unmarked = second / "marked.jpg", second / "unmarked.jpg"
    for path in (marked, unmarked):
        Image.new("RGB", (32, 24), "green").save(path)
    ctx = window.plugins.records["example.info"].context
    ctx.set_image_annotation(marked, rating=4.5, color="green")
    missing = second / "missing.jpg"
    ctx.set_image_annotation(missing, rating=5)
    ctx.set_image_annotation(folder / "ignored.txt", rating=5)
    panel.filter_menu()
    popup = panel.popup
    popup.scope.setChecked(False)
    try:
        qtbot.waitUntil(lambda: panel.count_paths[False] == [marked], timeout=5000)
        popup.apply()
        qtbot.waitUntil(lambda: panel.model.paths == [marked])
    except QtTimeoutError:
        record = window.plugins.records["example.images"]
        pytest.fail(
            repr(
                {
                    "state": record.state,
                    "error": record.error,
                    "active": panel.active,
                    "filters": panel.filters,
                    "paths": panel.model.paths,
                    "counts": panel.count_paths,
                    "notes": panel.notes,
                    "generation": panel.generation,
                    "job": panel.job,
                    "scope_job": panel.scope_job,
                    "popup": panel.popup,
                    "refresh_timer": panel.refresh_timer.isActive(),
                    "scope_timer": panel.scope_timer.isActive(),
                }
            )
        )
    panel.open_index(panel.model.index(0))
    assert window.current_path == marked
    panel.filters["local"] = True
    panel.schedule()
    qtbot.waitUntil(lambda: set(panel.model.paths) == {marked, unmarked})
    window.open_image(folder / "0.png")
    qtbot.waitUntil(
        lambda: len(panel.model.paths) == 8 and all(p.parent == folder for p in panel.model.paths)
    )
    (folder / "new.png").write_bytes((folder / "0.png").read_bytes())
    qtbot.waitUntil(lambda: panel.model.rowCount() == 9, timeout=5000)


def test_popup_corners_and_cleanup(host, qtbot):
    window, _, panel = enable(host, qtbot)
    panel.filter_menu()
    popup = panel.popup
    qtbot.wait(30)
    assert popup.grab().toImage().pixelColor(0, 0).alpha() == 0
    popup.hide()
    qtbot.wait(20)
    assert panel.popup is None
    window.plugins.disable("example.images")


@pytest.mark.parametrize("host", [6], indirect=True)
def test_two_columns_when_no_vertical_scrollbar_is_needed(host, qtbot):
    window, folder = host
    window.plugins.enable("example.images")
    panel = window.plugins.records["example.images"].instance
    window.panel_hovers.controllers["example.images"].resize_extent(310)
    window.panel_hovers.controllers["example.images"].pin()
    qtbot.waitUntil(lambda: panel.model.rowCount() == 6)
    qtbot.wait(100)
    first, second, third = [panel.grid.visualRect(panel.model.index(n)) for n in range(3)]
    assert second.top() == first.top() and third.top() > first.top()
    outer_size = panel.grid.size()
    for policy in (
        Qt.ScrollBarPolicy.ScrollBarAlwaysOn,
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        Qt.ScrollBarPolicy.ScrollBarAsNeeded,
    ):
        panel.grid.setVerticalScrollBarPolicy(policy)

        def two_columns():
            rectangles = [panel.grid.visualRect(panel.model.index(n)) for n in range(3)]
            return rectangles[0].top() == rectangles[1].top() < rectangles[2].top()

        qtbot.waitUntil(two_columns)
        assert panel.grid.size() == outer_size
