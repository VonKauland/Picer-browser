"""Disk accounting, removal consent and third-party command ownership."""

import json
import zipfile

import pytest
from PySide6.QtCore import Qt

from picer.plugin_storage import directory_size
from picer.plugins.tasks import TaskToken
from picer.settings import ApplicationSettings
from picer.window import MainWindow


def test_directory_size_ignores_links(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "a").write_bytes(b"abc")
    (tmp_path / "nested" / "b").write_bytes(b"12345")
    try:
        (tmp_path / "loop").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pass  # Windows developer mode may be unavailable.
    assert directory_size(tmp_path, TaskToken()) == 8


@pytest.fixture
def setup(qtbot, tmp_path):
    host = MainWindow(load_examples=False, plugin_root=tmp_path / "state")
    qtbot.addWidget(host)
    archive = tmp_path / "plugin.zip"
    manifest = {
        "id": "test.thirdparty",
        "name": "第三方功能",
        "version": "1.0.0",
        "api_version": 1,
        "type": "function",
        "entrypoint": "plugin:Plugin",
        "permissions": ["ui.commands"],
    }
    source = (
        "class Plugin:\n    def activate(self, ctx):\n"
        '        ctx.add_command("run", "第三方操作", lambda: None)\n'
    )
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("manifest.json", json.dumps(manifest))
        package.writestr("plugin.py", source)
    key = host.plugins.install(archive)
    host.plugins.enable(key)
    dialog = ApplicationSettings(host)
    qtbot.addWidget(dialog)
    yield host, dialog, key
    host.plugins.shutdown()


def test_storage_scan_and_external_marker(setup, qtbot):
    host, dialog, key = setup
    panel = dialog.plugin_storage
    qtbot.waitUntil(lambda: key in panel.sizes)
    assert panel.sizes[key] == directory_size(host.plugins.records[key].directory, TaskToken())
    assert panel.rows["picer.transforms"].text() == "随应用提供"
    editor = dialog.binding_editor
    items = [editor.functions.item(i) for i in range(editor.functions.count())]
    marked = [
        i.data(Qt.ItemDataRole.UserRole) for i in items if i.data(Qt.ItemDataRole.UserRole + 1)
    ]
    assert marked == [key + ":run"]


def test_uninstall_cancel_then_accept_keeps_other_staged_settings(setup, monkeypatch, qtbot):
    host, dialog, key = setup
    directory = host.plugins.records[key].directory
    monkeypatch.setattr("picer.plugin_storage.confirm", lambda *args: False)
    dialog.plugin_storage.uninstall(key)
    assert directory.exists() and host.plugins.records[key].state == "enabled"
    value = dialog.editors["cache_mb"].value() + 1
    dialog.editors["cache_mb"].setValue(value)
    monkeypatch.setattr("picer.plugin_storage.confirm", lambda *args: True)
    dialog.plugin_storage.uninstall(key)
    assert key not in host.plugins.records and not directory.exists()
    assert key + ":run" not in dialog.binding_editor.primary_editors
    dialog.apply()
    assert host.plugins.preferences["ui"]["application"]["cache_mb"] == value
    qtbot.waitUntil(lambda: not dialog.plugin_storage.jobs)


def test_dependency_blocks_uninstall_before_disabling(setup, monkeypatch):
    host, dialog, key = setup
    directory = host.plugins.records[key].directory
    notices = []
    monkeypatch.setattr("picer.plugin_storage.confirm", lambda *args: True)
    monkeypatch.setattr(host.plugins, "_dependents", lambda plugin_id: ["dependent"])
    monkeypatch.setattr(
        "picer.plugin_storage.MessageBox.warning", lambda *args: notices.append(args)
    )
    dialog.plugin_storage.uninstall(key)
    assert directory.exists() and host.plugins.records[key].state == "enabled"
    assert notices and "依赖" in notices[0][-1]
    monkeypatch.undo()
