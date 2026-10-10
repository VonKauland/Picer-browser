"""Read source metadata off the GUI thread; bounded values and sampled histograms."""

import hashlib
from datetime import datetime
from pathlib import Path

from PIL import ExifTags, Image, ImageStat

from picer.exif import sections
from picer.imaging import RAW_SUFFIXES, read_image


def describe(value):
    if isinstance(value, bytes):
        return f"{len(value)} 字节 · SHA256 {hashlib.sha256(value).hexdigest()[:16]}"
    text = str(value)
    return text[:2048] + ("…" if len(text) > 2048 else "")


def inspect_image(path: Path, token=None) -> dict:
    def checkpoint():
        if token:
            token.checkpoint()

    checkpoint()
    stat = path.stat()
    result = {
        "path": str(path),
        "file": {
            "文件名": path.name,
            "路径": str(path),
            "文件大小": f"{stat.st_size:,} 字节",
            "修改时间": datetime.fromtimestamp(stat.st_mtime).isoformat(
                sep=" ", timespec="seconds"
            ),
        },
        "exif": {},
        "extra": {},
        "warnings": [],
    }
    if path.suffix.lower() in RAW_SUFFIXES:
        return inspect_raw(path, result, token)
    try:
        with Image.open(path) as source:
            result["dimensions"] = {
                "宽度": str(source.width),
                "高度": str(source.height),
                "格式": source.format or "未知",
                "帧数": str(getattr(source, "n_frames", 1)),
                "DPI": describe(source.info.get("dpi", "未记录")),
            }
            result["color"] = {
                "色彩模式": source.mode,
                "通道": ", ".join(source.getbands()),
                "每通道位深": "16"
                if "16" in source.mode
                else "32"
                if source.mode in {"I", "F"}
                else "1"
                if source.mode == "1"
                else "8",
                "透明度": "是"
                if "A" in source.getbands() or "transparency" in source.info
                else "否",
            }
            icc = source.info.get("icc_profile")
            result["color"]["ICC 配置"] = describe(icc) if icc else "未嵌入"
            exif = source.getexif()
            camera_tags = {}
            for tag, value in exif.items():
                if tag not in (34665, 34853, 40965):
                    name = ExifTags.TAGS.get(tag, f"Tag {tag}")
                    result["exif"][name] = describe(value)
                    camera_tags[name] = value
            for pointer, prefix, names in (
                (34665, "相机", ExifTags.TAGS),
                (34853, "GPS", ExifTags.GPSTAGS),
                (40965, "互操作", ExifTags.TAGS),
            ):
                if pointer in exif:
                    try:
                        for tag, value in exif.get_ifd(pointer).items():
                            name = names.get(tag, f"Tag {tag}")
                            result["exif"][f"{prefix} · {name}"] = describe(value)
                            camera_tags[name] = value
                    except (OSError, ValueError, TypeError, KeyError) as error:
                        result["warnings"].append(f"{prefix} EXIF：{error}")
            result["exif_sections"] = sections(camera_tags)
            result["embedded_rating"] = (
                int(exif.get(18246, 0)) if str(exif.get(18246, 0)).isdigit() else 0
            )
            for key, value in source.info.items():
                if key not in {"exif", "icc_profile"}:
                    result["extra"][str(key)] = describe(value)
            checkpoint()
            source.draft("RGB", (1024, 1024))
            source.thumbnail((1024, 1024))
            sample = source.copy()
            sample = sample.convert("RGB")
            histogram = sample.histogram()
            result["histogram"] = [histogram[i : i + 256] for i in (0, 256, 512)]
            result["sample_size"] = sample.size
            result["color"]["平均 RGB（采样）"] = ", ".join(
                f"{v:.1f}" for v in ImageStat.Stat(sample).mean
            )
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        result["warnings"].append(f"部分元数据无法读取：{error}")
    checkpoint()
    return result


def inspect_raw(path, result, token):
    import exifread
    import rawpy

    # Parse camera tags independently: a decoder/histogram failure must not hide EXIF.
    try:
        with path.open("rb") as handle:
            tags = exifread.process_file(handle, details=False, extract_thumbnail=False)
        result["exif"] = {str(key): describe(value) for key, value in tags.items()}
        result["exif_sections"] = sections(tags)
    except (OSError, ValueError, TypeError, KeyError) as error:
        result["warnings"].append(f"RAW EXIF 无法读取：{error}")
    try:
        if token:
            token.checkpoint()
        with rawpy.RawPy() as raw:
            raw.open_file(str(path))
            result["dimensions"] = {
                "宽度": str(raw.sizes.width),
                "高度": str(raw.sizes.height),
                "格式": path.suffix[1:].upper() + " / LibRaw",
                "帧数": "1",
            }
            result["color"] = {
                "色彩模式": "相机 RAW → sRGB",
                "显示位深": "8 位 / 通道",
                "传感器白电平": str(raw.white_level),
                "传感器黑电平": describe(raw.black_level_per_channel),
            }
        if token:
            token.checkpoint()
        image = read_image(path, edge=1024, token=token)
        image = image.convertToFormat(image.Format.Format_RGBA8888)
        sample = Image.frombytes("RGBA", (image.width(), image.height()), bytes(image.constBits()))
        sample = sample.convert("RGB")
        histogram = sample.histogram()
        result["histogram"] = [histogram[i : i + 256] for i in (0, 256, 512)]
        result["sample_size"] = sample.size
        result["color"]["平均 RGB（预览采样）"] = ", ".join(
            f"{v:.1f}" for v in ImageStat.Stat(sample).mean
        )
    except (OSError, ValueError, RuntimeError, rawpy.LibRawError) as error:
        result["warnings"].append(f"部分 RAW 元数据无法读取：{error}")
    if token:
        token.checkpoint()
    return result
