#!/usr/bin/env python3
"""Short city texts from Wikivoyage (else Wikipedia) for the maps (IDEA-22).

    python3 fetch_wiki.py --only Lisbon          # one or more places, comma-separated
    python3 fetch_wiki.py                        # every place in places.yaml
    python3 fetch_wiki.py --max-age 28           # weekly run: only texts not checked for four weeks

Each place's Wikidata item is `wd:` in data/places.yaml (by hand) or else looked up by name and
checked by distance (data/wiki/wikidata.yaml). For each map language (settings.origins) Wikidata
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
import math
import unicodedata
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
MIN_CHARS = 220            # a long next sentence may take it past MAX_CHARS (up to HARD_MAX) while shorter
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
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)                 # space before punctuation (removed brackets, footnotes)
    t = re.sub(r"[,;:]+([.!?])", r"\1", t)                  # "Riviera,." -> "Riviera." (da Lisbon, 13.11.2026)
    if len(t) <= MAX_CHARS:
        return t
    parts, out = re.split(r"(?<=[.!?])\s+(?=[A-ZÄÖÅÜÉÈÀÂÎÔÇØÆ0-9«\"„“])", t), ""
    for p in parts:
        n = len(out) + 1 + len(p)
        if out and n > MAX_CHARS and (len(out) >= MIN_CHARS or n > HARD_MAX):
            break
        out = f"{out} {p}".strip()
    return out if len(out) <= HARD_MAX else out[:HARD_MAX].rsplit(" ", 1)[0] + " …"


# A short Wikivoyage intro is often a one-line teaser; the description follows in the background
# section. Its name differs per language; a heading matches if it starts with one of these (Swedish:
# "Fakta om Lissabon"). Checked on Lisbon 13.11.2026: en, fr, it, fi, sv; de and da have their own way
# (German intros are long; Danish has no Wikivoyage).
BACKGROUND = {"en": ["Understand"], "de": ["Hintergrund", "Verstehen"], "fr": ["Comprendre"],
              "sv": ["Fakta om", "Förstå", "Bakgrund"], "fi": ["Ymmärrä", "Tausta"], "it": ["Da sapere", "Conoscere"],
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
        if any(head.casefold().startswith(n) for n in names):
            # it may open straight with a sub-heading: take the first text inside it - never the
            # next section's (13.11.2026: Finnish 'Ymmärrä' was empty and 'Saapuminen' got taken)
            texts = [body.strip()]
            for lv, _, b in sections[i + 1:]:
                if lv <= level:
                    break
                texts.append(b.strip())
            # the whole section, sub-sections included; clean() cuts it at a sentence end near
            # MAX_CHARS (13.11.2026: English 'Understand' opens with one short paragraph)
            body = "\n\n".join(t for t in texts if t)
            if body:
                return f"{intro}\n\n{body}".strip(), head, []
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


MAX_KM = 25                # a Wikidata item found by name must lie this close to our coordinates
RETRY_DAYS = 28            # places with no item / texts are looked at again after this many days


def km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = math.radians
    a = math.sin(r(lat2 - lat1) / 2) ** 2 + math.cos(r(lat1)) * math.cos(r(lat2)) * math.sin(r(lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def coords(entity: dict) -> tuple[float, float] | None:
    for c in (entity.get("claims") or {}).get("P625") or []:
        v = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {}
        if "latitude" in v:
            return v["latitude"], v["longitude"]
    return None


# Items that are not the town itself: a station, a province around it, a district inside it.
# The first full run (13.11.2026) took Frankfurt Hbf, Kraków County, the Canton of Geneva, Stuttgart-Süd ...
NOT_THE_TOWN = re.compile(r"^(main |central )?(railway |train )?station|^(former )?(province|county|canton|powiat|district|"
                          r"borough|quarter|human settlement|metropolitan)|^urban district", re.I)
NOT_THE_TOWN_LABEL = re.compile(r"\b(province|county|canton|station|hauptbahnhof|hbf)\b|^province of|-süd$|-nord$", re.I)


def fold(x: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(x)) if unicodedata.category(c) != "Mn").casefold().strip()


def pick(place: dict, entities: dict, names: tuple = ()) -> dict | None:
    """The item for the town: within MAX_KM, and in this order - not a station / province / district,
    named exactly like the place (or an alias), with a Wikivoyage article, nearest. (Distance alone took
    stations and provinces; Wikivoyage settles Monaco city vs country, San Marino; distance Brest FR/BY.)"""
    wanted = {fold(n) for n in names}
    best = None
    for qid, ent in entities.items():
        c = coords(ent)
        if not c:
            continue
        d = km(place["lat"], place["lon"], *c)
        if d > MAX_KM:
            continue
        label = ((ent.get("labels") or {}).get("en") or {}).get("value", "")
        desc = ((ent.get("descriptions") or {}).get("en") or {}).get("value", "")
        other = bool(NOT_THE_TOWN.search(desc) or NOT_THE_TOWN_LABEL.search(label))
        exact = fold(label) in wanted
        voy = any(k.endswith("wikivoyage") for k in (ent.get("sitelinks") or {}))
        key = (other, not exact, not voy, d)
        if best is None or key < best[0]:
            best = (key, {"wd": qid, "label": label, "description": desc, "km": round(d, 1)})
    return best[1] if best else None


def find_item(name: str, place: dict, pause: float) -> dict | None:
    """Search Wikidata by the place's name (then its aliases) and pick an item near our coordinates."""
    for term in [name, *(place.get("aliases") or [])[:2]]:
        q = urllib.parse.urlencode({"action": "wbsearchentities", "search": term, "language": "en", "uselang": "en",
                                    "type": "item", "limit": 10, "format": "json"})
        ids = [x["id"] for x in get_json(f"https://www.wikidata.org/w/api.php?{q}").get("search") or []]
        time.sleep(pause)
        if not ids:
            continue
        q = urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(ids), "format": "json",
                                    "props": "claims|sitelinks|labels|descriptions", "languages": "en"})
        found = pick(place, get_json(f"https://www.wikidata.org/w/api.php?{q}").get("entities") or {},
                     (name, *(place.get("aliases") or [])))
        time.sleep(pause)
        if found:
            return found
    return None


