"""Verify actual plugin packages, failures, dependency lifecycle and worker delivery."""

import json
import sys
import textwrap
import zipfile
from pathlib import Path
from threading import Event

import pytest
from PySide6.QtCore import QThread
from PySide6.QtGui import QImage

from picer.plugins import PluginContext, PluginError
from picer.plugins.dialog import PluginDialog
from picer.window import MainWindow


@pytest.fixture
def window(qtbot, tmp_path):
    window = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(window)
    window.show()
    yield window
    window.plugins.shutdown()


def package(tmp_path, plugin_id="test.sample", code=None, **metadata):
    manifest = {
        "id": plugin_id,
        "name": plugin_id,
        "version": "1.0.0",
        "api_version": 1,
        "entrypoint": "main:Plugin",
        "permissions": ["ui.commands", "image.read"],
    }
    manifest.update(metadata)
    archive = tmp_path / f"{plugin_id}.zip"
    if code is None:
        code = """
            class Plugin:
                def activate(self, context):
                    self.context = context
                    self.calls = 0
                    context.add_command("test", "Test", self.run, requires_image=False)
                def run(self):
                    self.calls += 1
        """
    with zipfile.ZipFile(archive, "w") as file:
        file.writestr("manifest.json", json.dumps(manifest))
        file.writestr("main.py", textwrap.dedent(code))
    return archive


def open_image(window, tmp_path):
    image = QImage(80, 60, QImage.Format.Format_RGB32)
    image.fill(0x112233)
    path = tmp_path / "picture.png"
    assert image.save(str(path))
    assert window.open_image(path)
    return path


def test_install_does_not_import_and_enable_registers_command(window, tmp_path):
    marker = tmp_path / "executed"
    archive = package(
        tmp_path,
        code=f"""\nfrom pathlib import Path
Path({str(marker)!r}).touch()
class Plugin:
    def activate(self, context):
        context.add_command("test", "Test", lambda: None, requires_image=False)
""",
    )
    manager = window.plugins
    manager.install(archive)
    assert not marker.exists()
    assert manager.records["test.sample"].state == "disabled"
    manager.enable("test.sample")
    assert marker.exists()
    assert manager.commands["test.sample:test"].isEnabled()
    assert manager.records["test.sample"].state == "enabled"


def test_disable_revokes_context_and_cleans_modules_and_actions(window, tmp_path):
    manager = window.plugins
    manager.install(package(tmp_path))
    manager.enable("test.sample")
    record = manager.records["test.sample"]
    context, namespace = record.context, record.namespace
    manager.commands["test.sample:test"].trigger()
    assert record.instance.calls == 1
    manager.disable("test.sample")
    assert "test.sample:test" not in manager.commands
    assert not any(key.startswith(namespace) for key in sys.modules)
    with pytest.raises(PluginError, match="停用"):
        context.image()


def test_activation_failure_rolls_back_partial_commands(window, tmp_path):
    manager = window.plugins
    manager.install(
        package(
            tmp_path,
            code="""
        class Plugin:
            def activate(self, context):
                context.add_command("one", "One", lambda: None)
                raise RuntimeError("activation failed")
            def deactivate(self):
                raise RuntimeError("cleanup failed")
    """,
        )
    )
    with pytest.raises(PluginError, match="activation failed"):
        manager.enable("test.sample")
    assert manager.records["test.sample"].state == "error"
    assert "test.sample:one" not in manager.commands
    assert manager.records["picer.transforms"].state == "enabled"


def test_command_error_disables_plugin_and_preserves_viewer(window, tmp_path):
    manager = window.plugins
    manager.install(
        package(
            tmp_path,
            code="""
        class Plugin:
            def activate(self, context):
                context.add_command("fail", "Fail", self.fail, requires_image=False)
            def fail(self):
                raise ValueError("command failed")
    """,
        )
    )
    manager.enable("test.sample")
    manager.commands["test.sample:fail"].trigger()
    assert manager.records["test.sample"].state == "error"
    assert not manager.preferences["enabled"]["test.sample"]
    assert "command failed" in manager.records["test.sample"].error
    assert window.isVisible()
    assert "command failed" in manager.log_file.read_text()


