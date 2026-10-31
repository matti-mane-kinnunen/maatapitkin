#!/usr/bin/env python3
"""Add trains to data/legs.yaml one at a time, checked against Transitous.

Write a leg as   A -> B : train
    python3 add_leg.py "Stockholm -> Malmö : X2 523"
    python3 add_leg.py "Basel -> Bern : ICE 271 @08:30"     # search from about 08:30 (quicker)
    python3 add_leg.py "Copenhagen -> Malmö : *"            # every direct train that day
    python3 add_leg.py "Paris -> London : EST*"             # every direct train whose name starts EST
    python3 add_leg.py "Vienna -> Trieste : * bus"              # '*' skips buses unless you add 'bus'
    python3 add_leg.py "Helsinki -> Tallinn : Megastar 07:30-09:30 ferry"
    python3 add_leg.py "A -> B : name every 60 07:00-21:00 2:17"   # a departure every 60 min 07:00-21:00,
                                                            # 2 h 17 each (your own times, not looked up)
    python3 add_leg.py "A -> B : name every 30 06:00-22:30 0:45 mon-fri"  # only on weekdays
                                                            # your own times, not looked up
    python3 add_leg.py                                      # type legs one per line, empty line to stop
    python3 add_leg.py --file pairs.txt                     # a whole list, no questions, summary at the end
    python3 add_leg.py --file pairs.txt --new               # only the lines not in legs.yaml yet

The tool looks each line up on sample days of one week (Tuesday for Mon-Fri, Saturday,
Sunday; --days tue,fri,sat,sun adds Friday; --date picks the week) and stores which days
each train runs (runs: mon-fri, sat ...). It finds the train in Transitous,
shows what it found and asks before writing. Places it does not know are looked up
and added to data/places.yaml. Run `python3 build.py` afterwards (or use --build).
Trains with many departures (Eurostar, Öresundståg, X2...) are stored as one entry
with a list of times, so you type them once.
"""
from __future__ import annotations

import argparse
import difflib
import datetime as dt
import fnmatch
import json
import re
import subprocess
import time
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))
import transitous as T  # noqa: E402

LEGS = ROOT / "data" / "legs.yaml"
PLACES = ROOT / "data" / "places.yaml"
SECTION = "  # --- Added with add_leg.py ----------------------------------------------"
LINE_RE = re.compile(r"^\s*(?P<a>.+?)\s*->\s*(?P<b>.+?)\s*:\s*(?P<svc>.+?)\s*$")
FLAGS = {"ferry", "bus", "train", "night"}
RUNS_WORD = re.compile(r"(?i)^(daily|(mon|tue|wed|thu|fri|sat|sun)(-(mon|tue|wed|thu|fri|sat|sun))?"
                       r"(,(mon|tue|wed|thu|fri|sat|sun)(-(mon|tue|wed|thu|fri|sat|sun))?)*)$")
EVERY_RE = re.compile(r"(?i)\bevery\s+(\d+)\s+(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})\s+(\d{1,2}:\d{2})\s*$")   # 'bus' also lets '*' include buses


class Quit(Exception):
    pass


LOG: dict = {"status": None, "places": [], "guesses": [], "answers": 0, "elsewhere": Counter()}       # what happened, for the --file summary


def status(text: str) -> bool:
    LOG["status"] = text
    return False


def ask(prompt: str, default: str = "", auto: bool = False) -> str:
    if auto:
        print(f"{prompt}{default}")
        return default
    try:
        ans = input(prompt).strip()
    except EOFError:
        raise Quit
    return ans or default


def yes(prompt: str, auto: bool, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    a = ask(f"{prompt} [{d}] ", "y" if default else "n", auto).lower()
    return a.startswith("y")


def q(s: str) -> str:
    return json.dumps(str(s), ensure_ascii=False)


# --- places -------------------------------------------------------------------
def load_places() -> tuple[dict, dict]:
    d = yaml.safe_load(PLACES.read_text())
    return d["places"], d.get("not_yet_covered") or {}


def find_place(name: str, places: dict) -> str | None:
    """Exact match on the name or one of its aliases, ignoring case and accents."""
    f = T.fold(name)
    for k, v in places.items():
        if T.fold(k) == f or any(T.fold(a) == f for a in (v or {}).get("aliases", []) or []):
            return k
    return None


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, T.fold(a), T.fold(b)).ratio()


def guess_place(name: str, places: dict) -> tuple[str, float] | None:
    """The known place a misspelt name most likely means (Tallin -> Tallinn)."""
    best = None
    for k, v in places.items():
        for cand in [k, *((v or {}).get("aliases", []) or [])]:
            r = similarity(name, cand)
            if T.fold(name)[:1] == T.fold(cand)[:1] and r >= 0.75 and (best is None or r > best[1]):
                best = (k, r)
    return best


