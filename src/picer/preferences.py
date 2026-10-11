"""Validated application preferences; component settings remain separate."""

DEFAULTS = {
    "start": "empty",
    "remember_window": True,
    "tooltips": True,
    "focus_image": True,
    "default_scale": "fit",
    "auto_orient": True,
    "browse_folder": True,
    "wrap": True,
    "zoom_step": 25,
    "key_repeat_ms": 120,
    "key_repeat_delay_ms": 1000,
    "double_click": "toggle",
    "glass": True,
    "glass_strength": 70,
    "density": "standard",
    "accent_color": "",
    "cache_mb": 512,
}
CHOICES = {
    "start": {"empty", "last"},
    "default_scale": {"fit", "actual"},
    "double_click": {"toggle", "fit", "actual"},
    "density": {"standard", "compact"},
}
RANGES = {
    "key_repeat_ms": (30, 2000),
    "key_repeat_delay_ms": (0, 5000),
    "zoom_step": (5, 100),
    "glass_strength": (0, 100),
    "cache_mb": (16, 16384),
}


def read_preferences(manager):
    stored = manager.preferences["ui"].get("application", {})
    stored = stored if isinstance(stored, dict) else {}
    result = dict(DEFAULTS)
    from picer.color_editor import valid_accent

    for key, default in DEFAULTS.items():
        value = stored.get(key, default)
        if key == "accent_color":
            result[key] = value.upper() if valid_accent(value) else default
        elif type(default) is bool:
            result[key] = value if type(value) is bool else default
        elif key in CHOICES:
            result[key] = value if isinstance(value, str) and value in CHOICES[key] else default
        elif type(value) is int:
            low, high = RANGES[key]
            result[key] = max(low, min(high, value))
    return result
