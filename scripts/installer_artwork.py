"""Small deterministic installer surfaces; native controls render all text."""

from pathlib import Path

from PIL import Image, ImageDraw

WIDTH, HEIGHT, SCALE = 1000, 640, 2
BACKGROUND, CARD, INPUT = "#232323", "#2e2e2e", "#38383b"
ACCENT = "#e2ff45"


def prepare_installer_artwork(icon: Path, destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    brand = Image.open(icon).convert("RGBA")
    outputs = []
    for state in ("setup", "progress", "finished"):
        image = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), BACKGROUND)
        draw = ImageDraw.Draw(image)

        def box(rect, radius, fill, outline=None, draw=draw):
            draw.rounded_rectangle(
                tuple(v * SCALE for v in rect),
                radius=radius * SCALE,
                fill=fill,
                outline=outline,
                width=SCALE,
            )

        box((0, 0, WIDTH - 1, HEIGHT - 1), 20, BACKGROUND, "#616a32")
        draw.line((0, 58 * SCALE, WIDTH * SCALE, 58 * SCALE), fill="#343436", width=SCALE)
        draw.line((292 * SCALE, 88 * SCALE, 292 * SCALE, 614 * SCALE), fill="#343436")
        box((25, 587, 136, 616), 14, "#2c2c2f", "#3a3a3e")
        for x, y, size in ((63, 215, 11), (244, 165, 14), (227, 195, 9), (238, 300, 7)):
            draw.regular_polygon(
                (x * SCALE, y * SCALE, size * SCALE / 2),
                n_sides=4,
                rotation=0,
                fill="#485020",
            )
        for x, y, size in ((23, 13, 32), (68, 192, 140)):
            mark = brand.resize((size * SCALE, size * SCALE), Image.Resampling.LANCZOS)
            image.paste(mark, (x * SCALE, y * SCALE), mark)
        if state == "setup":
            box((330, 174, 970, 304), 16, CARD)
            box((350, 222, 834, 264), 12, INPUT, "#48484c")
            box((330, 320, 970, 520), 16, CARD)
        elif state == "progress":
            box((330, 174, 970, 520), 16, CARD)
        else:
            box((330, 222, 970, 470), 16, CARD)
            draw.ellipse((332 * SCALE, 95 * SCALE, 374 * SCALE, 137 * SCALE), fill=ACCENT)
            draw.line(
                [
                    (344 * SCALE, 116 * SCALE),
                    (351 * SCALE, 123 * SCALE),
                    (363 * SCALE, 109 * SCALE),
                ],
                fill=BACKGROUND,
                width=3 * SCALE,
            )
        target = destination / f"installer-{state}.bmp"
        image.save(target)
        outputs.append(target)
    return outputs