def add_place(name: str, lat: float, lon: float, country: str, capital: bool, aliases: list[str] | None = None) -> None:
    text = PLACES.read_text()
    if re.search(rf"(?m)^  {re.escape(name)}:", text.split("not_yet_covered:")[0]):
        return                                   # already there: never write a place twice
    al = [a for a in (aliases or []) if a and T.fold(a) != T.fold(name)]
    line = (f"  {name}: {{lat: {lat:.3f}, lon: {lon:.3f}{', capital: true' if capital else ''}, "
            f"country: {q(country.upper()) if country else q('')}"
            f"{', aliases: [' + ', '.join(q(a) for a in al) + ']' if al else ''}}}  # added by add_leg.py\n")
    # drop it from the "not yet covered" list if it is there
    nyc = re.search(r"(?m)^not_yet_covered:", text)
    if nyc:
        head, tail = text[:nyc.start()], text[nyc.start():]
        tail = re.sub(rf"(?m)^  {re.escape(name)}:[^\n]*\n", "", tail, count=1)
        text = head + tail
    marker = re.search(r"(?m)^(# European capitals with no legs yet|not_yet_covered:)", text)
    if marker:
        text = text[:marker.start()].rstrip("\n") + "\n" + line + "\n" + text[marker.start():]
    else:
        text = text.rstrip("\n") + "\n" + line
    PLACES.write_text(text)


def resolve(name: str, auto: bool) -> tuple[str, dict]:
    name = name.strip()
    if not re.search(r"[^\W\d_]", name) or name[0] in ":->":
        raise ValueError(f"'{name}' is not a city name - write the line as  A -> B : train")
    places, missing = load_places()
    key = find_place(name, places)
    if key:
        return key, places[key]
    if not find_place(name, missing):
        g = guess_place(name, places) or guess_place(name, missing)
        if g:
            known = g[0]
            if auto or yes(f"  '{name}' is not known. Did you mean {known}?", auto):
                if auto:
                    LOG["guesses"].append(f"{name} -> {known}")
                    print(f"  '{name}' taken as {known}")
                if known in places:
                    return known, places[known]
                name = known
    was_missing = find_place(name, missing)
    print(f"  '{name}' is not in places.yaml - looking it up in Transitous...")
    found = [m for m in T.geocode(name) if "lat" in m and "lon" in m]
    # only Europe and around the Mediterranean (Porto must not become Porto Alegre)
    matches = [m for m in found if 27 <= m["lat"] <= 72 and -32 <= m["lon"] <= 45]
    if not matches:
        elsewhere = ", ".join(f"{m.get('name')} ({m['lat']:.1f}, {m['lon']:.1f})" for m in found[:2])
        raise ValueError(f"Transitous does not know '{name}' in Europe"
                         f"{' (only ' + elsewhere + ')' if elsewhere else ''}. Add it to places.yaml by hand.")

    def in_town(m):   # a station in the town of that name beats a street stop called that elsewhere
        return any(T.fold(a.get("name", "")) == T.fold(name) for a in m.get("areas", []) or [])
    matches = sorted(matches, key=lambda m: (not in_town(m), not T.fold(m.get("name", "")).startswith(T.fold(name))))[:5]
    stops = [m for m in matches if m.get("type") == "STOP"] or matches
    if auto:
        # without a person to check, only accept a station whose name looks like what was typed
        ok = [m for m in stops if T.fold(name) in T.fold(m.get("name", "")) or
              similarity(name, str(m.get("name", "")).split()[0]) >= 0.8]
        if not ok:
            raise ValueError(f"unknown place '{name}' - Transitous suggests "
                             f"{', '.join(repr(m.get('name')) for m in stops[:3])}; check the spelling")
        stops = ok
    for i, m in enumerate(stops, 1):
        area = ", ".join(a.get("name", "") for a in m.get("areas", [])[:3] if a.get("name"))
        print(f"    {i}. {m.get('name')}  ({m['lat']:.3f}, {m['lon']:.3f}){'  ' + area if area else ''}")
    pick = ask("  Which one is the station? [1] ", "1", auto)
    m = stops[max(0, min(len(stops) - 1, int(pick) - 1 if pick.isdigit() else 0))]
    stored = was_missing or name.strip()          # keep the name as you wrote it
    station = str(m.get("name", ""))
    aliases = [station] if station and T.fold(station) != T.fold(stored) else []
    places_now, _ = load_places()
    same = find_place(stored, places_now) or (find_place(station, places_now) if station else None)
    if same:                                       # the station is already known under another name
        print(f"  '{name}' is {same}, already in places.yaml")
        return same, places_now[same]
    country = (m.get("country") or "").upper()
    if was_missing:
        country = country or missing[was_missing].get("country", "")
    if not country:
        country = ask("  Country code (e.g. SE, EE) - needed for the time zone: ", "", auto)
    capital = bool(was_missing) or yes(f"  Is {stored} a capital?", auto, default=False)
    add_place(stored, m["lat"], m["lon"], country, capital, aliases)
    print(f"  Added {stored} to places.yaml.")
    LOG["places"].append(f"{stored}: {m.get('name')} ({m['lat']:.3f}, {m['lon']:.3f}), country {country or '?'}"
                         f"{', capital' if capital else ', not marked as capital'}")
    places, _ = load_places()
    return stored, places[stored]


