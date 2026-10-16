"""Bounded Canon CR3 TIFF metadata and recorded Canon AF geometry.

Container/AF layout references: ExifTool Canon CMT1-CMT4, AFInfo and AFInfo2
tag documentation. No pixel payloads are scanned and no AF positions inferred.
"""

import struct
from fractions import Fraction
from pathlib import Path

from PIL import ExifTags

LIMIT = 2 * 1024 * 1024
CANON_UUID = bytes.fromhex("85c0b687820f11e08111f4ce462b6a48")


class Tiff:
    def __init__(self, data):
        self.data = data
        self.endian = "<" if data[:2] == b"II" else ">" if data[:2] == b"MM" else ""
        if not self.endian or len(data) < 8 or self.unpack("H", 2)[0] != 42:
            raise ValueError("Invalid TIFF metadata")
        self.first = self.unpack("I", 4)[0]

    def unpack(self, code, position):
        return struct.unpack_from(self.endian + code, self.data, position)

    def ifd(self, offset=None):
        offset = self.first if offset is None else offset
        if not 8 <= offset <= len(self.data) - 2:
            return {}, {}
        count = self.unpack("H", offset)[0]
        if count > 2048 or offset + 2 + count * 12 > len(self.data):
            return {}, {}
        values, positions = {}, {}
        formats = {1: "B", 3: "H", 4: "I", 9: "i", 11: "f", 12: "d"}
        sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8, 11: 4, 12: 8}
        for i in range(count):
            p = offset + 2 + 12 * i
            tag, kind, n = self.unpack("HHI", p)
            size = sizes.get(kind, 0) * n
            if not 0 < size <= 262144:
                continue
            start = p + 8 if size <= 4 else self.unpack("I", p + 8)[0]
            if start + size > len(self.data):
                continue
            raw = self.data[start : start + size]
            if kind == 2:
                value = raw.rstrip(b"\0").decode("utf-8", errors="replace")
            elif kind == 7:
                value = raw
            elif kind in (5, 10):
                code = "II" if kind == 5 else "ii"
                pairs = struct.iter_unpack(self.endian + code, raw)
                value = [Fraction(a, b) if b else 0 for a, b in pairs]
                value = value[0] if n == 1 else value
            elif kind in formats:
                value = list(self.unpack(formats[kind] * n, start))
                value = value[0] if n == 1 else value
            else:
                continue
            values[tag], positions[tag] = value, start
        return values, positions


def cr3_blocks(path, token=None):
    result, budget = {}, [0]
    with Path(path).open("rb") as handle:
        end = handle.seek(0, 2)

        def walk(start, stop, depth):
            if depth > 8:
                return
            pos = start
            while pos + 8 <= stop and budget[0] < 8192:
                if token:
                    token.checkpoint()
                budget[0] += 1
                handle.seek(pos)
                header = handle.read(8)
                if len(header) != 8:
                    return
                length, kind = struct.unpack(">I4s", header)
                head = 8
                if length == 1:
                    extended = handle.read(8)
                    if len(extended) != 8:
                        return
                    length, head = struct.unpack(">Q", extended)[0], 16
                elif length == 0:
                    length = stop - pos
                if length < head or pos + length > stop:
                    return
                payload, finish = pos + head, pos + length
                if (
                    kind in (b"CMT1", b"CMT2", b"CMT3", b"CMT4")
                    and kind not in result
                    and length - head <= LIMIT
                ):
                    result.setdefault(kind, handle.read(length - head))
                elif kind == b"moov":
                    walk(payload, finish, depth + 1)
                elif kind == b"uuid" and finish - payload >= 16:
                    handle.seek(payload)
                    if handle.read(16) == CANON_UUID:
                        walk(payload + 16, finish, depth + 1)
                pos = finish  # skip mdat/preview payloads, including very large files

        walk(0, end, 0)
    return result


def canon_focus(values, model=""):
    for tag in (0x26, 0x32, 0x12):
        words = values.get(tag)
        if not isinstance(words, (list, tuple)) or len(words) < 8:
            continue
        newer = tag != 0x12
        n, valid = words[2:4] if newer else words[:2]
        width, height = words[6:8] if newer else words[4:6]
        if not (0 < valid <= n <= 4096 and width > 0 and height > 0):
            continue
        needed = 8 + (4 if newer else 2) * n
        masks = (n + 15) // 16
        if len(words) < needed + masks:
            continue

        def signed(x):
            return x - 65536 if x >= 32768 else x

        if newer:
            widths, heights = words[8 : 8 + n], words[8 + n : 8 + 2 * n]
            xs, ys = words[8 + 2 * n : 8 + 3 * n], words[8 + 3 * n : 8 + 4 * n]
        else:
            widths, heights = [words[6]] * n, [words[7]] * n
            xs, ys = words[8 : 8 + n], words[8 + n : 8 + 2 * n]
        boxes = []
        for i in range(valid):
            if not (words[needed + i // 16] & (1 << (i % 16))):
                continue
            w, h = signed(widths[i]) / width, signed(heights[i]) / height
            x = 0.5 + signed(xs[i]) / width
            y = 0.5 + (1 if "PowerShot" in model else -1) * signed(ys[i]) / height
            if 0 < w <= 1 and 0 < h <= 1 and 0 <= x <= 1 and 0 <= y <= 1:
                left, top = max(0, x - w / 2), max(0, y - h / 2)
                boxes.append((left, top, min(1, x + w / 2) - left, min(1, y + h / 2) - top))
                if len(boxes) >= 512:
                    break
        return boxes
    return []


def metadata_from_tiff(data, *, maker=False):
    tiff = Tiff(data)
    root, positions = tiff.ifd()
    if maker:
        return {}, root
    tags = {ExifTags.TAGS.get(k, f"Tag {k}"): v for k, v in root.items() if k not in (34665, 34853)}
    extra, exif_positions = tiff.ifd(root.get(34665, 0))
    tags.update({ExifTags.TAGS.get(k, f"Tag {k}"): v for k, v in extra.items()})
    if 34853 in root:
        gps, _ = tiff.ifd(root[34853])
        tags.update({ExifTags.GPSTAGS.get(k, f"GPS {k}"): v for k, v in gps.items()})
    offset = exif_positions.get(37500, positions.get(37500))
    notes, _ = tiff.ifd(offset) if offset is not None else ({}, {})
    return tags, notes


def read_cr3(path, token=None):
    tags, notes = {}, {}
    for kind, data in cr3_blocks(path, token).items():
        try:
            values, maker = metadata_from_tiff(data, maker=kind == b"CMT3")
            if kind == b"CMT4":
                values = {
                    ExifTags.GPSTAGS.get(k, f"GPS {k}"): v for k, v in Tiff(data).ifd()[0].items()
                }
            tags.update(values)
            notes.update(maker)
        except (ValueError, TypeError, struct.error):
            continue
    if isinstance(notes.get(0x95), str):
        tags.setdefault("LensModel", notes[0x95])
    return tags, canon_focus(notes, str(tags.get("Model", "")))


def tiff_focus(data):
    try:
        tags, notes = metadata_from_tiff(data)
        if str(tags.get("Make", "")).strip() != "Canon":
            return []
        return canon_focus(notes, str(tags.get("Model", "")))
    except (ValueError, TypeError, struct.error):
        return []
