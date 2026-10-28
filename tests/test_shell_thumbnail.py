"""Actual pixels, helper isolation, bitmap wire format and scoped registration."""

import struct
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

from picer.shell_thumbnail import (
    PROVIDER_CLSID,
    THUMBNAIL_IID,
    corner_polygon,
    decoration_allowed,
    render_thumbnail,
    write_bitmap,
)
from scripts.build_installer import registry_lines


@pytest.mark.parametrize("size", [(400, 200), (180, 400), (256, 256), (600, 30)])
@pytest.mark.parametrize("edge", [32, 64, 256])
def test_complete_image_and_only_two_neutral_corner_tags(qapp, size, edge):
    source = QImage(*size, QImage.Format.Format_ARGB32)
    source.fill(QColor(200, 70, 20))
    original = source.copy()
    result = render_thumbnail(source, ".webp", edge)
    assert source == original
    assert max(result.width(), result.height()) == edge
    factor = edge / max(size)
    assert abs(result.width() - size[0] * factor) <= 1
    assert abs(result.height() - size[1] * factor) <= 1
    baseline = source.scaled(
        edge, edge, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    ).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    assert result.pixelColor(result.width() // 2, result.height() // 2) == QColor(200, 70, 20)
    # The two untagged corners retain content, with no new border or backing plate.
    assert result.pixel(result.width() - 1, 0) == baseline.pixel(result.width() - 1, 0)
    assert result.pixel(0, result.height() - 1) == baseline.pixel(0, result.height() - 1)
    top, _ = corner_polygon(result.width(), result.height())
    bottom, _ = corner_polygon(result.width(), result.height(), bottom=True)
    for y in range(result.height()):
        for x in range(result.width()):
            color = result.pixelColor(x, y)
            if color != QColor(200, 70, 20) and color.red() == color.green() == color.blue():
                # All material and format text are grayscale, without an accent tint.
                assert top.boundingRect().adjusted(-1, -1, 1, 1).contains(x, y) or (
                    bottom.boundingRect().adjusted(-1, -1, 1, 1).contains(x, y)
                )


def test_format_changes_only_bottom_tag_and_alpha_is_preserved(qapp):
    source = QImage(256, 256, QImage.Format.Format_ARGB32)
    source.fill(QColor(30, 120, 190, 140))
    jpg = render_thumbnail(source, ".jpg", 256)
    png = render_thumbnail(source, ".png", 256)
    assert jpg.copy(0, 0, 256, 128) == png.copy(0, 0, 256, 128)
    assert jpg.copy(128, 128, 128, 128) != png.copy(128, 128, 128, 128)
    assert jpg.pixelColor(120, 120).alpha() == 140
    # Lettering remains within the strap: changing labels cannot alter outer pixels.
    polygon, _ = corner_polygon(256, 256, bottom=True)
    from PySide6.QtCore import QPointF, Qt

    for y in range(256):
        for x in range(256):
            if jpg.pixel(x, y) != png.pixel(x, y):
                assert polygon.containsPoint(QPointF(x + 0.5, y + 0.5), Qt.FillRule.OddEvenFill)


def test_bitmap_is_bounded_top_down_bgra(qapp, tmp_path):
    source = QImage(40, 30, QImage.Format.Format_ARGB32)
    source.fill(QColor(80, 20, 10, 128))
    target = tmp_path / "thumbnail.bmp"
    write_bitmap(source, target)
    data = target.read_bytes()
    assert len(data) == 54 + 40 * 30 * 4
    assert struct.unpack_from("<2sIHHI", data) == (b"BM", len(data), 0, 0, 54)
    assert struct.unpack_from("<IiiHH", data, 14) == (40, 40, -30, 1, 32)
    assert data[54:58] == bytes((5, 10, 40, 128))
    assert not target.with_suffix(".tmp").exists()


def test_packaged_entry_dispatches_without_viewer_state_and_rejects_invalid_size(tmp_path):
    root = Path(__file__).resolve().parents[1]
    work = tmp_path / "含空格 thumbnail"
    work.mkdir()
    source = work / "source.jpg"
    (work / "origin.name").write_text(r"C:\Photos\oriented.jpg", encoding="utf-16-le")
    image = Image.new("RGB", (120, 80), "red")
    exif = Image.Exif()
    exif[274] = 6
    image.save(source, exif=exif)
    before = source.read_bytes()
    command = [sys.executable, str(root / "scripts/entrypoint.py"), "--shell-thumbnail", str(work)]
    result = subprocess.run(command + ["128"], cwd=tmp_path, timeout=20, capture_output=True)
    assert result.returncode == 0, result.stderr
    with Image.open(work / "thumbnail.bmp") as output:
        assert output.size == (85, 128)  # EXIF orientation, complete aspect ratio.
        red, green, blue = output.convert("RGB").getpixel((10, 5))
        assert red == green == blue
    assert source.read_bytes() == before
    assert set(p.name for p in tmp_path.iterdir()) == {work.name}
    assert set(p.name for p in work.iterdir()) == {"source.jpg", "origin.name", "thumbnail.bmp"}
    assert subprocess.run(command + ["4096"], timeout=20).returncode == 2


@pytest.mark.parametrize(
    ("name", "allowed"),
    [
        (r"C:\Photos\photo.png", True),
        (r"\\?\C:\Photos\photo.png", True),
        (r"\\?\UNC\nas\Photos\photo.png", True),
        (r"\\?\C:\Windows\System32\icon.png", False),
        (r"\\nas\Photos\photo.PNG", True),
        (r"C:\Photos\photo.jpg", False),
        ("inifile.png", False),
        ("", False),
        ("file:///C:/Photos/photo.png", False),
        ("@{Microsoft.Notepad?ms-resource://Notepad/Files/Assets/inifile.png}", False),
        (r"C:\Program Files\WindowsApps\Microsoft.Notepad\Assets\inifile.png", False),
        (r"D:\WindowsApps\Notepad\Assets\inifile.png", False),
        (r"C:\Windows\SystemResources\icon.png", False),
        (r"C:\Program Files\SomeApplication\icon.png", False),
        (r"D:\Profile\Local\Packages\Notepad\Assets\inifile.png", False),
        ("C:\\Photos\\photo.png\x00", False),
    ],
)
def test_only_named_document_previews_receive_straps(tmp_path, monkeypatch, name, allowed):
    monkeypatch.setenv("LOCALAPPDATA", r"D:\Profile\Local")
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    monkeypatch.setenv("ProgramFiles(x86)", r"C:\Program Files (x86)")
    monkeypatch.setenv("ProgramW6432", r"C:\Program Files")
    (tmp_path / "origin.name").write_text(name, encoding="utf-16-le")
    assert decoration_allowed(tmp_path, ".png") is allowed
    assert not decoration_allowed(tmp_path, ".img")


@pytest.mark.parametrize(
    "metadata", [None, b"\x00", b"x" * 65536], ids=["missing", "invalid-utf16", "oversized"]
)
def test_missing_or_invalid_origin_falls_back_to_unmodified_preview(tmp_path, metadata):
    if metadata is not None:
        (tmp_path / "origin.name").write_bytes(metadata)
    assert not decoration_allowed(tmp_path, ".png")


@pytest.mark.parametrize(
    ("filename", "origin"),
    [
        ("source.png", r"C:\Program Files\WindowsApps\Notepad\Assets\inifile.png"),
        ("source.png", None),
        ("source.img", None),
    ],
)
def test_icon_resource_or_anonymous_stream_keeps_exact_original_pixels(tmp_path, filename, origin):
    source = tmp_path / filename
    Image.new("RGBA", (90, 60), (40, 80, 120, 255)).save(source, format="PNG")
    if origin is not None:
        (tmp_path / "origin.name").write_text(origin, encoding="utf-16-le")
    entry = Path(__file__).resolve().parents[1] / "scripts/entrypoint.py"
    result = subprocess.run(
        [sys.executable, str(entry), "--shell-thumbnail", str(tmp_path), "128"],
        timeout=20,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    with Image.open(tmp_path / "thumbnail.bmp") as image:
        assert image.size == (90, 60)
        assert set(image.convert("RGBA").getdata()) == {(40, 80, 120, 255)}


@pytest.mark.parametrize("extension", ["ini", "ps1"])
def test_configuration_and_script_inputs_never_become_thumbnails(tmp_path, extension):
    (tmp_path / ("source." + extension)).write_text("name=Example\nscreenshot=Cover.png\n")
    Image.new("RGB", (90, 60), "blue").save(tmp_path / "Cover.png")
    entry = Path(__file__).resolve().parents[1] / "scripts/entrypoint.py"
    result = subprocess.run(
        [sys.executable, str(entry), "--shell-thumbnail", str(tmp_path), "128"],
        timeout=20,
        capture_output=True,
    )
    assert result.returncode == 2
    assert not (tmp_path / "thumbnail.bmp").exists()


def test_registration_does_not_override_other_viewers_thumbnail_handlers():
    text = registry_lines([".png", ".dng"])
    assert PROVIDER_CLSID in text and THUMBNAIL_IID in text
    assert 'ValueData: "{app}\\shell\\PicerThumbnail.dll"' in text
    assert "DllSurrogate" in text and "ThreadingModel" in text
    for line in text.splitlines():
        if THUMBNAIL_IID in line:
            assert "Picer.Image\\shellex" in line or "Applications\\Picer.exe\\shellex" in line
        assert "UserChoice" not in line


def test_unnamed_stream_detection_and_bad_raw_exit_without_ui(qapp, tmp_path):
    from picer.shell_thumbnail import decode_stream_image

    source = tmp_path / "source.img"
    Image.new("RGB", (90, 60), "blue").save(source, format="PNG")
    image, label = decode_stream_image(source, 64)
    assert label == "png" and (image.width(), image.height()) == (64, 42)
    source.rename(tmp_path / "source.dng")
    (tmp_path / "source.dng").write_bytes(b"invalid raw")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/entrypoint.py"),
            "--shell-thumbnail",
            str(tmp_path),
            "64",
        ],
        timeout=20,
        capture_output=True,
    )
    assert result.returncode == 1 and not (tmp_path / "thumbnail.bmp").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Native per-user COM registration")
def test_native_provider_registration_isolated(tmp_path):
    from picer.windows_integration import WindowsIntegration

    exe = tmp_path / "Picer.exe"
    exe.touch()
    dll = tmp_path / "shell/PicerThumbnail.dll"
    dll.parent.mkdir()
    dll.touch()
    root = "Software\\PicerThumbnailTests\\" + uuid4().hex
    service = WindowsIntegration(exe, root=root)
    old = "{00000000-0000-0000-0000-000000000001}"
    other = "Software\\Classes\\.png\\shellex\\" + THUMBNAIL_IID
    service.write(other, "", old)
    try:
        service.register_viewer([".png"])
        assert service.read(other, "") == old
        assert (
            service.read("Software\\Classes\\Picer.Image\\shellex\\" + THUMBNAIL_IID, "")
            == PROVIDER_CLSID
        )
        assert service.read(
            "Software\\Classes\\CLSID\\" + PROVIDER_CLSID + "\\InprocServer32", ""
        ) == str(dll)
    finally:
        service.delete("")
