"""Latest-request-wins decoding, bounded previews and reusable folder indexes."""

import os
from collections import OrderedDict, deque
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, Qt, QThreadPool, QTimer
from PySide6.QtGui import QImageReader

from picer.animation import animation_source
from picer.imaging import RAW_SUFFIXES, read_image
from picer.plugins.tasks import TaskCancelled, Worker
from picer.video import VIDEO_SUFFIXES


class ImageLoader(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.pools = {name: QThreadPool(self) for name in ("preview", "prefetch", "full", "index")}
        for pool in self.pools.values():
            pool.setMaxThreadCount(1)
        self.pools["preview"].setMaxThreadCount(2)
        self.rapid = False
        self.direction = 1
        self.prefetch_again = False
        self.jobs = {}
        self.generation = 0
        self.closed = False
        self.cache = OrderedDict()
        self.cache_bytes = 0
        self.cache_generation = 0
        self.cache_limit = 192 * 1048576
        self.directories = OrderedDict()
        self.indexing = set()
        self.format_generation = 0
        self.dirty_directories = set()
        self.folder_candidates = deque()
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.invalidate_directory)
        self.refine = QTimer(self)
        self.refine.setSingleShot(True)
        self.refine.setInterval(180)
        self.refine.timeout.connect(self.load_full)
        self.prefetch_timer = QTimer(self)
        self.prefetch_timer.setSingleShot(True)
        self.prefetch_timer.setInterval(80)
        self.prefetch_timer.timeout.connect(self.prefetch)
        self.thumbnail_timer = QTimer(self)
        self.thumbnail_timer.setSingleShot(True)
        self.thumbnail_timer.setInterval(30)
        self.thumbnail_timer.timeout.connect(self.flush_thumbnail)
        self.pending_thumbnail = None
        self.requested = None
        self.options = True
        self.camera_preview_owners = set()

    def camera_preview(self, path):
        return bool(self.camera_preview_owners) and path.suffix.lower() in RAW_SUFFIXES

    def set_camera_preview(self, owner, enabled):
        previous = bool(self.camera_preview_owners)
        if enabled:
            self.camera_preview_owners.add(owner)
        else:
            self.camera_preview_owners.discard(owner)
        path = self.requested or self.host.current_path
        if (
            previous != bool(self.camera_preview_owners)
            and path
            and path.suffix.lower() in RAW_SUFFIXES
            and not self.closed
            and not self.host.plugins._closed
            and not self.host.image_edited
        ):
            if path != self.host.current_path:
                self.open(path)
                return
            self.generation += 1
            generation = self.generation
            self.refine.stop()
            self.prefetch_timer.stop()
            for worker, lane, _ in self.jobs.values():
                if lane != "index":
                    worker.token.cancel()
            camera, options = self.camera_preview(path), self.options
            try:
                key = self.key(path, 0)
            except OSError:
                return
            cache_generation = self.cache_generation

            def finish(image, error):
                if generation != self.generation or self.host.current_path != path:
                    return
                if error:
                    self.host.notify(f"RAW 效果切换失败：{error}")
                    return
                self.remember(key, image, generation=cache_generation)
                size = (
                    int(image.text("picer.native_width") or image.width()),
                    int(image.text("picer.native_height") or image.height()),
                )
                self.host.source_size = size[::-1] if self.host.image_rotation % 180 else size
                self.host.view.native_width = self.host.source_size[0]
                self.host.refine_image(image)
                self.host.image_revision += 1
                self.host.double_page.refresh()
                self.host.plugins.emit_image("raw-preview")

            cached = self.cached(key)
            if cached is not None:
                finish(cached, None)
            else:
                self.submit(
                    "full",
                    lambda token: read_image(
                        path, auto_orient=options, camera_preview=camera, token=token
                    ),
                    finish,
                    foreground=True,
                )

    def set_rapid(self, active):
        if self.closed or self.rapid == active:
            return
        self.rapid = active
        self.refine.stop()
        if active:
            for worker, lane, _ in self.jobs.values():
                if lane == "full":
                    worker.token.cancel()
        elif self.requested == self.host.current_path:
            if self.host.double_page.second.isVisible():
                self.host.double_page.refine.start()
            self.refine.start()
            self.prefetch_timer.start()

    def settle(self):
        if not self.rapid:
            self.refine.start()
        self.prefetch_timer.start(20 if self.rapid else 80)

    def submit(self, lane, work, done, *, foreground=False):
        worker = Worker(work)
        worker.setAutoDelete(False)
        key = id(worker)
        self.jobs[key] = (worker, lane, foreground)

        def finish(result, error):
            self.jobs.pop(key, None)
            if self.closed:
                if result and isinstance(result, tuple) and len(result) == 2:
                    source = result[1]
                    if hasattr(source, "close"):
                        source.close()
                return
            done(result, error)
            if lane == "prefetch" and self.prefetch_again:
                self.prefetch_timer.start(20)

        worker.signals.finished.connect(finish, Qt.ConnectionType.QueuedConnection)
        self.pools[lane].start(worker, 1 if foreground else 0)
        return worker

    def key(self, path, edge):
        stat = path.stat()
        return (path, stat.st_mtime_ns, stat.st_size, edge, self.options, self.camera_preview(path))

    def remember(self, key, image, *, generation=None):
        if generation is not None and generation != self.cache_generation:
            return
        old = self.cache.pop(key, None)
        if old:
            self.cache_bytes -= old.sizeInBytes()
        if image.sizeInBytes() > self.cache_limit:
            return
        self.cache[key] = image
        self.cache_bytes += image.sizeInBytes()
        while len(self.cache) > 24 or self.cache_bytes > self.cache_limit:
            _, removed = self.cache.popitem(last=False)
            self.cache_bytes -= removed.sizeInBytes()

    def cached(self, key):
        image = self.cache.get(key)
        if image is not None:
            self.cache.move_to_end(key)
        return image

    def invalidate_directory(self, directory):
        if self.closed:
            return
        path = Path(directory)
        self.directories.pop(path, None)
        if path in self.indexing:
            self.dirty_directories.add(path)
            return
        if self.requested and self.requested.parent == path:
            self.index_directory(path, force=True)

    def apply_index(self, directory, paths):
        self.directories[directory] = paths
        self.directories.move_to_end(directory)
        if str(directory) not in self.watcher.directories():
            self.watcher.addPath(str(directory))
        while len(self.directories) > 3:
            removed, _ = self.directories.popitem(last=False)
            self.watcher.removePath(str(removed))
        if self.host.current_path and self.host.current_path.parent == directory:
            self.host.set_image_paths(paths)

    def formats_changed(self):
        self.format_generation += 1
        if self.requested and self.requested.suffix.lower() not in self.host.supported_suffixes:
            self.generation += 1
            self.requested = self.host.current_path
            self.refine.stop()
            for worker, lane, _ in self.jobs.values():
                if lane != "index":
                    worker.token.cancel()
        for worker, lane, _ in self.jobs.values():
            if lane == "index":
                worker.token.cancel()
        self.directories.clear()
        self.indexing.clear()
        self.dirty_directories.clear()
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        if self.host.current_path:
            self.index_directory(self.host.current_path.parent, force=True)

    def index_directory(self, directory, *, force=False):
        if not self.host.app_preferences["browse_folder"]:
            return [self.requested] if self.requested else []
        if directory in self.directories and not force:
            return self.directories[directory]
        if directory in self.indexing:
            return None
        suffixes = self.host.supported_suffixes
        format_generation = self.format_generation

        def scan(token=None, limit=0):
            paths = []
            with os.scandir(directory) as entries:
                for number, entry in enumerate(entries):
                    if token:
                        token.checkpoint()
                    if limit and number == limit:
                        return None
                    if Path(entry.name).suffix.lower() in suffixes and entry.is_file():
                        paths.append(Path(entry.path))
            paths.sort(key=lambda p: (p.name.casefold(), p.name))
            return paths

        try:
            immediate = None if force else scan(limit=256)
        except OSError:
            immediate = []
        if immediate is not None:
            self.apply_index(directory, immediate)
            return immediate
        self.indexing.add(directory)

        def finish(paths, error):
            if format_generation != self.format_generation:
                return
            self.indexing.discard(directory)
            if directory in self.dirty_directories:
                self.dirty_directories.discard(directory)
                if self.requested and self.requested.parent == directory:
                    self.index_directory(directory, force=True)
                return
            if error is None:
                self.apply_index(directory, paths)
                self.prefetch_timer.start()

        worker = self.submit("index", lambda token: scan(token), finish)
        worker.directory = directory
        return None

    def open(self, path):
        path = Path(path).resolve()
        try:
            if path.suffix.lower() not in self.host.supported_suffixes:
                raise ValueError("此图片格式未启用，请在选项 → 系统设置 → 格式设置中开启。")
            if not path.is_file():
                raise ValueError("文件不存在")
            reader = QImageReader(str(path))
            raw = path.suffix.lower() in RAW_SUFFIXES
            video = path.suffix.lower() in VIDEO_SUFFIXES
            if not raw and not video and not reader.canRead():
                raise ValueError(reader.errorString())
            options = self.host.app_preferences["auto_orient"]
            self.options = options
            camera_preview = self.camera_preview(path)
            edge = 960 if self.rapid else 1600
            full_key, preview_key = self.key(path, 0), self.key(path, edge)
            full = self.cached(full_key)
            preview = self.cached(self.key(path, 1600)) or self.cached(preview_key)
            size = reader.size()
            animated_format = bytes(reader.format()).lower() in {b"gif", b"webp"}
            small = (
                not raw
                and not video
                and not animated_format
                and path.stat().st_size < 2 * 1048576
                and 0 < size.width() * size.height() <= 2_000_000
            )
            if self.rapid and not small:
                full = None  # Avoid uploading a cached full-resolution image on every repeat.
            if full is None and small:
                full = read_image(path, auto_orient=options)
        except Exception as error:
            self.host.last_error = f"无法打开 {path.name}：{error}"
            return False
        self.generation += 1
        generation = self.generation
        cache_generation = self.cache_generation
        self.requested = path
        self.refine.stop()
        self.prefetch_timer.stop()
        for key, (worker, lane, _) in list(self.jobs.items()):
            if lane != "index" or getattr(worker, "directory", path.parent) != path.parent:
                worker.token.cancel()
                if self.pools[lane].tryTake(worker):
                    self.jobs.pop(key, None)
                    if lane == "index":
                        self.indexing.discard(worker.directory)
        paths = self.index_directory(path.parent)
        if full is not None and not animated_format:
            self.remember(full_key, full)
            self.folder_candidates.clear()
            self.host.present_image(path, full, paths=paths)
            self.store_thumbnail(path, full)
            self.prefetch_timer.start()
            return True
        if preview is not None:
            self.folder_candidates.clear()
            self.host.present_image(path, preview, paths=paths, preview=True)
            self.settle()
            return True

        def work(token):
            source = None
            try:
                source = animation_source(path, token, auto_orient=options)
                image = (
                    source.preview(edge, token)
                    if source
                    else read_image(
                        path,
                        edge=edge,
                        auto_orient=options,
                        token=token,
                        camera_preview=camera_preview,
                    )
                )
                token.checkpoint()
                return image, source
            except Exception:
                if source:
                    source.close()
                raise

        def finish(result, error):
            if generation != self.generation:
                if result and result[1]:
                    result[1].close()
                return
            if error:
                while self.folder_candidates:
                    if self.open(self.folder_candidates.popleft()):
                        return
                self.host.loading_failed(path, str(error))
                return
            image, source = result
            self.folder_candidates.clear()
            self.store_thumbnail(path, image)
            if source is None:
                self.remember(preview_key, image, generation=cache_generation)
            self.host.present_image(
                path, image, paths=self.directories.get(path.parent), preview=source is None
            )
            if source:
                self.host.animation.start(source)
            else:
                self.settle()

        self.submit("preview", work, finish, foreground=True)
        return True

    def store_thumbnail(self, path, image):
        thumbnail = image.scaled(
            min(256, image.width()),
            min(256, image.height()),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        if not self.options:
            return  # Shared thumbnails always use EXIF orientation.
        self.host.thumbnail_cache.offer(path, thumbnail)
        self.pending_thumbnail = (path, thumbnail)
        self.thumbnail_timer.start()

    def flush_thumbnail(self):
        if self.pending_thumbnail is None:
            return
        path, thumbnail = self.pending_thumbnail
        self.pending_thumbnail = None
        self.host.thumbnails.seed(path, thumbnail)

    def load_full(self):
        path, generation, options = self.requested, self.generation, self.options
        camera_preview = self.camera_preview(path) if path else False
        cache_generation = self.cache_generation
        if not path or self.rapid or self.host.animation.state.active:
            return
        try:
            key = self.key(path, 0)
        except OSError:
            return
        cached = self.cached(key)
        if cached is not None:
            self.host.refine_image(cached)
            return

        def finish(image, error):
            if generation != self.generation or isinstance(error, TaskCancelled) or self.rapid:
                return
            if error:
                self.host.last_error = f"原图无法读取 {path.name}：{error}"
                return
            self.remember(key, image, generation=cache_generation)
            self.host.refine_image(image)

        self.submit(
            "full",
            lambda token: read_image(
                path, auto_orient=options, token=token, camera_preview=camera_preview
            ),
            finish,
            foreground=True,
        )

    def prefetch(self):
        # Thread count bounds execution, not Qt's queue. Keep a single neighbour
        # batch even when repeated timers fire during a slow disk/RAW decode.
        if self.closed:
            return
        if any(lane == "prefetch" for _, lane, _ in self.jobs.values()):
            self.prefetch_again = True
            return
        self.prefetch_again = False
        paths = self.host.paths
        if self.requested not in self.host.path_positions or len(paths) < 2:
            return
        index = self.host.path_positions[self.requested]
        options = self.options
        edge = 960 if self.rapid else 1600
        cache_generation = self.cache_generation
        targets = set()
        for offset in (self.direction, -self.direction):
            target = index + offset
            if not self.host.app_preferences["wrap"] and not 0 <= target < len(paths):
                continue
            path = paths[target % len(paths)]
            if path in targets:
                continue
            targets.add(path)
            if bytes(QImageReader(str(path)).format()).lower() in {b"gif", b"webp"}:
                continue
            try:
                key = self.key(path, edge)
            except OSError:
                continue
            if key in self.cache:
                continue

            def finish(image, error, key=key):
                if error is None:
                    self.remember(key, image, generation=cache_generation)

            camera = self.camera_preview(path)
            self.submit(
                "prefetch",
                lambda token, path=path, edge=edge, camera=camera: read_image(
                    path, edge=edge, auto_orient=options, token=token, camera_preview=camera
                ),
                finish,
            )

    def open_folder(self, directory):
        self.generation += 1
        generation = self.generation
        format_generation = self.format_generation
        self.refine.stop()
        self.prefetch_timer.stop()
        self.host.navigation_request = None
        suffixes = self.host.supported_suffixes

        def work(token):
            paths = []
            with os.scandir(directory) as entries:
                for entry in entries:
                    token.checkpoint()
                    if Path(entry.name).suffix.lower() in suffixes and entry.is_file():
                        paths.append(Path(entry.path))
            paths.sort(key=lambda path: (path.name.casefold(), path.name))
            return paths

        def finish(paths, error):
            if generation != self.generation or format_generation != self.format_generation:
                return
            if error:
                self.host.loading_failed(directory, str(error))
                return
            self.apply_index(directory, paths)
            for index, path in enumerate(paths):
                if self.host.open_image(path):
                    if self.host.current_path != path:
                        self.folder_candidates = deque(paths[index + 1 :])
                    return
            self.host.loading_failed(directory, "该文件夹中没有可读取的图片")

        self.submit("index", work, finish, foreground=True)

    def clear_cache(self):
        self.cache_generation += 1
        self.prefetch_again = False
        self.prefetch_timer.stop()
        self.cache.clear()
        self.cache_bytes = 0
        self.thumbnail_timer.stop()
        self.pending_thumbnail = None

    def shutdown(self):
        if self.closed:
            return
        self.closed = True
        self.refine.stop()
        self.prefetch_timer.stop()
        self.thumbnail_timer.stop()
        for worker, _, _ in self.jobs.values():
            worker.token.cancel()
        for pool in self.pools.values():
            pool.waitForDone()
        self.cache.clear()
