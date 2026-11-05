"""Drive the real, non-silent installer against the isolated test registry."""

import base64
import ctypes as C
import hashlib
import json
import os
import subprocess
import time
from ctypes import wintypes as W
from io import BytesIO


def verify_ui(setup, root, service):
    """Native input, edited path, progress and finish; never touch live associations."""
    from PIL import Image, ImageGrab

    from scripts.verify_installer import ROOT, uninstall, verify_payload

    user = C.WinDLL("user32", use_last_error=True)
    dwm = C.WinDLL("dwmapi", use_last_error=True)
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
    user.SetCursorPos.argtypes = [C.c_int, C.c_int]
    user.mouse_event.argtypes = [W.DWORD, W.DWORD, W.DWORD, W.DWORD, C.c_size_t]
    user.SetForegroundWindow.argtypes = [W.HWND]
    user.SetWindowPos.argtypes = [W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT]
    user.RedrawWindow.argtypes = [W.HWND, C.c_void_p, W.HRGN, W.UINT]
    user.CreateWindowExW.argtypes = [
        W.DWORD,
        W.LPCWSTR,
        W.LPCWSTR,
        W.DWORD,
        C.c_int,
        C.c_int,
        C.c_int,
        C.c_int,
        W.HWND,
        W.HMENU,
        W.HINSTANCE,
        C.c_void_p,
    ]
    user.CreateWindowExW.restype = W.HWND
    user.DestroyWindow.argtypes = [W.HWND]
    user.UpdateWindow.argtypes = [W.HWND]
    user.SetThreadDpiAwarenessContext.argtypes = [W.HANDLE]
    user.SetThreadDpiAwarenessContext.restype = W.HANDLE
    user.GetDpiForWindow.argtypes = [W.HWND]
    user.GetDpiForWindow.restype = W.UINT
    dwm.DwmGetWindowAttribute.argtypes = [W.HWND, W.DWORD, C.c_void_p, W.DWORD]
    previous_dpi = user.SetThreadDpiAwarenessContext(W.HANDLE(-4))

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
        return next(
            (
                h
                for h in windows(parent)
                if (caption(h) == text or caption(h).replace("&", "") == text)
            ),
            None,
        )

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
        left, top, right, bottom = rect(hwnd)
        x = left + 12 if caption(hwnd, class_name=True) == "TNewCheckBox" else (left + right) // 2
        user.SetCursorPos(x, (top + bottom) // 2)
        # Real mouse input exercises hover, focus, pressed and native check behavior.
        user.mouse_event(2, 0, 0, 0, 0)
        time.sleep(0.02)
        user.mouse_event(4, 0, 0, 0, 0)

    def rect(hwnd):
        value = W.RECT()
        if not user.GetWindowRect(hwnd, C.byref(value)):
            raise C.WinError(C.get_last_error())
        return value.left, value.top, value.right, value.bottom

    output = ROOT / "build/installer-ui"
    output.mkdir(parents=True, exist_ok=True)

    captures = {}
    backdrop = None

    def export_capture(name, image):
        if os.environ.get("PICER_INSTALLER_CAPTURE_LOG") != "1":
            return
        data = BytesIO()
        image.save(data, format="PNG")
        encoded = base64.b64encode(data.getvalue()).decode()
        print(f"INSTALLER_CAPTURE_BEGIN:{name}:{hashlib.sha256(data.getvalue()).hexdigest()}")
        for offset in range(0, len(encoded), 4096):
            print(
                f"INSTALLER_CAPTURE_CHUNK:{name}:{offset // 4096}:{encoded[offset : offset + 4096]}"
            )
        print(f"INSTALLER_CAPTURE_END:{name}", flush=True)

    def snapshot(hwnd, name):
        nonlocal backdrop
        left, top, right, bottom = rect(hwnd)
        # A real neutral desktop window makes translucent DWM corner coverage visible.
        # It never paints over the installer or alters the captured application pixels.
        if not backdrop:
            backdrop = user.CreateWindowExW(
                0x08000080,
                "STATIC",
                "Picer screenshot backdrop",
                0x90000004,
                left - 8,
                top - 8,
                right - left + 16,
                bottom - top + 16,
                None,
                None,
                None,
                None,
            )
            if not backdrop:
                raise C.WinError(C.get_last_error())
        user.SetWindowPos(
            backdrop, W.HWND(-1), left - 8, top - 8, right - left + 16, bottom - top + 16, 0x50
        )
        user.UpdateWindow(backdrop)
        user.SetWindowPos(hwnd, W.HWND(-1), 0, 0, 0, 0, 0x43)
        user.SetForegroundWindow(hwnd)
        user.RedrawWindow(hwnd, None, None, 0x585)
        dwm.DwmFlush()
        time.sleep(0.08)
        left, top, right, bottom = rect(hwnd)
        box = (left - 8, top - 8, right + 8, bottom + 8)
        image = ImageGrab.grab(bbox=box, include_layered_windows=True).convert("RGB")
        image.save(output / f"{name}.png")
        export_capture(name, image)

        def white(pixel):
            return min(pixel) > 185 and max(pixel) - min(pixel) < 35

        inspected = []
        for child in windows(hwnd):
            kind = caption(child, class_name=True)
            if kind not in {"TNewButton", "TNewCheckBox"}:
                continue
            x1, y1, x2, y2 = rect(child)
            x1 -= box[0]
            x2 -= box[0]
            y1 -= box[1]
            y2 -= box[1]
            pixels = [image.getpixel((x, y)) for x in range(x1, x2) for y in (y1, y2 - 1)]
            pixels += [image.getpixel((x, y)) for y in range(y1, y2) for x in (x1, x2 - 1)]
            if any(white(pixel) for pixel in pixels):
                raise RuntimeError(f"Native white frame leaked around {caption(child)!r}")
            inspected.append(caption(child))
        if name == "installing":
            # Contract: the progress track must never reveal its bitmap's white edges.
            scale = (right - left) / 1000
            x, y = round(358 * scale) + 8, round(264 * scale) + 8
            width, height = round(584 * scale), round(16 * scale)
            perimeter = [
                image.getpixel((px, py)) for px in range(x, x + width) for py in (y, y + height - 1)
            ]
            perimeter += [
                image.getpixel((px, py)) for py in range(y, y + height) for px in (x, x + width - 1)
            ]
            if any(white(pixel) for pixel in perimeter):
                raise RuntimeError("Progress bitmap exposes a white edge")
        corner = C.c_int()
        native_rounding = dwm.DwmGetWindowAttribute(hwnd, 33, C.byref(corner), 4) == 0
        if native_rounding:
            if corner.value != 2 or max(image.getpixel((8, 8))) >= 25:
                raise RuntimeError("DWM is not composing a rounded outer corner")
            colors = set(image.crop((8, 8, 20, 20)).getdata())
            if len(colors) < 6:
                raise RuntimeError("Window corner lacks antialiased coverage")
        captures[name] = {
            "capture": "Windows desktop / ImageGrab",
            "dpi": user.GetDpiForWindow(hwnd),
            "native_rounded_frame": native_rounding,
            "white_frame_checks": inspected,
        }

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
        snapshot(hwnd, "setup-initial")
        print(
            "Installer initial controls:",
            json.dumps([(caption(h, class_name=True), caption(h), h) for h in windows(hwnd)]),
            flush=True,
        )
        # Let the native directory -> task initialization complete before interacting.
        time.sleep(0.3)
        for text in ("创建桌面快捷方式", "加入 Windows 右键菜单", "设为默认图片浏览器"):
            control = find(hwnd, text)
            if not control or user.SendMessageW(control, 0xF0, 0, 0) != 0:
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
        browse = find(hwnd, "浏览")
        bx1, by1, bx2, by2 = rect(browse)
        user.SetCursorPos((bx1 + bx2) // 2, (by1 + by2) // 2)
        time.sleep(0.18)
        snapshot(hwnd, "setup-hover")
        click(find(hwnd, "安装"))
        wait_for(
            lambda: find(hwnd, "正在安装揽映") and find(hwnd, "安装进度"),
            "actual installation started",
        )
        snapshot(hwnd, "installing")
        wait_for(
            lambda: find(hwnd, "安装完成") and find(hwnd, str(target)) and find(hwnd, "完成"),
            "finished page and edited path",
        )
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
        if "Installer UI callback failed" in (root / "ui.log").read_text(
            encoding="utf-8-sig", errors="replace"
        ):
            raise RuntimeError("Installer renderer reported a callback failure")
        verify_payload(ROOT / "dist/Picer", target)
        uninstall(target, root / "ui-uninstall.log")
        (output / "result.json").write_text(
            json.dumps(
                {
                    "passed": True,
                    "states": ["setup", "installing", "finished"],
                    "edited_path": True,
                    "checkboxes": True,
                    "screenshots": captures,
                }
            ),
            encoding="utf-8",
        )
        print(
            "Interactive installer: setup, edited path, tasks, progress and finish passed",
            flush=True,
        )
    except BaseException:
        time.sleep(0.5)
        print(
            "Installer launcher result:",
            process.poll(),
            "top windows:",
            json.dumps([(h, caption(h, class_name=True), caption(h)) for h in windows()]),
            flush=True,
        )
        preview = output / "setup.png"
        if preview.exists():
            encoded = BytesIO()
            Image.open(preview).resize((800, 512)).save(encoded, format="JPEG", quality=65)
            print(
                "INSTALLER_UI_PREVIEW_BASE64:" + base64.b64encode(encoded.getvalue()).decode(),
                flush=True,
            )
        if hwnd:
            print(
                "Installer visible controls:",
                json.dumps(
                    [(caption(h, class_name=True), caption(h), rect(h)) for h in windows(hwnd)]
                ),
                flush=True,
            )
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
            print(
                log.read_text(encoding="utf-8-sig", errors="replace")[-12000:]
                .encode("ascii", "backslashreplace")
                .decode(),
                flush=True,
            )
        raise
    finally:
        if backdrop:
            user.DestroyWindow(backdrop)
        if previous_dpi:
            user.SetThreadDpiAwarenessContext(previous_dpi)
        if process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            process.wait(timeout=15)