# --- legs.yaml -------------------------------------------------------------------
BLOCK_RE = re.compile(r"(?ms)^  - \{.*?\}[ \t]*(?:#[^\n]*)?$")


def _norm(x) -> str:
    return re.sub(r"\s+", "", str(x or "")).casefold()


def existing_all(frm: str, to: str, service: str, query: str | None = None) -> list:
    """The legs.yaml entries a lookup replaces: same places and the same request (`query`,
    e.g. '*' or 'FR*'), or - for a single train - the same service name. One request can
    have several entries (daily, Mon-Fri, Sat ...). Matching on the request means you can
    rename a '*' entry by hand and a rerun still finds it."""
    text = LEGS.read_text()
    found = []
    for m in BLOCK_RE.finditer(text):
        try:
            d = yaml.safe_load(m.group(0).strip()[2:])
        except yaml.YAMLError:
            continue
        if not isinstance(d, dict) or d.get("from") != frm or d.get("to") != to:
            continue
        if query:
            if _norm(d.get("query")) == _norm(query) or \
               ("*" in query and "times" in d and d.get("source") == "transitous" and not d.get("query")):
                found.append(m)                       # (the second case: '*' entries from before 'query' existed)
        elif _norm(d.get("service")) == _norm(service):
            found.append(m)
    return found


def existing(frm: str, to: str, service: str, query: str | None = None):
    m = existing_all(frm, to, service, query)
    return m[0] if m else None


def entry_text(e: dict) -> str:
    parts = [f"from: {e['from']}", f"to: {e['to']}"]
    if "every" in e:
        parts += [f"service: {q(e['service'])}", f"mode: {e['mode']}"]
        if e.get("night"):
            parts.append("night: true")
        if e.get("runs"):
            parts.append(f"runs: {q(e['runs'])}")
        parts += [f"every: {e['every']}", f'first: "{e["first"]}"', f'last: "{e["last"]}"', f'duration: "{e["duration"]}"']
    elif "times" in e:
        parts.append(f"service: {q(e['service'])}")
        parts.append(f"mode: {e['mode']}")
        if e.get("night"):
            parts.append("night: true")
        if e.get("runs"):
            parts.append(f"runs: {q(e['runs'])}")
        times = [q(t) for t in e["times"]]
        rows = [", ".join(times[i:i + 6]) for i in range(0, len(times), 6)]
        parts.append("times: [" + (",\n      ".join(rows)) + "]")
    else:
        parts += [f'dep: "{e["dep"]}"', f'arr: "{e["arr"]}"', f"service: {q(e['service'])}", f"mode: {e['mode']}"]
        if e.get("night"):
            parts.append("night: true")
        if e.get("runs"):
            parts.append(f"runs: {q(e['runs'])}")
    if e.get("query"):
        parts.append(f"query: {q(e['query'])}")
    parts.append(f"checked: {e['checked']}")
    parts.append(f"source: {e['source']}")
    return "  - {" + ", ".join(parts) + "}"


def write_entries(entries: list[dict], olds: list) -> None:
    """Replace the old entries (if any) with the new ones, at the place of the first old one."""
    text = LEGS.read_text()
    lines = "\n".join(entry_text(e) for e in entries)
    if olds:
        pos = olds[0].start()
        for m in reversed(olds):
            end = m.end() + (1 if text[m.end():m.end() + 1] == "\n" else 0)
            text = text[:m.start()] + text[end:]
        text = text[:pos] + (lines + "\n" if lines else "") + text[pos:]
    else:
        if SECTION not in text:
            text = text.rstrip("\n") + "\n\n" + SECTION + "\n"
        text = text.rstrip("\n") + "\n" + lines + "\n"
    yaml.safe_load(text)                         # never write a broken file
    LEGS.write_text(text)


# --- which days a train runs ------------------------------------------------------
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def sample_dates(seed: dt.date, days: list[str]) -> list[tuple[str, dt.date]]:
    """The sample days in the week (Mon-Sun) that contains `seed`."""
    monday = seed - dt.timedelta(days=seed.weekday())
    return [(d, monday + dt.timedelta(days=WEEKDAYS.index(d))) for d in days]


