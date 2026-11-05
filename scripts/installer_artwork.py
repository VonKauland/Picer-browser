"""Small deterministic installer surfaces; native controls render all text."""

from pathlib import Path

from PIL import Image, ImageDraw

WIDTH, HEIGHT, SCALE = 1000, 640, 2
BACKGROUND, CARD, INPUT = "#232323", "#2e2e2e", "#38383b"
ACCENT = "#e2ff45"


def prepare_installer_artwork(icon: Path, destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    brand = Image.open(icon).convert("RGBA")
    drawing_scale = SCALE * 2
    outputs = []
    for state in ("setup", "progress", "finished"):
        image = Image.new("RGB", (WIDTH * drawing_scale, HEIGHT * drawing_scale), BACKGROUND)
        draw = ImageDraw.Draw(image)

        def box(rect, radius, fill, outline=None, draw=draw):
            draw.rounded_rectangle(
                tuple(v * drawing_scale for v in rect),
                radius=radius * drawing_scale,
                fill=fill,
                outline=outline,
                width=drawing_scale,
            )

        # DWM owns the outer frame and corner coverage; never bake a hard window mask.
        draw.line(
            (0, 58 * drawing_scale, WIDTH * drawing_scale, 58 * drawing_scale),
            fill="#343436",
            width=drawing_scale,
        )
        draw.line(
            (292 * drawing_scale, 88 * drawing_scale, 292 * drawing_scale, 614 * drawing_scale),
            fill="#343436",
        )
        box((25, 587, 136, 616), 14, "#2c2c2f", "#3a3a3e")
        for x, y, size in ((63, 215, 11), (244, 165, 14), (227, 195, 9), (238, 300, 7)):
            draw.regular_polygon(
                (x * drawing_scale, y * drawing_scale, size * drawing_scale / 2),
                n_sides=4,
                rotation=0,
                fill="#485020",
            )
        for x, y, size in ((23, 13, 32), (68, 192, 140)):
            mark = brand.resize(
                (size * drawing_scale, size * drawing_scale), Image.Resampling.LANCZOS
            )
            image.paste(mark, (x * drawing_scale, y * drawing_scale), mark)
        if state == "setup":
            box((330, 174, 970, 304), 16, CARD)
            box((350, 222, 834, 264), 12, INPUT, "#48484c")
            box((330, 320, 970, 520), 16, CARD)
        elif state == "progress":
            box((330, 174, 970, 520), 16, CARD)
        else:
            box((330, 222, 970, 470), 16, CARD)
            draw.ellipse(
                (332 * drawing_scale, 95 * drawing_scale, 374 * drawing_scale, 137 * drawing_scale),
                fill=ACCENT,
            )
            draw.line(
                [
                    (344 * drawing_scale, 116 * drawing_scale),
                    (351 * drawing_scale, 123 * drawing_scale),
                    (363 * drawing_scale, 109 * drawing_scale),
                ],
                fill=BACKGROUND,
                width=3 * drawing_scale,
            )
        target = destination / f"installer-{state}.bmp"
        image.resize((WIDTH * SCALE, HEIGHT * SCALE), Image.Resampling.LANCZOS).save(target)
        outputs.append(target)
    return outputs
