"""Render real popups and sliders to catch opaque corners and native white chrome."""

import zipfile
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox

from picer.host_style import mark_host
from picer.settings import ApplicationSettings
from picer.theme import COLORS, STYLE
from picer.ui import RoundedSlider
from picer.window import MainWindow

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def window(qtbot, tmp_path):
    host = MainWindow(load_examples=False, plugin_root=tmp_path / "state")
    qtbot.addWidget(host)
    host.show()
    yield host
    host.plugins.shutdown()


def enable_example(window, tmp_path, directory):
    source = ROOT / "examples" / directory
    archive = tmp_path / f"{directory}.zip"
    with zipfile.ZipFile(archive, "w") as package:
        for file in source.glob("*"):
            if file.is_file():
                package.write(file, file.name)
    plugin_id = window.plugins.install(archive)
    window.plugins.enable(plugin_id)
    return window.plugins.records[plugin_id].instance


def pixel(image, x, y):
    ratio = image.devicePixelRatio()
    return image.pixelColor(round(x * ratio), round(y * ratio))


def assert_clear_corners(widget):
    image = widget.grab().toImage()
    for x, y in (
        (0, 0),
        (widget.width() - 1, 0),
        (0, widget.height() - 1),
        (widget.width() - 1, widget.height() - 1),
    ):
        assert pixel(image, x, y).alpha() == 0
    return image


