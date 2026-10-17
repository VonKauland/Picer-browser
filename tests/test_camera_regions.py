"""Independent manufacturer wire layouts, bounded reads and mixed AF/face display."""

import struct
from fractions import Fraction

import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from picer.camera_regions import (
    canon_regions,
    fuji_regions,
    nikon_regions,
    panasonic_regions,
    pentax_regions,
    raw_regions,
    sony_regions,
    tiff_regions,
)
from picer.metadata import inspect_image
from picer.window import MainWindow
from picer.xmp_regions import xmp_faces


@pytest.mark.parametrize(
    "version,offset",
    [(b"0100", 16), (b"0101", 70), (b"0300", 42), (b"0400", 62), (b"0401", 62), (b"0402", 62)],
)
@pytest.mark.parametrize("endian", ["<", ">"])
def test_nikon_recorded_area_versions(version, offset, endian):
    data = bytearray(offset + 14)
    data[:4] = version
    data[4], data[7] = 1, 1
    struct.pack_into(endian + "6H", data, offset, 6000, 4000, 1800, 2400, 600, 400)
    points, _ = nikon_regions({0xB7: bytes(data)}, endian)
    assert points[0] == pytest.approx((0.25, 0.55, 0.1, 0.1))
    data[4], data[7] = 0, 0  # phase-detect IDs alone have no reliable pixel position
    assert nikon_regions({0xB7: bytes(data)}, endian)[0] == []
    assert nikon_regions({0xB7: bytes(data[:offset])}, endian)[0] == []


def test_nikon_faces_are_not_af_points():
    faces = struct.pack("<8H", 0, 1000, 500, 1, 50, 200, 100, 150)
    af, boxes = nikon_regions({0x21: faces}, "<")
    assert af == []
    assert boxes[0] == pytest.approx((0.2, 0.1, 0.1, 0.3))


def test_fuji_faces_and_focus_are_independent():
    af, faces = fuji_regions(
        {0x1023: [900, 1200], 0x4100: 1, 0x4103: [300, 400, 900, 1600]}, 3000, 2000
    )
    assert af[0] == pytest.approx((0.285, 0.585, 0.03, 0.03))
    assert faces[0] == pytest.approx((0.1, 0.2, 0.2, 0.6))


def test_panasonic_leica_rational_position_and_faces():
    af, faces = panasonic_regions(
        {0x4D: [Fraction(1, 4), Fraction(3, 4)], 0x4E: struct.pack("<5H", 1, 160, 100, 32, 20)},
        "<",
        6000,
        4000,
    )
    assert af[0][:2] == pytest.approx((0.235, 0.735))
    assert faces[0] == pytest.approx((0.45, 90 / (320 * 2 / 3), 0.1, 20 / (320 * 2 / 3)))
    assert panasonic_regions({0x4D: [16777216, 16777216]}, "<", 6000, 4000)[0] == []


def test_sony_multiple_points_and_validated_playback_fallback():
    record = bytes([1, 2]) + struct.pack("<6H", 640, 428, 320, 214, 160, 107)
    af, _ = sony_regions({0x202A: record}, "<")
    assert len(af) == 2
    assert af[1][:2] == pytest.approx((0.235, 0.235))
    assert sony_regions({0x2027: [6000, 4000, 3000, 2000]}, "<")[0] == []
    assert sony_regions({0x2027: [6000, 4000, 3000, 2000], 0x2037: [300, 200, 257]}, "<")[0]


def test_sony_shot_info_real_face_dimensions():
    data = bytearray(0x68)
    data[:2] = b"II"
    struct.pack_into("<H", data, 2, 0x48)
    struct.pack_into("<2H", data, 0x1A, 4000, 6000)
    struct.pack_into("<2H", data, 0x30, 1, 0x20)
    struct.pack_into("<4H", data, 0x48, 800, 600, 1200, 1800)
    af, faces = sony_regions({0x3000: bytes(data)}, "<")
    assert not af
    assert faces[0] == pytest.approx((0.1, 0.2, 0.3, 0.3))


