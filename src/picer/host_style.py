"""Scope skins to host controls, keeping plugin widgets and icons independent."""

import re

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QWidget

PLUGIN_STYLE = """
QWidget { background: transparent; color: #e6e9ef; font-size: 13px;
font-family: 'Microsoft YaHei', 'Noto Sans CJK SC', sans-serif; }
QLabel { background: transparent; }
QPushButton, QToolButton, QComboBox, QSpinBox, QLineEdit {
 background: rgba(255,255,255,18); border: 1px solid #414a58; border-radius: 5px; padding: 4px; }
QPushButton:hover, QToolButton:hover { background: rgba(255,255,255,32); }
QTreeView, QListWidget, QTextEdit, QScrollArea { background: transparent; border: none; }
QTreeView::item:selected, QListWidget::item:selected { background: #3c5677; }
QHeaderView::section { background: rgba(255,255,255,18); color: #e6e9ef;
border: none; padding: 4px; }
QGroupBox { border: 1px solid #414a58; border-radius: 5px; margin-top: 14px; padding-top: 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; }
QScrollBar { background: transparent; width: 9px; height: 9px; }
QScrollBar::handle { background: #586579; border-radius: 4px; min-height: 20px; min-width: 20px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
"""


def mark_host(widget: QWidget) -> None:
    for child in (widget, *widget.findChildren(QWidget)):
        child.setProperty("picerHost", True)


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
        if event.type() != QEvent.Type.Show or not isinstance(obj, QWidget):
            return False
        ancestor = obj
        while ancestor is not None:
            if ancestor.property("pluginSurface"):
                return False
            if ancestor is self.window:
                if not obj.property("picerHost"):
                    mark_host(obj)
                    obj.style().unpolish(obj)
                    obj.style().polish(obj)
                break
            ancestor = ancestor.parentWidget()
        return False
