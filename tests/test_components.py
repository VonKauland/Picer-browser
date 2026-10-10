"""Component contracts, menu operations, skin rollback and dock/window transitions."""

import json
import textwrap
import zipfile

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDockWidget, QLabel

from picer.chrome import STYLE
from picer.host_style import scope_style
from picer.plugins.api import PluginError
from picer.window import MainWindow


@pytest.fixture
def window(qtbot, tmp_path):
    window = MainWindow(load_examples=False, plugin_root=tmp_path / "data")
    qtbot.addWidget(window)
    window.show()
    yield window
    window.plugins.shutdown()


def component(tmp_path, kind="function", plugin_id="test.component", code=None, **metadata):
    manifest = dict(id=plugin_id, name=plugin_id, version="1.0.0", api_version=1, type=kind)
    if kind != "skin":
        manifest.update(
            entrypoint="main:Plugin",
            permissions=["ui.commands"] if kind == "function" else ["ui.panels"],
        )
    manifest.update(metadata)
    if code is None:
        code = (
            """
            from PySide6.QtWidgets import QLabel
            class Plugin:
                def activate(self, context):
                    self.calls = 0
                    context.add_command("run", "测试功能", self.run, requires_image=False)
                def run(self):
                    self.calls += 1
        """
            if kind == "function"
            else """
            from PySide6.QtWidgets import QLabel
            class Plugin:
                def activate(self, context):
                    context.add_panel(QLabel("示例面板"), area="right")
        """
        )
    archive = tmp_path / f"{plugin_id}.zip"
    with zipfile.ZipFile(archive, "w") as file:
        file.writestr("manifest.json", json.dumps(manifest))
        if kind == "skin":
            file.writestr(
                "theme.json", json.dumps({"colors": {"background": "#112233", "text": "#abcdef"}})
            )
            # A skin must never import this file.
            file.writestr("main.py", "raise RuntimeError('skin code executed')")
        else:
            file.writestr("main.py", textwrap.dedent(code))
    return archive


@pytest.mark.parametrize(
    "metadata",
    [
        {"type": "unknown"},
        {"type": []},
        {"type": "panel", "permissions": []},
        {"type": "function", "permissions": ["ui.panels"]},
        {"type": "skin", "entrypoint": "main:Plugin"},
        {"type": "skin", "theme": "../theme.json"},
    ],
)
def test_invalid_component_contract_rejected_before_install(window, tmp_path, metadata):
    archive = component(tmp_path, **metadata)
    with pytest.raises(PluginError):
        window.plugins.install(archive)
    assert "test.component" not in window.plugins.records


def test_skin_storage_switch_restart_and_default(window, tmp_path, qtbot):
    manager = window.plugins
    assert not manager.paths.skins.exists()
    plugin_id = manager.install(component(tmp_path, "skin", "test.skin"))
    assert manager.records[plugin_id].directory == manager.paths.skins / plugin_id
    assert manager.records[plugin_id].state == "disabled"
    manager.enable(plugin_id)
    assert window.view.backgroundBrush().color() == QColor("#112233")
    assert manager.records[plugin_id].namespace == ""
    manager.install(component(tmp_path, "skin", "test.other"))
    manager.enable("test.other")
    assert manager.records[plugin_id].state == "disabled"
    assert manager.records["test.other"].state == "enabled"
    manager.shutdown()
    restarted = MainWindow(load_examples=False, plugin_root=manager.root)
    qtbot.addWidget(restarted)
    assert restarted.plugins.records["test.other"].state == "enabled"
    assert restarted.view.backgroundBrush().color() == QColor("#112233")
    restarted.components.default_skin()
    assert restarted.styleSheet() == scope_style(STYLE)
    restarted.plugins.uninstall(plugin_id)
    assert not (manager.paths.skins / plugin_id).exists()
    restarted.plugins.shutdown()