def test_incompatible_api_never_imports(window, tmp_path):
    manager = window.plugins
    manager.install(package(tmp_path, api_version=99, code="raise RuntimeError('must not run')"))
    assert manager.records["test.sample"].state == "incompatible"
    with pytest.raises(PluginError, match="API"):
        manager.enable("test.sample")


def test_declared_api_permissions_are_checked(window, tmp_path):
    manager = window.plugins
    manager.install(package(tmp_path, permissions=["ui.commands"]))
    manager.enable("test.sample")
    with pytest.raises(PluginError, match="image.read"):
        manager.records["test.sample"].context.image()


def test_dependency_enable_and_disable_guard(window, tmp_path):
    manager = window.plugins
    manager.install(package(tmp_path, "test.base"))
    manager.install(package(tmp_path, "test.child", requires=["test.base"]))
    manager.enable("test.child")
    assert manager.records["test.base"].state == "enabled"
    with pytest.raises(PluginError, match="依赖"):
        manager.disable("test.base")
    manager.disable("test.child")
    manager.disable("test.base")


def test_dependency_cycle_and_missing_dependency(window, tmp_path):
    manager = window.plugins
    manager.install(package(tmp_path, "test.a", requires=["test.b"]))
    with pytest.raises(PluginError, match="缺少依赖"):
        manager.enable("test.a")
    manager.install(package(tmp_path, "test.b", requires=["test.a"]))
    with pytest.raises(PluginError, match="循环"):
        manager.enable("test.a")
    assert manager.records["test.a"].state == "disabled"
    assert manager.records["test.b"].state == "disabled"


def test_failed_child_rolls_back_new_dependencies(window, tmp_path):
    manager = window.plugins
    manager.install(package(tmp_path, "test.base"))
    manager.install(
        package(
            tmp_path,
            "test.child",
            requires=["test.base"],
            code="""
        class Plugin:
            def activate(self, context):
                raise ValueError("child failure")
    """,
        )
    )
    with pytest.raises(PluginError):
        manager.enable("test.child")
    assert manager.records["test.base"].state == "disabled"
    assert "test.base:test" not in manager.commands


def test_shortcut_conflict_and_duplicate_commands(window, tmp_path):
    manager = window.plugins
    for plugin_id, lines in (
        ("test.conflict", 'context.add_command("a", "A", lambda: None, shortcut="Ctrl+O")'),
        (
            "test.duplicate",
            'context.add_command("a", "A", lambda: None)\n'
            '        context.add_command("a", "Again", lambda: None)',
        ),
    ):
        code = f"class Plugin:\n    def activate(self, context):\n        {lines}\n"
        manager.install(package(tmp_path, plugin_id, code=code))
        with pytest.raises(PluginError):
            manager.enable(plugin_id)
        assert f"{plugin_id}:a" not in manager.commands


@pytest.mark.parametrize(
    "filename", ["../escape.py", "/absolute.py", "C:/drive.py", "dir\\evil.py"]
)
def test_zip_traversal_rejected(window, tmp_path, filename):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as file:
        file.writestr(filename.replace("\\", "/"), "bad")
    # ZipInfo normalizes backslashes on Windows. Patch both same-length filename headers
    # to model an actual malformed archive consistently on all operating systems.
    if "\\" in filename:
        archive.write_bytes(
            archive.read_bytes().replace(filename.replace("\\", "/").encode(), filename.encode())
        )
    with pytest.raises(PluginError, match="非法路径"):
        window.plugins.install(archive)
    assert not (tmp_path / "escape.py").exists()


def test_duplicate_id_cannot_replace_builtin(window, tmp_path):
    with pytest.raises(PluginError, match="已存在"):
        window.plugins.install(package(tmp_path, "picer.transforms"))
    assert window.plugins.records["picer.transforms"].directory is None


def test_settings_and_enabled_state_survive_restart(window, tmp_path, qtbot):
    manager = window.plugins
    manager.install(package(tmp_path, permissions=["ui.commands", "settings"]))
    manager.enable("test.sample")
    context = manager.records["test.sample"].context
    context.set_setting("options", {"values": [1, 2]})
    received = context.get_setting("options")
    received["values"].append(3)
    assert context.get_setting("options") == {"values": [1, 2]}
    manager.shutdown()
    restarted = MainWindow(plugin_root=manager.root)
    qtbot.addWidget(restarted)
    assert restarted.plugins.records["test.sample"].state == "enabled"
    assert restarted.plugins.records["test.sample"].context.get_setting("options") == {
        "values": [1, 2]
    }
    restarted.close()