def runs_spec(found: set[str], sampled: list[str]) -> str | None:
    """Days a train was found on -> legs.yaml 'runs'. Tuesday stands for Mon-Fri
    (Mon-Thu when Friday is sampled too). None = every sampled day = daily."""
    if set(found) >= set(sampled):
        return None
    parts = []
    for d in WEEKDAYS:
        if d in found:
            parts.append(("mon-thu" if "fri" in sampled else "mon-fri") if d == "tue" else d)
    spec = ",".join(parts).replace("mon-thu,fri", "mon-fri").replace("mon-fri,sat,sun", "daily")
    return None if spec == "daily" else spec


def group_by_days(obs: dict[str, set[str]], sampled: list[str]) -> list[tuple[str | None, list[str]]]:
    """{"06:12-06:51": {"tue", "sat"}, ...} -> [(runs, [times]), ...], daily first."""
    groups: dict = {}
    for t, ds in obs.items():
        groups.setdefault(runs_spec(ds, sampled), []).append(t)
    keys = sorted(groups, key=lambda k: (k is not None, k or ""))
    return [(k, sorted(groups[k])) for k in keys]


def runs_text(runs: str | None) -> str:
    return "daily" if not runs else runs.replace("mon-fri", "Mon–Fri").replace("mon-thu", "Mon–Thu") \
        .replace("fri", "Fri").replace("sat", "Sat").replace("sun", "Sun").replace(",", ", ")


# --- looking up trains -----------------------------------------------------------
def mode_of(legs: list[dict]) -> str:
    ms = {l.get("mode") for l in legs}
    if "FERRY" in ms:
        return "ferry"
    if ms <= {"BUS", "COACH"}:
        return "bus"
    return "train"


def is_night(dep: dt.datetime, arr: dt.datetime) -> bool:
    return (arr - dep) >= dt.timedelta(hours=5) and arr.date() > dep.date()


def clock(t: dt.datetime) -> str:
    return f"{t:%H:%M}"


def find_train(pa: dict, pb: dict, service: str, date: dt.date, near: str | None, args):
    tz_a, tz_b = T.tz_of(pa), T.tz_of(pb)
    start = dt.datetime.combine(date, dt.time(0, 0), tz_a)
    if near:
        h, m = map(int, near.split(":"))
        start = dt.datetime.combine(date, dt.time(h, m), tz_a) - dt.timedelta(minutes=60)
    end = dt.datetime.combine(date, dt.time(23, 59), tz_a)
    params = {"fromPlace": f"{pa['lat']},{pa['lon']}", "toPlace": f"{pb['lat']},{pb['lon']}",
              "arriveBy": "false", "numItineraries": 10}
    want = T.numbers(service)
    words = [w for w in re.findall(r"[^\W\d_]{3,}", service)]

    def matches(leg):
        lab = T.label(leg)
        if want:
            return any(T.same_number(w, f) for w in want for f in T.numbers(lab))
        return any(T.fold(w) in T.fold(lab) for w in words)

    def hit(it):
        c = T.core(it.get("legs", []))
        return any(matches(l) for l in c) and T.reaches(c, pa, pb)

    for it in T.day_itineraries(params, start, end, pause=args.pause, stop=hit):
        if hit(it):
            c = T.core(it["legs"])
            first = next(i for i, l in enumerate(c) if matches(l))
            last = max(i for i, l in enumerate(c) if matches(l))
            return c, first, last, tz_a, tz_b
    return None


def find_all(pa: dict, pb: dict, pattern: str, date: dt.date, args, buses: bool = False):
    tz_a, tz_b = T.tz_of(pa), T.tz_of(pb)
    start = dt.datetime.combine(date, dt.time(0, 0), tz_a)
    end = dt.datetime.combine(date, dt.time(23, 59), tz_a)
    params = {"fromPlace": f"{pa['lat']},{pa['lon']}", "toPlace": f"{pb['lat']},{pb['lon']}",
              "arriveBy": "false", "numItineraries": 10}
    pat = T.fold(pattern.strip() or "*")
    found = {}
    for it in T.day_itineraries(params, start, end, pause=args.pause, max_requests=40):
        c = T.core(it.get("legs", []))
        if len(c) != 1:                       # direct trains only
            continue
        if not buses and c[0].get("mode") in ("BUS", "COACH"):
            continue
        LOG["answers"] += 1
        if not T.reaches(c, pa, pb):                  # e.g. AVE to Málaga + bus to Algeciras (D-33)
            d_a = T.stop_km(c[0].get("from"), pa)
            far = c[0].get("from") if d_a is not None and d_a > T.near_km(pa, pb) else c[0].get("to")
            LOG["elsewhere"][(far or {}).get("name", "?")] += 1
            continue
        lab = T.label(c[0])
        if not fnmatch.fnmatch(T.fold(lab), pat):
            continue
        d = T.parse_t(c[0]["startTime"]).astimezone(tz_a)
        a = T.parse_t(c[0]["endTime"]).astimezone(tz_b)
        found.setdefault(clock(d), (d, a, lab, c[0]))
    return [found[k] for k in sorted(found)]


