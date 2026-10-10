"""Exercise real management forms, saved preferences and unchanged panel motion."""

import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QEasingCurve, Qt
from PySide6.QtGui import QColor, QKeySequence, QPalette
from PySide6.QtWidgets import QPushButton

from picer.cache import ThumbnailCache
from picer.panels import DOCK_AREAS
from picer.plugins.dialog import PluginDialog
from picer.preferences import DEFAULTS, read_preferences
from picer.settings import ApplicationSettings
from picer.theme import COLORS
from picer.window import MainWindow

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def window(qtbot, tmp_path):
    host = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(host)
    host.show()
    yield host
    host.plugins.shutdown()


def install_example(window, tmp_path, name):
    source = ROOT / "examples" / name
    archive = tmp_path / f"{name}.zip"
    with zipfile.ZipFile(archive, "w") as package:
        for file in source.rglob("*"):
            if file.is_file() and "__pycache__" not in file.parts:
                package.write(file, file.relative_to(source))
    plugin_id = window.plugins.install(archive)
    window.plugins.enable(plugin_id)
    return plugin_id


@pytest.mark.parametrize("name", ["file_browser", "info_panel", "progress_panel"])
def test_examples_have_no_settings_button(window, tmp_path, name):
    plugin_id = install_example(window, tmp_path, name)
    panel = window.plugins.records[plugin_id].instance.panel
    assert all(
        "设置" not in button.text() + button.toolTip() + button.accessibleName()
        for button in panel.findChildren(QPushButton)
    )
    dialog = PluginDialog(window.plugins, window, selected_id=plugin_id, open_settings=True)
    assert dialog.pages.currentIndex() == 1
    assert dialog.settings_form.parentWidget() is not None
    assert dialog.settings_form.editors
    dialog.deleteLater()


def test_embedded_browser_settings_apply_cancel_and_restart(window, tmp_path, qtbot):
    plugin_id = install_example(window, tmp_path, "file_browser")
    dialog = PluginDialog(window.plugins, window, selected_id=plugin_id, open_settings=True)
    qtbot.addWidget(dialog)
    form = dialog.settings_form
    form.editors["home"].setText(str(tmp_path))
    form.editors["icon_size"].setValue(48)
    form.editors["sort"].setCurrentIndex(form.editors["sort"].findData("modified"))
    form.editors["descending"].setChecked(True)
    form.dock_combo.setCurrentIndex(form.dock_combo.findData(DOCK_AREAS["right"]))
    dialog.save_settings()
    browser = window.plugins.records[plugin_id].instance
    assert browser.location.text() == str(tmp_path.resolve())
    assert browser.tree.iconSize().width() == 48
    assert browser.tree.header().sortIndicatorSection() == 3
    assert browser.tree.header().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    assert window.dockWidgetArea(browser.dock) == DOCK_AREAS["right"]
    assert dialog.summary.text() == "设置已保存"
    form.editors["icon_size"].setValue(20)
    dialog.cancel_settings()
    dialog.settings()
    assert dialog.settings_form.editors["icon_size"].value() == 48
    window.plugins.shutdown()
    restarted = MainWindow(plugin_root=window.plugins.root)
    qtbot.addWidget(restarted)
    assert restarted.plugins.records[plugin_id].instance.tree.iconSize().width() == 48
    assert restarted.panel_hovers.controllers[plugin_id].area == DOCK_AREAS["right"]
    restarted.plugins.shutdown()


def test_management_search_state_filter_and_disabled_form_cleanup(window, tmp_path, qtbot):
    plugin_id = install_example(window, tmp_path, "info_panel")
    dialog = PluginDialog(window.plugins, window, selected_id=plugin_id, open_settings=True)
    qtbot.addWidget(dialog)
    window.plugins.disable(plugin_id)
    assert dialog.pages.currentIndex() == 0
    assert dialog.settings_form is None
    assert not dialog.page_tabs.isTabEnabled(1)
    dialog.search.setText("EXAMPLE.INFO")
    assert dialog.list.count() == 1
    dialog.status_filter.setCurrentIndex(dialog.status_filter.findData("enabled"))
    assert dialog.list.count() == 0
    dialog.status_filter.setCurrentIndex(dialog.status_filter.findData("disabled"))
    assert dialog.list.count() == 1


