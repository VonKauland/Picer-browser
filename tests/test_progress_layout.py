"""Startup provisioning, bottom-only layout and the actual transparent preview."""

import json
import zipfile

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QCursor, QImage
from PySide6.QtWidgets import QComboBox

from picer.bundles import EXAMPLES
from picer.panels import DOCK_AREAS
from picer.plugins.api import PluginError
from picer.plugins.settings import SettingsForm
from picer.settings import ApplicationSettings
from picer.window import MainWindow


@pytest.fixture
def window(qtbot, tmp_path):
    host = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(host)
    host.show()
    qtbot.wait(30)
    yield host
    host.plugins.shutdown()


def test_defaults_installed_panels_open_skin_off_and_choices_survive(window, qtbot):
    manager = window.plugins
    for _, _, plugin_id, enabled in EXAMPLES:
        assert manager.records[plugin_id].state == ("enabled" if enabled else "disabled")
        assert manager.records[plugin_id].directory.is_dir()
    assert all(not dock.isHidden() for dock in manager.panels.values())
    manager.disable("example.info")
    manager.panels["example.files"].close()
    manager.set_setting("example.progress", "thumbnail_size", 120)
    manager.disable("example.negative")
    manager.uninstall("example.negative")
    manager.shutdown()
    restarted = MainWindow(plugin_root=manager.root)
    qtbot.addWidget(restarted)
    restarted.show()
    assert restarted.plugins.records["example.info"].state == "disabled"
    assert restarted.plugins.panels["example.files"].isHidden()
    assert restarted.plugins.get_setting("example.progress", "thumbnail_size", 0) == 120
    assert "example.negative" not in restarted.plugins.records
    restarted.plugins.shutdown()


def test_safe_mode_does_not_provision_or_execute_examples(tmp_path, qtbot):
    host = MainWindow(plugin_root=tmp_path, load_external=False)
    qtbot.addWidget(host)
    assert not any(key.startswith("example.") for key in host.plugins.records)
    assert not host.plugins.panels
    host.plugins.shutdown()


def test_old_progress_upgrade_preserves_settings_and_migrates_side_location(tmp_path, qtbot):
    host = MainWindow(plugin_root=tmp_path, load_examples=False)
    qtbot.addWidget(host)
    archive = tmp_path / "old-progress.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr(
            "manifest.json",
            json.dumps(
                {
                    "id": "example.progress",
                    "name": "Old Progress",
                    "version": "1.2.1",
                    "type": "panel",
                    "api_version": 1,
                    "entrypoint": "main:Plugin",
                    "permissions": ["ui.panels"],
                }
            ),
        )
        package.writestr("main.py", "raise RuntimeError('old code must not run')")
    host.plugins.install(archive)
    host.plugins.set_setting("example.progress", "thumbnail_size", 144)
    host.plugins.preferences["enabled"]["example.progress"] = True
    host.plugins.preferences["ui"]["panels"] = {"example.progress": False}
    host.plugins.preferences["ui"]["panel_layouts"] = {
        "example.progress": {"area": "left", "height": 500, "width": 500}
    }
    host.plugins._save()
    host.plugins.shutdown()
    upgraded = MainWindow(plugin_root=tmp_path)
    qtbot.addWidget(upgraded)
    upgraded.show()
    qtbot.wait(30)
    manager = upgraded.plugins
    record = manager.records["example.progress"]
    assert record.state == "enabled" and record.manifest.version == "1.7.0"
    assert manager.get_setting("example.progress", "thumbnail_size", 0) == 144
    assert manager.panels["example.progress"].isHidden()
    assert upgraded.panel_hovers.controllers["example.progress"].area == DOCK_AREAS["bottom"]
    assert manager.preferences["ui"]["panel_layouts"]["example.progress"]["area"] == "bottom"
    upgraded.plugins.shutdown()


