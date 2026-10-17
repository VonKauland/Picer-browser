"""Recorded AF/face geometry; manufacturer fields, not image-based detection.

Field layouts: ExifTool Nikon AFInfo2, Sony 202a/FocusLocation, Fujifilm
FocusPixel/FacePositions, Panasonic AFPointPosition/FaceDetInfo, Olympus
CameraSettings/ImageProcessing, Pentax AFInfoK3III/FaceInfoK3III, Ricoh Main.
Unknown schemas, missing coordinate frames and point IDs without geometry are
not converted to invented positions. See docs/camera-regions.md for coverage.
"""

import math
import struct
from pathlib import Path

from picer.camera_metadata import LIMIT, Tiff, canon_focus
from picer.xmp_regions import xmp_faces


class FileData:
    """Seek only requested metadata ranges, with a shared total-read budget."""

    def __init__(self, handle):
        self.handle = handle
        self.length = handle.seek(0, 2)
        self.used = 0

    def __len__(self):
        return self.length

    def __getitem__(self, span):
        start, stop, step = span.indices(self.length)
        if step != 1 or stop - start + self.used > LIMIT:
            raise ValueError("Camera metadata read budget exceeded")
        self.used += stop - start
        self.handle.seek(start)
        return self.handle.read(stop - start)


class FileTiff(Tiff):
    def unpack(self, code, position):
        size = struct.calcsize(self.endian + code)
        return struct.unpack(self.endian + code, self.data[position : position + size])


def sequence(value):
    return list(value) if isinstance(value, (list, tuple)) else []


def words(value, endian, code="H"):
    if isinstance(value, bytes):
        size = struct.calcsize(code)
        if len(value) % size:
            return []
        return [x[0] for x in struct.iter_unpack(endian + code, value)]
    return sequence(value)


def rectangle(x, y, w, h, width=1, height=1):
    """Normalize a recorded top-left rectangle; reject sentinel/outside data."""
    values = (x, y, w, h, width, height)
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
        return []
    if width <= 0 or height <= 0 or w <= 0 or h <= 0:
        return []
    left, top, right, bottom = x / width, y / height, (x + w) / width, (y + h) / height
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        return []
    return [(left, top, right - left, bottom - top)]


def center(x, y, width, height, w=None, h=None):
    # A tag containing only a point has no recorded area size. Use a small
    # display marker, not a claim about the actual physical AF sensor area.
    w = width * 0.03 if w is None else w
    h = height * 0.03 if h is None else h
    if width <= 0 or height <= 0 or not (0 <= x <= width and 0 <= y <= height):
        return []
    left, top = max(0, x - w / 2), max(0, y - h / 2)
    return rectangle(
        left, top, min(width, x + w / 2) - left, min(height, y + h / 2) - top, width, height
    )


def view(data, endian, first):
    reader = Tiff.__new__(Tiff)
    reader.data, reader.endian, reader.first = data, endian, first
    return reader


