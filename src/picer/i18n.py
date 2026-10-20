"""Offline UI catalogs. IDs, file content and user text are never translated implicitly."""

import json
from pathlib import Path

LANGUAGES = {
    "zh_CN": "简体中文",
    "zh_TW": "繁體中文",
    "en": "English",
    "ru": "Русский",
    "ja": "日本語",
    "ko": "한국어",
    "es": "Español",
}
_language = "zh_CN"
_catalog = {}
_qt_translator = None


def set_language(language):
    global _language, _catalog, _qt_translator
    language = language if isinstance(language, str) and language in LANGUAGES else "zh_CN"
    catalog = {}
    if language != "zh_CN":
        try:
            catalog = json.loads(
                (Path(__file__).parent / "locales" / f"{language}.json").read_text(encoding="utf-8")
            )
            if not isinstance(catalog, dict):
                catalog = {}
        except (OSError, ValueError, UnicodeError):
            catalog = {}
    _language, _catalog = language, catalog
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app:
        if _qt_translator:
            app.removeTranslator(_qt_translator)
            _qt_translator.deleteLater()
        translator = QTranslator(app)
        if translator.load(
            "qtbase_" + language, QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        ):
            app.installTranslator(translator)
        _qt_translator = translator
        QLocale.setDefault(QLocale(language))


def language():
    return _language


def tr(message):
    """Translate only an explicit UI message/template; format user values afterwards."""
    return _catalog.get(message, message)


def source_text(message):
    """Recover a UI label for legacy comparisons and icon selection, never for IDs."""
    return next((key for key, value in _catalog.items() if value == message), message)


def load_language(config):
    try:
        preferences = json.loads((Path(config) / "plugins.json").read_text(encoding="utf-8"))
        selected = preferences.get("ui", {}).get("application", {}).get("language", "zh_CN")
    except (OSError, ValueError, TypeError, AttributeError):
        selected = "zh_CN"
    set_language(selected)


def plugin_text(manager, plugin_id, message):
    """Localize shipped metadata only; keep external author-supplied names intact."""
    record = manager.records.get(plugin_id)
    shipped = manager.preferences.get("ui", {}).get("bundled_examples", {})
    return tr(message) if record and (record.directory is None or plugin_id in shipped) else message
