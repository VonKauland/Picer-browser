"""Read source metadata off the GUI thread; bounded values and sampled histograms."""

import hashlib
from datetime import datetime
from pathlib import Path

from PIL import ExifTags, Image, ImageStat


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
            for tag, value in exif.items():
                if tag not in (34665, 34853, 40965):
                    result["exif"][ExifTags.TAGS.get(tag, f"Tag {tag}")] = describe(value)
            for pointer, prefix, names in (
                (34665, "相机", ExifTags.TAGS),
                (34853, "GPS", ExifTags.GPSTAGS),
                (40965, "互操作", ExifTags.TAGS),
            ):
                if pointer in exif:
                    try:
                        for tag, value in exif.get_ifd(pointer).items():
                            result["exif"][f"{prefix} · {names.get(tag, f'Tag {tag}')}"] = describe(
                                value
                            )
                    except (OSError, ValueError, TypeError, KeyError) as error:
                        result["warnings"].append(f"{prefix} EXIF：{error}")
            result["embedded_rating"] = (
                int(exif.get(18246, 0)) if str(exif.get(18246, 0)).isdigit() else 0
            )
            for key, value in source.info.items():
                if key not in {"exif", "icc_profile"}:
                    result["extra"][str(key)] = describe(value)
            checkpoint()
            sample = source.copy()
            sample.thumbnail((1024, 1024))
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
