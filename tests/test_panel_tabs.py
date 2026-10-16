"""Stacked panel switching keeps geometry, hidden indicators and grip ownership."""

import pytest
from PySide6.QtWidgets import QTabBar

from picer.panels import DOCK_AREAS
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
        assert tab.width() == 16
        assert tab.geometry().center().x() == surface.grip.geometry().center().x()
        assert not tab.geometry().intersects(surface.grip.geometry())
    files.dock.widget().tabs["example.info"].click()
    qtbot.wait(20)
    assert info.dock.isVisible()
    assert not files.dock.isHidden()
    assert not info.strip.isVisible()
    assert all(bar.height() == 0 for bar in host.findChildren(QTabBar) if bar.parent() is host)


def test_hidden_indicators_and_tab_reveal_keep_preferences(host, qtbot):
    files, info, _ = stack(host, qtbot)
    files.dock.close()
    info.dock.close()
    qtbot.wait(20)
    assert files.strip.isVisible() and info.strip.isVisible()
    assert not files.strip.geometry().intersects(info.strip.geometry())
    files.reveal()
    qtbot.wait(50)
    tab = files.surface.tabs["example.info"]
    # Check an actual intermediate frame without depending on a loaded CI timer tick.
    tab.animation.setCurrentTime(tab.animation.duration() // 2)
    assert 0 < tab.scale < 1
    tab.click()
    qtbot.wait(30)
    assert files.popup is None and info.popup is not None
    assert files.dock.isHidden() and info.dock.isHidden()
    assert host.plugins.preferences["ui"]["panels"]["example.info"] is False
    info.collapse(immediate=True)
    assert info.surface is None


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