def test_gr_iii_iiix_and_pentax_regions_use_in_focus_flags():
    af = [
        2,
        0x2002,
        2,
        2,
        0,
        0,
        0,
        6000,
        4000,
        1800,
        2400,
        600,
        400,
        4,
        6000,
        4000,
        3000,
        2000,
        0,
        0,
        0x10,
    ]  # selected is not in-focus
    face = [6000, 4000, 0, 0, 0, 0, 1, 0, 0, 0, 800, 600, 1800, 1200]
    points, faces = pentax_regions(
        {
            0x40C: struct.pack("<" + "H" * len(af), *af),
            0x40B: struct.pack("<" + "I" * len(face), *face),
        },
        "<",
    )
    assert len(points) == 1
    assert points[0] == pytest.approx((0.25, 0.55, 0.1, 0.1))
    assert faces[0] == pytest.approx((0.1, 0.2, 0.3, 0.3))
    assert pentax_regions({0x231: [72, 48, 144, 96]}, "<")[0][0] == pytest.approx(
        (0.1, 0.1, 0.2, 0.2)
    )


def test_canon_face_centers_are_not_invented_extents():
    notes = {0x24: [0, 0, 1, 640, 480, 0, 0, 0, 160, 65536 - 120]}
    data = canon_regions(notes)
    assert data["faces"] == []
    assert data["face_points"][0] == (0.75, 0.25)


class Builder:
    def __init__(self, endian="<", magic=42):
        self.endian = endian
        self.data = bytearray(
            (b"II" if endian == "<" else b"MM") + struct.pack(endian + "HI", magic, 8)
        )

    def ifd(self, entries, *, base=0):
        start = len(self.data)
        self.data.extend(b"\0" * (6 + 12 * len(entries)))
        struct.pack_into(self.endian + "H", self.data, start, len(entries))
        for i, (tag, kind, value) in enumerate(entries):
            if isinstance(value, str):
                raw, count = value.encode() + b"\0", len(value.encode()) + 1
            elif isinstance(value, bytes):
                raw, count = value, len(value)
            elif kind in (5, 10):
                items = value
                raw = b"".join(
                    struct.pack(self.endian + ("II" if kind == 5 else "ii"), *pair)
                    for pair in items
                )
                count = len(items)
            else:
                items = value if isinstance(value, list) else [value]
                fmt = {3: "H", 4: "I", 8: "h"}[kind]
                raw, count = struct.pack(self.endian + fmt * len(items), *items), len(items)
            p = start + 2 + i * 12
            struct.pack_into(self.endian + "HHI", self.data, p, tag, kind, count)
            if len(raw) <= 4:
                self.data[p + 8 : p + 8 + len(raw)] = raw
            else:
                struct.pack_into(self.endian + "I", self.data, p + 8, len(self.data) - base)
                self.data.extend(raw)
        return start


def photo_tiff(make, note, *, endian="<", magic=42, model="Test"):
    root = Builder(endian, magic)
    # A stable EXIF pointer is reserved before writing the MakerNote payload.
    root.ifd(
        [
            (256, 4, 6000),
            (257, 4, 4000),
            (271, 2, make),
            (272, 2, model),
            (274, 3, 6),
            (34665, 4, 0),
        ]
    )
    exif = root.ifd([(37500, 7, note)])
    struct.pack_into(endian + "I", root.data, 8 + 2 + 5 * 12 + 8, exif)
    return bytes(root.data)


@pytest.mark.parametrize(
    "header,brand,model",
    [
        (b"RICOH\0II", "RICOH IMAGING COMPANY, LTD.", "RICOH GR III"),
        (b"RICOH\0II", "RICOH IMAGING COMPANY, LTD.", "RICOH GR IIIx"),
        (b"PENTAX \0II", "PENTAX", "K-3 Mark III"),
    ],
)
def test_real_maker_header_offsets(header, brand, model, tmp_path):
    note = Builder()
    note.data = bytearray(header)
    note.ifd([(0x231, 3, [72, 48, 144, 96])])
    data = photo_tiff(brand, bytes(note.data), model=model)
    parsed = tiff_regions(data)
    assert parsed["boxes"][0] == pytest.approx((0.1, 0.1, 0.2, 0.2))
    path = tmp_path / "record.dng"
    path.write_bytes(data)
    assert raw_regions(path) == parsed
    # AF extraction survives an undecodable pixel payload.
    assert inspect_image(path)["focus_points"]["boxes"] == parsed["boxes"]


