"""Pixel correctness, atomic saves, opt-in editor UI and session revocation."""

import copy

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QPoint, Qt

from picer.editing.engine import defaults, fingerprint, render, save_image, validate
from picer.editing.panel import SaveDialog
from picer.editing.presets import PresetDialog, PresetSettings, read_presets
from picer.plugins.api import PluginError
from picer.plugins.settings import SettingsForm
from picer.plugins.tasks import TaskCancelled, TaskToken
from picer.window import MainWindow


def pixels():
    data = np.zeros((6, 8, 4), dtype=np.uint8)
    data[:, :4] = [255, 0, 0, 255]
    data[:, 4:] = [0, 255, 0, 128]
    return Image.fromarray(data)


def test_geometry_and_alpha_have_expected_pixels():
    source = pixels()
    state = defaults(source.size)
    state["crop"].update(enabled=True, x=0.5, w=0.5)
    result, size = render(source, state)
    assert result.size == size == (4, 6)
    assert result.getpixel((0, 0)) == (0, 255, 0, 128)
    state["resize"].update(enabled=True, width=2, height=3)
    state["rotate"].update(enabled=True, angle=90)
    result, size = render(source, state)
    assert result.size == size == (3, 2)
    state = defaults(source.size)
    state["mirror"].update(enabled=True, horizontal=True, vertical=True)
    result, _ = render(source, state)
    assert result.getpixel((0, 0)) == source.getpixel((7, 5))
    assert source.getpixel((0, 0)) == (255, 0, 0, 255)


def test_selective_color_retains_target_only_and_hue_wraps():
    source = pixels()
    state = defaults(source.size)
    state["selective"].update(enabled=True, hue=359, range=10, softness=0)
    result, _ = render(source, state)
    assert result.getpixel((0, 0)) == (255, 0, 0, 255)
    r, g, b, a = result.getpixel((7, 0))
    assert r == g == b and a == 128
    state["selective"]["hue"] = 120
    result, _ = render(source, state)
    assert result.getpixel((7, 0)) == (0, 255, 0, 128)
    r, g, b, _ = result.getpixel((0, 0))
    assert r == g == b


def test_hsl_levels_curves_and_pixelation():
    source = pixels()
    state = defaults(source.size)
    state["hsl"].update(enabled=True, hue=120)
    result, _ = render(source, state)
    assert result.getpixel((0, 0)) == (0, 255, 0, 255)
    state["hsl"].update(hue=0, saturation=-100)
    result, _ = render(source, state)
    assert len(set(result.getpixel((0, 0))[:3])) == 1
    state = defaults(source.size)
    state["levels"].update(enabled=True, out_black=255, out_white=0)
    result, _ = render(source, state)
    assert result.getpixel((0, 0)) == (0, 255, 255, 255)
    state = defaults(source.size)
    state["curves"]["enabled"] = True
    state["curves"]["points"]["R"] = [[0, 255], [255, 0]]
    result, _ = render(source, state)
    assert result.getpixel((0, 0)) == (0, 0, 0, 255)
    state = defaults(source.size)
    state["pixelate"].update(enabled=True, size=8)
    result, _ = render(source, state)
    assert result.getpixel((0, 0)) == result.getpixel((7, 5))


def test_presets_validate_before_allocation_and_reject_nonfinite():
    for key, field, value in (
        ("crop", "w", 2),
        ("rotate", "angle", float("nan")),
        ("resize", "width", 30001),
        ("levels", "black", 255),
    ):
        state = defaults()
        state[key][field] = value
        with pytest.raises(ValueError):
            validate(state)
    state = defaults()
    state["curves"]["points"]["RGB"] = [[200, 0], [100, 255]]
    with pytest.raises(ValueError):
        validate(state)


