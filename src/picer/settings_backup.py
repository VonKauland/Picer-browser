"""Versioned system-settings transfer, independent of executable plugin packages."""

import copy
import json
import tempfile
from pathlib import Path

from PySide6.QtGui import QKeySequence

from picer.color_editor import valid_accent
from picer.i18n import tr
from picer.input_bindings import binding_conflict, normalize, read_bindings
from picer.panels import DOCK_AREAS
from picer.plugins.manifest import IDENTIFIER
from picer.preferences import CHOICES, DEFAULTS, RANGES, read_preferences

FORMAT = "picer-settings"
MAX_BYTES = 8 * 1048576


def validate_backup(data, host):
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError(tr("请选择揽映导出的设置 JSON 文件。"))
    if type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError(tr("此设置文件的版本暂不支持。"))
    fields = {"format", "version", "application", "input_bindings", "skin", "panels", "quick_slots"}
    if set(data) != fields:
        raise ValueError(tr("设置文件缺少必要内容或包含未知字段。"))
    application = data["application"]
    if not isinstance(application, dict) or set(application) - set(DEFAULTS):
        raise ValueError(tr("系统设置字段无效。"))
    values = dict(DEFAULTS)
    for key, value in application.items():
        default = DEFAULTS[key]
        if key == "readable_formats":
            from picer.formats import valid_formats

            valid = valid_formats(value)
        elif key == "accent_color":
            valid = valid_accent(value)
        elif key in CHOICES:
            valid = isinstance(value, str) and value in CHOICES[key]
        elif type(default) is bool:
            valid = type(value) is bool
        else:
            valid = type(value) is int and RANGES[key][0] <= value <= RANGES[key][1]
        if not valid:
            raise ValueError(tr("系统设置「{0}」的类型或取值无效。").format(key))
        values[key] = value.upper() if key == "accent_color" else value
    profiles = data["input_bindings"]
    if not isinstance(profiles, dict) or len(profiles) > 512:
        raise ValueError(tr("输入绑定结构无效。"))
    bindings, claimed, keyboard = {}, {}, {}
    for key, entries in profiles.items():
        if not isinstance(key, str) or not 1 <= len(key) <= 256:
            raise ValueError(tr("输入绑定的操作名称无效。"))
        if not isinstance(entries, list) or len(entries) > 32:
            raise ValueError(tr("每项操作最多可有 32 个输入绑定。"))
        bindings[key] = []
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"device", "value"}:
                raise ValueError(tr("输入绑定内容无效。"))
            device = entry["device"]
            if device not in ("keyboard", "mouse", "touch", "gamepad"):
                raise ValueError(tr("输入绑定的设备类型无效。"))
            value = normalize(device, entry["value"])
            if not value:
                raise ValueError(tr("输入绑定的按键无效。"))
            binding = {"device": device, "value": value}
            if device == "keyboard":
                sequence, node = QKeySequence(value), keyboard
                for index in range(sequence.count()):
                    if None in node:
                        raise ValueError(tr("设置文件中的输入绑定「{0}」存在冲突。").format(value))
                    node = node.setdefault(sequence[index].toCombined(), {})
                if node:
                    raise ValueError(tr("设置文件中的输入绑定「{0}」存在冲突。").format(value))
                node[None] = True
            else:
                previous = claimed.setdefault(device, [])
                if any(binding_conflict(binding, old) for old in previous):
                    raise ValueError(tr("设置文件中的输入绑定「{0}」存在冲突。").format(value))
                previous.append(binding)
            bindings[key].append(binding)
    skin = data["skin"]
    if not isinstance(skin, str) or skin and not IDENTIFIER.fullmatch(skin):
        raise ValueError(tr("皮肤名称无效。"))
    if skin:
        record = host.plugins.records.get(skin)
        if record is None or record.manifest.type != "skin":
            raise ValueError(tr("设置文件使用的皮肤未安装，请先在插件管理中安装对应皮肤。"))
    panels = data["panels"]
    if not isinstance(panels, dict) or len(panels) > 512:
        raise ValueError(tr("面板布局无效。"))
    for key, layout in panels.items():
        if not isinstance(key, str) or not IDENTIFIER.fullmatch(key):
            raise ValueError(tr("面板名称无效。"))
        required = {"area", "width", "height", "fixed"}
        if (
            not isinstance(layout, dict)
            or not required <= set(layout)
            or set(layout) - required - {"order"}
        ):
            raise ValueError(tr("面板布局内容无效。"))
        if "order" in layout and (
            type(layout["order"]) is not int or not 0 <= layout["order"] <= 10000
        ):
            raise ValueError(tr("面板顺序无效。"))
        if not isinstance(layout["area"], str) or layout["area"] not in DOCK_AREAS:
            raise ValueError(tr("面板停靠位置无效。"))
        minimum_height = 16 if layout["area"] == "bottom" else 80
        if (
            type(layout["fixed"]) is not bool
            or type(layout["width"]) is not int
            or not 80 <= layout["width"] <= 4096
            or type(layout["height"]) is not int
            or not minimum_height <= layout["height"] <= 4096
        ):
            raise ValueError(tr("面板尺寸或固定状态无效。"))
        record = host.plugins.records.get(key)
        if record and (
            record.manifest.type != "panel"
            or (layout["area"] == "bottom") != (record.manifest.panel_role == "progress")
        ):
            raise ValueError(tr("底部仅允许进度面板，侧边面板只能停靠在左右两侧。"))
    slots = data["quick_slots"]
    if (
        not isinstance(slots, list)
        or len(slots) != 5
        or any(not isinstance(value, str) or len(value) > 256 for value in slots)
    ):
        raise ValueError(tr("快捷栏位必须为 5 个功能名称。"))
    return {
        "format": FORMAT,
        "version": 1,
        "application": values,
        "input_bindings": bindings,
        "skin": skin,
        "panels": copy.deepcopy(panels),
        "quick_slots": slots.copy(),
    }


