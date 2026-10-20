"""Pure detached-pixel operations and guarded atomic still-image saving."""

import copy
import math
import os
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtGui import QImage

from picer.i18n import tr
from picer.imaging import MAX_PIXELS, read_image

DEFAULTS = {
    "crop": {"enabled": False, "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
    "resize": {
        "enabled": False,
        "width": 1920,
        "height": 1280,
        "linked": True,
        "method": "lanczos",
    },
    "rotate": {"enabled": False, "angle": 0.0},
    "mirror": {"enabled": False, "horizontal": False, "vertical": False},
    "levels": {
        "enabled": False,
        "channel": "RGB",
        "black": 0,
        "mid": 1.0,
        "white": 255,
        "out_black": 0,
        "out_white": 255,
    },
    "hsl": {"enabled": False, "hue": 0, "saturation": 0, "lightness": 0},
    "selective": {"enabled": False, "hue": 120, "range": 25, "softness": 20},
    "pixelate": {"enabled": False, "size": 16},
    "curves": {
        "enabled": False,
        "channel": "RGB",
        "points": {key: [[0, 0], [255, 255]] for key in ("RGB", "R", "G", "B")},
    },
}
SAVE_FORMATS = {
    ".png": "PNG",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".webp": "WEBP",
    ".bmp": "BMP",
    ".tif": "TIFF",
    ".tiff": "TIFF",
}


def defaults(size=(1920, 1280)):
    state = copy.deepcopy(DEFAULTS)
    state["resize"].update(width=size[0], height=size[1])
    return state


def validate(state):
    """Reject malformed presets before changing controls or allocating pixels."""
    if not isinstance(state, dict) or set(state) != set(DEFAULTS):
        raise ValueError(tr("预设修改器不完整"))
    result = copy.deepcopy(state)
    for key, spec in DEFAULTS.items():
        row = result[key]
        if not isinstance(row, dict) or set(row) != set(spec) or type(row["enabled"]) is not bool:
            raise ValueError(tr("预设参数无效"))
    limits = {
        "crop": {"x": (0, 1), "y": (0, 1), "w": (0.000001, 1), "h": (0.000001, 1)},
        "resize": {"width": (1, 30000), "height": (1, 30000)},
        "rotate": {"angle": (-180, 180)},
        "levels": {
            "black": (0, 254),
            "white": (1, 255),
            "mid": (0.1, 10),
            "out_black": (0, 255),
            "out_white": (0, 255),
        },
        "hsl": {"hue": (-180, 180), "saturation": (-100, 100), "lightness": (-100, 100)},
        "selective": {"hue": (0, 359), "range": (0, 180), "softness": (0, 100)},
        "pixelate": {"size": (1, 512)},
    }
    for key, bounds in limits.items():
        for field, (low, high) in bounds.items():
            value = result[key][field]
            if type(value) not in (int, float) or not low <= value <= high:
                raise ValueError(tr("预设数值超出范围"))
            if field not in {"x", "y", "w", "h", "angle", "mid"} and int(value) != value:
                raise ValueError(tr("预设须使用整数像素或参数"))
            if field not in {"x", "y", "w", "h", "angle", "mid"}:
                result[key][field] = int(value)
    if result["crop"]["x"] + result["crop"]["w"] > 1.000001 or (
        result["crop"]["y"] + result["crop"]["h"] > 1.000001
    ):
        raise ValueError(tr("裁剪范围超出图片"))
    resize = result["resize"]
    if resize["width"] * resize["height"] > MAX_PIXELS:
        raise ValueError(tr("输出超过 1.2 亿像素上限"))
    if resize["method"] not in {"lanczos", "bicubic", "nearest"}:
        raise ValueError(tr("未知插值算法"))
    for value in (resize["linked"], result["mirror"]["horizontal"], result["mirror"]["vertical"]):
        if type(value) is not bool:
            raise ValueError(tr("预设开关无效"))
    if result["levels"]["black"] >= result["levels"]["white"]:
        raise ValueError(tr("黑场必须小于白场"))
    for key in ("levels", "curves"):
        if result[key]["channel"] not in {"RGB", "R", "G", "B"}:
            raise ValueError(tr("未知颜色通道"))
    points = result["curves"]["points"]
    if not isinstance(points, dict) or set(points) != {"RGB", "R", "G", "B"}:
        raise ValueError(tr("曲线通道无效"))
    for nodes in points.values():
        if not isinstance(nodes, list) or not 2 <= len(nodes) <= 16:
            raise ValueError(tr("曲线须包含 2 至 16 个节点"))
        previous = -1
        for node in nodes:
            if not isinstance(node, list) or len(node) != 2:
                raise ValueError(tr("曲线节点无效"))
            x, y = node
            if any(type(v) not in (int, float) or not 0 <= v <= 255 for v in node) or x <= previous:
                raise ValueError(tr("曲线节点须按输入值递增"))
            previous = x
    return result


def to_pillow(image):
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombytes(
        "RGBA",
        (image.width(), image.height()),
        bytes(image.constBits()),
        "raw",
        "RGBA",
        image.bytesPerLine(),
    )


def output_size(native, state):
    w, h = native
    c = state["crop"]
    if c["enabled"]:
        w, h = max(1, round(w * c["w"])), max(1, round(h * c["h"]))
    if state["resize"]["enabled"]:
        w, h = state["resize"]["width"], state["resize"]["height"]
    angle = state["rotate"]["angle"] if state["rotate"]["enabled"] else 0
    if angle:
        a = math.radians(angle)
        w, h = (
            math.ceil(abs(w * math.cos(a)) + abs(h * math.sin(a)) - 1e-8),
            math.ceil(abs(w * math.sin(a)) + abs(h * math.cos(a)) - 1e-8),
        )
    return int(w), int(h)


def render(source, state, *, native=None, edge=0, token=None):
    state = validate(state)
    native = native or source.size
    target = output_size(native, state)
    if target[0] * target[1] > MAX_PIXELS:
        raise ValueError(tr("旋转后的输出超过 1.2 亿像素上限"))
    check = token.checkpoint if token else lambda: None
    check()
    image = source.convert("RGBA")
    c = state["crop"]
    if c["enabled"]:
        w, h = image.size
        left, top = min(w - 1, round(w * c["x"])), min(h - 1, round(h * c["y"]))
        image = image.crop(
            (
                left,
                top,
                min(w, max(left + 1, round(w * (c["x"] + c["w"])))),
                min(h, max(top + 1, round(h * (c["y"] + c["h"])))),
            )
        )
    r = state["resize"]
    if r["enabled"]:
        size = (int(r["width"]), int(r["height"]))
        if edge and max(size) > edge:
            size = tuple(max(1, round(v * edge / max(size))) for v in size)
        image = image.resize(
            size,
            {
                "lanczos": Image.Resampling.LANCZOS,
                "bicubic": Image.Resampling.BICUBIC,
                "nearest": Image.Resampling.NEAREST,
            }[r["method"]],
        )
    if state["rotate"]["enabled"]:
        image = image.rotate(
            -state["rotate"]["angle"], expand=True, resample=Image.Resampling.BICUBIC
        )
    if state["mirror"]["enabled"]:
        if state["mirror"]["horizontal"]:
            image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if state["mirror"]["vertical"]:
            image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    check()
    if edge:
        image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    # Process color rows in bounded chunks, permitting cancellation for very large files.
    colored = any(state[k]["enabled"] for k in ("levels", "hsl", "selective", "curves"))
    if colored:
        result = Image.new("RGBA", image.size)
        for y in range(0, image.height, 128):
            check()
            band = np.array(image.crop((0, y, image.width, min(y + 128, image.height))))
            rgb = band[..., :3].astype(np.float32) / 255
            levels = state["levels"]
            if levels["enabled"]:
                channels = (
                    slice(None) if levels["channel"] == "RGB" else "RGB".index(levels["channel"])
                )
                rgb[..., channels] = (
                    np.clip(
                        (rgb[..., channels] * 255 - levels["black"])
                        / (levels["white"] - levels["black"]),
                        0,
                        1,
                    )
                    ** (1 / levels["mid"])
                    * (levels["out_white"] - levels["out_black"])
                    / 255
                    + levels["out_black"] / 255
                )
            if state["hsl"]["enabled"]:
                rgb = adjust_hsl(rgb, state["hsl"])
            if state["selective"]["enabled"]:
                row = state["selective"]
                hue, saturation, _ = rgb_to_hsl(rgb)
                distance = np.abs((hue * 360 - row["hue"] + 180) % 360 - 180)
                feather = row["softness"] * 1.8
                keep = (
                    (distance <= row["range"]).astype(np.float32)
                    if not feather
                    else np.clip((row["range"] + feather - distance) / feather, 0, 1)
                )
                keep *= np.minimum(1, saturation * 20)
                gray = (rgb * np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)).sum(axis=2)
                rgb = gray[..., None] + (rgb - gray[..., None]) * keep[..., None]
            if state["curves"]["enabled"]:
                for channel in ("RGB", "R", "G", "B"):
                    nodes = state["curves"]["points"][channel]
                    lut = np.interp(np.arange(256), *np.array(nodes).T) / 255
                    if channel == "RGB":
                        rgb = lut[np.clip(np.rint(rgb * 255), 0, 255).astype(np.uint8)]
                    else:
                        n = "RGB".index(channel)
                        rgb[..., n] = lut[
                            np.clip(np.rint(rgb[..., n] * 255), 0, 255).astype(np.uint8)
                        ]
            band[..., :3] = np.rint(np.clip(rgb, 0, 1) * 255).astype(np.uint8)
            result.paste(Image.fromarray(band), (0, y))
        image = result
    if state["pixelate"]["enabled"]:
        block = state["pixelate"]["size"]
        if edge:
            block = max(1, round(block * max(image.size) / max(target)))
        small = (max(1, math.ceil(image.width / block)), max(1, math.ceil(image.height / block)))
        image = image.resize(small, Image.Resampling.BOX).resize(
            image.size, Image.Resampling.NEAREST
        )
    check()
    return image, target