def test_progress_is_compact_overlay_and_side_docks_reach_bottom(window, qtbot):
    progress = window.plugins.panels["example.progress"]
    assert progress.width() == window.width() // 3
    assert progress.height() == 72
    assert window.height() - 1 - progress.geometry().bottom() == 8
    assert window.dockWidgetArea(progress) == Qt.DockWidgetArea.NoDockWidgetArea
    for key in ("example.files", "example.info"):
        dock = window.plugins.panels[key]
        assert window.height() - 1 - dock.geometry().bottom() <= 1
        assert not (dock.allowedAreas() & DOCK_AREAS["bottom"])
    window.resize(1500, 900)
    qtbot.wait(30)
    assert progress.width() == 500
    assert abs(progress.geometry().center().x() - window.rect().center().x()) <= 1


@pytest.mark.parametrize(
    "plugin_id,forbidden",
    [
        ("example.progress", "left"),
        ("example.progress", "right"),
        ("example.files", "bottom"),
        ("example.info", "bottom"),
    ],
)
def test_forbidden_moves_are_ignored_in_both_modes(window, plugin_id, forbidden):
    controller = window.panel_hovers.controllers[plugin_id]
    original = controller.area
    controller.move_to(DOCK_AREAS[forbidden])
    assert controller.area == original
    controller.dock.close()
    controller.move_to(DOCK_AREAS[forbidden])
    assert controller.area == original and controller.dock.isHidden()
    controller.pin()
    assert not controller.dock.isHidden()


def test_display_actions_removed_and_settings_have_only_allowed_positions(window, qtbot):
    assert not any(
        action.text().startswith("显示：") for action in window.components.menus["panel"].actions()
    )
    assert window.createPopupMenu() is None
    settings = ApplicationSettings(window)
    qtbot.addWidget(settings)
    assert all(isinstance(editor, QComboBox) for editor in settings.panel_editors.values())
    assert settings.panel_editors["example.progress"].count() == 1
    assert settings.panel_editors["example.files"].count() == 2
    form = SettingsForm(window.plugins, "example.progress")
    qtbot.addWidget(form)
    assert form.dock_combo.count() == 1


