"""Decode only PSD's saved merged image, seeking past resources and layer data."""

import struct
import zlib
from pathlib import Path

import numpy as np
from PIL import Image


def header(handle):
    data = handle.read(26)
    if len(data) != 26 or data[:6] != b"8BPS\0\1":
        raise ValueError("不是支持的 PSD 文件")
    channels, height, width, depth, mode = struct.unpack(">HIIHH", data[12:])
    if not (1 <= channels <= 56 and 1 <= width <= 30000 and 1 <= height <= 30000):
        raise ValueError("PSD 尺寸或通道无效")
    if depth not in (8, 16, 32) or mode not in (1, 2, 3, 4, 8, 9):
        raise ValueError("此 PSD 的颜色模式或位深暂不支持合成预览")
    return width, height, depth, mode, channels


def merged_offset(handle):
    end = handle.seek(0, 2)
    handle.seek(26)
    palette = b""
    for section in range(3):
        length = handle.read(4)
        if len(length) != 4:
            raise ValueError("PSD 合成预览不完整")
        size = struct.unpack(">I", length)[0]
        start = handle.tell()
        if start + size > end:
            raise ValueError("PSD 数据区超出文件边界")
        if section == 0 and size == 768:
            palette = handle.read(size)
        handle.seek(start + size)  # Never enumerate/decode layers or masks.
    return palette


def psd_info(path):
    with Path(path).open("rb") as handle:
        width, height, depth, mode, _ = header(handle)
        merged_offset(handle)
        if len(handle.read(2)) != 2:
            raise ValueError("PSD 未保存可用合成预览，请启用最大兼容性后重新保存")
    return {
        "宽度": str(width),
        "高度": str(height),
        "格式": "PSD",
        "预览类型": "已保存的合成图",
        "位深": str(depth),
        "色彩模式": {1: "灰度", 2: "索引色", 3: "RGB", 4: "CMYK", 8: "双色调", 9: "Lab"}[mode],
    }


def unpack_row(data, size):
    output = bytearray()
    index = 0
    while index < len(data) and len(output) < size:
        count = data[index]
        index += 1
        if count < 128:
            count += 1
            output.extend(data[index : index + count])
            index += count
        elif count > 128:
            if index >= len(data):
                raise ValueError("PSD RLE 数据损坏")
            output.extend(data[index : index + 1] * (257 - count))
            index += 1
    if len(output) != size:
        raise ValueError("PSD RLE 行长度无效")
    return output


def read_psd(path, *, edge=0, token=None):
    from picer.imaging import MAX_PIXELS, pillow_image

    def checkpoint():
        if token:
            token.checkpoint()

    checkpoint()
    with Path(path).open("rb") as handle:
        width, height, depth, mode, channels = header(handle)
        base = 4 if mode == 4 else 3 if mode in (3, 9) else 1
        required = min(channels, base + (mode in (1, 3)))
        row_size = width * (depth // 8)
        needed = required * height * row_size
        if channels < base or width * height > MAX_PIXELS or needed > 512 * 1048576:
            raise ValueError("PSD 合成图超过读取上限或缺少颜色通道")
        palette = merged_offset(handle)
        compression = handle.read(2)
        if len(compression) != 2:
            raise ValueError("PSD 未保存可用合成预览")
        compression = struct.unpack(">H", compression)[0]
        if compression == 0:
            raw = bytearray()
            while len(raw) < needed:
                checkpoint()
                chunk = handle.read(min(65536, needed - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
        elif compression == 1:
            lengths = handle.read(channels * height * 2)
            if len(lengths) != channels * height * 2:
                raise ValueError("PSD RLE 行表不完整")
            rows = struct.iter_unpack(">H", lengths)
            raw = bytearray()
            for _ in range(required * height):
                checkpoint()
                size = next(rows)[0]
                raw.extend(unpack_row(handle.read(size), row_size))
        elif compression in (2, 3):
            decoder, raw = zlib.decompressobj(), bytearray()
            pending = b""
            while len(raw) < needed:
                checkpoint()
                pending = decoder.unconsumed_tail or handle.read(65536)
                if not pending:
                    break
                raw.extend(decoder.decompress(pending, min(65536, needed - len(raw))))
                if decoder.eof:
                    break
        else:
            raise ValueError("此 PSD 合成图的压缩方式暂不支持")
    if len(raw) != needed:
        raise ValueError("PSD 合成预览不完整，请使用最大兼容性保存")
    checkpoint()
    if compression == 3:
        if depth in (8, 16):
            kind = "u1" if depth == 8 else ">u2"
            rows = np.frombuffer(raw, dtype=kind).reshape(-1, width)
            raw = (
                np.cumsum(rows, axis=1, dtype=np.uint8 if depth == 8 else np.uint16)
                .astype(kind)
                .tobytes()
            )
        else:
            rows = np.frombuffer(raw, dtype=np.uint8).reshape(-1, width * 4)
            rows = np.cumsum(rows, axis=1, dtype=np.uint8)
            raw = rows.reshape(-1, 4, width).transpose(0, 2, 1).copy().tobytes()
    pixels = np.frombuffer(raw, dtype={8: "u1", 16: ">u2", 32: ">f4"}[depth])
    if depth == 16:
        # Take the high byte without allocating a float64 copy of a large composite.
        pixels = np.frombuffer(raw, dtype=np.uint8)[::2]
    elif depth == 32:
        pixels = np.nan_to_num(pixels, nan=0, posinf=1, neginf=0)
        pixels = (np.clip(pixels, 0, 1) * 255).astype(np.uint8)
    data = pixels.reshape(required, height, width).transpose(1, 2, 0).copy()
    if mode == 2:
        if len(palette) != 768:
            raise ValueError("PSD 缺少索引色调色板")
        image = Image.frombytes("P", (width, height), data.tobytes())
        colors = np.frombuffer(palette, dtype=np.uint8).reshape(3, 256).T
        image.putpalette(colors.tobytes())
    else:
        color = (
            "CMYK"
            if mode == 4
            else "LAB"
            if mode == 9
            else "RGBA"
            if required == 4
            else "RGB"
            if required == 3
            else "LA"
            if required == 2
            else "L"
        )
        if mode == 4:
            data = 255 - data
        image = Image.frombytes(color, (width, height), data.tobytes())
        if color == "LAB":
            from PIL import ImageCms

            image = ImageCms.profileToProfile(
                image,
                ImageCms.createProfile("LAB"),
                ImageCms.createProfile("sRGB"),
                outputMode="RGB",
            )
    if edge:
        image.thumbnail((edge, edge))
    checkpoint()
    result = pillow_image(image)
    result.setText("picer.native_width", str(width))
    result.setText("picer.native_height", str(height))
    return result
