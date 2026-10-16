"""CR3 containers, TIFF bounds and actual AF-mask coordinate semantics."""

import struct

import pytest

from picer.camera_metadata import LIMIT, canon_focus, cr3_blocks, read_cr3
from picer.focus_points import oriented_point
from picer.metadata import inspect_image
from picer.smoke_samples import make_cr3_metadata as make_cr3


def test_all_exif_orientation_mappings():
    expected = [
        (0.2, 0.3),
        (0.8, 0.3),
        (0.8, 0.7),
        (0.2, 0.7),
        (0.3, 0.2),
        (0.7, 0.2),
        (0.7, 0.8),
        (0.3, 0.8),
    ]
    for orientation, point in enumerate(expected, 1):
        assert oriented_point(0.2, 0.3, orientation) == pytest.approx(point)


def af_words():
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


def test_cr3_metadata_survives_pixel_decoder_failure(tmp_path):
    path = make_cr3(tmp_path / "camera.cr3")
    tags, boxes = read_cr3(path)
    assert tags["Make"] == "Canon" and tags["Model"] == "Canon EOS Test"
    assert tags["LensModel"] == "Test Lens" and tags["ISOSpeedRatings"] == 400
    assert boxes[0] == pytest.approx((0.375, 0.575, 0.05, 0.05))
    result = inspect_image(path)
    assert result["exif_sections"]["基础信息"]["相机型号"] == "Canon EOS Test"
    assert result["focus_points"]["orientation"] == 6
    assert result["warnings"]  # metadata-only fixture has no decodable pixel payload


def test_old_af_and_absent_masks_do_not_invent_points():
    words = [2, 2, 6000, 4000, 6000, 4000, 300, 200, 600, 65536 - 600, 400, 65536 - 400, 2]
    assert canon_focus({0x12: words}, "EOS")[0] == pytest.approx((0.375, 0.575, 0.05, 0.05))
    modern = af_words()
    modern[-1] = 0
    assert canon_focus({0x26: modern}, "EOS") == []
    assert canon_focus({0x26: af_words()[:-1]}, "EOS") == []
    modern[2] = 65535
    assert canon_focus({0x26: modern}, "EOS") == []


def test_cr3_skips_sparse_pixel_payload_and_rejects_oversized_metadata(tmp_path):
    path = make_cr3(tmp_path / "large.cr3")
    with path.open("r+b") as file:
        file.seek(0, 2)
        file.write(struct.pack(">I4s", 64 * 1024 * 1024, b"mdat"))
        file.seek(64 * 1024 * 1024 - 9, 1)
        file.write(b"\0")
    assert path.stat().st_size > 64 * 1024 * 1024
    assert len(cr3_blocks(path)) == 3
    assert read_cr3(path)[0]["Make"] == "Canon"
    bad = tmp_path / "bad.cr3"
    bad.write_bytes(struct.pack(">I4s", LIMIT + 9, b"CMT1"))
    assert cr3_blocks(bad) == {}
