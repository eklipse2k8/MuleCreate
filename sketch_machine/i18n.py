"""UI language: tr("German text") returns the translation, or the text itself if there is no entry.

The language is fixed at startup (setting "language", View → Language, takes effect after restart); constants
at module level also use tr(). MULE_LANG overrides the setting (tests, recordings). Internal names, file format and
the artist's notes stay untranslated.
"""
import os

from PySide6.QtCore import QSettings

from .i18n_en import EN

LANGUAGES = (("de", "Deutsch"), ("en", "English"))
_DEFAULT = "de"


def _load():
    lang = os.environ.get("MULE_LANG") or str(QSettings("SketchMachine", "SketchMachine").value("language", _DEFAULT))
    return lang if lang in dict(LANGUAGES) else _DEFAULT


LANG = _load()


def saved_language():
    """The language chosen for the next start."""
    lang = str(QSettings("SketchMachine", "SketchMachine").value("language", _DEFAULT))
    return lang if lang in dict(LANGUAGES) else _DEFAULT


def set_language(lang):
    """Remembers the language for the next start."""
    QSettings("SketchMachine", "SketchMachine").setValue("language", lang)


def tr(text):
    return EN.get(text, text) if LANG == "en" else text


def artist_language():
    """Language in which the AI talks to the artist."""
    return "English" if LANG == "en" else "German"