def rgb_to_hsl(rgb):
    maximum, minimum = rgb.max(axis=2), rgb.min(axis=2)
    delta = maximum - minimum
    light = (maximum + minimum) / 2
    sat = np.divide(
        delta,
        1 - np.abs(2 * light - 1),
        out=np.zeros_like(delta),
        where=(delta > 1e-7) & (light > 0) & (light < 1),
    )
    hue = np.zeros_like(delta)
    for n, shift in ((0, 0), (1, 2), (2, 4)):
        mask = (maximum == rgb[..., n]) & (delta > 1e-7)
        value = np.divide(
            rgb[..., (n + 1) % 3] - rgb[..., (n + 2) % 3],
            delta,
            out=np.zeros_like(delta),
            where=delta > 1e-7,
        )
        hue = np.where(mask, (value + shift) / 6, hue)
    return hue % 1, sat, light


def adjust_hsl(rgb, row):
    h, s, light = rgb_to_hsl(rgb)
    h = (h + row["hue"] / 360) % 1
    delta = row["saturation"] / 100
    s = np.clip(s + delta * (1 - s) if delta >= 0 else s * (1 + delta), 0, 1)
    delta = row["lightness"] / 100
    light = np.clip(light + delta * (1 - light) if delta >= 0 else light * (1 + delta), 0, 1)
    chroma = (1 - np.abs(2 * light - 1)) * s
    x = chroma * (1 - np.abs(h * 6 % 2 - 1))
    zero = np.zeros_like(h)
    parts = (
        (chroma, x, zero),
        (x, chroma, zero),
        (zero, chroma, x),
        (zero, x, chroma),
        (x, zero, chroma),
        (chroma, zero, x),
    )
    output = np.zeros_like(rgb)
    for n, part in enumerate(parts):
        mask = (h * 6 >= n) & (h * 6 < n + 1)
        output[mask] = np.stack(part, axis=2)[mask]
    return output + (light - chroma / 2)[..., None]