@pytest.mark.parametrize("endian", ["<", ">"])
def test_nikon_embedded_tiff_byte_order(endian):
    note = Builder(endian)
    af = bytearray(0x38)
    af[:4], af[7] = b"0300", 1
    struct.pack_into(endian + "6H", af, 0x2A, 6000, 4000, 1800, 2400, 600, 400)
    note.ifd([(0xB7, 7, bytes(af))])
    parsed = tiff_regions(photo_tiff("NIKON CORPORATION", b"Nikon\0\x02\x10\0\0" + note.data))
    assert parsed["boxes"][0] == pytest.approx((0.25, 0.55, 0.1, 0.1))


XMP = b"""<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:m="http://www.metadataworkinggroup.com/schemas/regions/" xmlns:a="http://ns.adobe.com/xmp/sType/Area#">
 <rdf:RDF><rdf:Description><m:Regions><m:RegionList><rdf:Bag><rdf:li m:Type="Face">
 <m:Area a:x="0.25" a:y="0.5" a:w="0.2" a:h="0.4" a:unit="normalized"/>
 </rdf:li><rdf:li m:Type="Pet"><m:Area a:x="0.5" a:y="0.5" a:w="0.2" a:h="0.2" a:unit="normalized"/>
 </rdf:li></rdf:Bag></m:RegionList></m:Regions></rdf:Description></rdf:RDF></x:xmpmeta>"""


@pytest.mark.parametrize(
    "make",
    [
        "Canon",
        "NIKON",
        "SONY",
        "FUJIFILM",
        "Panasonic",
        "LEICA",
        "OM SYSTEM",
        "RICOH",
        "PENTAX",
        "SIGMA",
        "Hasselblad",
        "SAMSUNG",
    ],
)
def test_embedded_standard_face_regions_for_every_make(make, tmp_path):
    path = tmp_path / "face.jpg"
    exif = Image.Exif()
    exif[271] = make
    exif[272] = "fp L" if make == "SIGMA" else "Test"
    Image.new("RGB", (100, 100)).save(path, exif=exif, xmp=XMP)
    assert inspect_image(path)["focus_points"]["faces"][0] == pytest.approx((0.15, 0.3, 0.2, 0.4))


def test_xmp_rejects_unsafe_and_invalid_records():
    assert xmp_faces(b'<!DOCTYPE a [<!ENTITY b "boom">]><a>&b;</a>') == []
    assert xmp_faces(XMP.replace(b"0.25", b"NaN")) == []
    assert xmp_faces(XMP.replace(b"normalized", b"pixel")) == []
    assert xmp_faces(XMP * 10000) == []


def test_overlay_faces_keep_extent_and_dash_style(qtbot, tmp_path):
    host = MainWindow(load_examples=False, plugin_root=tmp_path / "state")
    qtbot.addWidget(host)
    host.current_path = tmp_path / "face.jpg"
    host.view.image_item.setPixmap(QPixmap(1000, 800))
    data = {"boxes": [(0.1, 0.2, 0.3, 0.3)], "faces": [(0.1, 0.2, 0.3, 0.3)], "orientation": 1}
    try:
        host.focus_points.set("test", data)
        af = host.focus_points.item.path().boundingRect()
        face = host.focus_points.faces_item.path().boundingRect()
        assert af.width() == pytest.approx(100)
        assert face.width() == pytest.approx(300)
        assert host.focus_points.item.pen().style() == Qt.PenStyle.SolidLine
        assert host.focus_points.faces_item.pen().style() == Qt.PenStyle.DashLine
        host.focus_points.set("test", {"faces": data["faces"], "orientation": 6})
        assert host.focus_points.faces_item.isVisible()
        host.focus_points.remove("test")
        assert not host.focus_points.faces_item.isVisible()
        host.focus_points.set("test", {"face_points": [(0.75, 0.25)]})
        assert host.focus_points.faces_item.isVisible()
        host.focus_points.clear()
        assert host.focus_points.faces_item.path().isEmpty()
        with pytest.raises(ValueError):
            host.focus_points.set("test", {"faces": [(0, 0, float("nan"), 1)]})
    finally:
        host.plugins.shutdown()


