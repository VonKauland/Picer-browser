"""Host-owned component menus and the five persistent quick-action slots."""

from PySide6.QtGui import QActionGroup, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QMessageBox

from picer.host_style import mark_host
from picer.plugins.api import PluginError

TYPES = {"skin": "皮肤", "function": "功能", "panel": "面板"}
DEFAULT_SLOTS = [
    "picer.transforms:rotate",
    "picer.mirror:mirror",
    "picer.grayscale:grayscale",
    "",
    "",
]


def function_icon(label: str, color: str) -> QIcon:
    """Small, consistent outline icons; text stays in the tooltip and menu."""
    pixmap = QPixmap(40, 40)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(color), 2.4))
    if "旋转" in label:
        painter.drawArc(8, 8, 24, 24, 35 * 16, 285 * 16)
        painter.drawLine(31, 6, 31, 15)
        painter.drawLine(31, 15, 23, 15)
    elif "翻转" in label:
        painter.drawLine(20, 7, 20, 33)
        painter.drawLine(8, 13, 8, 27)
        painter.drawLine(8, 13, 15, 20)
        painter.drawLine(15, 20, 8, 27)
        painter.drawLine(32, 13, 32, 27)
        painter.drawLine(32, 13, 25, 20)
        painter.drawLine(25, 20, 32, 27)
    elif "灰度" in label or "负片" in label:
        painter.drawEllipse(8, 8, 24, 24)
        painter.setBrush(QColor(color))
        painter.drawPie(8, 8, 24, 24, 90 * 16, 180 * 16)
    elif "双页" in label:
        for x in (5, 22):
            painter.drawRoundedRect(x, 8, 13, 24, 2, 2)
            painter.drawLine(x + 4, 15, x + 9, 15)
            painter.drawLine(x + 4, 20, x + 9, 20)
    elif "触控" in label:
        painter.drawArc(9, 3, 18, 18, 0, 180 * 16)
        painter.drawRoundedRect(15, 10, 6, 21, 3, 3)
        painter.drawLine(21, 20, 30, 24)
        painter.drawLine(30, 24, 29, 34)
        painter.drawLine(29, 34, 17, 34)
        painter.drawLine(17, 34, 9, 24)
        painter.drawLine(9, 24, 15, 24)
    else:
        painter.drawRoundedRect(9, 9, 22, 22, 5, 5)
        painter.drawLine(20, 14, 20, 26)
        painter.drawLine(14, 20, 26, 20)
    painter.end()
    return QIcon(pixmap)


def component_icon(manager, plugin_id: str) -> QIcon:
    """Prefer a plugin's own icon, including for unassigned quick-slot actions."""
    for action in manager.commands.values():
        if action.property("plugin_id") == plugin_id and not action.icon().isNull():
            return action.icon()
    return function_icon(manager.records[plugin_id].manifest.name, "#e6e9ef")


