"""Small generated media used by source tests and the real packaged EXE check."""

import struct
import zlib

from PIL import Image

from picer.camera_metadata import CANON_UUID


def make_psd(path, *, depth=8, compression=0, layer_bytes=0):
    """A merged PSD with optional sparse layer area, never a layer fixture."""
    width, height = 40, 24
    rows = []
    for base in (90, 140, 200):
        for _ in range(height):
            row = b"".join(
                struct.pack(
                    {8: ">B", 16: ">H", 32: ">f"}[depth],
                    (base + x)
                    if depth == 8
                    else (base + x) * 257
                    if depth == 16
                    else (base + x) / 255,
                )
                for x in range(width)
            )
            rows.append(row)
    if compression == 1:
        encoded = [
            b"".join(
                bytes([len(row[i : i + 128]) - 1]) + row[i : i + 128]
                for i in range(0, len(row), 128)
            )
            for row in rows
        ]
        pixels = b"".join(struct.pack(">H", len(row)) for row in encoded) + b"".join(encoded)
    else:
        if compression == 3:
            predicted = []
            for row in rows:
                if depth == 16:
                    values = [v[0] for v in struct.iter_unpack(">H", row)]
                    row = b"".join(
                        struct.pack(">H", (value - (values[i - 1] if i else 0)) & 65535)
                        for i, value in enumerate(values)
                    )
                else:
                    if depth == 32:
                        row = b"".join(row[i::4] for i in range(4))
                    row = bytes(
                        (value - (row[i - 1] if i else 0)) & 255 for i, value in enumerate(row)
                    )
                predicted.append(row)
            rows = predicted
        pixels = b"".join(rows)
        if compression in (2, 3):
            pixels = zlib.compress(pixels)
    with path.open("wb") as handle:
        handle.write(b"8BPS\0\1" + b"\0" * 6 + struct.pack(">HIIHH", 3, height, width, depth, 3))
        handle.write(struct.pack(">III", 0, 0, layer_bytes))
        handle.seek(layer_bytes, 1)
        handle.write(struct.pack(">H", compression) + pixels)
    return path


def make_stills(folder):
    """Exercise independent Qt still-image codecs without downloaded samples."""
    from PySide6.QtGui import QImage

    formats = ("png", "jpg", "bmp", "tiff", "webp", "ico", "ppm", "xbm", "xpm")
    from picer.imaging import read_image, supported_suffixes

    image = QImage(32, 24, QImage.Format.Format_RGB32)
    image.fill(0x3399CC)
    checked = []
    for suffix in formats:
        if f".{suffix}" not in supported_suffixes():
            continue
        path = folder / f"codec.{suffix}"
        assert image.save(str(path)), f"Could not create {suffix} sample"
        decoded = read_image(path)
        assert decoded.width() == 32 and decoded.height() == 24
        assert not decoded.isNull()
        checked.append(suffix)
    if ".svg" in supported_suffixes():
        path = folder / "codec.svg"
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="24">'
            '<rect width="32" height="24" fill="#3399cc"/></svg>',
            encoding="utf-8",
        )
        decoded = read_image(path)
        assert decoded.width() == 32 and decoded.height() == 24
        assert decoded.pixelColor(16, 12).name() == "#3399cc"
        checked.append("svg")
    return checked


def make_video(path, codec="mpeg4"):
    import av

    with av.open(str(path), "w") as container:
        stream = container.add_stream(codec, rate=24)
        stream.width, stream.height, stream.pix_fmt = 160, 96, "yuv420p"
        for color in ("#4d8ab2", "#a05b48", "#6c7e44"):
            for packet in stream.encode(
                av.VideoFrame.from_image(Image.new("RGB", (160, 96), color))
            ):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return path


def make_animation(path):
    frames = [Image.new("RGBA", (96, 64), color) for color in ("red", "green", "blue")]
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=[80, 130, 190],
        loop=0,
        lossless=True,
    )


