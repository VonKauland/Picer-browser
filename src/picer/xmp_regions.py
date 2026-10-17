"""Bounded embedded MWG/Microsoft face regions, independent of camera make."""

import math
from xml.etree import ElementTree as ET

LIMIT = 1024 * 1024
MWG = "http://www.metadataworkinggroup.com/schemas/regions/"
AREA = "http://ns.adobe.com/xmp/sType/Area#"
MP = "http://ns.microsoft.com/photo/1.2/t/Region#"


def field(element, namespace, name):
    key = "{" + namespace + "}" + name
    child = element.find(key)
    return element.get(key) or (child.text if child is not None else "") or ""


def xmp_faces(packet):
    if not isinstance(packet, (str, bytes)) or len(packet) > LIMIT:
        return []
    raw = packet.encode("utf-8") if isinstance(packet, str) else packet
    # Do not process entity definitions, DTDs or binary/UTF-16 XML.
    if (
        len(raw) > LIMIT
        or b"\0" in raw
        or b"<!DOCTYPE" in raw.upper()
        or b"<!ENTITY" in raw.upper()
    ):
        return []
    try:
        root = ET.fromstring(raw)
        if sum(1 for _ in root.iter()) > 10000:
            return []
        result = []
        for element in root.iter():
            if len(result) >= 64:
                break
            try:
                if field(element, MWG, "Type").casefold() == "face":
                    area = element.find("{" + MWG + "}Area")
                    if area is None or field(area, AREA, "unit") != "normalized":
                        continue
                    x, y, w, h = (float(field(area, AREA, name)) for name in ("x", "y", "w", "h"))
                    box = (x - w / 2, y - h / 2, w, h)
                else:
                    text = field(element, MP, "Rectangle")
                    if not text:
                        continue
                    parts = text.split(",")
                    if len(parts) != 4:
                        continue
                    box = tuple(float(value) for value in parts)
                x, y, w, h = box
                if (
                    all(math.isfinite(v) for v in box)
                    and 0 <= x < x + w <= 1
                    and 0 <= y < y + h <= 1
                ):
                    if box not in result:
                        result.append(box)
            except (ValueError, TypeError, OverflowError):
                continue
        return result
    except (ET.ParseError, ValueError, TypeError, OverflowError, RecursionError):
        return []
