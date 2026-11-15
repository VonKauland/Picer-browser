"""Real item-view input follows Windows Ctrl/Shift selection and export semantics."""

import pytest
from PIL import Image
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QDrag, QMouseEvent
from PySide6.QtWidgets import QApplication

from picer.window import MainWindow

CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier


@pytest.fixture(params=["list", "tiles", "manager"])
def view(qtbot, tmp_path, request):
    host = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(host)
    host.show()
    host.activateWindow()
    folder = tmp_path / "photos"
    folder.mkdir()
    paths = [folder / f"{n}.png" for n in range(6)]
    for path in paths:
        Image.new("RGB", (40, 30), "blue").save(path)
    host.open_image(paths[0])
    if request.param == "manager":
        host.plugins.enable("example.images")
        plugin = host.plugins.records["example.images"].instance
        qtbot.waitUntil(lambda: plugin.model.rowCount() == 6)
        widget, drag = plugin.grid, plugin.file_drag

        def index(n):
            return plugin.model.index(plugin.model.positions[str(paths[n])])

        def selected():
            return {plugin.model.paths[i.row()] for i in widget.selectionModel().selectedRows()}

        host.panel_hovers.controllers["example.images"].pin()
    else:
        plugin = host.plugins.records["example.files"].instance
        plugin.context.set_setting("view", request.param)
        plugin.apply_view()
        plugin.open_folder(folder)
        qtbot.waitUntil(lambda: plugin.model.rowCount(plugin.tree.rootIndex()) == 6)
        widget = plugin.tree if request.param == "list" else plugin.tiles
        drag = plugin.file_drags[0 if request.param == "list" else 1]

        def index(n):
            return plugin.model.index(str(paths[n]))

        def selected():
            return {
                type(folder)(plugin.model.filePath(i))
                for i in widget.selectionModel().selectedRows()
            }

        host.panel_hovers.controllers["example.files"].pin()
    plugin.dock.raise_()
    qtbot.wait(100)
    yield host, plugin, widget, drag, index, selected, paths
    host.close()


def click(qtbot, widget, index, modifiers=Qt.KeyboardModifier.NoModifier):
    widget.scrollTo(index)
    qtbot.wait(10)
    qtbot.mouseClick(
        widget.viewport(),
        Qt.MouseButton.LeftButton,
        modifiers,
        widget.visualRect(index).center(),
    )


def test_ctrl_shift_selection_does_not_open_and_clear_ctrl_a(view, qtbot):
    host, plugin, widget, drag, index, selected, paths = view
    click(qtbot, widget, index(0))
    assert selected() == {paths[0]}
    click(qtbot, widget, index(2), CTRL)
    assert selected() == {paths[0], paths[2]}
    assert host.current_path == paths[0]
    click(qtbot, widget, index(2), CTRL)
    assert selected() == {paths[0]}
    click(qtbot, widget, index(0))
    click(qtbot, widget, index(3), SHIFT)
    assert selected() == set(paths[:4])
    click(qtbot, widget, index(2), SHIFT)
    assert selected() == set(paths[:3])
    click(qtbot, widget, index(5), CTRL | SHIFT)
    assert selected() == set(paths)
    assert host.current_path == paths[0]
    # Sorting/repainting the manager must not discard an in-progress range.
    if hasattr(plugin, "schedule"):
        plugin.schedule()
        qtbot.waitUntil(lambda: plugin.job is None and not plugin.refresh_timer.isActive())
        assert selected() == set(paths)
    click(qtbot, widget, index(1))
    qtbot.waitUntil(lambda: host.current_path == paths[1])
    assert selected() == {paths[1]}
    widget.setFocus()
    qtbot.keyClick(widget, Qt.Key.Key_A, modifier=CTRL)
    assert selected() == set(paths)
    if hasattr(plugin, "schedule"):
        other = paths[0].parent.parent / "another" / "new.png"
        other.parent.mkdir()
        Image.new("RGB", (40, 30), "red").save(other)
        host.open_image(other)
        qtbot.waitUntil(lambda: plugin.model.paths == [other])
        assert selected() == {other}


def test_drag_selected_images_exports_all_without_changing_selection(view, qtbot, monkeypatch):
    host, plugin, widget, drag, index, selected, paths = view
    click(qtbot, widget, index(0))
    click(qtbot, widget, index(2), CTRL)
    calls = []

    def export(instance, actions, default):
        calls.append({type(paths[0])(url.toLocalFile()) for url in instance.mimeData().urls()})
        return Qt.DropAction.CopyAction

    monkeypatch.setattr(QDrag, "exec", export)
    widget.scrollTo(index(0))
    point = widget.visualRect(index(0)).center()
    qtbot.mousePress(widget.viewport(), Qt.MouseButton.LeftButton, pos=point)
    target = QPointF(point.x() + QApplication.startDragDistance() + 5, point.y())
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        target,
        QPointF(widget.viewport().mapToGlobal(target.toPoint())),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget.viewport(), event)
    qtbot.mouseRelease(widget.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert calls == [{paths[0], paths[2]}]
    assert selected() == {paths[0], paths[2]}
    assert all(path.is_file() for path in paths)