def test_atomic_save_full_resolution_copy_collision_and_stale_source(tmp_path):
    source = tmp_path / "原图.png"
    pixels().resize((800, 600)).save(source)
    original = source.read_bytes()
    state = defaults((800, 600))
    state["crop"].update(enabled=True, w=0.5)
    mark = fingerprint(source)
    first = save_image(source, state, mark)
    second = save_image(source, state, mark)
    assert first != second and source.read_bytes() == original
    with Image.open(first) as opened:
        assert opened.size == (400, 600)
    save_image(source, state, mark, overwrite=True)
    with Image.open(source) as opened:
        assert opened.size == (400, 600)
    with pytest.raises(ValueError, match="原文件"):
        save_image(source, state, mark, overwrite=True)
    token = TaskToken()
    token.cancel()
    with pytest.raises(TaskCancelled):
        save_image(source, state, fingerprint(source), token=token)
    assert not list(tmp_path.glob(".picer-edit-*"))


@pytest.fixture
def editor(qtbot, tmp_path):
    window = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(window)
    window.resize(1200, 800)
    window.show()
    path = tmp_path / "source.png"
    pixels().resize((800, 600)).save(path)
    window.open_image(path)
    assert window.plugins.records["example.editor"].state == "disabled"
    window.plugins.enable("example.editor")
    panel = window.plugins.records["example.editor"].instance.panel
    qtbot.waitUntil(lambda: panel.session.source is not None, timeout=5000)
    yield window, path, panel
    window.plugins.shutdown()


def settle(panel, qtbot):
    qtbot.waitUntil(
        lambda: not panel.session.timer.isActive() and not panel.session.busy, timeout=5000
    )


def test_editor_default_right_switches_no_photo_previews_and_restore(editor, qtbot):
    window, path, panel = editor
    assert (
        window.dockWidgetArea(window.plugins.panels["example.editor"])
        == Qt.DockWidgetArea.RightDockWidgetArea
    )
    assert not any(switch.isChecked() for switch in panel.switches.values())
    assert all(not widget.isVisible() for widget in panel.parameters.values())
    original = path.read_bytes()
    panel.switches["mirror"].setChecked(True)
    panel.editors["mirror", "horizontal"].setChecked(True)
    settle(panel, qtbot)
    assert panel.session.applied and path.read_bytes() == original
    image = window.view.image_item.pixmap().toImage()
    assert image.pixelColor(0, 0).green() > 200
    panel.switches["mirror"].setChecked(False)
    settle(panel, qtbot)
    assert panel.session.state["mirror"]["horizontal"] is True
    panel.switches["mirror"].setChecked(True)
    settle(panel, qtbot)
    context = window.plugins.records["example.editor"].context
    window.plugins.disable("example.editor")
    qtbot.waitUntil(lambda: not window.image_edited)
    assert not panel.session.active and not panel.navigator.timer.isActive()
    assert "example.editor" not in window.plugins.editing_sessions
    with pytest.raises(PluginError):
        context.create_editing_session()


def test_preset_form_and_save_confirmation_do_not_write_implicitly(editor, qtbot):
    window, path, panel = editor
    context = window.plugins.records["example.editor"].context
    state = copy.deepcopy(panel.session.state)
    state["hsl"].update(enabled=True, saturation=-100)
    context.set_setting("presets", [{"name": "灰度", "state": state}])
    panel.reload_presets()
    panel.use_preset(1)
    settle(panel, qtbot)
    assert panel.session.state["hsl"]["saturation"] == -100
    original = path.read_bytes()
    dialog = SaveDialog(panel, True)
    dialog.choose(None)
    assert dialog.choice is None and path.read_bytes() == original
    dialog.deleteLater()
    names = PresetDialog({"灰度"}, panel)
    names.name.setText("灰度")
    assert not names.confirm.isEnabled()
    names.name.setText("新预设")
    assert names.confirm.isEnabled()
    names.deleteLater()
    form = SettingsForm(window.plugins, "example.editor")
    assert isinstance(form.custom, PresetSettings)
    assert form.save() and len(read_presets(context)) == 1
    form.deleteLater()
    assert panel.session.save(False)
    qtbot.waitUntil(lambda: window.current_path != path, timeout=5000)
    assert path.read_bytes() == original
    assert window.current_path.is_file()