def test_event_failure_cleans_subscriptions(window, tmp_path):
    manager = window.plugins
    manager.install(
        package(
            tmp_path,
            permissions=["events.subscribe"],
            code="""
        class Plugin:
            def activate(self, context):
                context.subscribe("image.opened", self.fail)
            def fail(self, event):
                raise ValueError("event failure")
    """,
        )
    )
    manager.enable("test.sample")
    open_image(window, tmp_path)
    assert manager.records["test.sample"].state == "error"
    assert manager.subscribers["image.opened"] == []
    assert window.current_path is not None


def test_example_package_and_background_image_transform(window, tmp_path, qtbot):
    root = Path(__file__).resolve().parents[1] / "examples" / "negative_plugin"
    archive = tmp_path / "negative.zip"
    with zipfile.ZipFile(archive, "w") as file:
        for name in ("manifest.json", "main.py"):
            file.write(root / name, name)
    manager = window.plugins
    manager.install(archive)
    manager.enable("example.negative")
    path = open_image(window, tmp_path)
    manager.commands["example.negative:negative"].trigger()
    qtbot.waitUntil(lambda: not manager.jobs)
    pixel = window.view.image_item.pixmap().toImage().pixelColor(0, 0)
    assert (pixel.red(), pixel.green(), pixel.blue()) == (238, 221, 204)
    assert manager.records["example.negative"].context.get_setting("opened_count") == 1
    assert path.exists()


def test_tasks_return_on_gui_thread_and_discard_stale_image(window, tmp_path, qtbot):
    manager = window.plugins
    manager.install(package(tmp_path, permissions=["ui.commands", "tasks"]))
    manager.enable("test.sample")
    context = manager.records["test.sample"].context
    delivered = []
    token = context.run_task(
        lambda token: 7, lambda result: delivered.append((result, QThread.currentThread()))
    )
    qtbot.waitUntil(lambda: len(delivered) == 1)
    assert delivered[0] == (7, window.thread())
    assert not token.cancelled
    started, release = Event(), Event()

    def work(token):
        started.set()
        release.wait(5)
        return 8

    context.run_task(work, delivered.append)
    assert started.wait(2)
    try:
        open_image(window, tmp_path)
    finally:
        release.set()
    qtbot.waitUntil(lambda: not manager.jobs)
    assert len(delivered) == 1


def test_disable_cancels_task_and_drops_result(window, tmp_path, qtbot):
    manager = window.plugins
    manager.install(package(tmp_path, permissions=["ui.commands", "tasks"]))
    manager.enable("test.sample")
    started, release = Event(), Event()
    results = []

    def work(token):
        started.set()
        release.wait(5)
        return 9

    token = manager.records["test.sample"].context.run_task(work, results.append)
    assert started.wait(2)
    try:
        manager.disable("test.sample")
    finally:
        release.set()
    qtbot.waitUntil(lambda: not manager.jobs)
    assert token.cancelled
    assert results == []


def test_reload_relative_import_and_uninstall(window, tmp_path):
    manager = window.plugins
    archive = package(
        tmp_path,
        code="""
        from .helper import VALUE
        class Plugin:
            def activate(self, context):
                self.value = VALUE
    """,
    )
    with zipfile.ZipFile(archive, "a") as file:
        file.writestr("helper.py", "VALUE = 333")
    manager.install(archive)
    manager.enable("test.sample")
    record = manager.records["test.sample"]
    assert record.instance.value == 333
    (record.directory / "helper.py").write_text("VALUE = 444", encoding="utf-8")
    manager.reload("test.sample")
    assert record.instance.value == 444
    manager.disable("test.sample")
    directory = record.directory
    manager.uninstall("test.sample")
    assert "test.sample" not in manager.records
    assert not directory.exists()


def test_corrupt_preferences_do_not_break_startup(tmp_path, qtbot):
    (tmp_path / "plugins.json").write_text("[]")
    window = MainWindow(plugin_root=tmp_path)
    qtbot.addWidget(window)
    assert window.plugins.records["picer.transforms"].state == "enabled"
    assert window.plugins.diagnostics
    window.close()