def test_sdk_settings_entry_opens_management_page(window, tmp_path, monkeypatch):
    plugin_id = install_example(window, tmp_path, "progress_panel")
    opened = []

    def inspect(dialog):
        opened.append((dialog.selected_id(), dialog.pages.currentIndex()))
        return 0

    monkeypatch.setattr(PluginDialog, "exec", inspect)
    window.plugins.records[plugin_id].context.show_settings()
    assert opened == [(plugin_id, 1)]


def test_application_settings_save_restart_and_cancel(window, tmp_path, qtbot):
    dialog = ApplicationSettings(window)
    qtbot.addWidget(dialog)
    assert dialog.pages.count() == 6
    dialog.editors["zoom_step"].setValue(40)
    dialog.editors["wrap"].setChecked(False)
    dialog.editors["glass"].setChecked(False)
    dialog.editors["start"].setCurrentIndex(dialog.editors["start"].findData("last"))
    action_name = next(
        name for name, action in window.shortcut_actions.items() if action is window.open_action
    )
    dialog.shortcut_editors[action_name].setKeySequence(QKeySequence("Ctrl+Alt+O"))
    dialog.save()
    assert window.view.zoom_step == 40
    assert window.app_preferences["glass"] is False
    assert window.open_action.shortcut() == QKeySequence("Ctrl+Alt+O")
    path = tmp_path / "remember.png"
    Image.new("RGB", (50, 30)).save(path)
    window.open_image(path)
    window.close()
    state = json.loads(window.plugins.state_file.read_text(encoding="utf-8"))
    assert state["ui"]["application"]["wrap"] is False
    assert state["ui"]["last_image"] == str(path)
    restarted = MainWindow(plugin_root=window.plugins.root)
    qtbot.addWidget(restarted)
    restarted.restore_startup()
    assert restarted.current_path == path
    assert restarted.view.zoom_step == 40
    cancelled = ApplicationSettings(restarted)
    qtbot.addWidget(cancelled)
    cancelled.editors["zoom_step"].setValue(90)
    cancelled.reject()
    assert restarted.view.zoom_step == 40
    restarted.plugins.shutdown()


def test_duplicate_shortcut_does_not_save_preferences(window, qtbot, monkeypatch):
    dialog = ApplicationSettings(window)
    qtbot.addWidget(dialog)
    editors = list(dialog.shortcut_editors.values())
    editors[0].setKeySequence(QKeySequence("Ctrl+Shift+Z"))
    editors[1].setKeySequence(QKeySequence("Ctrl+Shift+Z"))
    dialog.editors["zoom_step"].setValue(50)
    warnings = []
    monkeypatch.setattr("picer.settings.QMessageBox.warning", lambda *args: warnings.append(args))
    dialog.save()
    assert warnings
    assert window.view.zoom_step == DEFAULTS["zoom_step"]


def test_new_dialog_controls_apply_dark_styles_on_first_show(window, qtbot):
    management = PluginDialog(window.plugins, window)
    qtbot.addWidget(management)
    management.show()
    settings = ApplicationSettings(window)
    qtbot.addWidget(settings)
    settings.show()
    qtbot.wait(50)
    for control in (management.toggle_button, management.details, settings.skin):
        assert control.property("picerHost") is True
        role = (
            QPalette.ColorRole.Text
            if control is management.details
            else QPalette.ColorRole.ButtonText
        )
        assert control.palette().color(role) == QColor(COLORS["text"])
    card = settings.skin.parentWidget()
    assert card.palette().color(QPalette.ColorRole.Window) == QColor(COLORS["menu"])


def test_browsing_preferences_have_effect(window, tmp_path, qtbot):
    for name in ("a.png", "b.png"):
        Image.new("RGB", (50, 30)).save(tmp_path / name)
    dialog = ApplicationSettings(window)
    qtbot.addWidget(dialog)
    dialog.editors["wrap"].setChecked(False)
    dialog.editors["default_scale"].setCurrentIndex(
        dialog.editors["default_scale"].findData("actual")
    )
    dialog.save()
    window.open_image(tmp_path / "b.png")
    window.next_action.trigger()
    assert window.current_path == tmp_path / "b.png"
    assert window.view.transform().m11() == 1
    assert not window.view.fit_mode
    dialog = ApplicationSettings(window)
    qtbot.addWidget(dialog)
    dialog.editors["browse_folder"].setChecked(False)
    dialog.save()
    window.open_image(tmp_path / "a.png")
    assert window.paths == [tmp_path / "a.png"]


