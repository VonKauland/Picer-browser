"""Stacked panel switching keeps geometry, hidden indicators and grip ownership."""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QTabBar

from picer.panels import DOCK_AREAS
from picer.settings_backup import snapshot, validate_backup
from picer.window import MainWindow


@pytest.fixture
def host(qtbot, tmp_path):
    window = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(window)
    window.resize(1100, 800)
    window.show()
    qtbot.wait(50)
    yield window
    window.plugins.shutdown()


def stack(host, qtbot):
    controllers = host.panel_hovers.controllers
    files, info = controllers["example.files"], controllers["example.info"]
    width = files.dock.width()
    info.move_to(DOCK_AREAS["left"])
    qtbot.wait(50)
    return files, info, width


def test_fixed_stack_switch_preserves_width_and_grip(host, qtbot):
    files, info, width = stack(host, qtbot)
    assert info.dock in host.tabifiedDockWidgets(files.dock)
    assert abs(files.dock.width() - width) <= 2
    for controller in (files, info):
        surface = controller.dock.widget()
        assert len(surface.tabs) == 2
        tab = surface.tabs[controller.plugin_id]
        assert next(iter(surface.tabs.values())).y() == 3
        assert tab.width() == 36
        assert tab.geometry().center().x() == surface.grip.geometry().center().x()
        assert not tab.geometry().intersects(surface.grip.geometry())
    files.dock.widget().tabs["example.info"].click()
    qtbot.wait(20)
    assert info.dock.isVisible()
    assert not files.dock.isHidden()
    assert not info.strip.isVisible()
    assert all(bar.height() == 0 for bar in host.findChildren(QTabBar) if bar.parent() is host)