def service_type(label: str) -> str:
    """'X2 523' -> 'X2', 'ICE 27 ICE 1027' -> 'ICE', 'RS4 (87406)' -> 'RS4', 'Øresundståg 1073' -> 'Øresundståg'."""
    keep = []
    for t in label.split():
        if re.fullmatch(r"\(?\d+\)?", t) or t in keep:
            continue
        keep.append(t if len(t) <= 15 else t.split("-")[0])
        if len(keep) == 1 and len(t) > 3:
            break
    return " ".join(keep[:2]) or label


# --- one leg ---------------------------------------------------------------------
def handle(line: str, args) -> bool:
    m = LINE_RE.match(line)
    if not m:
        print("  Write it as:  A -> B : train   (e.g. Stockholm -> Malmö : X2 523)")
        return status("not understood - write it as  A -> B : train")
    svc = m["svc"]
    flags = {w.lower() for w in svc.split() if w.lower() in FLAGS}
    svc = " ".join(w for w in svc.split() if w.lower() not in FLAGS)
    near = None
    nm = re.search(r"@\s*(\d{1,2}:\d{2})", svc)
    if nm:
        near, svc = nm.group(1), (svc[:nm.start()] + svc[nm.end():]).strip()
    words = svc.split()
    runs = None
    if words and RUNS_WORD.match(words[-1]) and (EVERY_RE.search(" ".join(words[:-1])) or
                                                  re.search(r"\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2}$", " ".join(words[:-1]))):
        runs = words[-1].lower()                            # e.g. "mon-fri" after your own times
        runs = None if runs == "daily" else runs
        svc = " ".join(words[:-1])
    every = EVERY_RE.search(svc)
    if every:
        svc = svc[:every.start()].strip()
    manual = None if every else re.search(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})\s*$", svc)
    if manual:
        svc = svc[:manual.start()].strip()

    frm, pa = resolve(m["a"], args.yes)
    to, pb = resolve(m["b"], args.yes)
    today = dt.date.today().isoformat()

    if every:                                              # your own regular departures
        step = int(every.group(1))
        first, last, dur = (f"{int(x.split(':')[0]):02d}:{x.split(':')[1]}" for x in every.groups()[1:])
        mins = lambda x: int(x[:2]) * 60 + int(x[3:])
        if not 5 <= step <= 720:
            print('  ' + "'every' takes minutes between 5 and 720, e.g. every 60"); return status("'every' takes minutes between 5 and 720, e.g. every 60")
        if mins(last) < mins(first):
            print('  ' + "the last departure must be after the first, e.g. 07:00-21:00"); return status("the last departure must be after the first, e.g. 07:00-21:00")
        if mins(dur) == 0:
            print('  ' + "give the journey time as H:MM, e.g. 2:17"); return status("give the journey time as H:MM, e.g. 2:17")
        n = (mins(last) - mins(first)) // step + 1
        e = {"from": frm, "to": to, "service": svc or "?", "every": step, "first": first, "last": last,
             "duration": f"{mins(dur) // 60}:{mins(dur) % 60:02d}", "runs": runs,
             "mode": next((f for f in ("ferry", "bus") if f in flags), "train"),
             "night": "night" in flags, "checked": today, "source": "manual"}
        print(f"  {frm} -> {to}  {e['service']}: {n} departures, every {step} min {first}-{last}, "
              f"{e['duration']} each{' (' + runs_text(runs) + ')' if runs else ''} - not looked up")
        return save_entries([e], args)

    if manual:                                             # the user's own times
        d, a = (f"{int(x.split(':')[0]):02d}:{x.split(':')[1]}" for x in manual.groups())
        dur = (int(a[:2]) * 60 + int(a[3:]) - int(d[:2]) * 60 - int(d[3:])) % 1440
        e = {"from": frm, "to": to, "dep": d, "arr": a, "service": svc or "?",
             "mode": next((f for f in ("ferry", "bus") if f in flags), "train"),
             "night": "night" in flags or (dur >= 300 and a < d), "runs": runs, "checked": today, "source": "manual"}
        print(f"  {frm} -> {to}  {d}-{a}  {e['service']}  ({e['mode']}{', night' if e['night'] else ''}) - not looked up")
        return save_entries([e], args)

    samples = sample_dates(args.date, args.days)
    when = ", ".join(f"{d:%a %-d.%-m.}" for _, d in samples)

    if "*" in svc:                                         # every direct train, on each sample day
        print(f"  Collecting direct trains {frm} -> {to} on {when} ...")
        obs, kinds, legs_seen, nights = {}, Counter(), [], []
        LOG["answers"], LOG["elsewhere"] = 0, Counter()
        for key, day in samples:
            deps = find_all(pa, pb, svc, day, args, buses="bus" in flags)
            print(f"    {day:%a %-d.%-m.}: {len(deps)} direct train{'' if len(deps) == 1 else 's'}")
            for d, a, lab, leg in deps:
                obs.setdefault(f"{clock(d)}-{clock(a)}", set()).add(key)
                kinds[service_type(lab)] += 1
                legs_seen.append(leg); nights.append(is_night(d, a))
        if LOG["elsewhere"]:
            where = ", ".join(f"{n} ({k}×)" for n, k in LOG["elsewhere"].most_common(3))
            print(f"  Not counted - they don't start in {frm} or don't end in {to}: {where}")
        if not obs:
            print("  No direct trains found. Check the names with '*' alone, or give times yourself.")
            olds = existing_all(frm, to, svc, svc)
            if olds and LOG["answers"]:
                # Transitous answered, but no train runs directly: old entries are wrong or gone
                write_entries([], olds)
                print(f"  Removed {len(olds)} old entr{'y' if len(olds) == 1 else 'ies'} for this line from legs.yaml.")
                return status(f"no direct trains - removed {len(olds)} old entr{'y' if len(olds) == 1 else 'ies'}")
            return status("no direct trains found")
        print("  " + ", ".join(f"{k}: {n}" for k, n in kinds.most_common(4)))
        name = kinds.most_common(1)[0][0]
        name = ask(f"  Name for these trains [{name}]: ", name, args.yes)
        entries = [{"from": frm, "to": to, "service": name, "mode": mode_of(legs_seen), "night": all(nights),
                    "times": times, "runs": runs, "query": svc, "checked": today, "source": "transitous"}
                   for runs, times in group_by_days(obs, args.days)]
        for e in entries:
            ts = e["times"]
            print(f"  {runs_text(e['runs'])}: {len(ts)} departure{'' if len(ts) == 1 else 's'}, "
                  + (ts[0] if len(ts) == 1 else f"{ts[0]} … {ts[-1]}"))
        return save_entries(entries, args)

    print(f"  Looking for {svc} {frm} -> {to} on {when} ...")
    obs, info, whole = {}, None, None
    for key, day in samples:
        r = find_train(pa, pb, svc, day, near, args)
        if not r:
            print(f"    {day:%a %-d.%-m.}: not running")
            continue
        c, first, last, tz_a, tz_b = r
        if info is None:                                    # show the first find in full
            for i, l in enumerate(c):
                mark = "*" if first <= i <= last else " "
                print(f"   {mark} {T.parse_t(l['startTime']).astimezone(tz_a):%H:%M}-"
                      f"{T.parse_t(l['endTime']).astimezone(tz_b):%H:%M}  {T.label(l)}"
                      f"  ({l.get('from', {}).get('name', '?')} -> {l.get('to', {}).get('name', '?')})")
            if first > 0 or last < len(c) - 1:
                print(f"  Note: {svc} does not cover the whole way; the lines without * are other trains.")
                whole = yes("  Store the whole chain as one leg?", args.yes, default=True)
        span = c if (whole and (first > 0 or last < len(c) - 1)) else c[first:last + 1]
        d = T.parse_t(span[0]["startTime"]).astimezone(tz_a)
        a = T.parse_t(span[-1]["endTime"]).astimezone(tz_b)
        t = f"{clock(d)}-{clock(a)}"
        obs.setdefault(t, set()).add(key)
        print(f"    {day:%a %-d.%-m.}: {t}")
        if info is None:
            info = {"name": svc if len(span) == last - first + 1 and span[0] is c[first] else " + ".join(T.label(l) for l in span),
                    "mode": mode_of(span), "night": is_night(d, a)}
    if not obs:
        print(f"  {svc} was not found between {frm} and {to} on {when}.")
        print("  Try another week (--date), '*' to list the direct trains, or give the times yourself:")
        print(f"     {frm} -> {to} : {svc} HH:MM-HH:MM")
        return status(f"{svc} not found in the week of {args.date:%-d.%-m.}")
    entries = []
    for runs, times in group_by_days(obs, args.days):
        e = {"from": frm, "to": to, "service": info["name"], "mode": info["mode"], "night": info["night"],
             "runs": runs, "checked": today, "source": "transitous"}
        if len(times) == 1:
            e["dep"], e["arr"] = times[0].split("-")
        else:
            e["times"] = times
        entries.append(e)
    return save_entries(entries, args)


