"""Input settings geometry, tab independence and packaged controller artwork."""

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QScrollArea

from picer.gamepad_editor import CANVAS, CENTERS
from picer.settings import ApplicationSettings
from picer.window import MainWindow


@pytest.fixture
def settings(qtbot, tmp_path):
    window = MainWindow(load_examples=False, plugin_root=tmp_path / "state")
    qtbot.addWidget(window)
    window.show()
    dialog = ApplicationSettings(window)
    qtbot.addWidget(dialog)
    dialog.navigation.setCurrentRow(4)
    dialog.show()
    yield dialog
    dialog.reject()
    window.close()


def contained(widget, ancestor):
    top = widget.mapTo(ancestor, widget.rect().topLeft())
    bottom = widget.mapTo(ancestor, widget.rect().bottomRight())
    return ancestor.rect().contains(top) and ancestor.rect().contains(bottom)


@pytest.mark.parametrize("size", [(760, 500), (1000, 780), (1280, 900)])
@pytest.mark.parametrize("font_px", [13, 18])
def test_all_tabs_keep_binding_controls_inside_dialog(settings, qtbot, size, font_px):
    settings.setStyleSheet(f"QWidget {{ font-size: {font_px}px; }}")
    settings.resize(*size)
    editor = settings.binding_editor
    assert not isinstance(settings.pages.currentWidget(), QScrollArea)
    heights = []
    for tab in (3, 0, 1, 2, 3, 0):
        editor.tabs.setCurrentIndex(tab)
        qtbot.wait(40)
        heights.append(editor.height())
        assert contained(editor, settings.pages.currentWidget())
        assert contained(editor.tabs, settings)
        assert editor.tabs.currentWidget().viewport().height() >= 40
        for control in (editor.bindings, editor.add_button, editor.remove_button):
            assert contained(control, settings), (size, font_px, tab, control.geometry())
        assert editor.bindings.y() + editor.bindings.height() <= editor.add_button.y()
        viewport = editor.tabs.currentWidget()
        assert viewport.horizontalScrollBar().maximum() == 0
    assert max(heights) - min(heights) <= 2  # No reflow caused by hidden-page hints.
    field = editor.keyboard_stack.currentWidget()
    assert field.height() <= 65
    assert editor.keyboard_add.height() <= 65
    assert abs(field.height() - editor.keyboard_add.height()) <= 8


def test_keyboard_fields_are_compact_and_form_scrolls_only_when_needed(settings, qtbot):
    settings.resize(1000, 780)
    editor = settings.binding_editor
    editor.tabs.setCurrentIndex(0)
    qtbot.wait(40)
    viewport = editor.tabs.currentWidget()
    assert viewport.verticalScrollBar().maximum() == 0
    primary = editor.keyboard_stack.currentWidget()
    assert primary.parentWidget().height() < 70
    gap = (
        editor.keyboard_add.mapTo(viewport.widget(), editor.keyboard_add.rect().topLeft()).y()
        - primary.mapTo(viewport.widget(), primary.rect().bottomLeft()).y()
    )
    assert gap < 90
    settings.resize(760, 500)
    editor.tabs.setCurrentIndex(3)
    qtbot.wait(50)
    assert editor.tabs.currentWidget().verticalScrollBar().maximum() > 0
    assert contained(editor.add_button, settings)


def test_artwork_transparency_aspect_and_highlight_hit_alignment(settings, qtbot):
    settings.resize(1120, 820)
    editor = settings.binding_editor
    editor.tabs.setCurrentIndex(3)
    qtbot.wait(40)
    page, diagram = editor.gamepad_page, editor.gamepad_page.diagram
    assert not diagram.artwork.isNull()
    image = diagram.artwork.toImage()
    assert image.hasAlphaChannel() and image.pixelColor(0, 0).alpha() == 0
    assert (image.width(), image.height()) == CANVAS
    for size in [(300, 200), (480, 260), (230, 250)]:
        diagram.resize(*size)
        scale, left, top = diagram.transform()
        assert left >= 0 and top >= 0
        for key, (x, y) in CENTERS.items():
            assert diagram.hit_test(QPointF(left + x * scale, top + y * scale)) == key
    # Restore the layout before clicking, then select a visibly exposed face button.
    settings.resize(1121, 821)
    qtbot.wait(40)
    scale, left, top = diagram.transform()
    x, y = CENTERS["Guide"]
    point = QPointF(left + x * scale, top + y * scale)
    before = diagram.grab().toImage()
    qtbot.mouseClick(diagram, Qt.MouseButton.LeftButton, pos=point.toPoint())
    assert page.button.currentData() == "Guide"
    page.set_value("RT+A")
    assert "RT+A" in page.selection.text()
    assert before != diagram.grab().toImage()