def maker_reader(tiff, root, exif, positions):
    raw = exif.get(37500, root.get(37500))
    offset = positions.get(37500)
    if not isinstance(raw, bytes) or offset is None:
        return None
    make = str(root.get(271, "")).upper()
    if raw.startswith(b"Nikon\0\x02") and len(raw) >= 18:
        reader = Tiff(raw[10:])
        return "nikon", reader, reader.first, 0
    # These headers define offsets relative to the start of the MakerNote.
    layouts = (
        (b"FUJIFILM", "fuji", 12, "<"),
        (b"OLYMPUS\0", "olympus", 12, None),
        (b"OM SYSTEM\0", "olympus", 16, None),
        (b"PENTAX \0", "pentax", 10, None),
        (b"RICOH\0", "pentax", 8, None),
    )
    for signature, brand, first, order in layouts:
        if raw.startswith(signature):
            endian = order or (
                {b"II": "<", b"MM": ">"}.get(raw[len(signature) : len(signature) + 2])
            )
            if endian is None:
                if signature == b"RICOH\0":
                    continue  # older GR MakerNotes do not use the Pentax header
                return None
            if brand == "fuji":
                first = struct.unpack_from("<I", raw, 8)[0]
            reader = view(b"\0" * 8 + raw, endian, first + 8)
            return brand, reader, first + 8, 8
    # fp/fp L samples use absolute enclosing-TIFF offsets, not MakerNote offsets.
    model = str(root.get(272, "")).lower().replace(" ", "")
    if (
        "SIGMA" in make
        and model in ("fp", "fpl", "sigmafp", "sigmafpl")
        and raw.startswith(b"SIGMA\0\0\0\x01\x04")
    ):
        return "sigma", tiff, offset + 10, 0
    # Older makers use the enclosing TIFF offset base.
    if raw.startswith(b"Panasonic\0"):
        return "panasonic", tiff, offset + 12, 0
    if raw.startswith(b"LEICA\0"):
        return "panasonic", tiff, offset + 8, 0
    if raw.startswith((b"SONY DSC", b"SONY CAM", b"SONY MOBILE", b"VHAB")):
        return "sony", tiff, offset + 12, 0
    if raw.startswith((b"OLYMP\0", b"EPSON\0")):
        return "olympus", tiff, offset + 8, 0
    if raw.startswith(b"AOC\0") and raw[4:6] in (b"II", b"MM"):
        reader = view(tiff.data, "<" if raw[4:6] == b"II" else ">", offset + 6)
        return "pentax", reader, offset + 6, 0
    if "RICOH" in make and raw[:2] in (b"II", b"MM"):
        reader = view(tiff.data, "<" if raw[:2] == b"II" else ">", offset + 8)
        return "ricoh", reader, offset + 8, 0
    if "RICOH" in make and raw[:5].upper() == b"RICOH":
        return "ricoh", tiff, offset + 8, 0
    if "CANON" in make:
        return "canon", tiff, offset, 0
    if "SONY" in make:  # ARW native MakerNotes can be a bare IFD.
        return "sony", tiff, offset, 0
    return None


def nikon_regions(notes, endian):
    boxes, faces = [], []
    af = notes.get(0xB7, b"")
    if isinstance(af, bytes) and len(af) >= 8:
        version = af[:4]
        offset = None
        if version in (b"0100", b"0101") and af[4] == 1:
            offset = 0x10 if version == b"0100" else 0x46
        elif version in (b"0300", b"0301") and af[7] == 1:
            offset = 0x2A
        elif version in (b"0400", b"0401", b"0402") and af[7] == 1:
            offset = 0x3E
        if offset is not None and len(af) >= offset + 12:
            width, height, x, y, w, h = struct.unpack_from(endian + "6H", af, offset)
            if width and height and x and y and w and h:
                boxes = center(x, y, width, height, w, h)
    data = words(notes.get(0x21), endian)
    if len(data) >= 4 and 0 < data[3] <= 64:
        width, height, count = data[1:4]
        if len(data) >= 4 + count * 4:
            for i in range(count):
                top, left, w, h = data[4 + i * 4 : 8 + i * 4]
                faces += rectangle(left, top, w, h, width, height)
    return boxes, faces


def fuji_regions(notes, width, height):
    boxes, faces = [], []
    point = sequence(notes.get(0x1023))
    if len(point) == 2 and point != [0, 0]:
        boxes = center(*point, width, height)
    count, data = notes.get(0x4100, 0), sequence(notes.get(0x4103))
    if isinstance(count, int) and 0 < count <= 64 and len(data) >= count * 4:
        for i in range(count):
            left, top, right, bottom = data[i * 4 : i * 4 + 4]
            faces += rectangle(left, top, right - left, bottom - top, width, height)
    if notes.get(0x1021) == 1:
        boxes = []
    return boxes, faces