def save_entries(entries: list[dict], args) -> bool:
    e0 = entries[0]
    olds = existing_all(e0["from"], e0["to"], e0["service"], e0.get("query"))
    if olds and e0.get("query"):
        prev = yaml.safe_load(olds[0].group(0).strip()[2:])
        for e in entries:
            e["service"] = str(prev.get("service") or e["service"])   # keep a name you gave it
    for e in entries:
        print("  " + entry_text(e).strip().replace("\n", "\n  "))
    n = sum(len(e["times"]) if "times" in e else 1 for e in entries)
    if "every" in e0:
        what = f"every {e0['every']} min {e0['first']}-{e0['last']}, {e0['duration']}"
    elif len(entries) == 1 and "times" not in e0:
        what = f"{e0['dep']}-{e0['arr']}"
    else:
        what = f"{n} departure{'' if n == 1 else 's'}"
    if "every" in e0:
        what += f" ({runs_text(e0.get('runs'))})" if e0.get("runs") else ""
    elif len(entries) > 1 or e0.get("runs"):
        what += " (" + ", ".join(f"{runs_text(e.get('runs'))} {len(e['times']) if 'times' in e else 1}" for e in entries) + ")"
    what += f"  {e0['service']}" + (" (your own times)" if e0["source"] == "manual" else "")
    if olds:
        print("  Already in legs.yaml:\n  " + "\n  ".join(m.group(0).strip().split("\n")[0][:110] for m in olds))
        if not yes("  Replace?", args.yes):
            return status("kept the existing entry")
    elif not yes("  Add to legs.yaml?", args.yes):
        return status("skipped")
    write_entries(entries, olds)
    print("  Saved.")
    LOG["status"] = ("updated: " if olds else "added: ") + what
    return True