@pytest.mark.parametrize("offset", [0, 10])
def test_crop_canvas_select_and_stale_navigation(editor, qtbot, offset):
    window, path, panel = editor
    panel.switches["crop"].setChecked(True)
    settle(panel, qtbot)
    panel.session.begin_tool("crop")
    view = window.view
    rect = view.mapFromScene(view.image_item.sceneBoundingRect()).boundingRect()
    start = rect.topLeft() + QPoint(offset, offset)
    end = rect.center()
    qtbot.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(view.viewport(), pos=end)
    qtbot.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
    settle(panel, qtbot)
    assert panel.session.state["crop"]["w"] < 0.6
    other = path.with_name("other.png")
    Image.new("RGB", (200, 100), "blue").save(other)
    window.open_image(other)
    qtbot.waitUntil(lambda: panel.session.path == other and panel.session.source is not None)
    assert not any(row["enabled"] for row in panel.session.state.values())
    assert not window.image_edited


def test_failed_commit_preserves_source_and_leaves_no_partial_copy(tmp_path, monkeypatch):
    path = tmp_path / "photo.png"
    pixels().save(path)
    original = path.read_bytes()
    import picer.editing.engine as engine

    def denied(*args):
        raise PermissionError("模拟磁盘提交失败")

    monkeypatch.setattr(engine.os, "replace", denied)
    for overwrite in (True, False):
        with pytest.raises(PermissionError):
            save_image(path, defaults(), fingerprint(path), overwrite=overwrite)
        assert path.read_bytes() == original
        assert list(tmp_path.iterdir()) == [path]


def test_exif_orientation_normalized_and_camera_tags_preserved(tmp_path):
    path = tmp_path / "oriented.jpg"
    exif = Image.Exif()
    exif[274], exif[271], exif[272] = 6, "Camera Maker", "Model"
    pixels().convert("RGB").save(path, exif=exif)
    result = save_image(path, defaults(), fingerprint(path))
    with Image.open(result) as saved:
        assert saved.size == (6, 8)
        assert saved.getexif()[274] == 1
        assert saved.getexif()[271] == "Camera Maker"


def test_animated_editor_rejects_destructive_frame_conversion(qtbot, tmp_path):
    window = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(window)
    path = tmp_path / "animated.gif"
    Image.new("RGB", (30, 20), "red").save(
        path,
        save_all=True,
        append_images=[Image.new("RGB", (30, 20), "blue")],
        duration=100,
        loop=0,
    )
    window.open_image(path)
    window.plugins.enable("example.editor")
    panel = window.plugins.records["example.editor"].instance.panel
    qtbot.waitUntil(lambda: bool(panel.session.error), timeout=5000)
    assert "动态图" in panel.session.error and not panel.save_button.isEnabled()
    assert window.plugins.records["example.editor"].state == "enabled"
    window.plugins.shutdown()


def test_navigation_during_save_resumes_new_image_editor(editor, qtbot, monkeypatch):
    from threading import Event

    import picer.editing.session as session_module

    window, path, panel = editor
    other = path.with_name("new.png")
    Image.new("RGB", (200, 100), "blue").save(other)
    entered, release = Event(), Event()
    original_save = session_module.save_image

    def blocked(*args, **kwargs):
        entered.set()
        release.wait(5)
        return original_save(*args, **kwargs)

    monkeypatch.setattr(session_module, "save_image", blocked)
    assert panel.session.save(False)
    try:
        qtbot.waitUntil(entered.is_set)
        window.open_image(other)
        qtbot.waitUntil(lambda: panel.session.path == other)
        qtbot.wait(180)  # The image-change debounce expires while the write is pending.
        assert panel.session.source is None
    finally:
        release.set()
    qtbot.waitUntil(
        lambda: panel.session.source is not None and not panel.session.saving, timeout=5000
    )
    assert window.current_path == other and panel.session.native == (200, 100)
    assert window.view.image_item.pixmap().toImage().pixelColor(0, 0).blue() > 240