def sony_regions(notes, endian, width=0, height=0):
    boxes = []
    data = notes.get(0x202A)
    if isinstance(data, bytes) and len(data) >= 6 and data[0] == 1:
        count = data[1]
        width, height = struct.unpack_from(endian + "2H", data, 2)
        if 0 < count <= 15 and len(data) >= 6 + count * 4:
            for i in range(count):
                x, y = struct.unpack_from(endian + "2H", data, 6 + i * 4)
                boxes += center(x, y, width, height)
    # Playback-zoom FocusLocation may default to image center when AF failed.
    # Only use it when the camera also records a valid focus frame.
    frame = sequence(notes.get(0x2037))
    point = sequence(notes.get(0x204A, notes.get(0x2027)))
    if not boxes and len(frame) == 3 and frame[2] and len(point) == 4:
        width, height, x, y = point
        boxes = center(x, y, width, height, *frame[:2])
    spot = sequence(notes.get(0x201D))
    if not boxes and notes.get(0x201C) in (3, 4, 12) and len(spot) == 2:
        if notes.get(0x201B) in (2, 3, 4, 6, 7):
            boxes = center(*spot, 640, 480)
    if notes.get(0x201B) == 0:
        boxes = []
    faces = []
    shot = notes.get(0x3000)
    if isinstance(shot, bytes) and shot[:2] == b"II" and len(shot) >= 0x34:
        offset = struct.unpack_from("<H", shot, 2)[0]
        count, stride = struct.unpack_from("<2H", shot, 0x30)
        frame_h, frame_w = struct.unpack_from("<2H", shot, 0x1A)
        if (offset, stride) in ((0x48, 0x20), (0x5E, 0x25)) and 0 < count <= 8:
            if len(shot) >= offset + (count - 1) * stride + 8:
                for i in range(count):
                    top, left, h, w = struct.unpack_from("<4H", shot, offset + i * stride)
                    faces += rectangle(left, top, w, h, frame_w or width, frame_h or height)
    return boxes, faces


def panasonic_regions(notes, endian, width, height):
    boxes, faces = [], []
    point = sequence(notes.get(0x4D))
    if len(point) == 2:
        # Fraction values must stay rational until after validation.
        x, y = (float(v) for v in point)
        if (x, y) != (0, 0):
            boxes = center(x, y, 1, 1)
    data = words(notes.get(0x4E), endian)
    if data and 0 < data[0] <= 15 and len(data) >= 1 + data[0] * 4 and width and height:
        frame_height = 320 * height / width
        for i in range(data[0]):
            x, y, w, h = data[1 + i * 4 : 5 + i * 4]
            faces += rectangle(x - w / 2, y - h / 2, w, h, 320, frame_height)
    if notes.get(0x07) == 2:
        boxes = []
    return boxes, faces


def pentax_regions(notes, endian):
    boxes, faces = [], []
    af = words(notes.get(0x40C), endian)
    if len(af) >= 7 and af[0] in (0, 2) and 0 < af[3] <= min(af[2], 512):
        count = af[3]
        if len(af) >= 7 + count * 7:
            for i in range(count):
                width, height, x, y, w, h, flags = af[7 + i * 7 : 14 + i * 7]
                if flags & 4:  # in-focus, not merely selected/peripheral
                    boxes += center(x, y, width, height, w or None, h or None)
    if not boxes and (not af or af[0] in (0, 2)):
        area = sequence(notes.get(0x231))
        if len(area) == 4:
            boxes = rectangle(*area, 720, 480)
    data = words(notes.get(0x40B), endian, "I")
    if len(data) >= 10 and 0 < data[6] <= 64 and len(data) >= 10 + (data[6] - 1) * 20 + 4:
        width, height = data[:2]
        for i in range(data[6]):
            top, left, w, h = data[10 + i * 20 : 14 + i * 20]
            faces += rectangle(left, top, w, h, width, height)
    mode = notes.get(0x0D)
    if isinstance(mode, int) and mode & 0x7FFF in (2, 3, 5, 12):
        boxes = []  # infinity / MF / pan-focus / GR Snap can retain older CAF data
    return boxes, faces


def olympus_regions(reader, notes, base):
    boxes, faces = [], []
    settings = notes.get(0x2020)
    if isinstance(settings, int):
        fields, _ = reader.ifd(settings + base, base=base)
        area = sequence(fields.get(0x305))
        if len(area) == 5:
            x1, y1, x2, y2 = (float(v) for v in area[1:])
            boxes = rectangle(x1, y1, x2 - x1, y2 - y1)
    processing = notes.get(0x2040)
    if isinstance(processing, int):
        fields, _ = reader.ifd(processing + base, base=base)
        count, frame = sequence(fields.get(0x1200)), sequence(fields.get(0x1203))
        area = sequence(fields.get(0x1201))
        # Only the documented four-corner form; rotated square layouts differ.
        if len(count) == 2 and len(frame) >= 2 and 0 < count[0] <= 64:
            crop = sequence(fields.get(0x1207))
            left, top, width, height = 0, 0, *frame[:2]
            if len(crop) >= 4 and any(crop[:4]):
                left, top, width, height = crop[:4]
                if left < 0 or top < 0 or left + width > frame[0] or top + height > frame[1]:
                    return boxes, faces
            if len(area) >= count[0] * 8:
                for i in range(count[0]):
                    points = area[i * 8 : i * 8 + 8]
                    xs, ys = points[::2], points[1::2]
                    faces += rectangle(
                        min(xs) - left,
                        min(ys) - top,
                        max(xs) - min(xs),
                        max(ys) - min(ys),
                        width,
                        height,
                    )
    return boxes, faces


