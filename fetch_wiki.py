#!/usr/bin/env python3
"""Short city texts from Wikivoyage (else Wikipedia) for the maps (IDEA-22).

    python3 fetch_wiki.py --only Lisbon          # one or more places, comma-separated
    python3 fetch_wiki.py                        # every place in places.yaml with a wd: (Wikidata) id

For each place with `wd:` in data/places.yaml and each map language (settings.origins), Wikidata
gives the article title in that language; the intro section comes from that language's Wikivoyage, or
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


# A short Wikivoyage intro is often a one-line teaser; the description follows in the background
# section. Its name differs per language - these are tried in order (13.11.2026: unverified guesses
# for some languages; the log says which matched).
BACKGROUND = {"en": ["Understand"], "de": ["Hintergrund", "Verstehen"], "fr": ["Comprendre"],
              "sv": ["Förstå", "Bakgrund"], "fi": ["Ymmärrä", "Tausta"], "it": ["Da sapere", "Conoscere"],
              "da": ["Forstå", "Baggrund"]}
SHORT_INTRO = 250          # below this, add the background section
TOO_SHORT = 200            # below this after all, try Wikipedia instead (main())
HEADING = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$", re.M)


def split_sections(extract: str) -> tuple[str, list[tuple[int, str, str]]]:
    """Plain-text extract with '== Heading ==' lines -> (intro, [(level, heading, text up to the next heading)])."""
    parts = HEADING.split(extract or "")
    intro, out = parts[0], []
    for i in range(1, len(parts) - 2, 3):
        out.append((len(parts[i]), parts[i + 1], parts[i + 2]))
    return intro.strip(), out


def compose(extract: str, lang: str) -> tuple[str, str, list[str]]:
    """(text, section used or '', headings when none matched) - the intro, plus the background
    section's opening if the intro is short."""
    intro, sections = split_sections(extract)
    if len(intro) >= SHORT_INTRO:
        return intro, "", []
    names = [n.casefold() for n in BACKGROUND.get(lang, [])]
    for i, (level, head, body) in enumerate(sections):
        if head.casefold() in names:
            # it may open straight with a sub-heading: take the first text inside it - never the
            # next section's (13.11.2026: Finnish 'Ymmärrä' was empty and 'Saapuminen' got taken)
            texts = [body.strip()]
            for lv, _, b in sections[i + 1:]:
                if lv <= level:
                    break
                texts.append(b.strip())
            first = next((t for t in texts if t), "")
            if first:
                return f"{intro}\n\n{first}".strip(), head, []
    return intro, "", [h for lv, h, _ in sections if lv == 2][:12]


def from_page(page: dict, site: str, lang: str, today: str) -> dict | None:
    """One entry from the query API's page (plain text with headings), or None if it is missing,
    a disambiguation page or a stub. clean() joins the paragraphs and cuts the length."""
    if not page or page.get("missing") or "disambiguation" in (page.get("pageprops") or {}):
        return None
    raw, section, heads = compose(page.get("extract", ""), lang) if site == "wikivoyage" \
        else (split_sections(page.get("extract", ""))[0], "", [])
    if heads:
        print(f"  {lang}.{site} {page.get('title', '')!r}: short intro, no background section among {heads}")
    text = clean(raw)
    if len(text) < 40:
        return None
    title = page.get("title", "")
    revs = page.get("revisions") or [{}]
    e = {"text": text, "source": site, "title": title,
         "url": f"https://{lang}.{site}.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
         "revid": revs[0].get("revid"), "fetched": today}
    if section:
        e["section"] = section
    return e


def page_text(lang: str, site: str, title: str) -> dict | None:
    """The article as plain text with '== Heading ==' lines, plus its revision id (TextExtracts).
    13.11.2026: the REST summary, then the intro alone, were too short on most Wikivoyages."""
    q = urllib.parse.urlencode({"action": "query", "format": "json", "formatversion": 2, "redirects": 1,
                                "prop": "extracts|revisions|pageprops", "explaintext": 1, "exsectionformat": "wiki",
                                "rvprop": "ids", "ppprop": "disambiguation", "titles": title})
    pages = (get_json(f"https://{lang}.{site}.org/w/api.php?{q}").get("query") or {}).get("pages") or []
    return pages[0] if pages else None


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
                e = from_page(page_text(lang, site, title), site, lang, today)
                time.sleep(args.pause)
                if e and (not entry or len(e["text"]) > len(entry["text"])):
                    entry = e
                if entry and len(entry["text"]) >= TOO_SHORT:
                    break
            if entry:
                old = texts.get(name) or {}
                if old.get("revid") == entry["revid"] and old.get("text") == entry["text"]:
                    entry["fetched"] = old.get("fetched", today)     # unchanged: keep the file quiet
                texts[name] = entry
                print(f"{lang} {name}: {entry['source']} {entry['title']!r} rev {entry['revid']}, {len(entry['text'])} chars"
                      + (f", + section {entry['section']!r}" if entry.get("section") else ""))
            else:
                print(f"{lang} {name}: no article")
        head = (f"# City texts in '{lang}' for the maps (IDEA-22), written by fetch_wiki.py - do not edit by hand,\n"
                "# use overrides.yaml. Texts: Wikivoyage / Wikipedia contributors, CC BY-SA 4.0 (see each url).\n")
        f.write_text(head + yaml.safe_dump(dict(sorted(texts.items())), allow_unicode=True, sort_keys=True, width=110))
    return 0


if __name__ == "__main__":
    sys.exit(main())
