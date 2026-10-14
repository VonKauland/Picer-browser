"""Normalize Pillow and ExifRead tags into camera tables without changing raw SDK data."""

from fractions import Fraction

BASIC = (
    ("相机制造商", "Make"),
    ("相机型号", "Model"),
    ("镜头制造商", "LensMake"),
    ("镜头型号", "LensModel"),
    ("光圈", "FNumber"),
    ("曝光时间", "ExposureTime"),
    ("ISO 速度", "ISOSpeedRatings"),
    ("焦距", "FocalLength"),
    ("35mm 焦距", "FocalLengthIn35mmFilm"),
)
DETAILS = {
    "原始": (
        ("作者", "Artist"),
        ("拍摄日期", "DateTimeOriginal"),
        ("程序名称", "Software"),
        ("取得时间", "DateTimeDigitized"),
        ("版权", "Copyright"),
    ),
    "相机": (
        ("相机制造商", "Make"),
        ("相机型号", "Model"),
        ("光圈", "FNumber"),
        ("曝光时间", "ExposureTime"),
        ("ISO 速度", "ISOSpeedRatings"),
        ("曝光补偿", "ExposureBiasValue"),
        ("焦距", "FocalLength"),
        ("最大光圈", "MaxApertureValue"),
        ("测光模式", "MeteringMode"),
        ("对象距离", "SubjectDistance"),
        ("闪光灯模式", "Flash"),
        ("闪光灯能源", "FlashEnergy"),
        ("35mm 焦距", "FocalLengthIn35mmFilm"),
    ),
    "照片详细信息": (
        ("镜头制造商", "LensMake"),
        ("镜头型号", "LensModel"),
        ("闪光灯制造商", "FlashManufacturer"),
        ("闪光灯型号", "FlashModel"),
        ("相机序号", "BodySerialNumber"),
        ("对比", "Contrast"),
        ("亮度", "BrightnessValue"),
        ("光源", "LightSource"),
        ("曝光程序", "ExposureProgram"),
        ("饱和度", "Saturation"),
        ("锐利度", "Sharpness"),
        ("白平衡", "WhiteBalance"),
        ("亮度测量解释", "PhotometricInterpretation"),
        ("数码变焦", "DigitalZoomRatio"),
        ("方向", "Orientation"),
        ("EXIF 版本", "ExifVersion"),
    ),
    "GPS": (("经度", "GPSLongitude"), ("纬度", "GPSLatitude"), ("高度", "GPSAltitude")),
}
ENUMS = {
    "MeteringMode": {
        0: "未知",
        1: "平均",
        2: "中央重点平均",
        3: "点测光",
        4: "多点",
        5: "评价测光",
        6: "局部",
    },
    "ExposureProgram": {
        0: "未定义",
        1: "手动",
        2: "程序自动",
        3: "光圈优先",
        4: "快门优先",
        5: "创意程序",
        6: "运动",
        7: "人像",
        8: "风景",
    },
    "LightSource": {
        0: "未知",
        1: "日光",
        2: "荧光灯",
        3: "钨丝灯",
        4: "闪光灯",
        9: "晴天",
        10: "阴天",
        11: "阴影",
        255: "其他",
    },
    "Contrast": {0: "标准", 1: "柔和", 2: "硬"},
    "Saturation": {0: "标准", 1: "低饱和度", 2: "高饱和度"},
    "Sharpness": {0: "标准", 1: "柔和", 2: "硬"},
    "WhiteBalance": {0: "自动", 1: "手动"},
    "Orientation": {
        1: "标准",
        2: "水平镜像",
        3: "旋转 180°",
        4: "垂直镜像",
        5: "转置",
        6: "旋转 90°",
        7: "横向转置",
        8: "旋转 270°",
    },
}
ALIASES = {
    "PhotographicSensitivity": "ISOSpeedRatings",
    "ISO": "ISOSpeedRatings",
    "FocalLengthIn35mmFormat": "FocalLengthIn35mmFilm",
}


def canonical(tags):
    result = {}
    for key, value in tags.items():
        name = str(key).replace(" · ", " ").rsplit(" ", 1)[-1]
        name = ALIASES.get(name, name)
        if hasattr(value, "values"):
            value = value.values
            if isinstance(value, (tuple, list)) and len(value) == 1:
                value = value[0]
        result[name] = value
    if "Artist" not in result and "XPAuthor" in result:
        try:
            result["Artist"] = bytes(result["XPAuthor"]).decode("utf-16le").rstrip("\x00")
        except (ValueError, TypeError, UnicodeError):
            pass
    for destination, apex in (("FNumber", "ApertureValue"), ("ExposureTime", "ShutterSpeedValue")):
        if destination not in result and apex in result:
            try:
                amount = number(result[apex])
                result[destination] = 2 ** (amount / 2) if destination == "FNumber" else 2**-amount
            except (ValueError, TypeError, ZeroDivisionError, OverflowError):
                pass
    return result


def number(value):
    if hasattr(value, "num") and hasattr(value, "den"):
        return value.num / value.den
    return float(Fraction(str(value)))


def display(name, value, tags):
    if value is None:
        return "未记录"
    try:
        if name == "FNumber":
            return f"f/{number(value):g}"
        if name == "MaxApertureValue":
            return f"f/{2 ** (number(value) / 2):.2f}"
        if name == "ExposureTime":
            fraction = Fraction(number(value)).limit_denominator(1_000_000)
            return f"{fraction} s"
        if name in {"FocalLength", "FocalLengthIn35mmFilm"}:
            return f"{number(value):g} mm"
        if name == "ExposureBiasValue":
            return f"{number(value):+g} EV"
        if name in {"SubjectDistance", "GPSAltitude"}:
            amount = number(value)
            if name == "GPSAltitude" and tags.get("GPSAltitudeRef") in (1, b"\x01"):
                amount = -amount
            return f"{amount:g} m"
        if name in {"GPSLatitude", "GPSLongitude"} and isinstance(value, (list, tuple)):
            degrees = sum(
                number(part) / divisor for part, divisor in zip(value, (1, 60, 3600), strict=False)
            )
            ref = str(tags.get(name + "Ref", ""))
            return f"{degrees:.6f}° {ref}".strip()
        if name in ENUMS:
            return ENUMS[name].get(int(number(value)), str(value))
        if name == "Flash":
            code = int(number(value))
            fired = "闪光" if code & 1 else "未闪光"
            mode = {1: "强制", 2: "关闭", 3: "自动"}.get((code >> 3) & 3, "")
            return fired + (f"（{mode}）" if mode else "")
        if name == "ExifVersion":
            if isinstance(value, (list, tuple)):
                value = bytes(value)
            text = (
                value.decode("ascii", errors="replace") if isinstance(value, bytes) else str(value)
            )
            if text.isdigit() and len(text) == 4:
                return f"{int(text[:2])}.{text[2:]}"
        if name in {"DateTimeOriginal", "DateTimeDigitized"}:
            text = str(value)
            return text[:10].replace(":", "-") + text[10:]
    except (ValueError, TypeError, ZeroDivisionError, OverflowError):
        pass
    if isinstance(value, bytes):
        return f"{len(value)} 字节"
    return str(value).strip("\x00")[:2048]


def sections(tags):
    values = canonical(tags)
    basic = {label: display(name, values.get(name), values) for label, name in BASIC}
    details = {
        group: {label: display(name, values.get(name), values) for label, name in fields}
        for group, fields in DETAILS.items()
        if group != "GPS" or any(name.startswith("GPS") for name in values)
    }
    return {"基础信息": basic, "详细信息": details}