def days_since(d) -> int:
    try:
        return (dt.date.today() - dt.date.fromisoformat(str(d))).days
    except ValueError:
        return 10 ** 6


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="", help="comma-separated place names (English keys in places.yaml); "
                                               "these are fetched whatever their age")
    ap.add_argument("--max-age", type=int, default=0,
                    help="skip texts checked fewer than this many days ago (weekly run: 28, so a quarter a week)")
    ap.add_argument("--pause", type=float, default=0.5, help="seconds between requests (be gentle)")
    ap.add_argument("--max-errors", type=int, default=20, help="stop after this many failed requests")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "data/places.yaml").read_text())
    places = cfg["places"]
    langs = sorted({(o or {}).get("lang", "en") for o in cfg["settings"]["origins"].values()})
    only = [x.strip() for x in args.only.split(",") if x.strip()]
    unknown = [x for x in only if x not in places]
    if unknown:
        print(f"not in places.yaml: {', '.join(unknown)}", file=sys.stderr)
        return 2
    names = sorted(only or places)
    today = dt.date.today().isoformat()
    out_dir = ROOT / "data/wiki"
    out_dir.mkdir(exist_ok=True)
    errors = 0

    # 1. Wikidata items: wd: in places.yaml (by hand) wins; else data/wiki/wikidata.yaml (found here, by name
    #    and distance - check its label/description/km when it changes)
    idf = out_dir / "wikidata.yaml"
    ids = (yaml.safe_load(idf.read_text()) or {}) if idf.exists() else {}
    for name in names:
        if places[name].get("wd"):
            continue
        old = ids.get(name) or {}
        if old.get("wd") or (old and days_since(old.get("checked")) < RETRY_DAYS and name not in only):
            continue
        try:
            found = find_item(name, places[name], args.pause)
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            errors += 1
            print(f"  wikidata {name}: {e}")
            if errors >= args.max_errors:
                break
            continue
        ids[name] = {**found, "checked": today} if found else {"wd": None, "checked": today}
        print(f"wikidata {name}: " + (f"{found['wd']} {found['label']!r} ({found['description']}), {found['km']} km"
                                      if found else f"nothing within {MAX_KM} km"))
    idf.write_text("# Wikidata items for places.yaml, found by fetch_wiki.py by name and distance (IDEA-22).\n"
                   "# A wrong one: put the right wd: on the place in places.yaml - that always wins.\n"
                   + yaml.safe_dump(dict(sorted(ids.items())), allow_unicode=True, sort_keys=True, width=110))
    qid_of = {n: places[n].get("wd") or (ids.get(n) or {}).get("wd") for n in names}
    qid_of = {n: q for n, q in qid_of.items() if q}

    # 2. texts per language
    try:
        links = sitelinks(sorted(set(qid_of.values()))) if qid_of else {}
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        print(f"  wikidata sitelinks: {e} - texts left as they were")
        return 0
    for lang in langs:
        f = out_dir / f"{lang}.yaml"
        texts = (yaml.safe_load(f.read_text()) or {}) if f.exists() else {}
        for name, qid in sorted(qid_of.items()):
            old = texts.get(name) or {}
            if name not in only and args.max_age and days_since(old.get("checked", old.get("fetched"))) < args.max_age:
                continue
            if errors >= args.max_errors:
                break
            entry = None
            try:
                for site, key in (("wikivoyage", f"{lang}wikivoyage"), ("wikipedia", f"{lang}wiki")):
                    title = links.get(qid, {}).get(key)
                    if not title:
                        continue
                    e = from_page(page_text(lang, site, title), site, lang, today)
                    time.sleep(args.pause)
                    if e and entry and len(e["text"]) > len(entry["text"]):
                        print(f"  {lang} {name}: {entry['source']} gave only {len(entry['text'])} chars"
                              + (f" (with section {entry['section']!r})" if entry.get("section") else "")
                              + f" - {e['source']} is longer and is used")
                    if e and (not entry or len(e["text"]) > len(entry["text"])):
                        entry = e
                    if entry and len(entry["text"]) >= TOO_SHORT:
                        break
            except (urllib.error.URLError, TimeoutError, ValueError) as e:
                errors += 1
                print(f"  {lang} {name}: {e} - kept as it was")
                continue
            if entry:
                if old.get("revid") == entry["revid"] and old.get("text") == entry["text"]:
                    entry["fetched"] = old.get("fetched", today)     # unchanged: only 'checked' moves
                entry["checked"] = today
                texts[name] = entry
                print(f"{lang} {name}: {entry['source']} {entry['title']!r} rev {entry['revid']}, {len(entry['text'])} chars"
                      + (f", + section {entry['section']!r}" if entry.get("section") else ""))
            else:
                if old:
                    old["checked"] = today                         # the article went away: keep the old text
                print(f"{lang} {name}: no article")
        head = (f"# City texts in '{lang}' for the maps (IDEA-22), written by fetch_wiki.py - do not edit by hand,\n"
                "# use overrides.yaml. Texts: Wikivoyage / Wikipedia contributors, CC BY-SA 4.0 (see each url).\n")
        f.write_text(head + yaml.safe_dump(dict(sorted(texts.items())), allow_unicode=True, sort_keys=True, width=110))
    if errors:
        print(f"{errors} request(s) failed - those places keep their old data")
    return 0


if __name__ == "__main__":
    sys.exit(main())
