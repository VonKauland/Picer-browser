"""Compact filter popup with live faceted counts and no explanatory cards."""

import copy
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from picer.annotations import CATEGORIES
from picer.host_style import PLUGIN_STYLE
from picer.ui import Toggle, colors_for


def matches(mark, state, *, rating=True, color=True):
    value = mark.get("rating") or 0
    threshold = state["rating"]
    if rating and threshold is not None:
        if threshold == 0:
            if value != 0:
                return False
        elif state["compare"] == "eq" and value != threshold:
            return False
        elif state["compare"] == "ge" and value < threshold:
            return False
        elif state["compare"] == "le" and value > threshold:
            return False
    return not color or not state["color"] or mark.get("color") == state["color"]


def star_path(center, radius=5):
    path = QPainterPath()
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        r = radius if i % 2 == 0 else radius * 0.46
        p = center + QPointF(math.cos(a) * r, math.sin(a) * r)
        path.moveTo(p) if i == 0 else path.lineTo(p)
    path.closeSubpath()
    return path


class RatingRow(QAbstractButton):
    def __init__(self, popup, value):
        super().__init__(popup)
        self.popup, self.value = popup, value
        self.setFixedHeight(27)
        self.clicked.connect(lambda: self.select(self.value))
        self.setAccessibleName("尚未评分" if value == 0 else f"{value} 星；末颗星左半侧可选半星")
        self.setToolTip("点击最后一颗星的左半侧选择半星" if value else "尚未评分")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def actual_value(self):
        selected = self.popup.state["rating"]
        return selected if selected and math.ceil(selected) == self.value else self.value

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = colors_for(self)
        value = self.actual_value()
        selected = self.popup.state["rating"] == value
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors["hover"]))
            painter.drawRoundedRect(QRectF(self.rect()), 5, 5)
        painter.setPen(QColor(colors["accent"]))
        if selected:
            painter.drawText(QRectF(3, 0, 17, 27), Qt.AlignmentFlag.AlignCenter, "✓")
        painter.setPen(QColor(colors["text"]))
        if not self.value:
            painter.drawText(QRectF(25, 0, 120, 27), Qt.AlignmentFlag.AlignVCenter, "尚未评分")
        else:
            for i in range(5):
                x = 29 + i * 19
                path = star_path(QPointF(x + 6, 13.5))
                painter.setPen(QPen(QColor(colors["muted"]), 0.8))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(path)
                painter.save()
                painter.setClipRect(QRectF(x, 6, 12 * max(0, min(1, value - i)), 15))
                painter.fillPath(path, QColor(colors["text"]))
                painter.restore()
        count = self.popup.rating_counts.get(value, 0)
        painter.setPen(QColor(colors["muted"]))
        painter.drawText(
            QRectF(self.width() - 47, 0, 40, 27),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            str(count),
        )

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.setDown(False)
        if not self.rect().contains(event.position().toPoint()):
            return
        value = self.value
        last_left = 29 + (self.value - 1) * 19
        if self.value and last_left <= event.position().x() < last_left + 6:
            value -= 0.5
        self.select(value)
        event.accept()

    def select(self, value):
        self.popup.state["rating"] = None if self.popup.state["rating"] == value else value
        self.popup.refresh_counts()


class ColorChoice(QAbstractButton):
    def __init__(self, popup, category):
        super().__init__(popup)
        self.popup, self.category = popup, category
        self.setFixedSize(33, 49)
        self.setAccessibleName(category[1])
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self.choose)

    def choose(self):
        key = self.category[0]
        self.popup.state["color"] = "" if self.popup.state["color"] == key else key
        self.popup.refresh_counts()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.width() / 2, 13)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.category[2]))
        painter.drawEllipse(center, 6, 6)
        if self.popup.state["color"] == self.category[0]:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(colors_for(self)["text"]), 1))
            painter.drawEllipse(center, 9, 9)
        painter.setPen(QColor(colors_for(self)["text"]))
        painter.drawText(
            QRectF(0, 28, self.width(), 20),
            Qt.AlignmentFlag.AlignCenter,
            str(self.popup.color_counts.get(self.category[0], 0)),
        )