def outer_photo(make, signature, entries, endian="<"):
    root = Builder(endian)
    root.ifd([(256, 4, 6000), (257, 4, 4000), (271, 2, make), (34665, 4, 0)])
    exif = root.ifd([(37500, 7, b"xx")])
    struct.pack_into(endian + "I", root.data, 8 + 2 + 3 * 12 + 8, exif)
    maker = len(root.data)
    root.data.extend(signature)
    root.ifd(entries)
    struct.pack_into(endian + "II", root.data, exif + 2 + 4, len(root.data) - maker, maker)
    return bytes(root.data)


@pytest.mark.parametrize(
    "make,signature", [("Panasonic", b"Panasonic\0\0\0"), ("LEICA", b"LEICA\0\0\0")]
)
@pytest.mark.parametrize("endian", ["<", ">"])
def test_panasonic_and_leica_outer_tiff_offsets(make, signature, endian):
    data = outer_photo(make, signature, [(0x4D, 5, [(1, 4), (3, 4)])], endian)
    assert tiff_regions(data)["boxes"][0][:2] == pytest.approx((0.235, 0.735))


def test_gr_older_native_fields_and_face_rectangles():
    face = bytearray(0xBC + 8)
    face[0xB5] = 1
    struct.pack_into("<2H", face, 0xB6, 1000, 500)
    struct.pack_into("<4H", face, 0xBC, 200, 50, 100, 150)
    data = outer_photo(
        "RICOH",
        b"Ricoh\0\0\0",
        [(0x1200, 3, 1), (0x1203, 4, 1800), (0x1204, 4, 2400), (0x1A, 7, bytes(face))],
    )
    region = tiff_regions(data)
    assert region["boxes"][0][:2] == pytest.approx((0.285, 0.585))
    assert region["faces"][0] == pytest.approx((0.2, 0.1, 0.1, 0.3))
    # Do not display a focus area when the camera reports AF failure.
    data = outer_photo(
        "RICOH", b"Ricoh\0\0\0", [(0x1200, 3, 0), (0x1203, 4, 1800), (0x1204, 4, 2400)]
    )
    assert not tiff_regions(data)["boxes"]


def test_fuji_raf_reads_only_embedded_exif(tmp_path):
    note = Builder()
    note.data = bytearray(b"FUJIFILM" + struct.pack("<I", 12))
    note.ifd([(0x1023, 3, [1800, 2400])])
    exif = b"Exif\0\0" + photo_tiff("FUJIFILM", bytes(note.data))
    jpeg = b"\xff\xd8\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif + b"\xff\xda"
    path = tmp_path / "photo.raf"
    header = bytearray(140)
    header[:16] = b"FUJIFILMCCD-RAW "
    struct.pack_into(">2I", header, 84, 140, len(jpeg))
    path.write_bytes(header + jpeg)
    assert raw_regions(path)["boxes"][0][:2] == pytest.approx((0.285, 0.585))


def test_rw2_skips_large_preview_pixel_payload(tmp_path):
    inner = outer_photo("Panasonic", b"Panasonic\0\0\0", [(0x4D, 5, [(1, 4), (3, 4)])])
    exif = b"Exif\0\0" + inner
    jpeg = b"\xff\xd8\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif + b"\xff\xda"
    root = Builder(magic=85)
    root.ifd([(0x2E, 7, jpeg)])
    start = struct.unpack_from("<I", root.data, 8 + 2 + 8)[0]
    length = 128 * 1024 * 1024
    struct.pack_into("<I", root.data, 8 + 2 + 4, length)
    path = tmp_path / "photo.rw2"
    with path.open("wb") as handle:
        handle.write(root.data)
        handle.seek(start + length - 1)
        handle.write(b"\0")
    assert raw_regions(path)["boxes"][0][:2] == pytest.approx((0.235, 0.735))