def main():
    ap = argparse.ArgumentParser(prog="add_leg.py", description=__doc__.split("\n\n")[0],
                                 epilog=__doc__.split("\n", 2)[2], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("leg", nargs="*", help='e.g. "Stockholm -> Malmö : X2 523"')
    ap.add_argument("--date", help="a day in the week to look trains up in, YYYY-MM-DD (default: next week)")
    ap.add_argument("--days", default="tue,sat,sun",
                    help="sample days in that week: tue,sat,sun (default) or tue,fri,sat,sun. Tuesday stands for "
                         "Mon-Fri; a train missing on some of them is stored with 'runs' (e.g. mon-fri)")
    ap.add_argument("--file", metavar="PAIRS.TXT",
                    help="read legs from a file, one per line ('#' starts a comment); implies --yes "
                         "and prints a summary at the end")
    ap.add_argument("--new", action="store_true",
                    help="with --file: only look up lines that are not in legs.yaml yet")
    ap.add_argument("--oldest-first", action="store_true",
                    help="with --file: look up first the lines that are new or were checked longest ago")
    ap.add_argument("--budget", type=float, metavar="MINUTES",
                    help="with --file: start no new line after this many minutes; the rest keep their "
                         "earlier data and come first next time with --oldest-first")
    ap.add_argument("--yes", action="store_true", help="don't ask, accept the first answer")
    ap.add_argument("--build", action="store_true", help="run build.py afterwards")
    ap.add_argument("--pause", type=float, default=1.0, help="seconds between Transitous requests")
    argv = [f"--{a}" if re.fullmatch(r"(date|pause|file|days|budget)=.*", a) else a for a in sys.argv[1:]]
    args = ap.parse_args(argv)
    today = dt.date.today()
    args.date = dt.date.fromisoformat(args.date) if args.date else today + dt.timedelta(days=7)
    args.days = [d.strip().lower()[:3] for d in args.days.split(",") if d.strip()]
    if not args.days or "tue" not in args.days or any(d not in ("tue", "fri", "sat", "sun") for d in args.days):
        ap.error("--days takes tue (required) and any of fri, sat, sun - e.g. tue,sat,sun")
    args.days = [d for d in WEEKDAYS if d in args.days]
    past = [d for _, d in sample_dates(args.date, args.days) if d < today]
    if past:
        print(f"Note: {', '.join(f'{d:%a %-d.%-m.}' for d in past)} already passed - Transitous may have no data for "
              f"{'it' if len(past) == 1 else 'them'}. Use --date with a day in a later week.")

    if args.file:
        try:
            raw = Path(args.file).read_text(encoding="utf-8").splitlines()
        except OSError as ex:
            sys.exit(f"Cannot read {args.file}: {ex}")
        lines = [ln.split("#", 1)[0].strip() for ln in raw]
        lines = [ln for ln in lines if ln]
        if not lines:
            sys.exit(f"{args.file} has no legs in it.")
        args.yes = True
        return run_file(lines, args)

    lines = [" ".join(args.leg)] if args.leg else None
    added = 0
    try:
        if lines:
            for ln in lines:
                added += handle(ln, args)
        else:
            print("Type a leg as  A -> B : train   (empty line to finish)")
            while True:
                ln = ask("leg> ")
                if not ln:
                    break
                try:
                    added += handle(ln, args)
                except (ValueError, OSError) as ex:
                    print(f"  {ex}")
    except Quit:
        pass
    except (ValueError, OSError) as ex:
        print(f"  {ex}")
        sys.exit(1)
    if added and (args.build or (not args.leg and not args.yes and yes("Rebuild the map and routes now?", False))):
        subprocess.run([sys.executable, str(ROOT / "build.py")], check=False)
    elif added:
        print("Run  python3 build.py  to rebuild the map and routes.")


def line_entries(line: str, places: dict | None = None) -> list:
    """The legs.yaml entries this pairs.txt line looked up last time (empty if none or places unknown)."""
    m = LINE_RE.match(line)
    if not m:
        return []
    if places is None:
        places, _ = load_places()
    frm, to = find_place(m["a"], places), find_place(m["b"], places)
    if not frm or not to:
        return []
    svc = " ".join(w for w in m["svc"].split() if w.lower() not in FLAGS)
    svc = re.sub(r"@\s*\d{1,2}:\d{2}", "", svc)
    if svc.split() and RUNS_WORD.match(svc.split()[-1]):
        svc = " ".join(svc.split()[:-1])
    svc = EVERY_RE.sub("", svc).strip()
    svc = re.sub(r"\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2}\s*$", "", svc).strip()
    return existing_all(frm, to, svc, svc if "*" in svc else None)


def already_there(line: str) -> bool:
    """Is this line's leg in legs.yaml already? (Only places already known count.)"""
    return bool(line_entries(line))


def last_checked(line: str, places: dict) -> dt.date:
    """When this line was last looked up: the oldest 'checked' of its entries; never = date.min."""
    dates = []
    for m in line_entries(line, places):
        try:
            c = (yaml.safe_load(m.group(0).strip()[2:]) or {}).get("checked")
        except yaml.YAMLError:
            c = None
        if isinstance(c, dt.date):
            dates.append(c)
        elif c:
            try:
                dates.append(dt.date.fromisoformat(str(c)[:10]))
            except ValueError:
                pass
    return min(dates) if dates else dt.date.min


def run_file(lines: list[str], args) -> None:
    print(f"{len(lines)} legs from {args.file}, sample days "
          f"{', '.join(f'{d:%a %-d.%-m.%Y}' for _, d in sample_dates(args.date, args.days))}")
    if args.oldest_first:
        places, _ = load_places()
        when = {ln: last_checked(ln, places) for ln in lines}
        lines = sorted(lines, key=lambda ln: when[ln])        # stable: same age keeps the file order
        never = sum(1 for d in when.values() if d == dt.date.min)
        print(f"Oldest first: {never} new line{'s' if never != 1 else ''}, then by date last checked")
    if args.budget:
        print(f"Time budget {args.budget:g} min: lines not reached keep their earlier data")
    print()
    results, started = [], time.monotonic()
    for n, ln in enumerate(lines, 1):
        if args.budget and (time.monotonic() - started) / 60 > args.budget:
            print(f"Time budget used up after {n - 1} line{'s' if n != 2 else ''}; {len(lines) - n + 1} left for next time.\n")
            results += [(x, None, "not reached (time budget)") for x in lines[n - 1:]]
            break
        print(f"[{n}/{len(lines)}] {ln}")
        LOG["status"] = None
        if args.new and already_there(ln):
            print("  already in legs.yaml - skipped (--new)\n")
            results.append((ln, None, "already there"))
            continue
        try:
            ok = handle(ln, args)
            results.append((ln, ok, LOG["status"] or ("added" if ok else "not added")))
        except Quit:
            break
        except Exception as ex:                         # keep going with the rest of the list
            results.append((ln, False, f"error: {ex}"))
            print(f"  error: {ex}")
        print()

    good = [r for r in results if r[1]]
    bad = [r for r in results if r[1] is False]
    later = [r for r in results if r[2] == "not reached (time budget)"]
    kept = [r for r in results if r[1] is None and r not in later]
    width = max(len(r[0]) for r in results)
    print("=" * 72)
    print(f"Summary: {len(good)} added or updated, {len(bad)} not added, "
          f"{len(kept)} already there, {len(LOG['places'])} new places"
          + (f", {len(later)} left for next time (time budget, {(time.monotonic() - started) / 60:.0f} min used)" if later else ""))
    if good:
        print("\nAdded or updated:")
        for ln, _, st in good:
            print(f"  {ln:<{width}}  {st}")
    if bad:
        print("\nNot added - check by hand or give the times yourself (A -> B : name HH:MM-HH:MM):")
        for ln, _, st in bad:
            print(f"  {ln:<{width}}  {st}")
    if LOG["guesses"]:
        print("\nNames I guessed - fix pairs.txt if any of these is wrong:")
        for g in LOG["guesses"]:
            print(f"  {g}")
    if LOG["places"]:
        print("\nNew places in data/places.yaml - check the station, country and capital flag:")
        for p in LOG["places"]:
            print(f"  {p}")
    if good:
        if args.build:
            print()
            subprocess.run([sys.executable, str(ROOT / "build.py")], check=False)
        else:
            print("\nRun  python3 build.py  to rebuild the map and routes.")


if __name__ == "__main__":
    main()