class FilterPopup(QWidget):
    def __init__(self, owner):
        super().__init__(owner.panel, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.owner = owner
        self.state = copy.deepcopy(owner.filters)
        self.setProperty("pluginSurface", True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(PLUGIN_STYLE)
        self.setFixedWidth(248)
        self.rating_counts, self.color_counts = {}, {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(7)
        scope = QHBoxLayout()
        scope.addWidget(QLabel("仅本文件夹"), 1)
        self.scope = Toggle()
        self.scope.setChecked(self.state["local"])
        scope.addWidget(self.scope)
        layout.addLayout(scope)
        self.scope.toggled.connect(self.change_scope)
        layout.addWidget(QLabel("星级评分"))
        self.ratings = [RatingRow(self, n) for n in range(6)]
        for row in self.ratings:
            layout.addWidget(row)
        self.comparators = []
        for key, label in (("ge", "大于等于"), ("le", "小于等于"), ("eq", "等于")):
            button = QPushButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda _, key=key: self.compare(key))
            self.comparators.append((key, button))
            layout.addWidget(button)
        layout.addWidget(QLabel("颜色分类"))
        colors = QHBoxLayout()
        colors.setSpacing(3)
        self.colors = [ColorChoice(self, category) for category in CATEGORIES]
        for button in self.colors:
            colors.addWidget(button)
        layout.addLayout(colors)
        actions = QHBoxLayout()
        clear = QPushButton("清除筛选")
        clear.clicked.connect(self.clear)
        apply = QPushButton("应用")
        apply.setObjectName("primaryButton")
        apply.clicked.connect(self.apply)
        actions.addWidget(clear)
        actions.addWidget(apply)
        layout.addLayout(actions)
        self.refresh_counts()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(colors_for(self)["accent"]).darker(230), 1))
        painter.setBrush(QColor(colors_for(self)["menu"]))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)

    def change_scope(self, local):
        self.state["local"] = local
        self.owner.request_scope(self)

    def compare(self, key):
        self.state["compare"] = key
        self.refresh_counts()

    def clear(self):
        self.state.update(rating=None, color="", compare="eq")
        self.refresh_counts()

    def refresh_counts(self):
        notes = self.owner.notes
        rows = self.owner.count_paths.get(self.state["local"], [])
        name = self.owner.search.text().casefold()
        self.rating_counts = {n / 2: 0 for n in range(11)}
        self.color_counts = {key: 0 for key, _, _ in CATEGORIES}
        for path in rows:
            if name not in path.name.casefold():
                continue
            mark = notes.get(str(path), {})
            if matches(mark, self.state, rating=False):
                value = mark.get("rating") or 0
                if value in self.rating_counts:
                    self.rating_counts[value] += 1
            if matches(mark, self.state, color=False) and mark.get("color") in self.color_counts:
                self.color_counts[mark["color"]] += 1
        for key, button in self.comparators:
            button.setChecked(key == self.state["compare"])
            label = {"eq": "等于", "ge": "大于等于", "le": "小于等于"}[key]
            button.setText(("✓  " if button.isChecked() else "    ") + label)
            background = colors_for(self)["hover"] if button.isChecked() else "transparent"
            button.setStyleSheet(f"background: {background}; text-align: left; padding: 6px 10px;")
        for widget in self.ratings + self.colors:
            widget.update()

    def apply(self):
        self.owner.filters = self.state.copy()
        self.owner.context.set_setting("filters", self.owner.filters)
        self.owner.schedule()
        self.close()

    def closeEvent(self, event):
        self.owner.popup = None
        self.deleteLater()
        super().closeEvent(event)

    def hideEvent(self, event):
        if self.owner.popup is self:
            self.owner.popup = None
        self.deleteLater()
        super().hideEvent(event)