def test_exif_orientation_preference(window, tmp_path):
    exif = Image.Exif()
    exif[274] = 6
    path = tmp_path / "rotated.jpg"
    Image.new("RGB", (80, 60)).save(path, exif=exif)
    window.open_image(path)
    assert window.view.image_item.pixmap().width() == 60
    window.plugins.preferences["ui"]["application"] = {"auto_orient": False}
    window.apply_preferences()
    window.open_image(path)
    assert window.view.image_item.pixmap().width() == 80


def test_hidden_panel_motion_is_preserved(window, tmp_path):
    plugin_id = install_example(window, tmp_path, "progress_panel")
    controller = window.panel_hovers.controllers[plugin_id]
    controller.dock.close()
    controller.reveal()
    assert controller.animation.duration() == 420
    assert controller.animation.easingCurve().type() == QEasingCurve.Type.OutBack
    assert controller.animation.easingCurve().overshoot() == pytest.approx(0.55)
    assert controller.leave_timer.interval() == 220
    controller.progress = 0.6
    controller.collapse()
    assert controller.animation.duration() == 300
    assert controller.animation.easingCurve().type() == QEasingCurve.Type.InOutCubic
    assert controller.animation.startValue() == pytest.approx(0.6)
    controller.restore()


def test_malformed_preferences_fall_back_without_crashing(window):
    window.plugins.preferences["ui"]["application"] = {
        "zoom_step": True,
        "glass_strength": -100,
        "start": [],
        "glass": "yes",
        "cache_mb": 999999,
    }
    values = read_preferences(window.plugins)
    assert values["zoom_step"] == 25
    assert values["glass_strength"] == 0
    assert values["start"] == "empty"
    assert values["glass"] is True
    assert values["cache_mb"] == 16384


def test_cache_byte_limit_keeps_newest_files_and_originals(tmp_path):
    cache = ThumbnailCache(tmp_path, byte_limit=15)
    cache.directory.mkdir()
    import os

    for index in range(3):
        path = cache.directory / f"{index}.png"
        path.write_bytes(b"0123456789")
        os.utime(path, (index + 1, index + 1))
    original = tmp_path / "original.png"
    original.write_bytes(b"original")
    cache.prune()
    assert [path.name for path in cache.directory.glob("*.png")] == ["2.png"]
    assert original.read_bytes() == b"original"


def test_plugin_using_freed_core_shortcut_survives_restart(window, tmp_path, qtbot):
    name = next(
        name for name, action in window.shortcut_actions.items() if action is window.open_action
    )
    window.plugins.preferences["ui"]["shortcuts"] = {name: "Ctrl+Alt+O"}
    window.apply_preferences()
    archive = tmp_path / "shortcut.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr(
            "manifest.json",
            json.dumps(
                {
                    "id": "test.shortcut",
                    "name": "Shortcut",
                    "version": "1.0.0",
                    "api_version": 1,
                    "type": "function",
                    "entrypoint": "main:Plugin",
                    "permissions": ["ui.commands"],
                }
            ),
        )
        package.writestr(
            "main.py",
            "class Plugin:\n"
            "    def activate(self, context):\n"
            "        context.add_command('run', 'Run', lambda: None, shortcut='Ctrl+O')\n",
        )
    window.plugins.install(archive)
    window.plugins.enable("test.shortcut")
    window.plugins.shutdown()
    restarted = MainWindow(plugin_root=window.plugins.root)
    qtbot.addWidget(restarted)
    assert restarted.open_action.shortcut() == QKeySequence("Ctrl+Alt+O")
    assert restarted.plugins.records["test.shortcut"].state == "enabled"
    assert restarted.plugins.commands["test.shortcut:run"].shortcut() == QKeySequence("Ctrl+O")
    restarted.plugins.shutdown()
