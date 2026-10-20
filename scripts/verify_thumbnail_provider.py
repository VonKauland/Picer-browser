"""Exercise the real packaged COM DLL without registering live Explorer classes."""

import ctypes
import hashlib
import sys
import tempfile
from pathlib import Path
from uuid import UUID

from PIL import Image

from picer.shell_thumbnail import PROVIDER_CLSID


def verify(application):
    if sys.platform != "win32":
        raise OSError("Native thumbnail provider verification requires Windows")
    from ctypes import wintypes as w

    class GUID(ctypes.Structure):
        _fields_ = [("a", w.DWORD), ("b", w.WORD), ("c", w.WORD), ("d", w.BYTE * 8)]

        def __init__(self, text):
            super().__init__()
            ctypes.memmove(ctypes.byref(self), UUID(text).bytes_le, 16)

    class Bitmap(ctypes.Structure):
        _fields_ = [
            ("kind", w.LONG),
            ("width", w.LONG),
            ("height", w.LONG),
            ("stride", w.LONG),
            ("planes", w.WORD),
            ("bits", w.WORD),
            ("pixels", ctypes.c_void_p),
        ]

    def method(pointer, index, result, *types):
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(result, ctypes.c_void_p, *types)(table[index])

    def release(pointer):
        if pointer.value:
            method(pointer, 2, w.ULONG)(pointer)

    def check(hr):
        if hr < 0:
            raise RuntimeError(f"Native thumbnail COM call failed: 0x{hr & 0xFFFFFFFF:08x}")

    dll_path = application / "shell/PicerThumbnail.dll"
    dll = ctypes.WinDLL(str(dll_path))
    get_factory = dll.DllGetClassObject
    get_factory.argtypes = [
        ctypes.POINTER(GUID),
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    get_factory.restype = w.LONG
    dll.DllCanUnloadNow.restype = w.LONG
    ole = ctypes.OleDLL("ole32")
    ole.CoInitializeEx(None, 2)
    sh = ctypes.WinDLL("shlwapi")
    sh.SHCreateStreamOnFileEx.argtypes = [
        w.LPCWSTR,
        w.DWORD,
        w.DWORD,
        w.BOOL,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    sh.SHCreateStreamOnFileEx.restype = w.LONG
    gdi = ctypes.WinDLL("gdi32")
    gdi.GetObjectW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    gdi.GetObjectW.restype = ctypes.c_int
    gdi.DeleteObject.argtypes = [ctypes.c_void_p]
    factory = ctypes.c_void_p()
    state = application / "config/plugins.json"
    before = state.read_bytes()
    try:
        check(
            get_factory(
                ctypes.byref(GUID(PROVIDER_CLSID)),
                ctypes.byref(GUID("00000001-0000-0000-C000-000000000046")),
                ctypes.byref(factory),
            )
        )
        with tempfile.TemporaryDirectory(prefix="picer-shell-test-") as temporary:
            folder = Path(temporary)
            image = folder / "照片 with spaces.png"
            Image.new("RGB", (180, 120), (180, 70, 20)).save(image)
            digest = hashlib.sha256(image.read_bytes()).digest()
            for source, success in ((image, True), (folder / "broken.png", False)):
                if not success:
                    source.write_bytes(b"not an image")
                initializer, provider, stream = (ctypes.c_void_p() for _ in range(3))
                bitmap = ctypes.c_void_p()
                try:
                    check(
                        method(
                            factory,
                            3,
                            w.LONG,
                            ctypes.c_void_p,
                            ctypes.POINTER(GUID),
                            ctypes.POINTER(ctypes.c_void_p),
                        )(
                            factory,
                            None,
                            ctypes.byref(GUID("B824B49D-22AC-4161-AC8A-9916E8FA3F7F")),
                            ctypes.byref(initializer),
                        )
                    )
                    check(
                        sh.SHCreateStreamOnFileEx(
                            str(source), 0x40, 0, False, None, ctypes.byref(stream)
                        )
                    )
                    check(
                        method(initializer, 3, w.LONG, ctypes.c_void_p, w.DWORD)(
                            initializer, stream, 0
                        )
                    )
                    check(
                        method(
                            initializer,
                            0,
                            w.LONG,
                            ctypes.POINTER(GUID),
                            ctypes.POINTER(ctypes.c_void_p),
                        )(
                            initializer,
                            ctypes.byref(GUID("E357FCCD-A995-4576-B01F-234630154E96")),
                            ctypes.byref(provider),
                        )
                    )
                    alpha = w.DWORD()
                    thumbnail = method(
                        provider,
                        3,
                        w.LONG,
                        w.UINT,
                        ctypes.POINTER(ctypes.c_void_p),
                        ctypes.POINTER(w.DWORD),
                    )
                    assert thumbnail(provider, 4096, ctypes.byref(bitmap), ctypes.byref(alpha)) < 0
                    assert not bitmap.value
                    result = thumbnail(provider, 128, ctypes.byref(bitmap), ctypes.byref(alpha))
                    if success:
                        check(result)
                        assert bitmap.value and alpha.value == 2
                        data = Bitmap()
                        assert gdi.GetObjectW(bitmap, ctypes.sizeof(data), ctypes.byref(data))
                        assert data.width == 128 and data.height == 85 and data.bits == 32
                        pixels = ctypes.string_at(data.pixels, data.stride * data.height)
                        center = data.stride * (data.height // 2) + (data.width // 2) * 4
                        assert pixels[center : center + 4] == bytes((20, 70, 180, 255))
                    else:
                        assert result < 0 and not bitmap.value
                finally:
                    if bitmap.value:
                        gdi.DeleteObject(bitmap)
                    for pointer in (provider, initializer, stream):
                        release(pointer)
            assert hashlib.sha256(image.read_bytes()).digest() == digest
        assert state.read_bytes() == before, "Thumbnail helper changed viewer preferences"
    finally:
        release(factory)
        assert dll.DllCanUnloadNow() == 0, "COM references leaked"
        ole.CoUninitialize()
        ctypes.windll.kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.FreeLibrary(dll._handle)
    print("Packaged native stream thumbnail provider, pixels, bad input and cleanup passed")


if __name__ == "__main__":
    verify(Path(__file__).resolve().parents[1] / "dist/Picer")