def test_hidden_indicators_without_tabs_and_shared_pin_state(host, qtbot):
    files, info, _ = stack(host, qtbot)
    files.dock.close()
    info.dock.close()
    qtbot.wait(20)
    assert files.strip.isVisible() and info.strip.isVisible()
    assert not files.strip.geometry().intersects(info.strip.geometry())
    files.reveal()
    qtbot.wait(50)
    assert not files.surface.tabs
    assert not files.surface.rail.isVisible()
    files.pin()
    qtbot.wait(30)
    assert not files.dock.isHidden() and not info.dock.isHidden()
    assert files.dock.geometry().left() >= 0
    tab = files.dock.widget().tabs["example.info"]
    # Check an actual intermediate frame without depending on a loaded CI timer tick.
    tab.animation.setCurrentTime(tab.animation.duration() // 2)
    assert 0 < tab.scale < 1
    tab.click()
    qtbot.wait(30)
    assert files.popup is None and info.popup is None
    assert not files.dock.isHidden() and not info.dock.isHidden()
    info.dock.close()
    assert files.dock.isHidden() and info.dock.isHidden()
    assert host.plugins.preferences["ui"]["panels"]["example.files"] is False
    assert host.plugins.preferences["ui"]["panels"]["example.info"] is False


def test_removal_and_move_clear_tabs(host, qtbot):
    files, info, _ = stack(host, qtbot)
    info.move_to(DOCK_AREAS["right"])
    qtbot.wait(30)
    assert not files.dock.widget().tabs
    assert not info.dock.widget().tabs
    info.move_to(DOCK_AREAS["left"])
    qtbot.wait(20)
    host.plugins.disable("example.info")
    qtbot.wait(20)
    assert not files.dock.widget().tabs


@pytest.mark.parametrize("side", ["left", "right"])
def test_outward_tabs_preserve_content_and_fade_only_background(host, qtbot, side):
    controllers = host.panel_hovers.controllers
    files, info = controllers["example.files"], controllers["example.info"]
    files.move_to(DOCK_AREAS[side])
    qtbot.wait(30)
    surface = files.dock.widget()
    margins = surface.layout().getContentsMargins()
    width = files.dock.width()
    info.move_to(DOCK_AREAS[side])
    host.panel_hovers.activate_tab(files)
    qtbot.wait(30)
    assert surface.layout().getContentsMargins() == margins
    assert abs(files.dock.width() - width) <= 2
    tab = surface.tabs["example.files"]
    tab.animation.setCurrentTime(tab.animation.duration())
    origin = tab.mapTo(host, QPoint())
    bounds = surface.rect().translated(surface.mapTo(host, QPoint()))
    assert (
        origin.x() + tab.width() > bounds.right() if side == "left" else origin.x() < bounds.left()
    )
    assert surface.rail.mask().contains(tab.geometry().center())
    # Empty gaps in the floating rail must pass through to the canvas.
    assert not surface.rail.mask().contains(QPoint(18, tab.geometry().bottom() + 3))
    image = QImage(tab.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("transparent"))
    tab.render(image)
    outer, inner = (34, 1) if side == "left" else (1, 34)
    assert image.pixelColor(outer, 25).alpha() > image.pixelColor(inner, 25).alpha() + 100
    # Text stays opaque inside the fade, with at least 8px horizontal padding.
    assert any(image.pixelColor(x, 18).alpha() > 240 for x in range(8, 28))


def drag(qtbot, tab, destination):
    qtbot.mousePress(tab, Qt.MouseButton.LeftButton, pos=tab.rect().center())
    point = tab.mapFromGlobal(destination)
    qtbot.mouseMove(tab, point)
    qtbot.mouseRelease(tab, Qt.MouseButton.LeftButton, pos=point)
    qtbot.wait(30)


def test_drag_reorders_changes_side_and_persists(host, qtbot, tmp_path):
    files, info, _ = stack(host, qtbot)
    host.panel_hovers.activate_tab(info)
    surface = info.dock.widget()
    drag(
        qtbot,
        surface.tabs["example.info"],
        surface.tabs["example.files"].mapToGlobal(QPoint(18, 2)),
    )
    assert list(surface.tabs) == ["example.info", "example.files"]
    assert info.order < files.order
    backup = snapshot(host)
    assert backup["panels"]["example.info"]["order"] < backup["panels"]["example.files"]["order"]
    dialog = host.show_settings()
    dialog.load_backup(backup)
    dialog.apply()
    assert info.order < files.order
    dialog.close()
    # An unsupported middle-canvas drop must leave order and docking unchanged.
    drag(qtbot, surface.tabs["example.files"], host.mapToGlobal(host.rect().center()))
    assert files.area == DOCK_AREAS["left"]
    assert info.order < files.order
    host.close()
    restored = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(restored)
    restored.show()
    qtbot.wait(50)
    controllers = restored.panel_hovers.controllers
    files, info = controllers["example.files"], controllers["example.info"]
    restored.panel_hovers.activate_tab(info)
    assert list(info.dock.widget().tabs) == ["example.info", "example.files"]
    drag(
        qtbot,
        info.dock.widget().tabs["example.files"],
        restored.mapToGlobal(QPoint(restored.width() - 4, 130)),
    )
    assert files.area == DOCK_AREAS["right"]
    assert info.area == DOCK_AREAS["left"]
    assert not files.dock.widget().tabs and not info.dock.widget().tabs


def test_join_hidden_side_adopts_group_mode(host, qtbot):
    controllers = host.panel_hovers.controllers
    files, info = controllers["example.files"], controllers["example.info"]
    progress = controllers["example.progress"]
    progress_hidden = progress.dock.isHidden()
    files.dock.close()
    info.move_to(DOCK_AREAS["left"])
    assert files.dock.isHidden() and info.dock.isHidden()
    assert files.strip.isVisible() and info.strip.isVisible()
    info.reveal()
    qtbot.wait(30)
    assert not info.surface.tabs and not info.surface.rail.isVisible()
    info.pin()
    assert not files.dock.isHidden() and not info.dock.isHidden()
    assert progress.dock.isHidden() == progress_hidden


@pytest.mark.parametrize("order", [-1, True, 10001, "first"])
def test_invalid_backup_tab_order_is_rejected(host, order):
    data = snapshot(host)
    data["panels"]["example.files"]["order"] = order
    with pytest.raises(ValueError, match="顺序"):
        validate_backup(data, host)


def test_move_during_fullscreen_restores_uniform_destination_mode(host, qtbot):
    controllers = host.panel_hovers.controllers
    files, info = controllers["example.files"], controllers["example.info"]
    info.dock.close()
    host.toggle_fullscreen()
    qtbot.wait(30)
    files.move_to(DOCK_AREAS["right"])
    host.toggle_fullscreen()
    qtbot.wait(30)
    assert files.dock.isHidden() and info.dock.isHidden()
    assert host.plugins.preferences["ui"]["panels"]["example.files"] is False
