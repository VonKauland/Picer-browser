"""Scope skins to host controls, keeping plugin widgets and icons independent."""

import re

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QWidget

from picer.theme import CONTROLS

PLUGIN_STYLE = (
    """
QWidget { background: transparent; color: #F3F3F0; font-size: 13px;
font-family: 'Microsoft YaHei', 'Noto Sans CJK SC', sans-serif; }
QLabel { background: transparent; }
"""
    + CONTROLS
)


def mark_host(widget: QWidget) -> None:
    for child in (widget, *widget.findChildren(QWidget)):
        if child.property("picerHost") is not True:
            child.setProperty("picerHost", True)
            # Dynamic QSS properties set after parenting require an explicit repolish.
            child.style().unpolish(child)
            child.style().polish(child)


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
        if event.type() not in {QEvent.Type.Show, QEvent.Type.ToolTip} or not isinstance(
            obj, QWidget
        ):
            return False
        ancestor = obj
        while ancestor is not None:
            if ancestor.property("pluginSurface"):
                return False
            if ancestor is self.window:
                if event.type() == QEvent.Type.ToolTip:
                    return not self.window.app_preferences["tooltips"]
                if not obj.property("picerHost"):
                    mark_host(obj)
                break
            ancestor = ancestor.parentWidget()
        return False
