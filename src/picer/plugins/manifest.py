"""Validate metadata before importing any plugin code."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from picer.plugins.api import PERMISSIONS, PluginError

IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*")
VERSION = re.compile(r"\d+\.\d+\.\d+")
ENTRYPOINT = re.compile(r"([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*):([a-zA-Z_]\w*)")


@dataclass(frozen=True)
class Manifest:
    id: str
    name: str
    version: str
    api_version: int
    entrypoint: str
    description: str = ""
    author: str = ""
    permissions: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    type: str = "function"
    theme: str = "theme.json"
    legacy: bool = False

    @classmethod
    def read(cls, path: Path) -> "Manifest":
        try:
            if path.stat().st_size > 64 * 1024:
                raise PluginError("manifest.json 过大")
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise PluginError("插件清单必须为 JSON 对象")
            kind = data.get("type", "function")
            if not isinstance(kind, str) or kind not in {"skin", "function", "panel"}:
                raise PluginError("type 必须为 skin、function 或 panel")
            for field in ("id", "name", "version"):
                if not isinstance(data.get(field), str) or not data[field].strip():
                    raise PluginError(f"缺少有效字段：{field}")
            if not IDENTIFIER.fullmatch(data["id"]):
                raise PluginError("插件 id 必须是小写字母开头的点分标识符")
            if not VERSION.fullmatch(data["version"]):
                raise PluginError("version 必须为 major.minor.patch")
            if type(data.get("api_version")) is not int:
                raise PluginError("api_version 必须为整数")
            entrypoint = data.get("entrypoint", "")
            if not isinstance(entrypoint, str):
                raise PluginError("entrypoint 必须为字符串")
            if kind != "skin" and (
                not isinstance(entrypoint, str) or not ENTRYPOINT.fullmatch(entrypoint)
            ):
                raise PluginError("entrypoint 必须为 module:Class")
            theme = data.get("theme", "theme.json")
            if not isinstance(theme, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+\.json", theme):
                raise PluginError("theme 必须为包内 JSON 文件名")
            for field in ("permissions", "requires"):
                values = data.get(field, [])
                if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
                    raise PluginError(f"{field} 必须为字符串数组")
                if len(values) != len(set(values)):
                    raise PluginError(f"{field} 含重复项")
            if set(data.get("permissions", [])) - PERMISSIONS:
                raise PluginError("插件包含未知权限")
            if any(not IDENTIFIER.fullmatch(v) for v in data.get("requires", [])):
                raise PluginError("requires 含无效插件 id")
            for field in ("description", "author"):
                if not isinstance(data.get(field, ""), str):
                    raise PluginError(f"{field} 必须为字符串")
            if kind == "skin" and (data.get("permissions") or data.get("requires") or entrypoint):
                raise PluginError("皮肤必须为无入口、无权限、无依赖的声明式资源包")
            if kind == "panel" and "ui.panels" not in data.get("permissions", []):
                raise PluginError("面板组件必须声明 ui.panels 权限")
            if kind != "panel" and "ui.panels" in data.get("permissions", []):
                raise PluginError("只有面板组件可声明 ui.panels")
            return cls(
                **{key: data[key] for key in ("id", "name", "version", "api_version")},
                entrypoint=entrypoint,
                type=kind,
                theme=theme,
                legacy="type" not in data,
                description=data.get("description", ""),
                author=data.get("author", ""),
                permissions=tuple(data.get("permissions", [])),
                requires=tuple(data.get("requires", [])),
            )
        except (OSError, UnicodeError, ValueError, TypeError) as error:
            raise PluginError(f"清单读取失败：{error}") from error
