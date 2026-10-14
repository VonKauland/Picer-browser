"""Scope skins to host controls, keeping plugin widgets and icons independent."""

import re

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QComboBox, QFrame, QMenu, QStyledItemDelegate, QWidget

from picer.theme import CONTROLS

PLUGIN_STYLE = (
    """
QWidget { background: transparent; color: #F3F3F0; font-size: 13px;
font-family: 'Microsoft YaHei', 'Noto Sans CJK SC', sans-serif; }
QLabel { background: transparent; }
"""
    + CONTROLS
)


def prepare_popup(widget):
    """Configure alpha before a native popup window is created or shown."""
    if isinstance(widget, QMenu) or widget.metaObject().className() == "QComboBoxPrivateContainer":
        widget.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        widget.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint)
        widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        widget.setAutoFillBackground(False)
        if not isinstance(widget, QMenu):
            widget.setObjectName("picerComboPopup")
            widget.setFrameShape(QFrame.Shape.NoFrame)
            widget.setLineWidth(0)
            widget.setMidLineWidth(0)


def mark_host(widget: QWidget) -> None:
    for child in (widget, *widget.findChildren(QWidget)):
        prepare_popup(child)
        if child.property("picerHost") is not True:
            child.setProperty("picerHost", True)
            # Dynamic QSS properties set after parenting require an explicit repolish.
            child.style().unpolish(child)
            child.style().polish(child)
        if isinstance(child, QComboBox):
            # Qt measures the first popup before its Show event. Style its lazy
            # view now so row sizes and rounded selection geometry are measured once.
            view = child.view()
            if not isinstance(view.itemDelegate(), QStyledItemDelegate):
                view.setItemDelegate(QStyledItemDelegate(view))
            mark_host(view.window())


def scope_style(style: str) -> str:
    """Append a host marker to each final QSS selector, including subcontrols."""
    style = re.sub(r"/\*.*?\*/", "", style, flags=re.DOTALL)

    def selector(match):
        selectors = []
        for value in match[1].split(","):
            value = value.strip()
            prefix, _, target = value.rpartition(" ")
            offset = target.find(":")
            if offset < 0:
                offset = len(target)
            scoped = target[:offset] + '[picerHost="true"]' + target[offset:]
            selectors.append((prefix + " " if prefix else "") + scoped)
        return ", ".join(selectors) + " {"

    return re.sub(r"([^{}]+)\{", selector, style)


class HostStyleFilter(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window

    def eventFilter(self, obj, event):
        if event.type() not in {
            QEvent.Type.Polish,
            QEvent.Type.Show,
            QEvent.Type.ToolTip,
        } or not isinstance(obj, QWidget):
            return False
        ancestor = obj
        while ancestor is not None:
            if ancestor.property("pluginSurface"):
                if event.type() == QEvent.Type.Polish:
                    prepare_popup(obj)
                return False
            if ancestor is self.window:
                if event.type() == QEvent.Type.ToolTip:
                    return not self.window.app_preferences["tooltips"]
                if not obj.property("picerHost"):
                    mark_host(obj)
                break
            ancestor = ancestor.parentWidget()
        return False