def test_invalid_skin_does_not_replace_active_skin(window, tmp_path):
    manager = window.plugins
    manager.install(component(tmp_path, "skin", "test.skin"))
    manager.enable("test.skin")
    manager.install(component(tmp_path, "skin", "test.bad"))
    path = manager.records["test.bad"].directory / "theme.json"
    path.write_text('{"colors":{"background":"red"}}')
    with pytest.raises(PluginError, match="颜色"):
        manager.enable("test.bad")
    assert manager.records["test.skin"].state == "enabled"
    assert window.view.backgroundBrush().color() == QColor("#112233")


def test_function_activation_failure_restores_skin_dependency(window, tmp_path):
    manager = window.plugins
    for plugin_id in ("test.old", "test.new"):
        manager.install(component(tmp_path, "skin", plugin_id))
    manager.enable("test.old")
    manager.install(
        component(
            tmp_path,
            code="""
        class Plugin:
            def activate(self, context):
                raise RuntimeError("fail after skin change")
    """,
            requires=["test.new"],
        )
    )
    with pytest.raises(PluginError, match="fail after"):
        manager.enable("test.component")
    assert manager.records["test.old"].state == "enabled"
    assert manager.records["test.new"].state == "disabled"


@pytest.mark.parametrize(
    "code",
    [
        """class Plugin:
        def activate(self, context):
            pass
    """,
        """class Plugin:
        def activate(self, context):
            context.add_command("one", "One", lambda: None)
            context.add_command("two", "Two", lambda: None)
    """,
    ],
)
def test_function_must_register_exactly_one_command(window, tmp_path, code):
    manager = window.plugins
    manager.install(component(tmp_path, code=code))
    with pytest.raises(PluginError, match="一个功能按钮"):
        manager.enable("test.component")
    assert not any(key.startswith("test.component:") for key in manager.commands)


def test_function_menu_switch_slots_cleanup_and_persistence(window, tmp_path, qtbot):
    manager = window.plugins
    manager.install(component(tmp_path))
    menu = window.components.menus["function"]
    next(action for action in menu.actions() if action.text() == "test.component").trigger()
    assert manager.records["test.component"].state == "enabled"
    window.components.assign(4, "test.component:run")
    buttons = window.title_bar.quick_slots
    assert len(buttons) == 5
    assert all(button.width() == 28 for button in buttons)
    qtbot.mouseClick(buttons[4], Qt.MouseButton.LeftButton)
    assert manager.records["test.component"].instance.calls == 1
    manager.disable("test.component")
    assert buttons[4].defaultAction() is None
    manager.enable("test.component")
    assert buttons[4].defaultAction() is manager.commands["test.component:run"]
    manager.shutdown()
    restarted = MainWindow(load_examples=False, plugin_root=manager.root)
    qtbot.addWidget(restarted)
    assert (
        restarted.title_bar.quick_slots[4].defaultAction()
        is restarted.plugins.commands["test.component:run"]
    )
    restarted.plugins.shutdown()


@pytest.mark.parametrize("area", ["left", "right"])
def test_panel_docking_hiding_fullscreen_and_cleanup(window, tmp_path, qtbot, area):
    manager = window.plugins
    manager.install(
        component(
            tmp_path,
            "panel",
            code=f"""
        from PySide6.QtWidgets import QLabel
        class Plugin:
            def activate(self, context):
                context.add_panel(QLabel("Panel"), area={area!r})
    """,
        )
    )
    manager.enable("test.component")
    dock = manager.panels["test.component"]
    assert not dock.isHidden()
    assert window.dockWidgetArea(dock) == getattr(
        Qt.DockWidgetArea, area.title() + "DockWidgetArea"
    )
    assert not dock.features() & QDockWidget.DockWidgetFeature.DockWidgetFloatable
    window.toggle_fullscreen()
    assert dock.isHidden()
    window.panel_hovers.controllers["test.component"].pin()
    assert not dock.isHidden()  # Users may explicitly display a panel in fullscreen.
    window.exit_fullscreen()
    assert not dock.isHidden()
    dock.close()
    assert dock.isHidden()
    window.toggle_fullscreen()
    window.exit_fullscreen()
    assert dock.isHidden()  # An explicit normal-mode hide is retained.
    manager.disable("test.component")
    assert not manager.panels
    qtbot.wait(1)
    assert not window.findChildren(QDockWidget)


