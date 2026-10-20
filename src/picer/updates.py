"""Bounded, optional GitHub release checks; downloads open only on user action."""

import html
import json
import re
import threading
import time
import urllib.request
from dataclasses import dataclass
from http.client import HTTPException
from urllib.parse import unquote, urlsplit

from PySide6.QtCore import (
    QObject,
    QPoint,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from picer import __version__
from picer.host_style import mark_host
from picer.i18n import tr

REPOSITORY = "VonKauland/Picer-browser"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
MAX_RESPONSE = 512 * 1024


def version_tuple(value):
    if not isinstance(value, str) or len(value) > 32:
        return None
    match = re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value or "")
    return tuple(map(int, match.groups())) if match else None


def release_url(value, *, asset=False):
    if not isinstance(value, str) or len(value) > 2048:
        return ""
    parsed = urlsplit(value)
    prefix = f"/{REPOSITORY}/releases/" + ("download/" if asset else "tag/")
    path = unquote(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or parsed.query
        or parsed.fragment
        or not path.startswith(prefix)
        or ".." in path.split("/")
    ):
        return ""
    return value


@dataclass(frozen=True)
class Release:
    version: str
    page: str
    notes: str
    portable: str = ""
    installer: str = ""

    @classmethod
    def parse(cls, data, current=__version__):
        if (
            not isinstance(data, dict)
            or data.get("draft") is not False
            or data.get("prerelease") is not False
        ):
            return None
        tag = data.get("tag_name")
        version = version_tuple(tag) if isinstance(tag, str) else None
        baseline = version_tuple(current)
        if not version or not baseline or version <= baseline:
            return None
        page = release_url(data.get("html_url"))
        if not page or unquote(urlsplit(page).path) != f"/{REPOSITORY}/releases/tag/{tag}":
            return None
        version_text = ".".join(map(str, version))
        assets = {}
        entries = data.get("assets", [])
        for item in entries[:100] if isinstance(entries, list) else []:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            for kind, suffix in (("portable", "portable.zip"), ("installer", "setup.exe")):
                if name == f"Picer-{version_text}-windows-x64-{suffix}":
                    url = release_url(item.get("browser_download_url"), asset=True)
                    if (
                        url
                        and unquote(urlsplit(url).path)
                        == f"/{REPOSITORY}/releases/download/{tag}/{name}"
                    ):
                        assets[kind] = url
        notes = data.get("body", "")
        notes = notes[:65536] if isinstance(notes, str) else ""
        return cls(version_text, page, notes, **assets)


class GitHubRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if parsed.scheme != "https" or parsed.netloc != "api.github.com":
            raise ValueError("Unexpected update API redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_release():
    request = urllib.request.Request(
        API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"Picer/{__version__}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    opener = urllib.request.build_opener(GitHubRedirect())
    deadline = time.monotonic() + 12
    with opener.open(request, timeout=8) as response:
        chunks, size = [], 0
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError("Update request timed out")
            block = response.read1(min(65536, MAX_RESPONSE + 1 - size))
            if not block:
                break
            chunks.append(block)
            size += len(block)
            if size > MAX_RESPONSE:
                raise ValueError("Update response is too large")
    return Release.parse(json.loads(b"".join(chunks)))


class Result(QObject):
    ready = Signal(object, bool)


class Check:
    def __init__(self):
        self.result = Result()

    def run(self):
        try:
            self.result.ready.emit(fetch_release(), True)
        except (OSError, ValueError, TypeError, UnicodeError, OverflowError, HTTPException):
            self.result.ready.emit(None, False)


class NotesBrowser(QTextBrowser):
    def loadResource(self, kind, url):
        # Release content is untrusted. No remote or local images/resources.
        return None


class UpdatePopup(QWidget):
    def __init__(self, host, release):
        super().__init__(host, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.host, self.release = host, release
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAccessibleName(tr("发现新版本"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 28, 22, 22)
        layout.setSpacing(12)
        header = QHBoxLayout()
        heading = QLabel(tr("发现新版本"))
        heading.setStyleSheet("font-size: 18px; font-weight: 600;")
        header.addWidget(heading, 1)
        close = QPushButton("×")
        close.setFixedSize(28, 28)
        close.setObjectName("circleButton")
        close.setAccessibleName(tr("关闭"))
        close.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 0; "
            "border-radius: 14px; }"
        )
        close.clicked.connect(self.close)
        header.addWidget(close)
        layout.addLayout(header)
        version = QLabel(f"Picer {release.version}")
        version.setWordWrap(True)
        version.setStyleSheet("font-size: 22px; font-weight: 600;")
        layout.addWidget(version)
        current = QLabel(tr("当前版本 {0}").format(__version__))
        current.setObjectName("muted")
        layout.addWidget(current)
        layout.addWidget(QLabel(tr("更新内容")))
        self.notes = NotesBrowser()
        self.notes.setOpenLinks(False)
        self.notes.setOpenExternalLinks(False)
        self.notes.setAccessibleName(tr("更新日志"))
        self.notes.setMarkdown(
            html.escape(release.notes) if release.notes else tr("暂无更新说明。")
        )
        self.notes.setStyleSheet("QTextBrowser { background: transparent; border: none; }")
        layout.addWidget(self.notes, 1)
        self.page = QPushButton(tr("打开 Release 页面 ↗"))
        self.page.setObjectName("quietButton")
        self.page.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 4px 0; color: "
            + host.skin_colors["accent"]
            + "; text-align: left; }"
        )
        self.page.clicked.connect(lambda: self.open_url(release.page))
        layout.addWidget(self.page, 0, Qt.AlignmentFlag.AlignLeft)
        buttons = QHBoxLayout()
        self.portable = QPushButton(tr("下载 ZIP 版"))
        self.portable.setObjectName("primaryButton")
        self.installer = QPushButton(tr("下载安装版"))
        for button, url in ((self.portable, release.portable), (self.installer, release.installer)):
            button.setEnabled(bool(url))
            if not url:
                button.setToolTip(tr("此版本未提供该下载文件"))
            button.clicked.connect(lambda checked=False, target=url: self.open_url(target))
            buttons.addWidget(button, 1)
        layout.addLayout(buttons)
        self.setStyleSheet(host.styleSheet())
        mark_host(self)
        screen = host.screen().availableGeometry()
        self.resize(min(430, screen.width() - 16), min(490, screen.height() - 16))

    def open_url(self, url):
        from PySide6.QtCore import QUrl

        if release_url(url) or release_url(url, asset=True):
            QDesktopServices.openUrl(QUrl(url))

    def paintEvent(self, event):
        colors = self.host.skin_colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(colors["menu"]))
        painter.setPen(QPen(QColor(colors["accent"]).darker(230), 1))
        painter.drawRoundedRect(QRectF(1, 9, self.width() - 2, self.height() - 10), 16, 16)
        painter.drawPolygon(QPolygonF([QPointF(14, 10), QPointF(22, 2), QPointF(30, 10)]))


class UpdateButton(QToolButton):
    def __init__(self, host):
        super().__init__(host.title_bar.left)
        self.host = host
        self.setFixedSize(28, 28)
        self.setAccessibleName(tr("发现新版本"))
        self.setToolTip(tr("发现新版本"))
        self.setStyleSheet("QToolButton { background: transparent; border: none; padding: 0; }")
        self.hide()

    def paintEvent(self, event):
        colors = self.host.skin_colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors["accent"]))
        painter.drawEllipse(QRectF(3, 5, 20, 20))
        painter.drawEllipse(QRectF(22, 1, 5, 5))
        painter.setPen(
            QPen(QColor(colors["title"]), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        )
        painter.drawLine(13, 18, 13, 10)
        painter.drawLine(13, 10, 9, 14)
        painter.drawLine(13, 10, 17, 14)
        painter.drawArc(7, 9, 12, 12, 205 * 16, 130 * 16)


class UpdateChecker(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host, self.release, self.popup = host, None, None
        self.closed, self.started, self.manual = False, False, False
        self.job = None
        self.enabled = False
        self.button = UpdateButton(host)
        host.title_bar.left.layout().addWidget(self.button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.button.clicked.connect(self.show_popup)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.check)

    def start(self):
        self.started = True
        self.configure()

    def configure(self):
        enabled = self.started and not self.closed and self.host.app_preferences["check_updates"]
        if enabled == self.enabled:
            return
        self.enabled = enabled
        self.timer.stop()
        if enabled:
            self.timer.start(3000)

    def check(self, manual=False):
        if self.closed:
            return
        self.manual = self.manual or manual
        if self.job:
            return
        self.job = Check()
        self.job.result.ready.connect(self.finished)
        threading.Thread(target=self.job.run, name="picer-update-check", daemon=True).start()

    def finished(self, release, success):
        self.job = None
        if self.closed:
            return
        manual, self.manual = self.manual, False
        if success:
            self.release = release
            self.button.setVisible(release is not None)
            self.host.title_bar.arrange()
            if release and manual:
                self.show_popup()
            elif manual:
                self.host.notify(tr("当前已是最新版本"))
        elif manual:
            self.host.notify(tr("暂时无法检测更新，请稍后重试"))
        if self.started and self.host.app_preferences["check_updates"]:
            self.timer.start(24 * 60 * 60 * 1000)

    def show_popup(self):
        if not self.release or self.closed:
            return
        if self.popup:
            self.popup.close()
            self.popup.deleteLater()
        self.popup = UpdatePopup(self.host, self.release)
        point = self.button.mapToGlobal(QPoint(0, self.button.height()))
        screen = self.button.screen().availableGeometry()
        self.popup.move(
            max(screen.left() + 8, min(point.x() - 8, screen.right() - self.popup.width() - 8)),
            max(screen.top() + 8, min(point.y(), screen.bottom() - self.popup.height() - 8)),
        )
        self.popup.show()

    def dispose(self):
        if self.closed:
            return
        self.closed = True
        self.timer.stop()
        self.button.hide()
        if self.job:
            self.job.result.ready.disconnect(self.finished)
        if self.popup:
            self.popup.close()
            self.popup.deleteLater()
            self.popup = None