@pytest.mark.parametrize("size", [48, 80, 144, 200])
def test_preview_transparent_fading_compact_controls_and_size_setting(
    window, qtbot, tmp_path, size
):
    for index in range(9):
        image = QImage(160, 120, QImage.Format.Format_RGB32)
        image.fill(QColor("#538899"))
        assert image.save(str(tmp_path / f"{index}.png"))
    window.open_image(tmp_path / "4.png")
    progress = window.plugins.records["example.progress"].instance
    window.plugins.set_setting("example.progress", "thumbnail_size", size)
    progress.show_preview()
    qtbot.waitUntil(lambda: len(progress.preview.items) == 9)
    qtbot.waitUntil(lambda: progress.expansion == 1)
    preview = progress.preview
    assert preview.thumbnail_size == size and preview.height() == size + 18
    assert preview.width() == progress.dock.width()
    assert progress.dock.height() == 52
    assert all(button.height() == 20 for button in progress.controls.values())
    pixels = preview.grab().toImage()
    # The entire strip has no background; the outermost pixels dissolve to alpha 0.
    assert pixels.pixelColor(0, pixels.height() // 2).alpha() == 0
    assert pixels.pixelColor(pixels.width() - 1, pixels.height() // 2).alpha() < 16
    assert pixels.pixelColor(pixels.width() // 2, 0).alpha() == 0
    assert pixels.pixelColor(pixels.width() // 2, pixels.height() // 2).alpha() == 255
    window.resize(1400, 850)
    qtbot.wait(30)
    assert preview.width() == progress.dock.width()
    qtbot.keyClick(preview, Qt.Key.Key_Escape)
    assert preview.isVisible()
    progress.controls["preview"].click()
    qtbot.waitUntil(lambda: not preview.isVisible() and progress.dock.height() == 72)
    assert all(button.height() == 28 for button in progress.controls.values())


def test_progress_hover_pin_fullscreen_and_cleanup(window, qtbot):
    controller = window.panel_hovers.controllers["example.progress"]
    controller.dock.close()
    assert controller.strip.isVisible()
    controller.reveal()
    qtbot.wait(450)
    assert controller.popup is not None and controller.popup.width() == window.width() // 3
    qtbot.mouseClick(controller.strip, Qt.MouseButton.LeftButton, pos=QPoint(42, 2))
    assert controller.popup is None and not controller.dock.isHidden()
    window.toggle_fullscreen()
    assert controller.dock.isHidden()
    window.exit_fullscreen()
    assert not controller.dock.isHidden()
    window.plugins.disable("example.progress")
    assert "example.progress" not in window.panel_hovers.controllers


def test_external_zip_still_requires_enable_and_side_cannot_claim_bottom(window, tmp_path):
    archive = tmp_path / "external.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr(
            "manifest.json",
            json.dumps(
                {
                    "id": "test.external",
                    "name": "External",
                    "version": "1.0.0",
                    "type": "panel",
                    "api_version": 1,
                    "entrypoint": "main:Plugin",
                    "permissions": ["ui.panels"],
                }
            ),
        )
        package.writestr(
            "main.py",
            "from PySide6.QtWidgets import QLabel\nclass Plugin:\n"
            " def activate(self, context):\n  context.add_panel(QLabel('Panel'), area='bottom')",
        )
    window.plugins.install(archive)
    assert window.plugins.records["test.external"].state == "disabled"
    with pytest.raises(PluginError, match="底部仅用于进度面板"):
        window.plugins.enable("test.external")


def test_only_one_declared_progress_component_can_claim_bottom(window, tmp_path):
    archive = tmp_path / "other-progress.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr(
            "manifest.json",
            json.dumps(
                {
                    "id": "test.progress",
                    "name": "Progress",
                    "version": "1.0.0",
                    "type": "panel",
                    "panel_role": "progress",
                    "api_version": 1,
                    "entrypoint": "main:Plugin",
                    "permissions": ["ui.panels"],
                }
            ),
        )
        package.writestr(
            "main.py",
            "from PySide6.QtWidgets import QLabel\nclass Plugin:\n"
            " def activate(self, context):\n  context.add_panel(QLabel('Progress'), area='bottom')",
        )
    window.plugins.install(archive)
    with pytest.raises(PluginError, match="只能启用一个进度面板"):
        window.plugins.enable("test.progress")
    assert "test.progress" not in window.plugins.panels
    window.plugins.disable("example.progress")
    window.plugins.enable("test.progress")
    assert window.panel_hovers.controllers["test.progress"].area == DOCK_AREAS["bottom"]


def test_preview_inside_autohide_reveal_and_cleanup(window, qtbot, tmp_path):
    for index in range(4):
        image = QImage(80, 60, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.cyan)
        image.save(str(tmp_path / f"{index}.png"))
    window.open_image(tmp_path / "1.png")
    controller = window.panel_hovers.controllers["example.progress"]
    progress = window.plugins.records["example.progress"].instance
    controller.dock.close()
    controller.reveal()
    qtbot.wait(450)
    QCursor.setPos(window.mapToGlobal(controller.bounds().center()))
    progress.controls["preview"].click()
    qtbot.waitUntil(lambda: len(progress.preview.items) == 4)
    qtbot.waitUntil(lambda: progress.expansion == 1)
    assert progress.preview.isVisible()
    assert progress.preview.width() == controller.bounds().width()
    assert controller.popup.height() == 52 and controller.dock.isHidden()
    qtbot.keyClick(progress.preview, Qt.Key.Key_Right)
    qtbot.keyClick(progress.preview, Qt.Key.Key_Return)
    assert window.current_path.name == "2.png"
    assert progress.preview.isVisible()
    progress.controls["preview"].click()
    qtbot.waitUntil(lambda: not progress.preview.isVisible())
    controller.pin()
    progress.show_preview()
    window.plugins.disable("example.progress")
    qtbot.wait(30)
    assert "example.progress" not in window.plugins.panels
    assert "example.progress" not in window.panel_hovers.controllers