def ricoh_regions(notes, endian, width, height):
    boxes, faces = [], []
    if (
        notes.get(0x1200) == 1
        and notes.get(0x1006) not in (1, 4, 5)
        and 0x1203 in notes
        and 0x1204 in notes
    ):
        boxes = center(notes[0x1203], notes[0x1204], width, height)
    data = notes.get(0x1A)
    if isinstance(data, bytes) and len(data) >= 188:
        count = data[0xB5]
        if 0 < count <= 8 and len(data) >= 0xBC + (count - 1) * 12 + 8:
            w, h = struct.unpack_from(endian + "2H", data, 0xB6)
            for i in range(count):
                faces += rectangle(*struct.unpack_from(endian + "4H", data, 0xBC + i * 12), w, h)
    return boxes, faces


def sigma_regions(notes, width, height):
    """fp/fp L sample mapping confirmed by the user; coordinates precede EXIF rotation."""
    boxes, eyes = [], []
    # Do not display a previous AF selection from a manual-focus exposure.
    if str(notes.get(0x06, "")).strip().upper() != "AF":
        return boxes, eyes
    areas = sequence(notes.get(0x010F))
    if len(areas) == 36:
        for i in range(0, 36, 4):
            boxes += rectangle(*areas[i : i + 4], width, height)
    eye = sequence(notes.get(0x0066))
    if len(eye) == 4:
        eyes = rectangle(*eye, width, height)
    return boxes, eyes


def canon_regions(notes, model="", endian="<"):
    points = []
    data = words(notes.get(0x24), endian)
    if len(data) >= 8 and 0 < data[2] <= 9 and len(data) >= 8 + 2 * data[2]:
        frame_w, frame_h = data[3:5]
        if frame_w and frame_h:
            for i in range(data[2]):
                x, y = data[8 + 2 * i : 10 + 2 * i]
                x = x - 65536 if x >= 32768 else x
                y = y - 65536 if y >= 32768 else y
                points.append((0.5 + x / frame_w, 0.5 + y / frame_h))
    return {
        "boxes": canon_focus(notes, model),
        "faces": [],
        "face_points": [(x, y) for x, y in points if 0 <= x <= 1 and 0 <= y <= 1],
    }


def dimensions(reader, root, exif):
    if isinstance(exif.get(40962), int) and isinstance(exif.get(40963), int):
        if exif[40962] > 0 and exif[40963] > 0:
            return exif[40962], exif[40963]
    candidates, pending, seen = [root], sequence(root.get(330)), set()
    if isinstance(root.get(330), int):
        pending = [root[330]]
    while pending and len(seen) < 16:
        offset = pending.pop()
        if not isinstance(offset, int) or offset in seen:
            continue
        seen.add(offset)
        fields, _ = reader.ifd(offset)
        candidates.append(fields)
        pending += sequence(fields.get(330))
    sizes = []
    for fields in candidates:
        width, height = fields.get(256, 0), fields.get(257, 0)
        if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
            sizes.append((width, height))
    return max(sizes, key=lambda pair: pair[0] * pair[1], default=(0, 0))