class ComponentUI:
    def __init__(self, window, menu) -> None:
        self.window = window
        self.manager = window.plugins
        self.menus = {key: menu.addMenu(value) for key, value in TYPES.items()}
        self.slots_menu = menu.addMenu("快捷栏位")
        for child in (*self.menus.values(), self.slots_menu):
            mark_host(child)
        self.slot_submenus = []
        for index, button in enumerate(window.title_bar.quick_slots):
            button.customContextMenuRequested.connect(
                lambda point, slot=index, widget=button: self.show_slot_menu(
                    slot, widget.mapToGlobal(point)
                )
            )
        self.manager.changed.connect(self.refresh)
        self.refresh()

    def operation(self, callback) -> None:
        try:
            callback()
        except PluginError as error:
            QMessageBox.warning(self.window, "组件操作未完成", str(error))
        self.refresh()

    def toggle(self, plugin_id: str, checked: bool) -> None:
        self.operation(
            lambda: self.manager.enable(plugin_id) if checked else self.manager.disable(plugin_id)
        )

    def refresh(self) -> None:
        self.refresh_function_icons()
        if hasattr(self, "skin_group"):
            self.skin_group.deleteLater()
        for menu in self.menus.values():
            menu.clear()
        self.skin_group = QActionGroup(self.menus["skin"])
        self.skin_group.setExclusive(True)
        default = self.menus["skin"].addAction("默认暗黑")
        default.setCheckable(True)
        self.skin_group.addAction(default)
        skins = [
            key
            for key, record in self.manager.records.items()
            if record.manifest.type == "skin" and record.state == "enabled"
        ]
        default.setChecked(not skins)
        default.triggered.connect(lambda: self.operation(self.default_skin))
        for plugin_id, record in self.manager.records.items():
            menu = self.menus[record.manifest.type]
            action = menu.addAction(record.manifest.name)
            action.setCheckable(True)
            action.setChecked(record.state == "enabled")
            action.setEnabled(record.state != "incompatible")
            action.setToolTip(record.error or record.manifest.description)
            if record.manifest.type == "function":
                action.setIcon(component_icon(self.manager, plugin_id))
            if record.manifest.type == "skin":
                self.skin_group.addAction(action)
                action.triggered.connect(
                    lambda _, key=plugin_id: self.operation(lambda: self.manager.enable(key))
                )
            else:
                action.triggered.connect(lambda checked, key=plugin_id: self.toggle(key, checked))
        self.refresh_slots()

    def default_skin(self) -> None:
        for plugin_id, record in list(self.manager.records.items()):
            if record.manifest.type == "skin" and record.state == "enabled":
                self.manager.disable(plugin_id)

    def assignments(self) -> list[str]:
        values = self.manager.preferences["ui"].get("quick_slots", DEFAULT_SLOTS)
        if (
            not isinstance(values, list)
            or len(values) != 5
            or any(not isinstance(value, str) for value in values)
        ):
            return list(DEFAULT_SLOTS)
        return values.copy()

    def assign(self, index: int, key: str) -> None:
        values = self.assignments()
        values[index] = key
        self.manager.preferences["ui"]["quick_slots"] = values
        self.manager._save()
        self.refresh_slots()

    def show_slot_menu(self, index, position) -> None:
        menu = self.slot_menu(index)
        try:
            menu.exec(position)
        finally:
            menu.deleteLater()

    def slot_menu(self, index: int, parent=None) -> QMenu:
        menu = QMenu(f"栏位 {index + 1}", parent or self.window)
        current = self.assignments()[index]
        clear = menu.addAction("清空栏位")
        clear.triggered.connect(lambda: self.assign(index, ""))
        menu.addSeparator()
        for key, command in self.manager.commands.items():
            action = menu.addAction(command.text())
            action.setIcon(command.icon())
            action.setCheckable(True)
            action.setChecked(key == current)
            action.triggered.connect(lambda _, value=key: self.assign(index, value))
        mark_host(menu)
        return menu

    def refresh_slots(self) -> None:
        self.refresh_function_icons()
        self.slots_menu.clear()
        for menu in self.slot_submenus:
            menu.deleteLater()
        self.slot_submenus.clear()
        assignments = self.assignments()
        for index, (button, key) in enumerate(
            zip(self.window.title_bar.quick_slots, assignments, strict=True)
        ):
            menu = self.slot_menu(index, self.slots_menu)
            self.slot_submenus.append(menu)
            self.slots_menu.addMenu(menu)
            action = self.manager.commands.get(key)
            if action is not None:
                button.setDefaultAction(action)
                button.setToolTip(f"{action.text()} · 右键配置栏位 {index + 1}")
            else:
                button.setDefaultAction(None)
                button.setEnabled(True)
                button.setIcon(QIcon())
                button.setText("·")
                button.setToolTip(
                    f"栏位 {index + 1} · 右键选择功能" + ("（原功能已停用）" if key else "")
                )
        self.window.title_bar.arrange()

    def refresh_function_icons(self) -> None:
        for key, command in self.manager.commands.items():
            if command.property("picerDefaultIcon") and key.startswith("picer."):
                command.setIcon(function_icon(command.text(), self.window.skin_colors["text"]))
