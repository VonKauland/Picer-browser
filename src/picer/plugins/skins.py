"""Declarative skin packages: validate every resource before changing the host."""

import json
import re
from pathlib import Path

from picer.chrome import STYLE
from picer.plugins.api import PluginError

COLORS = {
    "background": "#191b1f",
    "title": "#202226",
    "text": "#e5e6e8",
    "menu": "#25272c",
    "border": "#3a3d44",
    "hover": "#35383e",
    "muted": "#92969e",
}


def load_skin(directory: Path, theme: str) -> tuple[str, dict[str, str]]:
    try:
        path = directory / theme
        if path.stat().st_size > 64 * 1024:
            raise ValueError("皮肤定义不能超过 64 KiB")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("colors", {}), dict):
            raise ValueError("皮肤 colors 必须为对象")
        colors = dict(COLORS)
        for key, value in data.get("colors", {}).items():
            if (
                key not in COLORS
                or not isinstance(value, str)
                or not re.fullmatch(r"#[0-9a-fA-F]{6}", value)
            ):
                raise ValueError(f"无效皮肤颜色：{key}")
            colors[key] = value
        # Replace original color tokens in one pass, avoiding cascading replacements.
        replacements = {COLORS[key]: value for key, value in colors.items()}
        style = re.sub(
            r"#[0-9a-fA-F]{6}", lambda match: replacements.get(match[0], match[0]), STYLE
        )
        stylesheet = data.get("stylesheet", "")
        if not isinstance(stylesheet, str):
            raise ValueError("stylesheet 必须为字符串")
        if stylesheet:
            if not isinstance(stylesheet, str) or not re.fullmatch(
                r"[a-zA-Z0-9_-]+\.qss", stylesheet
            ):
                raise ValueError("stylesheet 必须为包内 QSS 文件名")
            extra = directory / stylesheet
            if extra.stat().st_size > 256 * 1024:
                raise ValueError("QSS 不能超过 256 KiB")
            style += "\n" + extra.read_text(encoding="utf-8")
        return style, colors
    except (OSError, ValueError, UnicodeError) as error:
        raise PluginError(f"皮肤读取失败：{error}") from error
