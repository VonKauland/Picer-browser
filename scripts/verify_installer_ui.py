"""Drive the real, non-silent installer against the isolated test registry."""

import ctypes as C
import json
import subprocess
import time
from ctypes import wintypes as W


def verify_ui(setup, root, service):
    """Native input, edited path, progress and finish; never touch live associations."""
    from PIL import Image

    from scripts.verify_installer import ROOT, uninstall, verify_payload

    user, gdi = C.WinDLL("user32", use_last_error=True), C.WinDLL("gdi32", use_last_error=True)
    callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    user.EnumWindows.argtypes = [callback_type, W.LPARAM]
    user.EnumChildWindows.argtypes = [W.HWND, callback_type, W.LPARAM]
    user.SendMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
    user.SendMessageW.restype = W.LPARAM
    user.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
    user.IsWindowVisible.argtypes = [W.HWND]
    user.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
    user.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
    user.GetWindowRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
    user.GetDC.argtypes = [W.HWND]
    user.GetDC.restype = W.HDC
    user.ReleaseDC.argtypes = [W.HWND, W.HDC]
    user.PrintWindow.argtypes = [W.HWND, W.HDC, W.UINT]
    gdi.CreateCompatibleDC.argtypes = [W.HDC]
    gdi.CreateCompatibleDC.restype = W.HDC
    gdi.CreateCompatibleBitmap.argtypes = [W.HDC, C.c_int, C.c_int]
    gdi.CreateCompatibleBitmap.restype = W.HBITMAP
    gdi.SelectObject.argtypes = [W.HDC, W.HGDIOBJ]
    gdi.SelectObject.restype = W.HGDIOBJ
    gdi.DeleteObject.argtypes = [W.HGDIOBJ]
    gdi.DeleteDC.argtypes = [W.HDC]
    gdi.GetDIBits.argtypes = [W.HDC, W.HBITMAP, W.UINT, W.UINT, C.c_void_p, C.c_void_p, W.UINT]

    def caption(hwnd, *, class_name=False):
        text = C.create_unicode_buffer(2048)
        function = user.GetClassNameW if class_name else user.GetWindowTextW
        function(hwnd, text, len(text))
        return text.value

    def windows(parent=None):
        found = []

        @callback_type
        def collect(hwnd, _):
            if user.IsWindowVisible(hwnd):
                found.append(hwnd)
            return True

        if parent:
            user.EnumChildWindows(parent, collect, 0)
        else:
            user.EnumWindows(collect, 0)
        return found

    def find(parent, text):
        return next((h for h in windows(parent) if caption(h) == text), None)

    def wait_for(predicate, description, seconds=120):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            result = predicate()
            if result:
                return result
            time.sleep(0.04)
        raise RuntimeError(f"Installer UI timed out: {description}")

    def click(hwnd):
        if not hwnd:
            raise RuntimeError("Installer UI control is missing")
        # Post avoids blocking the automation while Inno copies files or shows a modal.
        user.PostMessageW(hwnd, 0xF5, 0, 0)

    def rect(hwnd):
        value = W.RECT()
        if not user.GetWindowRect(hwnd, C.byref(value)):
            raise C.WinError(C.get_last_error())
        return value.left, value.top, value.right, value.bottom

    output = ROOT / "build/installer-ui"
    output.mkdir(parents=True, exist_ok=True)

    def snapshot(hwnd, name):
        left, top, right, bottom = rect(hwnd)
        width, height = right - left, bottom - top
        dc = user.GetDC(hwnd)
        memory = gdi.CreateCompatibleDC(dc)
        bitmap = gdi.CreateCompatibleBitmap(dc, width, height)
        previous = gdi.SelectObject(memory, bitmap)
        try:
            if not user.PrintWindow(hwnd, memory, 0):
                raise RuntimeError("Cannot capture the real installer window")
            gdi.SelectObject(memory, previous)
            # BITMAPINFOHEADER, uncompressed top-down 32-bit BGRA.
            import struct

            header = C.create_string_buffer(
                struct.pack(
                    "<IiiHHIIiiII", 40, width, -height, 1, 32, 0, width * height * 4, 0, 0, 0, 0
                )
            )
            pixels = C.create_string_buffer(width * height * 4)
            if gdi.GetDIBits(memory, bitmap, 0, height, pixels, header, 0) != height:
                raise RuntimeError("Cannot read installer screenshot")
            image = Image.frombytes("RGB", (width, height), pixels.raw, "raw", "BGRX")
            image.save(output / f"{name}.png")
            if name == "setup":
                colors = image.getcolors(width * height)
                if not colors or not any(
                    count > 10000 and color == (35, 35, 35) for count, color in colors
                ):
                    raise RuntimeError("Installer charcoal surface was not rendered")
        finally:
            gdi.SelectObject(memory, previous)
            gdi.DeleteObject(bitmap)
            gdi.DeleteDC(memory)
            user.ReleaseDC(hwnd, dc)

    target = root / "界面安装 自定义目录"
    process = subprocess.Popen(
        [
            str(setup),
            "/SP-",
            "/NORESTART",
            f"/DIR={root / 'initial path'}",
            "/TASKS=",
            f"/LOG={root / 'ui.log'}",
        ]
    )
    hwnd = None
    try:
        hwnd = wait_for(lambda: find(None, "揽映 Picer 安装程序"), "main window")
        wait_for(lambda: find(hwnd, "安装") and find(hwnd, "创建桌面快捷方式"), "setup controls")
        # Let the native directory -> task initialization complete before interacting.
        time.sleep(0.3)
        for text in ("创建桌面快捷方式", "加入 Windows 右键菜单", "设为默认图片浏览器"):
            control = find(hwnd, text)
            if user.SendMessageW(control, 0xF0, 0, 0) != 0:
                raise RuntimeError(f"Fresh optional task must be unchecked: {text}")
        launch = find(hwnd, "安装完成后启动揽映")
        if user.SendMessageW(launch, 0xF0, 0, 0) != 1:
            raise RuntimeError("Launch default was lost")
        click(launch)
        wait_for(lambda: user.SendMessageW(launch, 0xF0, 0, 0) == 0, "launch unchecked")
        for text in ("加入 Windows 右键菜单", "设为默认图片浏览器"):
            control = find(hwnd, text)
            click(control)
            wait_for(lambda control=control: user.SendMessageW(control, 0xF0, 0, 0) == 1, text)
        edit = next(h for h in windows(hwnd) if caption(h, class_name=True) == "TNewPathEdit")
        value = C.create_unicode_buffer(str(target))
        user.SendMessageW(edit, 0xC, 0, C.addressof(value))
        left, top, right, bottom = rect(hwnd)
        for child in windows(hwnd):
            x1, y1, x2, y2 = rect(child)
            if x1 < left or y1 < top or x2 > right or y2 > bottom:
                raise RuntimeError(f"Installer control outside window: {caption(child)}")
        snapshot(hwnd, "setup")
        click(find(hwnd, "安装"))
        wait_for(lambda: find(hwnd, "正在安装揽映"), "actual installation started")
        snapshot(hwnd, "installing")
        wait_for(lambda: find(hwnd, "安装完成"), "finished page")
        if not find(hwnd, str(target)):
            raise RuntimeError("Completed path does not match edited path")
        if user.SendMessageW(find(hwnd, "立即启动揽映"), 0xF0, 0, 0) != 0:
            raise RuntimeError("Launch checkbox changed between setup and finish")
        if not find(hwnd, "打开安装目录"):
            raise RuntimeError("Open installation folder action is missing")
        snapshot(hwnd, "finished")
        click(find(hwnd, "完成"))
        if process.wait(timeout=45) != 0:
            raise RuntimeError("Interactive installer failed")
        command = f'"{target / "Picer.exe"}" "%1"'
        if service.read(service.menu_key(".png") + r"\command", "") != command:
            raise RuntimeError("Interactive context-menu checkbox was ignored")
        if service.read(r"Software\Classes\Picer.Image\shell\open\command", "") != command:
            raise RuntimeError("Interactive default-viewer checkbox was ignored")
        verify_payload(ROOT / "dist/Picer", target)
        uninstall(target, root / "ui-uninstall.log")
        (output / "result.json").write_text(
            json.dumps(
                {
                    "passed": True,
                    "states": ["setup", "installing", "finished"],
                    "edited_path": True,
                    "checkboxes": True,
                }
            ),
            encoding="utf-8",
        )
        print(
            "Interactive installer: setup, edited path, tasks, progress and finish passed",
            flush=True,
        )
    except BaseException:
        if hwnd:
            (output / "controls.json").write_text(
                json.dumps(
                    [(caption(h, class_name=True), caption(h), rect(h)) for h in windows(hwnd)],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        log = root / "ui.log"
        if log.exists():
            print(log.read_text(encoding="utf-8-sig", errors="replace")[-12000:], flush=True)
        raise
    finally:
        if process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            process.wait(timeout=15)