@pytest.mark.parametrize("level", ["top", "submenu", "slot"])
def test_each_menu_level_has_transparent_corners_and_no_border(window, qtbot, level):
    # Keep QAction wrappers alive while accessing their associated QMenus.
    actions = window.title_bar.menu.actions()
    menu = (
        actions[3].menu()
        if level == "top"
        else window.components.menus["function"]
        if level == "submenu"
        else window.components.slot_submenus[0]
    )
    menu.popup(window.mapToGlobal(QPoint(100, 100)))
    qtbot.waitUntil(menu.isVisible)
    image = assert_clear_corners(menu)
    assert menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert menu.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert pixel(image, menu.width() // 2, 0) == QColor(COLORS["menu"])
    menu.hide()


@pytest.mark.parametrize("owner", ["host", "panel"])
def test_combobox_popup_rounding_selection_and_complete_rows(window, qtbot, tmp_path, owner):
    if owner == "panel":
        plugin = enable_example(window, tmp_path, "file_browser")
        combo = plugin.sort
    else:
        combo = QComboBox(window)
        combo.addItems(["名称", "大小", "类型", "修改时间"])
        combo.resize(240, 40)
        combo.move(100, 100)
        mark_host(combo)
        combo.show()
    for _ in range(2):
        combo.showPopup()
        popup, view = combo.view().window(), combo.view()
        qtbot.waitUntil(popup.isVisible)
        qtbot.wait(20)
        image = assert_clear_corners(popup)
        assert pixel(image, popup.width() // 2, 0) == QColor(COLORS["menu"])
        for index in range(combo.count()):
            rect = view.visualRect(
                view.model().index(index, combo.modelColumn(), combo.rootModelIndex())
            )
            assert view.viewport().rect().contains(rect)
        qtbot.keyClick(view, Qt.Key.Key_Escape)
        assert not popup.isVisible()
    combo.setCurrentIndex(0)
    combo.showPopup()
    qtbot.keyClick(combo.view(), Qt.Key.Key_Down)
    qtbot.keyClick(combo.view(), Qt.Key.Key_Return)
    assert combo.currentIndex() == 1
    assert not combo.view().window().isVisible()
    if owner == "panel":
        assert plugin.current_order()[0] == "size"
        assert plugin.context.get_setting("folder_orders")[plugin.location.text()]["sort"] == "size"


@pytest.mark.parametrize("orientation", [Qt.Orientation.Horizontal, Qt.Orientation.Vertical])
@pytest.mark.parametrize("value", [0, 50, 100])
@pytest.mark.parametrize("inverted", [False, True])
def test_slider_has_no_rectangular_background_and_unclipped_endpoints(
    qtbot, orientation, value, inverted
):
    slider = RoundedSlider(orientation)
    qtbot.addWidget(slider)
    slider.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    slider.setWindowFlag(Qt.WindowType.FramelessWindowHint)
    slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    slider.setStyleSheet(STYLE)
    slider.resize(200, 28) if orientation == Qt.Orientation.Horizontal else slider.resize(28, 200)
    slider.setRange(0, 100)
    slider.setValue(value)
    slider.setInvertedAppearance(inverted)
    slider.show()
    qtbot.waitUntil(slider.isVisible)
    image = assert_clear_corners(slider)
    horizontal = orientation == Qt.Orientation.Horizontal

    def sample(along, across):
        return pixel(image, along, across) if horizontal else pixel(image, across, along)

    # The far end is a rounded 4px cap, not the native full-height sub-page block.
    across = (slider.height() if horizontal else slider.width()) // 2
    minimum_at_start = horizontal != inverted
    center = 7 if (value == 0) == minimum_at_start else 193
    along = 193 if value == 50 or center == 7 else 6
    assert sample(along, across).alpha() > 0
    assert sample(along, across - 4).alpha() == 0
    assert sample(along, across + 4).alpha() == 0
    # The complete circular handle remains inside the widget at both extremes.
    if value != 50:
        assert sample(center, across).alpha() == 255


def test_empty_disabled_slider_still_has_a_thin_complete_track(qtbot):
    slider = RoundedSlider()
    qtbot.addWidget(slider)
    slider.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    slider.setWindowFlag(Qt.WindowType.FramelessWindowHint)
    slider.setStyleSheet(STYLE)
    slider.resize(200, 28)
    slider.setRange(0, 0)
    slider.setEnabled(False)
    slider.show()
    image = assert_clear_corners(slider)
    assert pixel(image, 193, 14).alpha() > 0
    assert pixel(image, 193, 10).alpha() == 0


def test_slider_native_keyboard_and_nontracking_drag(qtbot):
    slider = RoundedSlider()
    qtbot.addWidget(slider)
    slider.setStyleSheet(STYLE)
    slider.resize(220, 28)
    slider.setRange(0, 100)
    slider.setTracking(False)
    slider.show()
    slider.setFocus()
    qtbot.keyClick(slider, Qt.Key.Key_Right)
    assert slider.value() == 1
    qtbot.keyClick(slider, Qt.Key.Key_End)
    assert slider.value() == 100
    qtbot.keyClick(slider, Qt.Key.Key_Home)
    assert slider.value() == 0
    emitted = []
    slider.valueChanged.connect(emitted.append)
    qtbot.mousePress(slider, Qt.MouseButton.LeftButton, pos=QPoint(7, 14))
    qtbot.mouseMove(slider, QPoint(160, 14))
    assert not emitted
    qtbot.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=QPoint(160, 14))
    assert len(emitted) == 1
    assert 65 <= slider.value() <= 85


def test_host_skin_keeps_panel_slider_independent(window, tmp_path, qtbot):
    progress = enable_example(window, tmp_path, "progress_panel")
    enable_example(window, tmp_path, "macos_skin")
    assert window.skin_colors["accent"] == "#3478f6"
    progress.slider.setRange(0, 100)
    progress.slider.setValue(50)
    progress.slider.setEnabled(True)
    qtbot.wait(20)
    image = progress.slider.grab().toImage()
    assert pixel(image, progress.slider.width() // 4, progress.slider.height() // 2) == QColor(
        COLORS["accent"]
    )


def test_settings_dialog_has_clear_outer_corners(window, qtbot):
    settings = ApplicationSettings(window)
    qtbot.addWidget(settings)
    settings.show()
    qtbot.waitUntil(settings.isVisible)
    assert_clear_corners(settings)


@pytest.mark.parametrize("orientation", [Qt.Orientation.Horizontal, Qt.Orientation.Vertical])
@pytest.mark.parametrize("inverted", [False, True])
@pytest.mark.parametrize("rtl", [False, True])
def test_absolute_click_seek_respects_direction_and_keeps_native_drag(
    qtbot, orientation, inverted, rtl
):
    from PySide6.QtWidgets import QStyleOptionSlider

    slider = RoundedSlider(orientation, jump_on_click=True)
    qtbot.addWidget(slider)
    slider.setStyleSheet(STYLE)
    slider.resize(260, 30) if orientation == Qt.Orientation.Horizontal else slider.resize(30, 260)
    slider.setRange(5, 105)
    slider.setInvertedAppearance(inverted)
    slider.setLayoutDirection(
        Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight
    )
    slider.show()
    option = QStyleOptionSlider()
    slider.initStyleOption(option)
    option.sliderPosition = option.sliderValue = 85
    point = slider.handle_rect(option).center().toPoint()
    emitted = []
    slider.valueChanged.connect(emitted.append)
    qtbot.mouseClick(slider, Qt.MouseButton.LeftButton, pos=point)
    assert abs(slider.value() - 85) <= 1
    assert len(emitted) == 1  # No intermediate page-step value.
    slider.setTracking(False)
    option.sliderPosition = option.sliderValue = 45
    begin = slider.handle_rect(option).center().toPoint()
    option.sliderPosition = option.sliderValue = 95
    end = slider.handle_rect(option).center().toPoint()
    previous = slider.value()
    qtbot.mousePress(slider, Qt.MouseButton.LeftButton, pos=begin)
    qtbot.mouseMove(slider, end)
    assert slider.value() == previous
    qtbot.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=end)
    assert abs(slider.value() - 95) <= 1
