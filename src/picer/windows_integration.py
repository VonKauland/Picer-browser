"""Explicit, reversible per-user Explorer integration; never write UserChoice."""

import ctypes
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from picer.i18n import tr

APP_NAME = "Picer"
PROG_ID = "Picer.Image"
CAPABILITIES = r"Software\Picer\Capabilities"


def application_executable():
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        raise OSError(tr("请在 Windows 中运行打包后的 Picer.exe，再注册系统集成。"))
    return Path(sys.executable).resolve()


def reveal_file(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise OSError(tr("当前图片文件已不存在。"))
    if sys.platform == "win32":
        explorer = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "explorer.exe"
        # Keep the filename separate so spaces/commas cannot become Explorer switches.
        subprocess.Popen([str(explorer), "/select,", str(path)])
    elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent))):
        raise OSError(tr("无法打开图片所在文件夹。"))


class WindowsIntegration:
    """Own only Picer-named keys in HKCU; root supports isolated native CI checks."""

    def __init__(self, executable=None, *, root=""):
        import winreg

        self.registry = winreg
        self.root = root
        self.executable = Path(executable or application_executable()).resolve()
        if not self.executable.is_file() or self.executable.suffix.lower() != ".exe":
            raise OSError(tr("找不到可注册的应用程序 EXE。"))
        self.command = f'"{self.executable}" "%1"'

    def path(self, key):
        return self.root + ("\\" + key if key else "") if self.root else key

    def write(self, key, name, value, kind=None):
        reg = self.registry
        with reg.CreateKeyEx(reg.HKEY_CURRENT_USER, self.path(key), 0, reg.KEY_WRITE) as handle:
            reg.SetValueEx(handle, name, 0, reg.REG_SZ if kind is None else kind, value)

    def read(self, key, name, default=None):
        reg = self.registry
        try:
            with reg.OpenKey(reg.HKEY_CURRENT_USER, self.path(key)) as handle:
                return reg.QueryValueEx(handle, name)[0]
        except FileNotFoundError:
            return default

    def delete(self, key):
        reg = self.registry
        try:
            with reg.OpenKey(reg.HKEY_CURRENT_USER, self.path(key), 0, reg.KEY_READ) as handle:
                children = [reg.EnumKey(handle, i) for i in range(reg.QueryInfoKey(handle)[0])]
            for child in children:
                self.delete((key + "\\" if key else "") + child)
            reg.DeleteKey(reg.HKEY_CURRENT_USER, self.path(key))
        except FileNotFoundError:
            pass

    @staticmethod
    def formats(suffixes):
        from picer.formats import valid_formats

        suffixes = sorted(set(suffixes))
        if not suffixes or not valid_formats(suffixes):
            raise ValueError(tr("请至少选择一种可读取的图片格式。"))
        return suffixes

    def register_viewer(self, suffixes):
        suffixes = self.formats(suffixes)
        classes = r"Software\Classes"
        application = classes + r"\Applications\Picer.exe"
        self.write(classes + "\\" + PROG_ID, "", tr("揽映图片"))
        for key in (classes + "\\" + PROG_ID, application):
            self.write(key + r"\DefaultIcon", "", f'"{self.executable}",0')
            self.write(key + r"\shell\open\command", "", self.command)
        self.write(application, "FriendlyAppName", tr("揽映 Picer"))
        self.delete(application + r"\SupportedTypes")
        self.delete(CAPABILITIES + r"\FileAssociations")
        previous = self.stored_formats(CAPABILITIES, "Extensions")
        for suffix in previous:
            if suffix not in suffixes:
                self.remove_open_with(suffix)
        for suffix in suffixes:
            self.write(application + r"\SupportedTypes", suffix, "")
            self.write(CAPABILITIES + r"\FileAssociations", suffix, PROG_ID)
            self.write(
                classes + "\\" + suffix + r"\OpenWithProgids", PROG_ID, b"", self.registry.REG_NONE
            )
        self.write(CAPABILITIES, "ApplicationName", tr("揽映 Picer"))
        self.write(CAPABILITIES, "ApplicationDescription", tr("本地图片与 RAW 照片浏览器"))
        self.write(CAPABILITIES, "ApplicationIcon", f'"{self.executable}",0')
        self.write(CAPABILITIES, "Extensions", suffixes, self.registry.REG_MULTI_SZ)
        self.write(r"Software\RegisteredApplications", APP_NAME, CAPABILITIES)
        self.register_thumbnail_provider()
        self.changed()

    def register_thumbnail_provider(self):
        from picer.shell_thumbnail import PROVIDER_CLSID, THUMBNAIL_IID

        dll = self.executable.parent / "shell" / "PicerThumbnail.dll"
        if not dll.is_file():
            return  # Older portable folders can still register their open command.
        classes = r"Software\Classes"
        clsid = classes + "\\CLSID\\" + PROVIDER_CLSID
        self.write(clsid, "", "Picer isolated image thumbnails")
        self.write(clsid, "AppID", PROVIDER_CLSID)
        self.write(clsid + r"\InprocServer32", "", str(dll))
        self.write(clsid + r"\InprocServer32", "ThreadingModel", "Apartment")
        self.write(classes + "\\AppID\\" + PROVIDER_CLSID, "DllSurrogate", "")
        # Scope to our ProgID: never replace extension/SystemFileAssociations handlers.
        for name in (PROG_ID, r"Applications\Picer.exe"):
            key = classes + "\\" + name
            self.write(key + "\\shellex\\" + THUMBNAIL_IID, "", PROVIDER_CLSID)
            self.write(key, "Treatment", 0, self.registry.REG_DWORD)
            self.write(key, "TypeOverlay", "")

    def remove_open_with(self, suffix):
        reg = self.registry
        key = r"Software\Classes" + "\\" + suffix + r"\OpenWithProgids"
        try:
            with reg.OpenKey(reg.HKEY_CURRENT_USER, self.path(key), 0, reg.KEY_SET_VALUE) as handle:
                reg.DeleteValue(handle, PROG_ID)
        except FileNotFoundError:
            pass

    def register_context_menu(self, suffixes):
        suffixes = self.formats(suffixes)
        previous = self.stored_formats(r"Software\Picer", "ContextExtensions")
        for suffix in set(previous) - set(suffixes):
            self.delete(self.menu_key(suffix))
        for suffix in suffixes:
            key = self.menu_key(suffix)
            self.write(key, "", tr("使用揽映打开"))
            self.write(key, "Icon", f'"{self.executable}",0')
            self.write(key, "MultiSelectModel", "Single")
            self.write(key + r"\command", "", self.command)
        self.write(r"Software\Picer", "ContextExtensions", suffixes, self.registry.REG_MULTI_SZ)
        self.changed()

    @staticmethod
    def menu_key(suffix):
        return r"Software\Classes\SystemFileAssociations" + "\\" + suffix + r"\shell\Picer"

    def remove_context_menu(self):
        for suffix in self.stored_formats(r"Software\Picer", "ContextExtensions"):
            self.delete(self.menu_key(suffix))
        self.write(r"Software\Picer", "ContextExtensions", [], self.registry.REG_MULTI_SZ)
        self.changed()

    def stored_formats(self, key, name):
        from picer.formats import valid_formats

        value = self.read(key, name, [])
        return value if isinstance(value, list) and valid_formats(value) else []

    def changed(self):
        if not self.root:
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)


def open_default_apps():
    if not QDesktopServices.openUrl(QUrl("ms-settings:defaultapps?registeredAppUser=Picer")):
        raise OSError(tr("无法打开 Windows 默认应用设置，请在系统设置中手动选择揽映。"))
