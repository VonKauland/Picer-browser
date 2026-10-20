"""Enumerate disk shares through Windows NetShareEnum, off the GUI thread."""

import ctypes
import os
from ctypes import wintypes
from pathlib import Path

from picer.i18n import tr


def list_shares(server, token):
    if os.name != "nt":
        raise OSError(tr("网络服务器根目录需要 Windows"))

    class ShareInfo(ctypes.Structure):
        _fields_ = [
            ("name", wintypes.LPWSTR),
            ("kind", wintypes.DWORD),
            ("remark", wintypes.LPWSTR),
        ]

    api = ctypes.WinDLL(str(Path(os.environ["SystemRoot"]) / "System32" / "Netapi32.dll"))
    api.NetShareEnum.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    api.NetShareEnum.restype = wintypes.DWORD
    api.NetApiBufferFree.argtypes = [ctypes.c_void_p]
    api.NetApiBufferFree.restype = wintypes.DWORD
    resume, result = wintypes.DWORD(), []
    for _ in range(8):
        token.checkpoint()
        buffer, count, total = ctypes.c_void_p(), wintypes.DWORD(), wintypes.DWORD()
        try:
            status = api.NetShareEnum(
                server,
                1,
                ctypes.byref(buffer),
                65536,
                ctypes.byref(count),
                ctypes.byref(total),
                ctypes.byref(resume),
            )
            if status not in (0, 234):
                raise OSError(tr("无法列出共享文件夹（Windows 错误 {0}）").format(status))
            if count.value > 4096 or (count.value and not buffer.value):
                raise OSError(tr("服务器返回了无效的共享列表"))
            rows = ctypes.cast(buffer, ctypes.POINTER(ShareInfo))
            for i in range(count.value):
                token.checkpoint()
                name = rows[i].name
                if (rows[i].kind & 0xFFFF) == 0 and name and not name.endswith("$"):
                    result.append({"name": name, "path": server + "\\" + name})
                if len(result) >= 256:
                    return result
            if status == 0:
                return sorted(result, key=lambda row: row["name"].casefold())
        finally:
            if buffer.value:
                api.NetApiBufferFree(buffer)
    raise OSError(tr("共享列表过大，请直接添加需要的共享路径"))
