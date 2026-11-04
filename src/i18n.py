"""Page texts per language (IDEA-13): data/i18n/<lang>.yaml over English, the user guide in
src/guide/<lang>.html. Used by build.py (day labels, version line) and make_map.py (the page)."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
LOCALES = {"en": "en-GB", "fi": "fi-FI", "sv": "sv-SE", "da": "da-DK", "de": "de-DE"}


def texts(lang: str = "en") -> dict:
    """All texts for `lang`; anything missing comes from English."""
    d = yaml.safe_load((ROOT / "data" / "i18n" / "en.yaml").read_text(encoding="utf-8")) or {}
    f = ROOT / "data" / "i18n" / f"{lang}.yaml"
    if lang != "en" and f.exists():
        d.update({k: v for k, v in (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).items() if v is not None})
    d.setdefault("_locale", LOCALES.get(lang, "en-GB"))
    d["_lang"] = lang
    return d


def t(d: dict, key: str, **kw) -> str:
    """The text for `key` with {name} filled in; {one, other} picked by n (1 = one)."""
    s = d.get(key, key)
    if isinstance(s, dict):
        s = s.get("one") if kw.get("n") == 1 and "one" in s else s.get("other", "")
    return re.sub(r"\{(\w+)\}", lambda m: str(kw[m.group(1)]) if m.group(1) in kw else m.group(0), str(s))


def weekday(d: dict, day: dt.date) -> str:
    return d["weekdays_short"][day.isoweekday() % 7]


def guide(lang: str) -> str:
    f = ROOT / "src" / "guide" / f"{lang}.html"
    return (f if f.exists() else ROOT / "src" / "guide" / "en.html").read_text(encoding="utf-8")