def regions_from_tiff(reader):
    root, root_positions = reader.ifd()
    exif, positions = reader.ifd(root.get(34665, 0))
    width, height = dimensions(reader, root, exif)
    result = {"boxes": [], "faces": [], "face_points": [], "orientation": root.get(274, 1)}
    packet = root.get(700, b"")
    if isinstance(packet, list) and all(isinstance(v, int) and 0 <= v <= 255 for v in packet):
        packet = bytes(packet)
    result["faces"] = xmp_faces(packet)
    try:
        fields = maker_reader(reader, root, exif, {**root_positions, **positions})
        if not fields:
            return result
        brand, maker, first, base = fields
        notes, _ = maker.ifd(first, base=base)
        eyes = []
        if brand == "sigma":
            boxes, eyes = sigma_regions(notes, width, height)
            faces = []
        elif brand == "canon":
            canon = canon_regions(notes, str(root.get(272, "")), maker.endian)
            boxes, faces = canon["boxes"], canon["faces"]
        elif brand == "nikon":
            boxes, faces = nikon_regions(notes, maker.endian)
        elif brand == "fuji":
            boxes, faces = fuji_regions(notes, width, height)
        elif brand == "sony":
            boxes, faces = sony_regions(notes, maker.endian, width, height)
        elif brand == "panasonic":
            boxes, faces = panasonic_regions(notes, maker.endian, width, height)
        elif brand == "pentax":
            boxes, faces = pentax_regions(notes, maker.endian)
        elif brand == "ricoh":
            boxes, faces = ricoh_regions(notes, maker.endian, width, height)
        else:
            boxes, faces = olympus_regions(maker, notes, base)
        points = canon["face_points"] if brand == "canon" else []
        if brand == "pentax":
            data = notes.get(0x60)
            if isinstance(data, bytes) and len(data) >= 4 and data[0] > 0:
                points = [(data[2] / 100, data[3] / 100)]
        result.update(
            boxes=boxes[:512],
            eyes=eyes[:64],
            faces=(faces + result["faces"])[:64],
            face_points=[(x, y) for x, y in points if 0 <= x <= 1 and 0 <= y <= 1],
        )
        return result
    except (ValueError, TypeError, ZeroDivisionError, OverflowError, struct.error):
        return result


def tiff_regions(data):
    try:
        return regions_from_tiff(Tiff(data))
    except (ValueError, TypeError, ZeroDivisionError, OverflowError, struct.error):
        return {"boxes": [], "faces": []}


def jpeg_regions(data, start, length, token=None):
    stop = start + length
    if start < 0 or stop > len(data) or data[start : start + 2] != b"\xff\xd8":
        return {"boxes": [], "faces": []}
    pos = start + 2
    for _ in range(256):
        if token:
            token.checkpoint()
        marker = data[pos : pos + 4]
        if len(marker) < 4 or marker[0] != 255 or marker[1] in (0xDA, 0xD9):
            break
        size = struct.unpack(">H", marker[2:4])[0]
        if size < 2 or pos + 2 + size > stop:
            break
        if marker[1] == 0xE1 and data[pos + 4 : pos + 10] == b"Exif\0\0":
            return tiff_regions(data[pos + 10 : pos + 2 + size])
        pos += 2 + size
    return {"boxes": [], "faces": []}


def raw_regions(path, token=None):
    if token:
        token.checkpoint()
    try:
        with Path(path).open("rb") as handle:
            header = handle.read(92)
            data = FileData(handle)
            if header.startswith(b"FUJIFILMCCD-RAW") and len(header) == 92:
                start, length = struct.unpack_from(">2I", header, 84)
                if start >= 92:
                    return jpeg_regions(data, start, length, token)
                return {"boxes": [], "faces": []}
            reader = FileTiff(data)
            if reader.unpack("H", 2)[0] == 85:  # RW2/RWL EXIF lives in JpgFromRaw.
                offset = reader.first
                count = reader.unpack("H", offset)[0]
                if count <= 2048 and offset + 2 + count * 12 <= len(data):
                    for i in range(count):
                        if token:
                            token.checkpoint()
                        tag, kind, length, start = reader.unpack("HHII", offset + 2 + i * 12)
                        if tag in (0x2E, 0x127) and kind in (1, 7) and length > 4:
                            region = jpeg_regions(data, start, length, token)
                            if (
                                region.get("boxes")
                                or region.get("faces")
                                or region.get("face_points")
                            ):
                                return region
            return regions_from_tiff(reader)
    except (OSError, ValueError, TypeError, ZeroDivisionError, OverflowError, struct.error):
        return {"boxes": [], "faces": []}