def snapshot(host):
    panels = {}
    ui = host.plugins.preferences["ui"]
    layouts, fixed = ui.get("panel_layouts", {}), ui.get("panels", {})
    if isinstance(layouts, dict) and isinstance(fixed, dict):
        for key, layout in layouts.items():
            if isinstance(layout, dict) and layout.get("area") in DOCK_AREAS:
                panels[key] = {**layout, "fixed": fixed.get(key, True)}
    for key, controller in host.panel_hovers.controllers.items():
        panels[key] = {
            "area": next(name for name, area in DOCK_AREAS.items() if area == controller.area),
            **controller.extents,
            "order": controller.order,
            "fixed": fixed.get(key, True) if isinstance(fixed, dict) else True,
        }
    data = {
        "format": FORMAT,
        "version": 1,
        "application": read_preferences(host.plugins),
        "input_bindings": read_bindings(host),
        "skin": next(
            (
                key
                for key, r in host.plugins.records.items()
                if r.manifest.type == "skin" and r.state == "enabled"
            ),
            "",
        ),
        "panels": panels,
        "quick_slots": host.components.assignments(),
    }
    return validate_backup(data, host)


def write_backup(path, host):
    path = Path(path)
    if path.resolve() == host.plugins.state_file.resolve():
        raise ValueError(tr("请将导出文件另存为备份，不要覆盖应用正在使用的配置文件。"))
    content = json.dumps(snapshot(host), ensure_ascii=False, indent=2, allow_nan=False)
    if len(content.encode("utf-8")) > MAX_BYTES:
        raise ValueError(tr("设置文件过大。"))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as file:
            temporary = Path(file.name)
            file.write(content)
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def read_backup(path, host):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(tr("设置文件中含有重复字段。"))
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(tr("设置文件中不能含有非有限数值。"))

    try:
        with Path(path).open("rb") as file:
            content = file.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise ValueError(tr("设置文件不能超过 8 MiB。"))
        data = json.loads(
            content.decode("utf-8-sig"),
            object_pairs_hook=object_pairs,
            parse_constant=invalid_constant,
        )
        return validate_backup(data, host)
    except (UnicodeError, RecursionError) as error:
        raise ValueError(tr("设置文件的编码或结构无效。")) from error
