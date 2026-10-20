"""Bounded first-frame video previews. No player, audio output or transport state."""

from pathlib import Path

from PIL import ImageFilter
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen

from picer.i18n import tr

VIDEO_SUFFIXES = frozenset(
    ".mp4 .m4v .mov .mkv .avi .webm .wmv .mpg .mpeg .mpe .flv .mts .m2ts .ts .ogv .3gp .3g2".split()
)


def film_frame(image):
    """Decorate only preview pixels, using the same frame at every thumbnail size."""
    from picer.imaging import pillow_image

    rail, lip = max(8, round(image.height() * 0.052)), max(3, round(image.height() * 0.009))
    width, height = image.width() + 2 * rail, image.height() + 2 * lip
    output = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    output.fill(Qt.GlobalColor.transparent)
    painter = QPainter(output)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    shape = QPainterPath()
    shape.addRoundedRect(QRectF(0.5, 0.5, width - 1, height - 1), lip * 1.5, lip * 1.5)
    painter.setClipPath(shape)
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    from PIL import Image

    backdrop = Image.frombytes("RGBA", (image.width(), image.height()), bytes(rgba.constBits()))
    backdrop.thumbnail((512, 512))
    backdrop = backdrop.filter(ImageFilter.GaussianBlur(12))
    painter.drawImage(QRectF(0, 0, width, height), pillow_image(backdrop))
    glass = QLinearGradient(0, 0, width, height)
    glass.setColorAt(0, QColor(165, 168, 172, 190))
    glass.setColorAt(0.5, QColor(70, 72, 76, 220))
    glass.setColorAt(1, QColor(140, 143, 148, 200))
    painter.fillPath(shape, glass)
    painter.drawImage(rail, lip, image)
    painter.setClipping(False)
    painter.setPen(QPen(QColor(195, 198, 200, 130), max(1, lip / 7)))
    painter.drawPath(shape)
    hole_w, hole_h = rail * 0.56, rail * 0.48
    step = max(hole_h * 2.1, image.height() / 14)
    count = max(1, int(image.height() / step))
    offset = (height - (count - 1) * step - hole_h) / 2
    for i in range(count):
        for x in ((rail - hole_w) / 2, width - rail + (rail - hole_w) / 2):
            rect = QRectF(x, offset + i * step, hole_w, hole_h)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(Qt.GlobalColor.transparent)
            painter.drawRoundedRect(rect, hole_h * 0.2, hole_h * 0.2)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(200, 202, 205, 145), max(1, lip / 10)))
            painter.drawRoundedRect(rect, hole_h * 0.2, hole_h * 0.2)
    painter.end()
    return output


def video_info(path):
    import av

    with Path(path).open("rb") as handle, av.open(handle) as container:
        if not container.streams.video:
            raise ValueError(tr("文件中没有可读取的视频画面"))
        stream = container.streams.video[0]
        return {
            "宽度": str(stream.width),
            "高度": str(stream.height),
            "格式": Path(path).suffix[1:].upper(),
            "预览类型": tr("视频静态封面"),
            "编码": stream.codec_context.name or tr("未知"),
            "帧率": f"{float(stream.average_rate):.3g} fps"
            if stream.average_rate
            else tr("未记录"),
            "时长": tr("{0:.2f} 秒").format(container.duration / av.time_base)
            if container.duration
            else tr("未记录"),
        }


def read_video(path, *, edge=0, token=None, auto_orient=True):
    import av

    from picer.imaging import MAX_PIXELS, pillow_image

    with Path(path).open("rb") as handle, av.open(handle) as container:
        if not container.streams.video:
            raise ValueError(tr("文件中没有可读取的视频画面"))
        stream = container.streams.video[0]
        if stream.width * stream.height > MAX_PIXELS:
            raise ValueError(tr("视频画面超过像素读取上限"))
        stream.codec_context.thread_count = 1
        scanned = 0
        for index, packet in enumerate(container.demux(stream)):
            if token:
                token.checkpoint()
            scanned += packet.size
            if index >= 256 or scanned > 64 * 1024 * 1024:
                break
            for frame in packet.decode():
                if token:
                    token.checkpoint()
                if frame.width * frame.height > MAX_PIXELS:
                    raise ValueError(tr("视频画面超过像素读取上限"))
                angle = getattr(frame, "rotation", 0) or -int(stream.metadata.get("rotate", 0))
                native = (frame.width, frame.height)
                limit = edge or 3840
                if max(native) > limit:
                    factor = limit / max(native)
                    frame = frame.reformat(
                        width=max(1, round(native[0] * factor)),
                        height=max(1, round(native[1] * factor)),
                    )
                pixels = frame.to_image()
                if auto_orient and angle in (-270, -180, -90, 90, 180, 270):
                    pixels = pixels.rotate(angle, expand=True)
                    if abs(angle) in (90, 270):
                        native = native[::-1]
                if edge:
                    pixels.thumbnail((edge, edge))
                image = film_frame(pillow_image(pixels))
                # The decorative preview has its own aspect ratio and logical bounds.
                scale = native[0] / pixels.width
                image.setText("picer.native_width", str(round(image.width() * scale)))
                image.setText("picer.native_height", str(round(image.height() * scale)))
                image.setText("picer.video_preview", "1")
                return image
    raise ValueError(tr("未能在有界读取范围内提取视频封面"))