@pytest.mark.parametrize("header", [b"OLYMPUS\0II\x03\0", b"OM SYSTEM\0II\x04\0\0\0"])
def test_olympus_om_system_nested_regions_and_rational_values(header):
    note = Builder()
    note.data = bytearray(header)
    first = note.ifd([(0x2020, 4, 0), (0x2040, 4, 0)])
    settings = note.ifd([(0x305, 10, [(0, 0), (1, 10), (2, 10), (4, 10), (5, 10)])])
    processing = note.ifd(
        [
            (0x1200, 4, [1, 0]),
            (0x1203, 3, [1000, 800, 0, 0, 0, 0]),
            (0x1207, 8, [0] * 12),
            (0x1201, 8, [200, 160, 400, 160, 400, 320, 200, 320]),
        ]
    )
    struct.pack_into("<I", note.data, first + 2 + 8, settings)
    struct.pack_into("<I", note.data, first + 2 + 12 + 8, processing)
    region = tiff_regions(photo_tiff("OM SYSTEM", bytes(note.data)))
    assert region["boxes"][0] == pytest.approx((0.1, 0.2, 0.3, 0.3))
    assert region["faces"][0] == pytest.approx((0.2, 0.2, 0.2, 0.2))


def test_sony_flexible_spot_is_mode_gated():
    note = {0x201D: [160, 360], 0x201C: 3, 0x201B: 2}
    assert sony_regions(note, "<")[0][0][:2] == pytest.approx((0.235, 0.735))
    note[0x201C] = 0  # wide AF can leave stale flexible-spot settings
    assert sony_regions(note, "<")[0] == []
    note[0x201C], note[0x201B] = 3, 0
    assert sony_regions(note, "<")[0] == []


def test_standard_xmp_in_sigma_native_dng_does_not_claim_native_af():
    root = Builder()
    root.ifd([(271, 2, "SIGMA"), (272, 2, "fp L"), (700, 1, XMP)])
    result = tiff_regions(bytes(root.data))
    assert result["boxes"] == []
    assert result["faces"][0] == pytest.approx((0.15, 0.3, 0.2, 0.4))
    assert "样片" in result["message"]


def test_canon_cr3_standard_xmp_uuid_faces(tmp_path):
    from picer.camera_metadata import XMP_UUID, read_cr3
    from picer.smoke_samples import make_cr3_metadata

    path = make_cr3_metadata(tmp_path / "face.cr3")
    with path.open("ab") as handle:
        handle.write(struct.pack(">I4s", len(XMP) + 24, b"uuid") + XMP_UUID + XMP)
    _, data = read_cr3(path, regions=True)
    assert data["boxes"]
    assert data["faces"][0] == pytest.approx((0.15, 0.3, 0.2, 0.4))


def test_microsoft_rectangle_and_bad_region_isolation():
    packet = b"""<root xmlns:m="http://ns.microsoft.com/photo/1.2/t/Region#">
    <region m:Rectangle="nan,0.2,0.3,0.4"/><region m:Rectangle="0.1,0.2,0.3,0.4"/></root>"""
    assert xmp_faces(packet) == [(0.1, 0.2, 0.3, 0.4)]


def test_manual_and_gr_snap_modes_do_not_reuse_stale_af_locations():
    assert not fuji_regions({0x1021: 1, 0x1023: [900, 1200]}, 3000, 2000)[0]
    assert not panasonic_regions({7: 2, 0x4D: [Fraction(1, 4), Fraction(3, 4)]}, "<", 3000, 2000)[0]
    for mode in (2, 3, 12, 0x8003):
        assert not pentax_regions({0x0D: mode, 0x231: [72, 48, 144, 96]}, "<")[0]
    assert not pentax_regions({0x40C: [255] * 7, 0x231: [72, 48, 144, 96]}, "<")[0]
    data = outer_photo(
        "RICOH",
        b"RICOH\0\0\0",
        [(0x1006, 3, 4), (0x1200, 3, 1), (0x1203, 4, 1800), (0x1204, 4, 2400)],
    )
    assert not tiff_regions(data)["boxes"]
