"""A bottom-anchored, wrapping two-column EXIF table with upward expansion."""

from PySide6.QtCore import QEasingCurve, QEvent, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .labels import DetailLabel


class ExifView(QWidget):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        panel.installEventFilter(self)
        self.expanded = False
        self.fraction = 0.0
        self.data = {}
        self.layout_row = QVBoxLayout(self)
        self.layout_row.setContentsMargins(0, 0, 0, 10)
        self.layout_row.setSpacing(6)
        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.rows = QVBoxLayout(self.content)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(12)
        self.scroll.setWidget(self.content)
        self.layout_row.addWidget(self.scroll, 1)
        self.button = QPushButton("展开详细信息 ▴")
        self.button.setStyleSheet(
            "QPushButton { padding: 4px 12px; min-height: 0; border-radius: 14px; }"
        )
        self.button.setFixedHeight(max(28, self.button.fontMetrics().height() + 10))
        self.button.setAccessibleName("展开或收起 EXIF 详细信息")
        self.button.clicked.connect(self.toggle)
        self.layout_row.addWidget(self.button)
        self.motion = QVariantAnimation(self)
        self.motion.valueChanged.connect(self.animate)
        self.motion.finished.connect(self.finished)
        self.setMinimumWidth(0)

    def clear(self):
        self.motion.stop()
        self.expanded, self.fraction = False, 0.0
        self.data = {}
        while self.rows.count():
            widget = self.rows.takeAt(0).widget()
            if widget:
                widget.hide()
                widget.deleteLater()
        self.button.setText("展开详细信息 ▴")

    def table(self, values, heading=None):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        if heading:
            label = DetailLabel(heading)
            label.setStyleSheet("color: #A2A2A6; border-top: 1px solid #414145; padding-top: 8px;")
            layout.addWidget(label)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 3)
        for row, (key, value) in enumerate(values.items()):
            for column, text in enumerate((key, value)):
                cell = DetailLabel(str(text))
                cell.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                if column == 0:
                    cell.setStyleSheet("color: #A2A2A6;")
                grid.addWidget(cell, row, column, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(grid)
        return container

    def set_data(self, data):
        self.clear()
        self.data = data
        self.details = QWidget()
        layout = QVBoxLayout(self.details)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        for heading, values in data.get("详细信息", {}).items():
            layout.addWidget(self.table(values, heading))
        self.rows.addWidget(self.details)
        self.details.hide()
        self.basic = self.table(data.get("基础信息", {}))
        self.rows.addWidget(self.basic)
        self.button.setEnabled(bool(data.get("详细信息")))
        QTimer.singleShot(0, self.adjust_height)

    def target_height(self):
        self.basic.layout().activate()
        basic = max(150, self.basic.heightForWidth(max(80, self.scroll.viewport().width())))
        available = max(100, self.panel.height() - 120)
        controls = self.button.height() + self.layout_row.spacing() + 10
        return min(available, basic + controls + round(min(240, available * 0.4) * self.fraction))

    def adjust_height(self):
        if self.data:
            self.setMaximumHeight(self.target_height())
            self.updateGeometry()

    def animate(self, fraction):
        self.fraction = float(fraction)
        self.adjust_height()

    def toggle(self):
        self.expanded = not self.expanded
        self.details.show()
        self.button.setText("收起详细信息 ▾" if self.expanded else "展开详细信息 ▴")
        self.motion.stop()
        self.motion.blockSignals(True)
        self.motion.setStartValue(self.fraction)
        self.motion.setEndValue(1.0 if self.expanded else 0.0)
        self.motion.setDuration(
            max(
                80,
                round(
                    (280 if self.expanded else 220)
                    * abs((1 if self.expanded else 0) - self.fraction)
                ),
            )
        )
        self.motion.setEasingCurve(
            QEasingCurve.Type.OutCubic if self.expanded else QEasingCurve.Type.InOutCubic
        )
        self.motion.setCurrentTime(0)
        self.motion.blockSignals(False)
        self.motion.start()
        self.scroll.verticalScrollBar().setValue(0)

    def finished(self):
        self.details.setVisible(self.expanded)
        self.adjust_height()

    def sizeHint(self):
        return QSize(0, self.target_height() if self.data else 100)

    def eventFilter(self, obj, event):
        if obj is self.panel and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self.adjust_height)
        return False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.oldSize().width() != event.size().width():
            QTimer.singleShot(0, self.adjust_height)

    def text(self):
        return "\n".join(label.text() for label in self.content.findChildren(DetailLabel))
