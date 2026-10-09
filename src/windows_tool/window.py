"""An image browser with folder navigation and zoom controls."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QImageReader, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QMainWindow,
    QToolBar,
)


class ImageView(QGraphicsView):
    """Display an image with drag-to-pan and bounded zoom."""

    def __init__(self) -> None:
        super().__init__()
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.image_item = QGraphicsPixmapItem()
        self.scene.addItem(self.image_item)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(Qt.GlobalColor.darkGray)
        self.fit_mode = True

    def fit_image(self) -> None:
        self.fit_mode = True
        if not self.image_item.pixmap().isNull():
            self.fitInView(self.image_item, Qt.AspectRatioMode.KeepAspectRatio)

    def zoom(self, factor: float) -> None:
        if self.image_item.pixmap().isNull():
            return
        if 0.01 <= self.transform().m11() * factor <= 32:
            self.fit_mode = False
            self.scale(factor, factor)

    def actual_size(self) -> None:
        self.fit_mode = False
        self.resetTransform()

    def wheelEvent(self, event) -> None:
        self.zoom(1.25 if event.angleDelta().y() > 0 else 0.8)
        event.accept()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.fit_mode:
            self.fit_image()


class MainWindow(QMainWindow):
    """Browse supported images in the selected file's directory."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("WindowsTool 图片浏览器")
        self.resize(1000, 700)
        self.paths: list[Path] = []
        self.current_path: Path | None = None
        self.view = ImageView()
        self.setCentralWidget(self.view)
        self.supported_suffixes = {
            f".{bytes(fmt).decode().lower()}" for fmt in QImageReader.supportedImageFormats()
        }
        toolbar = QToolBar("图片操作", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.open_action = self.add_action(toolbar, "打开图片", "Ctrl+O", self.choose_image)
        self.previous_action = self.add_action(toolbar, "上一张", "Left", lambda: self.navigate(-1))
        self.next_action = self.add_action(toolbar, "下一张", "Right", lambda: self.navigate(1))
        toolbar.addSeparator()
        self.zoom_in_action = self.add_action(
            toolbar, "放大", "Ctrl+=", lambda: self.view.zoom(1.25)
        )
        self.zoom_out_action = self.add_action(
            toolbar, "缩小", "Ctrl+-", lambda: self.view.zoom(0.8)
        )
        self.fit_action = self.add_action(toolbar, "适应窗口", "Ctrl+0", self.view.fit_image)
        self.actual_action = self.add_action(toolbar, "原始大小", "Ctrl+1", self.view.actual_size)
        self.update_actions()
        self.statusBar().showMessage("点击“打开图片”开始浏览；滚轮缩放，拖动图片平移。")

    def add_action(self, toolbar, text, shortcut, callback) -> QAction:
        action = QAction(text, self)
        action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(callback)
        toolbar.addAction(action)
        return action

    def choose_image(self) -> None:
        patterns = " ".join(f"*{suffix}" for suffix in sorted(self.supported_suffixes))
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "打开图片",
            str(self.current_path.parent) if self.current_path else "",
            f"图片 ({patterns});;所有文件 (*)",
        )
        if filename:
            self.open_image(Path(filename))

    def open_image(self, path: Path) -> bool:
        """Decode before updating state so failed files leave the current image intact."""
        path = path.resolve()
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            self.statusBar().showMessage(f"无法打开 {path.name}：{reader.errorString()}")
            return False
        try:
            paths = sorted(
                (
                    p
                    for p in path.parent.iterdir()
                    if p.is_file() and p.suffix.lower() in self.supported_suffixes
                ),
                key=lambda p: (p.name.casefold(), p.name),
            )
        except OSError:
            paths = []
        if path not in paths:
            paths.append(path)
        self.paths = paths
        self.current_path = path
        self.view.image_item.setPixmap(QPixmap.fromImage(image))
        self.view.scene.setSceneRect(self.view.image_item.boundingRect())
        self.view.fit_image()
        self.setWindowTitle(f"{path.name} — WindowsTool 图片浏览器")
        self.statusBar().showMessage(
            f"{self.paths.index(path) + 1}/{len(self.paths)}  |  {path.name}  |  "
            f"{image.width()} × {image.height()} 像素"
        )
        self.update_actions()
        return True

    def navigate(self, offset: int) -> None:
        """Skip unreadable images and wrap around at folder boundaries."""
        if self.current_path is None or len(self.paths) < 2:
            return
        paths = self.paths.copy()
        index = paths.index(self.current_path)
        for step in range(1, len(paths)):
            if self.open_image(paths[(index + offset * step) % len(paths)]):
                return

    def update_actions(self) -> None:
        self.previous_action.setEnabled(len(self.paths) > 1)
        self.next_action.setEnabled(len(self.paths) > 1)
        for action in (
            self.zoom_in_action,
            self.zoom_out_action,
            self.fit_action,
            self.actual_action,
        ):
            action.setEnabled(self.current_path is not None)
