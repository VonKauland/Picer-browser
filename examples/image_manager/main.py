"""Current-folder image management; opt-in, shared marks and virtual thumbnails."""

import os
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QPoint, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from picer.file_drag import ImageFileDrag
from picer.host_style import prepare_popup
from picer.ui import RoundedSlider, ui_icon

from .filters import FilterPopup, matches
from .grid import PhotoGrid, PhotoModel


class Plugin:
    def activate(self, context):
        self.context, self.active = context, True
        self.current = context.current_path()
        self.notes = {}
        self.pixels, self.requests = OrderedDict(), {}
        self.wanted = set()
        self.count_paths = {True: [], False: []}
        self.source_key, self.source_paths = None, []
        self.generation = 0
        self.job, self.popup = None, None
        self.scope_job = None
        saved = context.get_setting("filters", {})
        saved = saved if isinstance(saved, dict) else {}
        rating = saved.get("rating")
        self.filters = {
            "local": saved.get("local", True) is not False,
            "rating": rating
            if type(rating) in (int, float) and rating in [n / 2 for n in range(11)]
            else None,
            "color": saved.get("color", "")
            if saved.get("color") in ("red", "orange", "yellow", "green", "blue", "purple")
            else "",
            "compare": saved.get("compare", "eq")
            if saved.get("compare") in ("eq", "le", "ge")
            else "eq",
        }
        self.sort = context.get_setting("sort", "name")
        if self.sort not in ("name", "modified", "rating"):
            self.sort = "name"
        self.descending = context.get_setting("descending", False) is True
        self.panel = QWidget()
        self.panel.setMinimumWidth(180)
        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(8, 6, 8, 4)
        layout.setSpacing(6)
        tools = QHBoxLayout()
        tools.setSpacing(5)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索图片")
        tools.addWidget(self.search, 1)
        self.sort_button, self.filter_button = QPushButton(), QPushButton()
        for button, icon, label in (
            (self.sort_button, "sort", "排序"),
            (self.filter_button, "filter", "筛选"),
        ):
            button.setIcon(ui_icon(icon))
            button.setFixedSize(28, 28)
            button.setStyleSheet("padding: 4px; border-radius: 14px;")
            button.setAccessibleName(label)
            button.setToolTip(label)
            tools.addWidget(button)
        layout.addLayout(tools)
        self.count = QLabel()
        self.count.setStyleSheet("color: #A2A2A6; font-size: 11px;")
        layout.addWidget(self.count)
        self.size = RoundedSlider()
        self.size.setRange(50, 200)
        value = context.get_setting("thumbnail_zoom", 100)
        self.size.setValue(value if type(value) is int and 50 <= value <= 200 else 100)
        self.size.setAccessibleName("缩略图大小")
        self.size.setToolTip("调整缩略图大小")
        self.load_timer = QTimer(self.panel)
        self.load_timer.setSingleShot(True)
        self.load_timer.setInterval(25)
        self.load_timer.timeout.connect(self.load_visible)
        self.refresh_timer = QTimer(self.panel)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(120)
        self.refresh_timer.timeout.connect(self.refresh)
        self.scope_timer = QTimer(self.panel)
        self.scope_timer.setSingleShot(True)
        self.scope_timer.setInterval(120)
        self.scope_timer.timeout.connect(self.start_scope)
        self.watcher = QFileSystemWatcher(self.panel)
        self.watcher.directoryChanged.connect(lambda _: self.schedule(invalidate=True))
        self.watcher.fileChanged.connect(self.file_changed)
        self.model = PhotoModel(self.panel)
        self.grid = PhotoGrid(self)
        self.file_drag = ImageFileDrag(
            self.grid,
            lambda index: self.model.paths[index.row()],
            context.readable_suffixes,
            lambda path: self.pixels.get(str(path)),
        )
        self.grid.setModel(self.model)
        self.grid.clicked.connect(self.open_index)
        layout.addWidget(self.grid, 1)
        footer = QHBoxLayout()
        small, large = QLabel(), QLabel()
        small.setPixmap(ui_icon("photo").pixmap(12, 12))
        large.setPixmap(ui_icon("photo").pixmap(18, 18))
        footer.addWidget(small)
        footer.addWidget(self.size, 1)
        footer.addWidget(large)
        layout.addLayout(footer)
        self.size.valueChanged.connect(self.resize_tiles)
        self.search.textChanged.connect(lambda _: self.schedule())
        self.sort_button.clicked.connect(self.sort_menu)
        self.filter_button.clicked.connect(self.filter_menu)
        self.dock = context.add_panel(self.panel, area="right")
        context.subscribe("image.changed", self.on_image)
        context.subscribe("appearance.changed", self.appearance)
        context.subscribe("annotations.changed", self.annotations_changed)
        self.schedule()

    def schedule(self, invalidate=False):
        if not self.active:
            return
        if invalidate:
            self.source_key = None
        self.generation += 1
        self.refresh_timer.start()

    def on_image(self, event):
        previous = self.current
        self.current = self.context.current_path()
        if (
            not previous
            or not self.current
            or previous.parent != self.current.parent
            or event.reason == "indexed"
        ):
            self.source_key = None
            self.count_paths = {True: [], False: []}
        self.schedule()

    def annotations_changed(self, event):
        self.source_key = None
        self.schedule()

    def appearance(self, event):
        self.sort_button.setIcon(ui_icon("sort", event["accent"]))
        self.filter_button.setIcon(ui_icon("filter", event["accent"]))
        self.source_key = None
        self.schedule()

    def refresh(self):
        if self.job is not None or not self.active:
            return
        generation = self.generation
        self.notes = self.context.image_annotations()
        notes = self.notes
        folder = self.current.parent if self.current else None
        directories = self.watcher.directories()
        target = [str(folder)] if folder else []
        if directories != target:
            if directories:
                self.watcher.removePaths(directories)
            if target:
                self.watcher.addPaths(target)
        local = self.filters["local"]
        from picer.video import VIDEO_SUFFIXES

        suffixes = self.context.readable_suffixes() - VIDEO_SUFFIXES
        source_key = (folder if local else None, local, suffixes)
        cached = list(self.source_paths) if self.source_key == source_key else None
        known = [
            Path(path) for path, mark in notes.items() if mark.get("rating") or mark.get("color")
        ]
        state = self.filters.copy()
        search, sort, descending = self.search.text().casefold(), self.sort, self.descending

        def work(token):
            paths = cached
            if paths is None:
                paths = []
                if local and folder:
                    try:
                        with os.scandir(folder) as entries:
                            for entry in entries:
                                token.checkpoint()
                                if Path(entry.name).suffix.lower() in suffixes and entry.is_file():
                                    paths.append(Path(entry.path))
                    except OSError:
                        pass
                elif not local:
                    for path in known:
                        token.checkpoint()
                        try:
                            if path.suffix.lower() in suffixes and path.is_file():
                                paths.append(path)
                        except (OSError, ValueError):
                            continue
            filtered = []
            for path in paths:
                token.checkpoint()
                if search in path.name.casefold() and matches(notes.get(str(path), {}), state):
                    filtered.append(path)

            def key(path):
                token.checkpoint()
                name = (path.name.casefold(), str(path).casefold())
                if sort == "rating":
                    return ((notes.get(str(path), {}).get("rating") or 0), *name)
                if sort == "modified":
                    try:
                        stamp = path.stat().st_mtime_ns
                    except OSError:
                        stamp = 0
                    return (stamp, *name)
                return name

            filtered.sort(key=key, reverse=descending)
            return paths, filtered

        def done(result):
            self.job = None
            if generation != self.generation:
                self.refresh_timer.start(0)
                return
            self.source_key, self.source_paths = source_key, result[0]
            self.count_paths[local] = result[0]
            self.model.replace(result[1])
            self.count.setText(
                ("当前文件夹" if local else "本设备已标记") + f" · {len(result[1])} 张"
            )
            self.grid.arrange()
            row = self.model.positions.get(str(self.current))
            if row is not None:
                index = self.model.index(row)
                self.grid.setCurrentIndex(index)
                self.grid.scrollTo(index)
            self.queue_load()
            if self.popup:
                self.popup.refresh_counts()

        self.job = self.context.run_task(work, done, image_bound=False)

    def queue_load(self):
        if self.active and not self.load_timer.isActive():
            self.load_timer.start()

    def load_visible(self):
        if not self.active:
            return
        size = self.grid.gridSize()
        columns = max(1, self.grid.viewport().width() // max(1, size.width()))
        start = max(0, self.grid.verticalScrollBar().value() // max(1, size.height()) - 1) * columns
        count = (self.grid.viewport().height() // max(1, size.height()) + 4) * columns
        paths = self.model.paths[start : start + min(80, count)]
        self.wanted = {str(path) for path in paths}
        watched = set(self.watcher.files())
        if watched - self.wanted:
            self.watcher.removePaths(list(watched - self.wanted))
        if self.wanted - watched:
            self.watcher.addPaths(list(self.wanted - watched))
        for key in list(self.requests):
            if key not in self.wanted:
                self.requests.pop(key).cancel()
        for path in paths:
            key = str(path)
            if key in self.pixels or key in self.requests:
                continue

            def render(image, key=key):
                self.requests.pop(key, None)
                if self.active and key in self.wanted:
                    self.pixels[key] = image
                    self.pixels.move_to_end(key)
                    while len(self.pixels) > 96:
                        self.pixels.popitem(last=False)
                    self.grid.viewport().update()

            self.requests[key] = self.context.request_thumbnail(path, render, edge=256)

    def file_changed(self, path):
        self.pixels.pop(path, None)
        token = self.requests.pop(path, None)
        if token:
            token.cancel()
        self.schedule(invalidate=True)
        self.queue_load()

    def open_index(self, index):
        if index.isValid() and self.model.paths[index.row()] != self.current:
            if not self.context.open_image(self.model.paths[index.row()]):
                self.context.notify("无法打开这张图片")

    def resize_tiles(self, value):
        self.context.set_setting("thumbnail_zoom", value)
        self.grid.arrange()

    def sort_menu(self):
        menu = QMenu(self.panel)
        prepare_popup(menu)
        for key, text in (("name", "名称"), ("modified", "修改时间"), ("rating", "星级评分")):
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(self.sort == key)
            action.triggered.connect(lambda _, key=key: self.set_sort(key))
        menu.addSeparator()
        for descending, text in ((False, "正序排列"), (True, "倒序排列")):
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(self.descending == descending)
            action.triggered.connect(lambda _, value=descending: self.set_descending(value))
        menu.exec(self.sort_button.mapToGlobal(QPoint(0, self.sort_button.height())))
        menu.deleteLater()

    def set_sort(self, key):
        self.sort = key
        self.context.set_setting("sort", key)
        self.schedule()

    def set_descending(self, value):
        self.descending = value
        self.context.set_setting("descending", value)
        self.schedule()

    def filter_menu(self):
        if self.popup:
            self.popup.close()
        self.popup = FilterPopup(self)
        self.popup.adjustSize()
        point = self.filter_button.mapToGlobal(QPoint(0, self.filter_button.height() + 4))
        screen = self.panel.screen().availableGeometry()
        point.setX(min(point.x(), screen.right() - self.popup.width()))
        point.setY(min(point.y(), screen.bottom() - self.popup.height()))
        self.popup.move(point)
        self.popup.show()

    def request_scope(self, popup):
        if self.popup is popup:
            self.scope_timer.start()

    def start_scope(self):
        if self.scope_job is not None or self.popup is None or not self.active:
            return
        popup = self.popup
        generation = self.generation
        # Preview another scope without changing the committed main-grid filter.
        local = popup.state["local"]
        notes = self.context.image_annotations()
        folder = self.current.parent if self.current else None
        from picer.video import VIDEO_SUFFIXES

        suffixes = self.context.readable_suffixes() - VIDEO_SUFFIXES

        def work(token):
            paths = []
            if local and folder:
                try:
                    with os.scandir(folder) as entries:
                        for entry in entries:
                            token.checkpoint()
                            if Path(entry.name).suffix.lower() in suffixes and entry.is_file():
                                paths.append(Path(entry.path))
                except OSError:
                    pass
            elif not local:
                for name, mark in notes.items():
                    token.checkpoint()
                    path = Path(name)
                    try:
                        if (
                            (mark.get("rating") or mark.get("color"))
                            and path.suffix.lower() in suffixes
                            and path.is_file()
                        ):
                            paths.append(path)
                    except (OSError, ValueError):
                        continue
            return paths

        def done(paths):
            self.scope_job = None
            if (
                self.popup is not popup
                or generation != self.generation
                or popup.state["local"] != local
            ):
                if self.popup is not None:
                    self.scope_timer.start()
                return
            self.notes = notes
            self.count_paths[local] = paths
            popup.refresh_counts()

        self.scope_job = self.context.run_task(work, done, image_bound=False)

    def deactivate(self):
        self.file_drag.stop()
        self.active = False
        self.refresh_timer.stop()
        self.load_timer.stop()
        self.scope_timer.stop()
        if self.scope_job:
            self.scope_job.cancel()
        watched = self.watcher.files() + self.watcher.directories()
        if watched:
            self.watcher.removePaths(watched)
        if self.job:
            self.job.cancel()
        for request in self.requests.values():
            request.cancel()
        self.requests.clear()
        self.pixels.clear()
        if self.popup:
            self.popup.close()
