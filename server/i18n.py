"""The server's words in the panel's language: the notices, the cards' words, the settings' names and help, the reasons
a code check gives, which the panel shows as they come.

The code is written in English; each other language is a table from the English to its own words
(server/locale/<lang>.json). The language is the panel's: a panel says which one its browser asks for when it connects
(English unless the browser lists Korean first), and the last panel to connect sets it for all. SIDENOTE_LANG=en or
ko fixes it instead.

    t("Pause")                          the word itself, or its translation
    t("{n} answers", n=3)               placeholders by name
    a Korean entry may write "{name|이/가}": the word, then 이 after a final consonant or 가 after a vowel

To add a language: copy server/locale/ko.json to <code>.json, translate the values, and add the code to SUPPORTED.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

SUPPORTED = ("en", "ko")
_DIR = Path(__file__).resolve().parent / "locale"
_CATALOGS: dict[str, dict[str, str]] = {}
_PLACE = re.compile(r"\{(\w+)(?:\|([^}]+))?\}")

_fixed = os.environ.get("SIDENOTE_LANG", "").strip().lower()
LANG = _fixed if _fixed in SUPPORTED else "en"


def set_lang(lang: str | None) -> bool:
    """The panel's language, unless SIDENOTE_LANG fixes one. True when it changed (the panel's words are sent again)."""
    global LANG
    if _fixed in SUPPORTED:
        return False
    lang = (lang or "").lower()[:2]
    new = lang if lang in SUPPORTED else "en"
    changed, LANG = new != LANG, new
    return changed


def cli_lang() -> str:
    """The language of a command run in a terminal (./sidenote report, gpu): SIDENOTE_LANG when it names one, else
    Korean when the locale is Korean (the first of LC_ALL, LC_MESSAGES and LANG that is set, as the C library reads
    them), else English."""
    if _fixed in SUPPORTED:
        return _fixed
    locale = next((v for v in (os.environ.get(k, "").strip() for k in ("LC_ALL", "LC_MESSAGES", "LANG")) if v), "")
    return "ko" if locale.lower().startswith("ko") else "en"


def _catalog(lang: str) -> dict[str, str]:
    if lang not in _CATALOGS:
        try:
            _CATALOGS[lang] = json.loads((_DIR / f"{lang}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _CATALOGS[lang] = {}
    return _CATALOGS[lang]


def particle(word: str, pair: str) -> str:
    """The Korean particle after a word: the first of the pair after a final consonant (and after anything not Hangul),
    the second after a vowel. A bracketed aside at the end is passed over."""
    first, second = pair.split("/", 1)
    last = re.sub(r"\s*\([^()]*\)\s*$", "", str(word or "")).strip()[-1:]
    if not last or not ("가" <= last <= "힣"):
        return first
    return first if (ord(last) - 0xAC00) % 28 else second


def t(text: str, **values) -> str:
    """`text` in the current language, its {placeholders} filled from `values`."""
    out = text if LANG == "en" else _catalog(LANG).get(text) or text
    if values:
        def fill(m: re.Match) -> str:
            key, pair = m.group(1), m.group(2)
            if key not in values:
                return m.group(0)
            value = str(values[key])
            return value + particle(value, pair) if pair else value
        out = _PLACE.sub(fill, out)
    return out
