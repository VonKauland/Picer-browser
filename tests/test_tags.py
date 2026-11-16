"""Durable tag assignments, opt-in lifecycle and bottom-anchored library behavior."""

import pytest
from PIL import Image
from PySide6.QtCore import Qt

from examples.tag_panel.store import TagStore
from picer.plugins.api import PluginError
from picer.window import MainWindow


def test_tag_store_durable_distinct_targets_validation_and_cascade(tmp_path):
    store = TagStore(tmp_path / "tags.sqlite3")
    tag = store.save("旅行", "#488fff")
    hidden = store.save("Private", "#A271F1", False)
    image, folder = tmp_path / "photo.jpg", tmp_path
    store.assign(image, "image", tag, True)
    store.assign(folder, "folder", hidden, True)
    with pytest.raises(ValueError):
        store.save("private", "#123456")
    for name, color in (("", "#123456"), ("a" * 65, "#123456"), ("name", "red")):
        with pytest.raises(ValueError):
            store.save(name, color)
    store.save("假日", "#FF9D42", False, tag)
    restarted = TagStore(store.path)
    assert restarted.assigned(image, "image") == {tag}
    assert restarted.assigned(folder, "folder") == {hidden}
    assert restarted.assigned(image, "folder") == set()
    rows = {row["id"]: row for row in restarted.tags()}
    assert rows[tag]["name"] == "假日" and rows[tag]["color"] == "#FF9D42"
    assert not rows[tag]["visible"]
    restarted.delete(tag)
    assert restarted.assigned(image, "image") == set()
    assert restarted.assigned(folder, "folder") == {hidden}


@pytest.fixture
def host(qtbot, tmp_path):
    window = MainWindow(plugin_root=tmp_path / "state")
    qtbot.addWidget(window)
    path = tmp_path / "photo.png"
    Image.new("RGB", (90, 60), "blue").save(path)
    window.show()
    window.open_image(path)
    yield window
    window.close()


def enable(host):
    assert host.plugins.records["example.tags"].state == "disabled"
    host.plugins.enable("example.tags")
    record = host.plugins.records["example.tags"]
    assert record.state == "enabled", record.error
    return record.instance


def test_tag_panel_default_right_visibility_folder_scope_and_durable_data(host, qtbot):
    panel = enable(host)
    context = host.plugins.records["example.tags"].context
    assert host.dockWidgetArea(panel.dock) == Qt.DockWidgetArea.RightDockWidgetArea
    assert not context.data_directory().is_relative_to(host.paths_layout.cache)
    tag = panel.store.save("风景", "#488FFF")
    hidden = panel.store.save("私藏", "#A271F1", False)
    path = host.current_path
    panel.store.assign(path, "image", tag, True)
    panel.store.assign(path, "image", hidden, True)
    panel.render()
    assert panel.chips.count() == 1 and panel.library.count() == 1
    panel.show_hidden.setChecked(True)
    assert panel.chips.count() == 2 and panel.library.count() == 2
    panel.selected_tag = tag
    panel.set_color("#FF9D42")
    assert panel.tag(tag)["color"] == "#FF9D42"
    panel.toggle_visibility(tag)
    assert not panel.tag(tag)["visible"]
    panel.show_hidden.setChecked(False)
    assert panel.chips.count() == 0 and panel.store.assigned(path, "image") == {tag, hidden}
    panel.scope.button(1).click()
    assert panel.target() == (path.parent, "folder")
    assert panel.chips.count() == 0
    panel.store.assign(path.parent, "folder", tag, True)
    panel.library_button.setChecked(True)
    panel.show_hidden.setChecked(True)
    panel.render()
    host.plugins.disable("example.tags")
    with pytest.raises(PluginError):
        context.data_directory()
    assert panel.store.assigned(path, "image") == {tag, hidden}
    restored = enable(host)
    assert restored.show_hidden.isChecked() and restored.library_button.isChecked()
    assert restored.store.assigned(path.parent, "folder") == {tag}
    assert restored.chips.count() == 2


def test_library_opens_upward_without_moving_footer_or_target(host, qtbot):
    panel = enable(host)
    controller = host.panel_hovers.controllers["example.tags"]
    controller.pin()
    panel.dock.raise_()
    qtbot.waitUntil(lambda: panel.panel.isVisible())
    qtbot.wait(30)
    before = panel.target_name.geometry()
    footer_y = panel.footer.y()
    panel.library_button.click()
    qtbot.waitUntil(panel.drawer.isVisible)
    assert panel.drawer.geometry().bottom() < panel.footer.y()
    assert panel.drawer.y() >= 0
    assert panel.footer.y() == footer_y and panel.target_name.geometry() == before
    host.resize(1000, 600)
    qtbot.wait(30)
    assert panel.drawer.geometry().bottom() < panel.footer.y()
    assert panel.drawer.width() <= panel.panel.width() - 24
    panel.library_button.click()
    assert panel.drawer.isHidden() and panel.add.isVisible()


def test_library_clicks_assign_remove_hide_and_change_the_selected_color(host, qtbot):
    panel = enable(host)
    controller = host.panel_hovers.controllers["example.tags"]
    controller.pin()
    panel.dock.raise_()
    first = panel.store.save("A", "#488FFF")
    second = panel.store.save("B", "#A271F1")
    panel.render()
    panel.library_button.click()
    qtbot.wait(30)
    rect = panel.library.visualItemRect(panel.library.item(0))
    qtbot.mouseClick(
        panel.library.viewport(),
        Qt.MouseButton.LeftButton,
        pos=rect.topLeft() + type(rect.center())(20, rect.height() // 2),
    )
    assert panel.store.assigned(host.current_path, "image") == {first}
    assert panel.chips.count() == 1
    rect = panel.chips.visualItemRect(panel.chips.item(0))
    qtbot.mouseClick(
        panel.chips.viewport(),
        Qt.MouseButton.LeftButton,
        pos=type(rect.center())(rect.right() - 8, rect.center().y()),
    )
    assert not panel.store.assigned(host.current_path, "image")
    panel.library.setCurrentRow(1)
    panel.color_buttons[1].click()
    assert panel.tag(second)["color"] == "#FF9D42"
    assert panel.tag(first)["color"] == "#488FFF"
    panel.search.setText("A")
    assert panel.selected_tag == first
    rect = panel.library.visualItemRect(panel.library.item(0))
    qtbot.mouseClick(
        panel.library.viewport(),
        Qt.MouseButton.LeftButton,
        pos=type(rect.center())(rect.right() - 50, rect.center().y()),
    )
    assert not panel.tag(first)["visible"] and panel.library.count() == 0
    assert all(not button.isEnabled() for button in panel.color_buttons)
    panel.show_hidden.setChecked(True)
    assert panel.library.count() == 1 and panel.selected_tag == first