def make_dng(path, *, embedded=False):
    """An original synthetic Bayer DNG, with no third-party camera sample."""
    tags = []

    def tag(number, kind, count, payload):
        tags.append((number, kind, count, payload))

    for number, value in (
        (256, 256),
        (257, 256),
        (273, 0),
        (278, 256),
        (279, 256 * 256 * 2),
        (50717, 65535),
    ):
        tag(number, 4, 1, struct.pack("<I", value))
    for number, value in (
        (258, 16),
        (259, 1),
        (262, 32803),
        (274, 1),
        (277, 1),
        (50711, 1),
        (50778, 21),
    ):
        tag(number, 3, 1, struct.pack("<H", value))
    tag(33421, 3, 2, struct.pack("<HH", 2, 2))
    tag(33422, 1, 4, bytes([0, 1, 1, 2]))
    tag(50706, 1, 4, bytes([1, 4, 0, 0]))
    tag(50707, 1, 4, bytes([1, 1, 0, 0]))
    manufacturer = b"Picer RAW Camera\0"
    tag(271, 2, len(manufacturer), manufacturer)
    model = b"PicerCamera\0"
    tag(272, 2, len(model), model)
    tag(50708, 2, len(model), model)
    tag(50710, 1, 3, bytes([0, 1, 2]))
    tag(50714, 5, 1, struct.pack("<II", 0, 1))
    tag(50721, 10, 9, b"".join(struct.pack("<ii", int(i % 4 == 0), 1) for i in range(9)))
    tag(50728, 5, 3, struct.pack("<IIIIII", 1, 1, 1, 1, 1, 1))
    tags.sort()
    offset = 8 + 2 + 12 * len(tags) + 4
    entries, extra = [], b""
    for number, kind, count, payload in tags:
        if len(payload) > 4:
            entry = struct.pack("<I", offset + len(extra))
            extra += payload
            if len(extra) % 2:
                extra += b"\0"
        else:
            entry = payload.ljust(4, b"\0")
        entries.append((number, kind, count, entry))
    pixel_offset = offset + len(extra)
    table = b"".join(
        struct.pack("<HHI", number, kind, count)
        + (struct.pack("<I", pixel_offset) if number == 273 else data)
        for number, kind, count, data in entries
    )
    pixels = b"".join(struct.pack("<H", (x + y) * 100) for y in range(256) for x in range(256))
    path.write_bytes(
        b"II*\0"
        + struct.pack("<I", 8)
        + struct.pack("<H", len(tags))
        + table
        + struct.pack("<I", 0)
        + extra
        + pixels
    )
    if embedded:
        from io import BytesIO

        jpeg = BytesIO()
        Image.new("RGB", (160, 100), "red").save(jpeg, format="JPEG")
        payload = jpeg.getvalue()
        data = bytearray(path.read_bytes())
        offset = len(data)
        struct.pack_into("<I", data, 10 + 12 * len(tags), offset)
        thumbnail = [
            (254, 4, 1),
            (256, 4, 160),
            (257, 4, 100),
            (258, 3, 8),
            (259, 3, 7),
            (262, 3, 6),
            (273, 4, 0),
            (277, 3, 3),
            (278, 4, 100),
            (279, 4, len(payload)),
            (513, 4, 0),
            (514, 4, len(payload)),
        ]
        start = offset + 2 + 12 * len(thumbnail) + 4
        data += struct.pack("<H", len(thumbnail))
        for number, kind, value in thumbnail:
            data += struct.pack("<HHII", number, kind, 1, start if number in (273, 513) else value)
        data += struct.pack("<I", 0) + payload
        path.write_bytes(data)


def _metadata_tiff(entries):
    end = 8 + 2 + 12 * len(entries) + 4
    records, extra = [], bytearray()
    for tag, kind, raw, count in entries:
        data = raw if len(raw) <= 4 else struct.pack("<I", end + len(extra))
        records.append(struct.pack("<HHI", tag, kind, count) + data.ljust(4, b"\0"))
        if len(raw) > 4:
            extra.extend(raw)
    return (
        b"II*\0\x08\0\0\0" + struct.pack("<H", len(entries)) + b"".join(records) + b"\0" * 4 + extra
    )


def _metadata_atom(kind, data):
    return struct.pack(">I4s", len(data) + 8, kind) + data


def _metadata_af_words():
    # Two recorded areas; only the second was in focus. Y is upward on EOS.
    return [
        0,
        2,
        2,
        2,
        6000,
        4000,
        6000,
        4000,
        300,
        300,
        200,
        200,
        600,
        65536 - 600,
        400,
        65536 - 400,
        2,
    ]


def make_cr3_metadata(path):
    words = _metadata_af_words()
    camera = _metadata_tiff(
        [
            (271, 2, b"Canon\0", 6),
            (272, 2, b"Canon EOS Test\0", 15),
            (274, 3, struct.pack("<H", 6), 1),
        ]
    )
    exif = _metadata_tiff(
        [
            (33434, 5, struct.pack("<II", 1, 125), 1),
            (33437, 5, struct.pack("<II", 28, 10), 1),
            (34855, 3, struct.pack("<H", 400), 1),
            (42036, 2, b"Test Lens\0", 10),
        ]
    )
    maker = _metadata_tiff([(0x26, 3, struct.pack("<" + "H" * len(words), *words), len(words))])
    payload = b"".join(
        _metadata_atom(k, v) for k, v in [(b"CMT1", camera), (b"CMT2", exif), (b"CMT3", maker)]
    )
    path.write_bytes(
        _metadata_atom(b"ftyp", b"crx \0\0\0\0crx ")
        + _metadata_atom(b"moov", _metadata_atom(b"uuid", CANON_UUID + payload))
    )
    return path
