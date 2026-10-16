"""Revocable, noninteractive AF outlines in image-local coordinates."""

import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsPathItem

from picer.theme import COLORS


def oriented_point(x, y, orientation):
    return {
        1: (x, y),
        2: (1 - x, y),
        3: (1 - x, 1 - y),
        4: (x, 1 - y),
        5: (y, x),
        6: (1 - y, x),
        7: (1 - y, 1 - x),
        8: (y, 1 - x),
    }.get(orientation, (x, y))


class FocusPoints:
    def __init__(self, host):
        self.host, self.owners = host, {}
        self.item = QGraphicsPathItem(host.view.image_item)
        self.item.setZValue(10)
        self.item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.item.setAcceptHoverEvents(False)
        self.item.hide()

    def set(self, owner, data):
        if data is None:
            self.owners.pop(owner, None)
        else:
            boxes = data.get("boxes", [])
            orientation = data.get("orientation", 1)
            if not isinstance(boxes, (tuple, list)) or len(boxes) > 512:
                raise ValueError("Invalid focus-point data")
            valid = []
            for box in boxes:
                if (
                    not isinstance(box, (tuple, list))
                    or len(box) != 4
                    or not all(isinstance(v, (float, int)) and math.isfinite(v) for v in box)
                ):
                    raise ValueError("Invalid focus-point rectangle")
                x, y, w, h = box
                if not (
                    0 <= x <= 1
                    and 0 <= y <= 1
                    and 0 < w <= 1
                    and 0 < h <= 1
                    and x + w <= 1.000001
                    and y + h <= 1.000001
                ):
                    raise ValueError("Focus point outside the source image")
                valid.append(tuple(box))
            if type(orientation) is not int or not 1 <= orientation <= 8:
                raise ValueError("Invalid image orientation")
            self.owners[owner] = (self.host.current_path, valid, orientation)
        self.refresh()

    def remove(self, owner):
        self.owners.pop(owner, None)
        self.refresh()

    def clear(self):
        self.owners.clear()
        self.item.setPath(QPainterPath())
        self.item.hide()

    def refresh(self):
        host, path = self.host, QPainterPath()
        image = host.view.image_item.pixmap()
        if host.image_edited or image.isNull():
            self.item.hide()
            return
        for current, boxes, orientation in self.owners.values():
            if current != host.current_path:
                continue
            if not host.app_preferences["auto_orient"]:
                orientation = 1
            for x, y, w, h in boxes:
                points = [
                    oriented_point(a, b, orientation)
                    for a, b in (
                        (x, y),
                        (x + w, y),
                        (x + w, y + h),
                        (x, y + h),
                    )
                ]
                for _ in range(host.image_rotation // 90):
                    points = [(1 - b, a) for a, b in points]
                xs, ys = [p[0] for p in points], [p[1] for p in points]
                path.addRect(
                    QRectF(
                        min(xs) * image.width(),
                        min(ys) * image.height(),
                        (max(xs) - min(xs)) * image.width(),
                        (max(ys) - min(ys)) * image.height(),
                    )
                )
        pen = QPen(QColor(host.app_preferences["accent_color"] or COLORS["accent"]), 1.5)
        pen.setCosmetic(True)
        self.item.setPen(pen)
        self.item.setPath(path)
        self.item.setVisible(not path.isEmpty())