def fingerprint(path):
    stat = Path(path).stat()
    return stat.st_mtime_ns, stat.st_size, stat.st_ino


def save_image(path, state, expected, *, overwrite=False, token=None, camera_preview=False):
    """Decode original resolution, render once, then atomically commit beside source."""
    path = Path(path)
    if fingerprint(path) != expected:
        raise ValueError(tr("原文件已被其他程序修改，请重新打开后编辑"))
    check = token.checkpoint if token else lambda: None
    check()
    fmt = SAVE_FORMATS.get(path.suffix.lower()) if overwrite else "PNG"
    if fmt is None:
        raise ValueError(tr("此格式仅支持保存 PNG 副本"))
    image = read_image(path, token=token, camera_preview=camera_preview)
    output, _ = render(to_pillow(image), state, token=token)
    kwargs = {}
    try:
        with Image.open(path) as source:
            if source.info.get("icc_profile") and fmt in {"PNG", "JPEG", "WEBP", "TIFF"}:
                kwargs["icc_profile"] = source.info["icc_profile"]
            exif = source.getexif()
            if exif and fmt in {"PNG", "JPEG", "WEBP", "TIFF"}:
                exif[274], exif[256], exif[257] = 1, output.width, output.height
                if 34665 in exif:
                    tags = exif.get_ifd(34665)
                    tags[40962], tags[40963] = output.width, output.height
                kwargs["exif"] = exif.tobytes()
    except (OSError, ValueError, KeyError):
        pass
    if fmt in {"JPEG", "BMP"}:
        background = Image.new("RGB", output.size, "white")
        background.paste(output, mask=output.getchannel("A"))
        output = background
    if fmt in {"JPEG", "WEBP"}:
        kwargs["quality"] = 95
    handle, name = tempfile.mkstemp(prefix=".picer-edit-", suffix=".tmp", dir=path.parent)
    target, reserved = path, None
    try:
        with os.fdopen(handle, "wb") as stream:
            output.save(stream, format=fmt, **kwargs)
            stream.flush()
            os.fsync(stream.fileno())
        check()
        if fingerprint(path) != expected:
            raise ValueError(tr("原文件已改变，未保存修改"))
        if not overwrite:
            for n in range(1, 10000):
                target = path.with_name(
                    path.stem + (tr(" - 编辑") if n == 1 else tr(" - 编辑 {0}").format(n)) + ".png"
                )
                try:
                    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    os.close(descriptor)
                    reserved = fingerprint(target)
                    break
                except FileExistsError:
                    continue
            else:
                raise ValueError(tr("无法分配副本名称"))
        else:
            os.chmod(name, path.stat().st_mode & 0o777)
        check()
        if reserved and fingerprint(target) != reserved:
            raise ValueError(tr("副本位置已被其他程序修改"))
        os.replace(name, target)
        return target
    except BaseException:
        if reserved and target.exists() and fingerprint(target) == reserved:
            target.unlink()
        raise
    finally:
        Path(name).unlink(missing_ok=True)
