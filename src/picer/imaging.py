"""Shared still/RAW decoding for the viewer and plugin thumbnails."""

import os
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QImageReader

RAW_SUFFIXES = frozenset(
    ".3fr .arw .bay .cr2 .cr3 .crw .dcr .dng .erf .fff .iiq .k25 .kdc "
    ".mef .mos .mrw .nef .nrw .orf .pef .raf .raw .rw2 .rwl .sr2 .srf .srw".split()
)
# LibRaw must not occupy every CPU while the viewer and thumbnails are active.
os.environ.setdefault("OMP_NUM_THREADS", str(max(1, min(4, (os.cpu_count() or 2) // 2))))
MAX_PIXELS = 120_000_000
QImageReader.setAllocationLimit(512)


def supported_suffixes():
    return RAW_SUFFIXES | {
        f".{bytes(fmt).decode().lower()}" for fmt in QImageReader.supportedImageFormats()
    }


def pillow_image(image):
    rgba = image.convert("RGBA")
    return QImage(
        rgba.tobytes(), rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888
    ).copy()


def read_image(path, *, edge=0, auto_orient=True, token=None):
    """Return detached pixels; RAW previews prefer the embedded JPEG."""
    if token:
        token.checkpoint()
    path = Path(path)
    if path.suffix.lower() in RAW_SUFFIXES:
        import rawpy

        with rawpy.RawPy() as raw:
            raw.open_file(str(path))
            if raw.sizes.width * raw.sizes.height > MAX_PIXELS:
                raise ValueError("图片超过 1.2 亿像素的读取上限")
            native = (raw.sizes.width, raw.sizes.height)
            image = None
            if edge:
                try:
                    thumb = raw.extract_thumb()
                    if thumb.format == rawpy.ThumbFormat.JPEG:
                        with Image.open(BytesIO(thumb.data)) as source:
                            source = ImageOps.exif_transpose(source) if auto_orient else source
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
