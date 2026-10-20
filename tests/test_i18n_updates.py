"""Locale persistence, stable identifiers, safe release parsing and popup routing."""

import ast
import json
import string
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton

from picer.i18n import LANGUAGES, language, set_language, tr
from picer.settings import ApplicationSettings
from picer.updates import Release, UpdatePopup
from picer.window import MainWindow

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def reset_locale():
    set_language("zh_CN")
    yield
    set_language("zh_CN")


def fields(text):
    return sorted(
        (name, spec, conv)
        for _, name, spec, conv in string.Formatter().parse(text)
        if name is not None
    )


def test_catalogs_have_matching_coverage_and_format_fields():
    catalogs = [
        json.loads((ROOT / "src/picer/locales" / f"{code}.json").read_text())
        for code in LANGUAGES
        if code != "zh_CN"
    ]
    expected = set(catalogs[0])
    assert len(expected) > 900
    for catalog in catalogs:
        assert set(catalog) == expected
        for key, text in catalog.items():
            assert isinstance(text, str) and text
            assert fields(key) == fields(text), (key, text)
    for path in [*(ROOT / "src/picer").rglob("*.py"), *(ROOT / "examples").rglob("*.py")]:
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "tr"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                assert node.args[0].value in expected, (path, node.lineno, node.args[0].value)


@pytest.mark.parametrize("code", LANGUAGES)
def test_restart_localizes_menus_and_bundled_panels_without_changing_ids(qtbot, tmp_path, code):
    config = tmp_path / "config"
    config.mkdir()
    (config / "plugins.json").write_text(
        json.dumps({"ui": {"application": {"language": code}}, "enabled": {}, "settings": {}})
    )
    host = MainWindow(plugin_root=tmp_path)
    qtbot.addWidget(host)
    try:
        assert language() == code
        assert host.main_menus[0].title() == tr("文件")
        assert host.open_action.text() == tr("打开图片…")
        assert host.shortcut_actions["打开图片…"] is host.open_action
        assert "上一张" in host.shortcut_actions and "打开父级文件夹" in host.shortcut_actions
        assert host.plugins.commands["picer.transforms:rotate"].text() == tr("顺时针旋转")
        assert host.plugins.panels["example.info"].windowTitle() == tr("图片信息")
        browser = host.plugins.records["example.files"].instance
        assert browser.search.placeholderText() == tr("搜索当前文件夹")
        host.plugins.enable("example.editor")
        editor = host.plugins.records["example.editor"].instance
        assert any(
            tr("裁剪图像") in button.text() for button in editor.panel.findChildren(QPushButton)
        )
        settings = ApplicationSettings(host)
        qtbot.addWidget(settings)
        assert settings.editors["language"].currentData() == code
        assert settings.editors["language"].count() == 7
        assert settings.editors["check_updates"].isChecked()
        assert (
            not host.updates.started
        )  # No network requests from constructing or testing a window.
        settings.close()
    finally:
        host.close()


def test_language_change_is_saved_but_staged_until_restart(qtbot, tmp_path):
    host = MainWindow(plugin_root=tmp_path, load_examples=False)
    qtbot.addWidget(host)
    settings = ApplicationSettings(host)
    qtbot.addWidget(settings)
    try:
        settings.editors["language"].setCurrentIndex(settings.editors["language"].findData("ja"))
        settings.reject()
        assert host.app_preferences["language"] == "zh_CN"
        settings = ApplicationSettings(host)
        qtbot.addWidget(settings)
        settings.editors["language"].setCurrentIndex(settings.editors["language"].findData("en"))
        settings.apply()
        assert host.app_preferences["language"] == "en"
        assert language() == "zh_CN"
        assert host.open_action.text() == "打开图片…"
        preferences = json.loads((tmp_path / "config/plugins.json").read_text())
        assert preferences["ui"]["application"]["language"] == "en"
    finally:
        settings.close()
        host.close()


def release_data():
    page = "https://github.com/VonKauland/Picer-browser/releases/"
    return {
        "tag_name": "v0.24.0",
        "draft": False,
        "prerelease": False,
        "html_url": page + "tag/v0.24.0",
        "body": "## Changes\n\n- A new feature",
        "assets": [
            {
                "name": f"Picer-0.24.0-windows-x64-{suffix}",
                "browser_download_url": page
                + f"download/v0.24.0/Picer-0.24.0-windows-x64-{suffix}",
            }
            for suffix in ("portable.zip", "setup.exe")
        ],
    }


