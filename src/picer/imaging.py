"""Shared still/RAW decoding for the viewer and plugin thumbnails."""

import os
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QImageReader, QTransform

from picer.video import VIDEO_SUFFIXES

RAW_SUFFIXES = frozenset(
    ".3fr .arw .bay .cr2 .cr3 .crw .dcr .dng .erf .fff .iiq .k25 .kdc "
    ".mef .mos .mrw .nef .nrw .orf .pef .raf .raw .rw2 .rwl .sr2 .srf .srw".split()
)
# LibRaw must not occupy every CPU while the viewer and thumbnails are active.
os.environ.setdefault("OMP_NUM_THREADS", str(max(1, min(4, (os.cpu_count() or 2) // 2))))
MAX_PIXELS = 120_000_000
QImageReader.setAllocationLimit(512)


def supported_suffixes():
    return (
        RAW_SUFFIXES
        | VIDEO_SUFFIXES
        | {f".{bytes(fmt).decode().lower()}" for fmt in QImageReader.supportedImageFormats()}
    )


def pillow_image(image):
    rgba = image.convert("RGBA")
    return QImage(
        rgba.tobytes(), rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888
    ).copy()


def read_image(path, *, edge=0, auto_orient=True, token=None, camera_preview=False):
    """Return detached pixels; RAW previews prefer the embedded JPEG."""
    if token:
        token.checkpoint()
    path = Path(path)
    if path.suffix.lower() in VIDEO_SUFFIXES:
        from picer.video import read_video

        return read_video(path, edge=edge, token=token, auto_orient=auto_orient)
    if path.suffix.lower() in RAW_SUFFIXES:
        import rawpy

        with rawpy.RawPy() as raw:
            raw.open_file(str(path))
            if raw.sizes.width * raw.sizes.height > MAX_PIXELS:
                raise ValueError("图片超过 1.2 亿像素的读取上限")
            native = (raw.sizes.width, raw.sizes.height)
            flip = getattr(raw.sizes, "flip", 0)
            image = None
            if edge or camera_preview:
                try:
                    thumb = raw.extract_thumb()
                    if thumb.format == rawpy.ThumbFormat.JPEG:
                        with Image.open(BytesIO(thumb.data)) as source:
                            if source.width * source.height > MAX_PIXELS:
                                raise ValueError("机内预览超过像素读取上限")
                            orientation = source.getexif().get(274, 1)
                            if auto_orient:
                                source = ImageOps.exif_transpose(source)
                                if orientation == 1:
                                    source = source.rotate(
                                        {3: 180, 5: 90, 6: 270}.get(flip, 0), expand=True
                                    )
                            if camera_preview:
                                native = source.size
                            if edge:
                                source.thumbnail((edge, edge))
                            image = pillow_image(source)
                    else:
                        data = thumb.data
                        image = QImage(
                            data.data,
                            data.shape[1],
                            data.shape[0],
                            data.strides[0],
                            QImage.Format.Format_RGB888,
                        ).copy()
                        if auto_orient and flip in (3, 5, 6):
                            image = image.transformed(
                                QTransform().rotate({3: 180, 5: -90, 6: 90}[flip])
                            )
                        if camera_preview:
                            native = (image.width(), image.height())
                    image.setText("picer.camera_preview", "1")
                except rawpy.LibRawNoThumbnailError:
                    pass
                except rawpy.LibRawUnsupportedThumbnailError:
                    pass
            if image is None:
                if token:
                    token.checkpoint()
                data = raw.postprocess(
                    use_camera_wb=True,
                    half_size=bool(edge),
                    output_bps=8,
                    user_flip=None if auto_orient else 0,
                )
                image = QImage(
                    data.data,
                    data.shape[1],
                    data.shape[0],
                    data.strides[0],
                    QImage.Format.Format_RGB888,
                ).copy()
    else:
        reader = QImageReader(str(path))
        reader.setAutoTransform(auto_orient)
        size = reader.size()
        native = (size.width(), size.height())
        if size.width() * size.height() > MAX_PIXELS:
            raise ValueError("图片超过 1.2 亿像素的读取上限")
        if edge and size.isValid() and max(size.width(), size.height()) > edge:
            reader.setScaledSize(size.scaled(edge, edge, Qt.AspectRatioMode.KeepAspectRatio))
        image = reader.read()
        if image.isNull():
            raise ValueError(reader.errorString())
    if token:
        token.checkpoint()
    if edge and max(image.width(), image.height()) > edge:
        image = image.scaled(
            edge,
            edge,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    if edge and min(native) > 0:
        # Orient logical source dimensions to match the decoded preview.
        width, height = sorted(native, reverse=image.width() >= image.height())
    else:
        width, height = image.width(), image.height()
    image.setText("picer.native_width", str(width))
    image.setText("picer.native_height", str(height))
    return image
