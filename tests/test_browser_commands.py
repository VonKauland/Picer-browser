"""Configurable operations, local search, image selection and scrollbar policies."""

from pathlib import Path
from threading import Event

import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget

from picer.folder_navigation import sibling_image
from picer.input_bindings import default_bindings, read_bindings
from picer.plugins.tasks import TaskToken
from picer.settings import ApplicationSettings
from picer.window import MainWindow


@pytest.fixture
def host(qtbot, tmp_path):
    host = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(host)
    host.show()
    host.activateWindow()
    yield host
    host.close()


def photo(path, color="red", size=(90, 130)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path.resolve()


def browser(host):
    return host.plugins.records["example.files"].instance


def wait_entries(qtbot, plugin, folder, count):
    plugin.open_folder(str(folder))
    qtbot.waitUntil(lambda: plugin.model.rowCount(plugin.tree.rootIndex()) == count)


def test_defaults_actions_and_saved_multi_input_bindings(host, qtbot):
    defaults = default_bindings(host)
    for key, value in (
        ("复制当前图片", "Ctrl+C"),
        ("打开父级文件夹", "Backspace"),
        ("打开选中文件夹", "Return"),
        ("全屏", "F11"),
        ("将当前文件夹加入快速访问", "Ctrl+F"),
    ):
        assert defaults[key] == [{"device": "keyboard", "value": value}]
    for key in (
        "跳转至首图",
        "跳转至尾图",
        "上一个图片文件夹",
        "下一个图片文件夹",
        "启用全屏",
        "退出全屏",
        "播放幻灯片",
        "停止幻灯片",
        "切换浏览方向",
    ):
        assert not defaults[key]
    settings = ApplicationSettings(host)
    qtbot.addWidget(settings)
    editor = settings.binding_editor
    assert editor.assign("跳转至首图", "keyboard", "Ctrl+Home")
    assert editor.assign("跳转至首图", "mouse", "Ctrl+Back")
    assert editor.assign("跳转至尾图", "touch", "R2")
    settings.save()
    profile = read_bindings(host)
    assert {b["device"] for b in profile["跳转至首图"]} == {"keyboard", "mouse"}
    assert profile["跳转至尾图"] == [{"device": "touch", "value": "R2"}]


def test_copy_pixels_not_path_and_jump_edges(host, qtbot, tmp_path):
    paths = [
        photo(tmp_path / "images" / f"{i}.png", color)
        for i, color in enumerate(("red", "green", "blue"))
    ]
    host.open_image(paths[1])
    host.view.setFocus()
    qtbot.keyClick(host.view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    pixels = QApplication.clipboard().image()
    assert pixels.size() == host.view.image_item.pixmap().size()
    assert pixels.pixelColor(10, 10).green() == 128
    host.last_action.trigger()
    assert host.current_path == paths[-1]
    host.first_action.trigger()
    assert host.current_path == paths[0]
    host.replace_image(host.view.image_item.pixmap().toImage().mirrored())
    host.copy_image()
    assert QApplication.clipboard().image() == host.view.image_item.pixmap().toImage()


def test_large_preview_copy_uses_full_resolution(host, qtbot, tmp_path):
    path = photo(tmp_path / "large.png", "blue", (3000, 2200))
    host.open_image(path)
    qtbot.waitUntil(lambda: host.current_path == path)
    host.loader.refine.stop()
    assert host.view.image_item.pixmap().width() < 3000
    QApplication.clipboard().clear()
    host.copy_image()
    qtbot.waitUntil(lambda: QApplication.clipboard().image().width() == 3000, timeout=10000)
    assert QApplication.clipboard().image().height() == 2200


def test_sibling_scan_skips_empty_nested_only_and_corrupt(tmp_path):
    current = photo(tmp_path / "B" / "first.png")
    previous = photo(tmp_path / "A" / "first.png")
    photo(tmp_path / "C" / "nested" / "hidden.png")
    (tmp_path / "C" / "broken.png").write_text("not an image")
    following = photo(tmp_path / "D" / "first.png")
    token = TaskToken()
    assert sibling_image(current.parent, -1, {".png"}, token) == previous
    assert sibling_image(current.parent, 1, {".png"}, token) == following
    assert sibling_image(previous.parent, -1, {".png"}, token) is None
    assert sibling_image(following.parent, 1, {".png"}, token) is None


def test_folder_commands_no_wrap_and_preserve_browser_folder(host, qtbot, tmp_path, monkeypatch):
    paths = [photo(tmp_path / "siblings" / name / "first.png") for name in ("A", "B", "C")]
    messages = []
    monkeypatch.setattr(host, "notify", messages.append)
    host.open_image(paths[1])
    browser(host).open_folder(str(paths[1].parent))
    host.next_folder_action.trigger()
    qtbot.waitUntil(lambda: host.current_path == paths[2])
    assert browser(host).location.text() == str(paths[1].parent)
    host.next_folder_action.trigger()
    qtbot.waitUntil(lambda: "已是最后一个图片文件夹" in messages)
    assert host.current_path == paths[2]
    host.previous_folder_action.trigger()
    qtbot.waitUntil(lambda: host.current_path == paths[1])
    host.previous_folder_action.trigger()
    qtbot.waitUntil(lambda: host.current_path == paths[0])
    host.previous_folder_action.trigger()
    qtbot.waitUntil(lambda: "已是第一个图片文件夹" in messages)
    assert host.current_path == paths[0]


def test_stale_folder_scan_cannot_replace_new_image(host, qtbot, tmp_path, monkeypatch):
    first = photo(tmp_path / "A" / "1.png")
    target = photo(tmp_path / "B" / "1.png")
    chosen = photo(tmp_path / "C" / "1.png")
    started, release = Event(), Event()

    def blocked(*args):
        started.set()
        release.wait(5)
        return target

    monkeypatch.setattr("picer.folder_navigation.sibling_image", blocked)
    host.open_image(first)
    host.folder_navigation.navigate(1)
    qtbot.waitUntil(started.is_set)
    host.open_image(chosen)
    release.set()
    qtbot.waitUntil(lambda: not any(lane == "index" for _, lane, _ in host.loader.jobs.values()))
    assert host.current_path == chosen


def test_browser_enter_backspace_remap_and_favorites(host, qtbot, tmp_path):
    plugin = browser(host)
    child = tmp_path / "parent" / "child"
    child.mkdir(parents=True)
    wait_entries(qtbot, plugin, child.parent, 1)
    plugin.tree.setCurrentIndex(plugin.model.index(str(child)))
    plugin.tree.setFocus()
    qtbot.keyClick(plugin.tree, Qt.Key.Key_Return)
    assert plugin.location.text() == str(child)
    qtbot.keyClick(plugin.tree, Qt.Key.Key_Backspace)
    assert plugin.location.text() == str(child.parent)
    plugin.tree.setCurrentIndex(plugin.model.index(str(child)))
    plugin.search.setFocus()
    qtbot.keyClick(plugin.search, Qt.Key.Key_Return)
    assert plugin.location.text() == str(child.parent)
    host.plugins.preferences["ui"]["input_bindings"] = {
        "打开父级文件夹": [{"device": "keyboard", "value": "Ctrl+U"}],
        "打开选中文件夹": [{"device": "keyboard", "value": "Ctrl+J"}],
    }
    host.inputs.reload()
    plugin.open_folder(str(child))
    plugin.tree.setFocus()
    qtbot.keyClick(plugin.tree, Qt.Key.Key_Backspace)
    assert plugin.location.text() == str(child)
    qtbot.keyClick(plugin.tree, Qt.Key.Key_U, Qt.KeyboardModifier.ControlModifier)
    assert plugin.location.text() == str(child.parent)
    qtbot.keyClick(plugin.tree, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert plugin.context.get_setting("favorites") == [str(child.parent)]
    plugin.search.setText("ab")
    plugin.search.setFocus()
    qtbot.keyClick(plugin.search, Qt.Key.Key_Backspace)
    assert plugin.search.text() == "a" and plugin.location.text() == str(child.parent)


def test_browser_parent_entry_enter_and_no_selected_file_open(host, qtbot, tmp_path):
    plugin = browser(host)
    path = photo(tmp_path / "folder" / "one.png")
    wait_entries(qtbot, plugin, path.parent, 1)
    plugin.tree.setCurrentIndex(plugin.model.index(str(path)))
    host.shortcut_actions["打开选中文件夹"].trigger()
    assert host.current_path is None
    plugin.parent_entry.setChecked(True)
    plugin.parent_entry.setFocus()
    qtbot.keyClick(plugin.parent_entry, Qt.Key.Key_Enter)
    assert plugin.location.text() == str(path.parent.parent)


def test_fullscreen_actions_are_separate_and_idempotent(host):
    host.shortcut_actions["启用全屏"].trigger()
    host.shortcut_actions["启用全屏"].trigger()
    assert host.isFullScreen()
    host.shortcut_actions["退出全屏"].trigger()
    host.shortcut_actions["退出全屏"].trigger()
    assert not host.isFullScreen()
    assert host.fullscreen_action.shortcut() == QKeySequence("F11")


def test_slideshow_start_stop_and_plugin_revocation(host, qtbot, tmp_path):
    paths = [photo(tmp_path / f"{i}.png") for i in range(2)]
    host.open_image(paths[0])
    progress = host.plugins.records["example.progress"].instance
    host.shortcut_actions["播放幻灯片"].trigger()
    assert progress.timer.isActive()
    host.shortcut_actions["播放幻灯片"].trigger()
    assert progress.timer.isActive()
    host.shortcut_actions["停止幻灯片"].trigger()
    assert not progress.timer.isActive()
    host.plugins.disable("example.progress")
    assert not host.shortcut_actions["播放幻灯片"].isEnabled()
    assert not host.shortcut_actions["停止幻灯片"].isEnabled()
    assert not host.plugins.call_panel_operation("slideshow.play")
    host.plugins.disable("example.files")
    assert not host.shortcut_actions["打开父级文件夹"].isEnabled()
    host.plugins.enable("example.files")
    assert host.shortcut_actions["打开父级文件夹"].isEnabled()


def test_reading_direction_changes_navigation_and_pair_layout(host, qtbot, tmp_path):
    paths = [photo(tmp_path / f"{i}.png") for i in range(4)]
    host.open_image(paths[0])
    host.plugins.commands["example.doublepage:toggle"].trigger()
    qtbot.waitUntil(lambda: host.double_page.second.isVisible())
    host.shortcut_actions["切换浏览方向"].trigger()
    qtbot.waitUntil(lambda: host.double_page.second.isVisible())
    assert host.app_preferences["reading_direction"] == "rtl"
    assert host.double_page.second.x() == 0 and host.view.image_item.x() > 0
    host.previous_action.trigger()
    assert host.current_path == paths[2]
    qtbot.waitUntil(lambda: host.double_page.second.isVisible())
    host.next_action.trigger()
    assert host.current_path == paths[0]
    assert host.plugins.preferences["ui"]["application"]["reading_direction"] == "rtl"


@pytest.mark.parametrize("mode", ["list", "tiles"])
def test_local_search_random_and_image_selection(host, qtbot, tmp_path, mode):
    plugin = browser(host)
    folder = tmp_path / "images"
    first = photo(folder / "Alpha.png")
    second = photo(folder / "Beta.png", "blue")
    photo(folder / "Child" / "OnlyNested.png")
    wait_entries(qtbot, plugin, folder, 3)
    plugin.set_view(mode)
    plugin.search.setText("ALPHA")
    root = plugin.views.currentWidget().rootIndex()
    assert plugin.model.rowCount(root) == 1
    assert Path(plugin.model.filePath(plugin.model.index(0, 0, root))) == first
    plugin.search.setText("OnlyNested")
    assert plugin.model.rowCount(root) == 0
    plugin.search.setText("Child")
    child = plugin.model.index(str(folder / "Child"))
    assert child.isValid() and plugin.model.rowCount(child) == 0
    plugin.random_button.click()
    assert plugin.search.text() == ""
    assert plugin.location.text() == str(folder)
    assert (
        Path(plugin.model.filePath(plugin.views.currentWidget().currentIndex())) == folder / "Child"
    )
    assert host.current_path is None
    host.open_image(first)
    qtbot.waitUntil(lambda: Path(plugin.model.filePath(plugin.tree.currentIndex())) == first)
    assert Path(plugin.model.filePath(plugin.tiles.currentIndex())) == first
    plugin.search.setText("Alpha")
    host.next_action.trigger()
    qtbot.waitUntil(lambda: Path(plugin.model.filePath(plugin.tree.currentIndex())) == second)
    assert plugin.search.text() == ""
    assert Path(plugin.model.filePath(plugin.tiles.currentIndex())) == second
    plugin.open_folder(str(folder / "Child"))
    host.previous_action.trigger()
    qtbot.wait(100)
    assert plugin.location.text() == str(folder / "Child")
    assert not plugin.image_timer.isActive()


def test_random_no_folder_is_noop_and_up_preserves_folder_selection(host, qtbot, tmp_path):
    plugin = browser(host)
    path = photo(tmp_path / "parent" / "child" / "1.png")
    wait_entries(qtbot, plugin, path.parent, 1)
    plugin.search.setText("1")
    plugin.random_button.click()
    assert plugin.search.text() == "1"
    assert not plugin.tree.currentIndex().isValid()
    host.open_image(path)
    plugin.go_up()
    qtbot.waitUntil(lambda: Path(plugin.model.filePath(plugin.tree.currentIndex())) == path.parent)
    assert plugin.location.text() == str(path.parent.parent)


def test_scrollbar_preference_applies_to_hidden_and_new_panel_views(host, qtbot):
    plugin = browser(host)
    views = (plugin.tree, plugin.tiles, plugin.favorites, plugin.recent)
    original = [v.verticalScrollBarPolicy() for v in views]
    dialog = ApplicationSettings(host)
    qtbot.addWidget(dialog)
    dialog.editors["panel_scrollbars"].setChecked(False)
    dialog.save()
    assert all(v.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff for v in views)
    assert host.view.verticalScrollBarPolicy() != Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    extra = QScrollArea(plugin.panel)
    extra.setWidget(QWidget())
    extra.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    extra.show()
    qtbot.waitUntil(
        lambda: extra.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    host.plugins.preferences["ui"]["application"]["panel_scrollbars"] = True
    host.apply_preferences()
    assert [v.verticalScrollBarPolicy() for v in views] == original
    assert extra.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    assert extra.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    from PySide6.QtWidgets import QStyle, QStyleOptionSlider

    for view in (*views, extra):
        bar = view.verticalScrollBar()
        option = QStyleOptionSlider()
        bar.initStyleOption(option)
        thumb = bar.style().subControlRect(
            QStyle.ComplexControl.CC_ScrollBar,
            option,
            QStyle.SubControl.SC_ScrollBarSlider,
            bar,
        )
        assert bar.sizeHint().width() == 12
        assert thumb.left() == 4 and thumb.width() == 8


def test_new_settings_persist_through_restart(host, qtbot):
    settings = ApplicationSettings(host)
    qtbot.addWidget(settings)
    settings.editors["panel_scrollbars"].setChecked(False)
    settings.editors["reading_direction"].setCurrentIndex(1)
    settings.save()
    root = host.plugins.root
    host.close()
    restarted = MainWindow(plugin_root=root)
    qtbot.addWidget(restarted)
    assert restarted.app_preferences["reading_direction"] == "rtl"
    assert not restarted.app_preferences["panel_scrollbars"]
    assert (
        browser(restarted).tree.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    restarted.close()


def test_queued_directory_loaded_after_plugin_disable_is_ignored(host, tmp_path):
    plugin = browser(host)
    plugin.open_folder(str(tmp_path))
    host.plugins.disable("example.files")
    # QFileSystemModel can deliver a previously queued worker signal after
    # the plugin context has been revoked. It must not reenter the SDK.
    plugin.directory_loaded(str(tmp_path))
    assert not plugin.active and not plugin.image_timer.isActive()