def test_management_dialog_enable_disable(window, qtbot):
    dialog = PluginDialog(window.plugins, window)
    qtbot.addWidget(dialog)
    assert dialog.selected_id() == "picer.transforms"
    dialog.toggle()
    assert window.plugins.records["picer.transforms"].state == "disabled"
    assert window.rotate_action is None
    dialog.toggle()
    assert window.rotate_action is not None
    assert "顺时针旋转" in dialog.details.toPlainText()
    assert "类型：功能" in dialog.details.toPlainText()


def test_background_context_access_is_rejected(window, tmp_path, qtbot):
    manager = window.plugins
    manager.install(package(tmp_path, permissions=["ui.commands", "tasks", "image.read"]))
    manager.enable("test.sample")
    context: PluginContext = manager.records["test.sample"].context
    context.run_task(lambda token: context.image(), lambda result: None)
    qtbot.waitUntil(lambda: not manager.jobs)
    assert manager.records["test.sample"].state == "error"
    assert "GUI 线程" in manager.records["test.sample"].error


def test_update_preserves_settings_and_requires_disabled_plugin(window, tmp_path):
    manager = window.plugins
    manager.install(package(tmp_path, permissions=["ui.commands", "settings"]))
    manager.enable("test.sample")
    manager.records["test.sample"].context.set_setting("value", 42)
    newer = package(tmp_path, version="2.0.0", permissions=["ui.commands", "settings"])
    with pytest.raises(PluginError, match="停用"):
        manager.install(newer, replace_existing=True)
    manager.disable("test.sample")
    manager.install(newer, replace_existing=True)
    assert manager.records["test.sample"].manifest.version == "2.0.0"
    assert manager.records["test.sample"].state == "disabled"
    manager.enable("test.sample")
    assert manager.records["test.sample"].context.get_setting("value") == 42


def test_dependency_failure_disables_dependents(window, tmp_path):
    manager = window.plugins
    manager.install(
        package(
            tmp_path,
            "test.base",
            code="""
        class Plugin:
            def activate(self, context):
                context.add_command("fail", "Fail", self.fail, requires_image=False)
            def fail(self):
                raise ValueError("dependency failure")
    """,
        )
    )
    manager.install(package(tmp_path, "test.child", requires=["test.base"]))
    manager.enable("test.child")
    manager.commands["test.base:fail"].trigger()
    assert manager.records["test.base"].state == "error"
    assert manager.records["test.child"].state == "error"
    assert "test.child:test" not in manager.commands


def test_safe_mode_skips_external_plugins_without_disabling_preferences(window, tmp_path, qtbot):
    manager = window.plugins
    manager.install(package(tmp_path))
    manager.enable("test.sample")
    manager.shutdown()
    safe = MainWindow(plugin_root=manager.root, load_external=False)
    qtbot.addWidget(safe)
    assert "test.sample" not in safe.plugins.records
    assert safe.plugins.preferences["enabled"]["test.sample"] is True
    safe.close()


@pytest.mark.parametrize(
    "metadata",
    [
        {"permissions": ["unknown"]},
        {"requires": ["bad-id"]},
        {"entrypoint": "../outside:Plugin"},
        {"api_version": True},
    ],
)
def test_invalid_manifest_is_rejected_before_install(window, tmp_path, metadata):
    with pytest.raises(PluginError):
        window.plugins.install(package(tmp_path, **metadata))
    assert "test.sample" not in window.plugins.records


def test_plugin_cache_and_thumbnail_sdk(window, tmp_path):
    manager = window.plugins
    manager.install(package(tmp_path, permissions=["ui.commands", "image.read", "cache"]))
    manager.enable("test.sample")
    context = manager.records["test.sample"].context
    open_image(window, tmp_path)
    assert context.thumbnail().width() == 80
    directory = context.cache_directory()
    assert directory == window.paths_layout.cache / "plugins" / "test.sample"
    assert directory.is_dir()
    assert manager.state_file == window.paths_layout.config / "plugins.json"
    assert manager.log_file == window.paths_layout.logs / "plugins.log"
