#!/usr/bin/env python3
"""Short city texts from Wikivoyage (else Wikipedia) for the maps (IDEA-22).

    python3 fetch_wiki.py --only Lisbon          # one or more places, comma-separated
    python3 fetch_wiki.py                        # every place in places.yaml with a wd: (Wikidata) id

For each place with `wd:` in data/places.yaml and each map language (settings.origins), Wikidata
gives the article title in that language; the intro comes from that language's Wikivoyage, or
Wikipedia when Wikivoyage has no article. The result goes to data/wiki/<lang>.yaml with its
source, link and revision (CC BY-SA needs the credit; the revision pins what we used).

Runs where the wikis can be reached (GitHub Actions: .github/workflows/fetch-wiki.yml) - the
build only reads the files, it never goes online. The texts are untrusted third-party data:
the page shows them as plain text, and nothing here passes them to a shell (D-47).
Corrections by hand: data/wiki/overrides.yaml (read by build.py, never overwritten).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
UA = "maatapitkin/0.3 (https://github.com/matti-mane-kinnunen/maatapitkin; city texts, a few requests a week)"
MAX_CHARS = 420            # about two or three sentences
HARD_MAX = 600


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def sitelinks(qids: list[str]) -> dict:
    """{qid: {site: title}} from Wikidata, 50 ids per request."""
    out = {}
    for i in range(0, len(qids), 50):
        q = urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(qids[i:i + 50]),
                                    "props": "sitelinks", "format": "json"})
        data = get_json(f"https://www.wikidata.org/w/api.php?{q}")
        for qid, ent in (data.get("entities") or {}).items():
            out[qid] = {k: v.get("title") for k, v in (ent.get("sitelinks") or {}).items()}
    return out


def clean(text: str) -> str:
    """Plain text, one paragraph, no control characters, cut at a sentence end near MAX_CHARS."""
    t = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(text or ""))
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s*\([^()]*\)", "", t) if len(t) > MAX_CHARS else t     # drop pronunciations etc. when long
    if len(t) <= MAX_CHARS:
        return t
    parts, out = re.split(r"(?<=[.!?])\s+(?=[A-ZÄÖÅÜÉÈÀÂÎÔÇØÆ0-9«\"„“])", t), ""
    for p in parts:
        if out and len(out) + 1 + len(p) > MAX_CHARS:
            break
        out = f"{out} {p}".strip()
    return out if len(out) <= HARD_MAX else out[:HARD_MAX].rsplit(" ", 1)[0] + " …"


def from_summary(data: dict, site: str, lang: str, today: str) -> dict | None:
    """One entry from a REST page summary, or None if it is not a usable article."""
    if not data or data.get("type") not in (None, "standard") or not data.get("extract"):
        return None
    text = clean(data["extract"])
    if len(text) < 40:
        return None
    url = ((data.get("content_urls") or {}).get("desktop") or {}).get("page") \
        or f"https://{lang}.{site}.org/wiki/{urllib.parse.quote(str(data.get('title', '')).replace(' ', '_'))}"
    return {"text": text, "source": site, "title": data.get("title"), "url": url,
            "revid": int(data["revision"]) if str(data.get("revision", "")).isdigit() else data.get("revision"),
            "fetched": today}


def summary(lang: str, site: str, title: str) -> dict | None:
    url = f"https://{lang}.{site}.org/api/rest_v1/page/summary/{urllib.parse.quote(title.replace(' ', '_'), safe='')}"
    try:
        return get_json(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="", help="comma-separated place names (English keys in places.yaml)")
    ap.add_argument("--pause", type=float, default=0.5, help="seconds between requests (be gentle)")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "data/places.yaml").read_text())
    places = cfg["places"]
    langs = sorted({(o or {}).get("lang", "en") for o in cfg["settings"]["origins"].values()})
    only = [x.strip() for x in args.only.split(",") if x.strip()]
    unknown = [x for x in only if x not in places]
    if unknown:
        print(f"not in places.yaml: {', '.join(unknown)}", file=sys.stderr)
        return 2
    wanted = {n: p["wd"] for n, p in places.items() if p.get("wd") and (not only or n in only)}
    missing_wd = [x for x in only if not places[x].get("wd")]
    if missing_wd:
        print(f"no wd: (Wikidata id) in places.yaml: {', '.join(missing_wd)}", file=sys.stderr)
    if not wanted:
        print("nothing to fetch")
        return 0
    links = sitelinks(sorted(set(wanted.values())))
    today = dt.date.today().isoformat()
    out_dir = ROOT / "data/wiki"
    out_dir.mkdir(exist_ok=True)
    for lang in langs:
        f = out_dir / f"{lang}.yaml"
        texts = (yaml.safe_load(f.read_text()) or {}) if f.exists() else {}
        for name, qid in sorted(wanted.items()):
            entry = None
            for site, key in (("wikivoyage", f"{lang}wikivoyage"), ("wikipedia", f"{lang}wiki")):
                title = links.get(qid, {}).get(key)
                if not title:
                    continue
                entry = from_summary(summary(lang, site, title), site, lang, today)
                time.sleep(args.pause)
                if entry:
                    break
            if entry:
                old = texts.get(name) or {}
                if old.get("revid") == entry["revid"] and old.get("text") == entry["text"]:
                    entry["fetched"] = old.get("fetched", today)     # unchanged: keep the file quiet
                texts[name] = entry
                print(f"{lang} {name}: {entry['source']} {entry['title']!r} rev {entry['revid']}, {len(entry['text'])} chars")
            else:
                print(f"{lang} {name}: no article")
        head = (f"# City texts in '{lang}' for the maps (IDEA-22), written by fetch_wiki.py - do not edit by hand,\n"
                "# use overrides.yaml. Texts: Wikivoyage / Wikipedia contributors, CC BY-SA 4.0 (see each url).\n")
        f.write_text(head + yaml.safe_dump(dict(sorted(texts.items())), allow_unicode=True, sort_keys=True, width=110))
    return 0


if __name__ == "__main__":
    sys.exit(main())