def test_release_parsing_uses_versions_not_strings_and_requires_trusted_assets():
    data = release_data()
    assert Release.parse(data, "0.23.0").version == "0.24.0"
    assert Release.parse(data, "0.24.0") is None
    assert Release.parse(data, "0.25.0") is None
    for key, value in (
        ("draft", True),
        ("prerelease", True),
        ("tag_name", "v0.24.0-rc1"),
        ("html_url", "https://example.com/fake"),
    ):
        assert Release.parse({**data, key: value}, "0.23.0") is None
    data["assets"][0]["browser_download_url"] = "file:///tmp/not-a-release.zip"
    release = Release.parse(data, "0.23.0")
    assert not release.portable and release.installer
    assert Release.parse({**release_data(), "assets": None}, "0.23.0").portable == ""


@pytest.mark.parametrize("code", LANGUAGES)
def test_update_popup_routes_three_actions_only_after_click(qtbot, tmp_path, monkeypatch, code):
    host = MainWindow(plugin_root=tmp_path, load_examples=False)
    qtbot.addWidget(host)
    set_language(code)
    release = Release.parse(release_data(), "0.23.0")
    opened = []
    monkeypatch.setattr(
        "picer.updates.QDesktopServices.openUrl", lambda url: opened.append(url.toString())
    )
    try:
        host.updates.finished(release, True)
        assert not host.updates.button.isHidden() and not opened
        host.updates.show_popup()
        popup = host.updates.popup
        assert isinstance(popup, UpdatePopup)
        assert popup.notes.toPlainText().startswith("Changes")
        assert popup.findChildren(QLabel)[0].text() == tr("发现新版本")
        for button in (popup.page, popup.portable, popup.installer):
            qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
        assert opened == [release.page, release.portable, release.installer]
        popup.open_url("file:///tmp/private")
        assert len(opened) == 3
        assert popup.notes.loadResource(2, None) is None
    finally:
        host.close()


def test_external_plugin_labels_and_user_paths_remain_original(qtbot, tmp_path):
    import zipfile

    from PIL import Image

    config = tmp_path / "config"
    config.mkdir()
    (config / "plugins.json").write_text(json.dumps({"ui": {"application": {"language": "en"}}}))
    host = MainWindow(plugin_root=tmp_path, load_examples=False)
    qtbot.addWidget(host)
    try:
        archive = tmp_path / "external.zip"
        manifest = {
            "id": "test.language",
            "name": "图片信息",
            "description": "设置",
            "version": "1.0.0",
            "api_version": 1,
            "type": "function",
            "entrypoint": "main:Plugin",
            "permissions": ["ui.commands"],
        }
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr("manifest.json", json.dumps(manifest))
            package.writestr(
                "main.py",
                "class Plugin:\n"
                "    def activate(self, context):\n"
                '        context.add_command("action", "设置", lambda: None, '
                "requires_image=False)\n"
                "    def deactivate(self):\n        pass\n",
            )
        host.plugins.install(archive)
        host.plugins.enable("test.language")
        assert host.plugins.commands["test.language:action"].text() == "设置"
        path = tmp_path / "设置.png"
        Image.new("RGB", (8, 8)).save(path)
        host.open_image(path)
        qtbot.waitUntil(
            lambda: host.current_path == path and host.source_size == (8, 8), timeout=5000
        )
        assert host.title_bar.filename == "设置.png"
    finally:
        host.close()


def test_update_worker_nonblocking_failure_deduplication_and_shutdown(qtbot, tmp_path, monkeypatch):
    import threading

    started, finish = threading.Event(), threading.Event()
    calls = []

    def fetch():
        calls.append(True)
        started.set()
        assert finish.wait(5)
        return Release.parse(release_data(), "0.23.0")

    monkeypatch.setattr("picer.updates.fetch_release", fetch)
    host = MainWindow(plugin_root=tmp_path, load_examples=False)
    qtbot.addWidget(host)
    try:
        host.updates.check()
        qtbot.waitUntil(started.is_set)
        host.updates.check()
        assert len(calls) == 1 and host.updates.job is not None
        finish.set()
        qtbot.waitUntil(lambda: host.updates.job is None)
        assert host.updates.release.version == "0.24.0"
        previous = host.updates.release
        host.updates.finished(None, False)
        assert host.updates.release == previous
        host.updates.finished(None, True)
        assert host.updates.button.isHidden()
    finally:
        finish.set()
        host.close()


def test_invalid_language_falls_back_without_catalog_path_access():
    for value in ("../../unexpected", ["en"], None, 3):
        set_language(value)
        assert language() == "zh_CN" and tr("设置") == "设置"
