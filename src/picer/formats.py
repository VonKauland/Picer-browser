"""Selectable decoder capabilities, shared by every opening/navigation path."""

import re

from picer.imaging import supported_suffixes


def valid_formats(value):
    return value is None or (
        isinstance(value, list)
        and len(value) <= 128
        and all(isinstance(s, str) and re.fullmatch(r"\.[a-z0-9]{1,12}", s) for s in value)
        and len(set(value)) == len(value)
    )


def enabled_formats(preferences):
    available = supported_suffixes()
    selected = preferences.get("readable_formats")
    return available if selected is None else available.intersection(selected)