def test_panel_enabled_in_fullscreen_hidden_then_visible(window, tmp_path, qtbot):
    manager = window.plugins
    manager.install(component(tmp_path, "panel"))
    window.toggle_fullscreen()
    manager.enable("test.component")
    assert manager.panels["test.component"].isHidden()
    window.exit_fullscreen()
    assert not manager.panels["test.component"].isHidden()
    manager.panels["test.component"].close()
    manager.shutdown()
    restarted = MainWindow(load_examples=False, plugin_root=manager.root)
    qtbot.addWidget(restarted)
    restarted.show()
    assert restarted.plugins.panels["test.component"].isHidden()
    restarted.plugins.shutdown()


def test_panel_partial_activation_failure_removes_dock(window, tmp_path, qtbot):
    manager = window.plugins
    manager.install(
        component(
            tmp_path,
            "panel",
            code="""
        from PySide6.QtWidgets import QLabel
        class Plugin:
            def activate(self, context):
                context.add_panel(QLabel("Panel"))
                context.add_panel(QLabel("Extra"))
    """,
        )
    )
    with pytest.raises(PluginError, match="一个面板"):
        manager.enable("test.component")
    assert not manager.panels
    qtbot.wait(1)
    assert not window.findChildren(QDockWidget)


def test_panel_rejects_top_dock_and_revokes_context(window, tmp_path):
    manager = window.plugins
    manager.install(component(tmp_path, "panel"))
    manager.enable("test.component")
    context = manager.records["test.component"].context
    manager.disable("test.component")
    with pytest.raises(PluginError, match="停用"):
        context.add_panel(QLabel("Late"))
    manager.install(
        component(
            tmp_path,
            "panel",
            "test.top",
            code="""
        from PySide6.QtWidgets import QLabel
        class Plugin:
            def activate(self, context):
                context.add_panel(QLabel("Panel"), area="top")
    """,
        )
    )
    with pytest.raises(PluginError, match="left、right 或 bottom"):
        manager.enable("test.top")


def test_legacy_multi_command_migration_and_type_update_guard(window, tmp_path):
    archive = component(
        tmp_path,
        code="""
        class Plugin:
            def activate(self, context):
                context.add_command("one", "One", lambda: None)
                context.add_command("two", "Two", lambda: None)
    """,
    )
    with zipfile.ZipFile(archive) as file:
        files = {name: file.read(name) for name in file.namelist()}
    manifest = json.loads(files["manifest.json"])
    del manifest["type"]
    files["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(archive, "w") as file:
        for name, data in files.items():
            file.writestr(name, data)
    manager = window.plugins
    manager.install(archive)
    manager.enable("test.component")
    assert manager.records["test.component"].manifest.legacy
    assert "test.component:one" in manager.commands
    assert "test.component:two" in manager.commands
    manager.disable("test.component")
    with pytest.raises(PluginError, match="不能更改组件类型"):
        manager.install(component(tmp_path, "skin"), replace_existing=True)
    assert manager.records["test.component"].manifest.type == "function"


def test_old_builtin_disabled_preference_preserved(tmp_path, qtbot):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "plugins.json").write_text(
        json.dumps({"enabled": {"picer.transforms": False}, "settings": {}})
    )
    window = MainWindow(load_examples=False, plugin_root=tmp_path)
    qtbot.addWidget(window)
    assert all(record.state == "disabled" for record in window.plugins.records.values())
    window.plugins.shutdown()


def test_minimum_window_title_bar_does_not_overlap(window, qtbot):
    window.resize(window.minimumWidth(), window.minimumHeight())
    qtbot.wait(1)
    bar = window.title_bar
    assert bar.left.geometry().right() < bar.right.geometry().left()
    assert bar.caption.width() > 0
