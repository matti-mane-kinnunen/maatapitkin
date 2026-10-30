#!/usr/bin/env python3
"""Add trains to data/legs.yaml one at a time, checked against Transitous.

Write a leg as   A -> B : train
    python3 add_leg.py "Stockholm -> Malmö : X2 523"
    python3 add_leg.py "Basel -> Bern : ICE 271 @08:30"     # search from about 08:30 (quicker)
    python3 add_leg.py "Copenhagen -> Malmö : *"            # every direct train that day
    python3 add_leg.py "Paris -> London : EST*"             # every direct train whose name starts EST
    python3 add_leg.py "Helsinki -> Tallinn : Megastar 07:30-09:30 ferry"
                                                            # your own times, not looked up
    python3 add_leg.py                                      # type legs one per line, empty line to stop
    python3 add_leg.py --file pairs.txt                     # a whole list, no questions, summary at the end

The tool finds the train in Transitous on the travel date (default next Tuesday),
shows what it found and asks before writing. Places it does not know are looked up
and added to data/places.yaml. Run `python3 build.py` afterwards (or use --build).
Trains with many departures (Eurostar, Öresundståg, X2...) are stored as one entry
with a list of times, so you type them once.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import re
import subprocess
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


class Quit(Exception):
    pass


LOG: dict = {"status": None, "places": []}       # what happened, for the --file summary


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
    f = T.fold(name)
    for k in places:
        if T.fold(k) == f:
            return k
    return None


def add_place(name: str, lat: float, lon: float, country: str, capital: bool) -> None:
    text = PLACES.read_text()
    line = (f"  {name}: {{lat: {lat:.3f}, lon: {lon:.3f}{', capital: true' if capital else ''}, "
            f"country: {q(country.upper()) if country else q('')}}}  # added by add_leg.py\n")
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
    places, missing = load_places()
    key = find_place(name, places)
    if key:
        return key, places[key]
    was_missing = find_place(name, missing)
    print(f"  '{name}' is not in places.yaml - looking it up in Transitous...")
    matches = [m for m in T.geocode(name) if "lat" in m and "lon" in m][:5]
    if not matches:
        raise ValueError(f"Transitous does not know '{name}'. Add it to places.yaml by hand.")
    stops = [m for m in matches if m.get("type") == "STOP"] or matches
    for i, m in enumerate(stops, 1):
        area = ", ".join(a.get("name", "") for a in m.get("areas", [])[:3] if a.get("name"))
        print(f"    {i}. {m.get('name')}  ({m['lat']:.3f}, {m['lon']:.3f}){'  ' + area if area else ''}")
    pick = ask("  Which one is the station? [1] ", "1", auto)
    m = stops[max(0, min(len(stops) - 1, int(pick) - 1 if pick.isdigit() else 0))]
    stored = was_missing or name.strip()
    country = (m.get("country") or "").upper()
    if was_missing:
        country = country or missing[was_missing].get("country", "")
    if not country:
        country = ask("  Country code (e.g. SE, EE) - needed for the time zone: ", "", auto)
    capital = bool(was_missing) or yes(f"  Is {stored} a capital?", auto, default=False)
    add_place(stored, m["lat"], m["lon"], country, capital)
    print(f"  Added {stored} to places.yaml.")
    LOG["places"].append(f"{stored}: {m.get('name')} ({m['lat']:.3f}, {m['lon']:.3f}), country {country or '?'}"
                         f"{', capital' if capital else ', not marked as capital'}")
    places, _ = load_places()
    return stored, places[stored]


# --- legs.yaml -------------------------------------------------------------------
BLOCK_RE = re.compile(r"(?ms)^  - \{.*?\}[ \t]*(?:#[^\n]*)?$")


def existing(frm: str, to: str, service: str):
    text = LEGS.read_text()
    norm = re.sub(r"\s+", "", service).casefold()
    for m in BLOCK_RE.finditer(text):
        try:
            d = yaml.safe_load(m.group(0).strip()[2:])
        except yaml.YAMLError:
            continue
        if isinstance(d, dict) and d.get("from") == frm and d.get("to") == to \
                and re.sub(r"\s+", "", str(d.get("service", ""))).casefold() == norm:
            return m
    return None


def entry_text(e: dict) -> str:
    parts = [f"from: {e['from']}", f"to: {e['to']}"]
    if "times" in e:
        parts.append(f"service: {q(e['service'])}")
        parts.append(f"mode: {e['mode']}")
        if e.get("night"):
            parts.append("night: true")
        times = [q(t) for t in e["times"]]
        rows = [", ".join(times[i:i + 6]) for i in range(0, len(times), 6)]
        parts.append("times: [" + (",\n      ".join(rows)) + "]")
    else:
        parts += [f'dep: "{e["dep"]}"', f'arr: "{e["arr"]}"', f"service: {q(e['service'])}", f"mode: {e['mode']}"]
        if e.get("night"):
            parts.append("night: true")
    parts.append(f"checked: {e['checked']}")
    parts.append(f"source: {e['source']}")
    return "  - {" + ", ".join(parts) + "}"


def write_entry(e: dict, replace=None) -> None:
    text = LEGS.read_text()
    line = entry_text(e)
    if replace is not None:
        text = text[:replace.start()] + line + text[replace.end():]
    else:
        if SECTION not in text:
            text = text.rstrip("\n") + "\n\n" + SECTION + "\n"
        text = text.rstrip("\n") + "\n" + line + "\n"
    yaml.safe_load(text)                         # never write a broken file
    LEGS.write_text(text)


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
        return any(matches(l) for l in T.core(it.get("legs", [])))

    for it in T.day_itineraries(params, start, end, pause=args.pause, stop=hit):
        if hit(it):
            c = T.core(it["legs"])
            first = next(i for i, l in enumerate(c) if matches(l))
            last = max(i for i, l in enumerate(c) if matches(l))
            return c, first, last, tz_a, tz_b
    return None


def find_all(pa: dict, pb: dict, pattern: str, date: dt.date, args):
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
        lab = T.label(c[0])
        if not fnmatch.fnmatch(T.fold(lab), pat):
            continue
        d = T.parse_t(c[0]["startTime"]).astimezone(tz_a)
        a = T.parse_t(c[0]["endTime"]).astimezone(tz_b)
        found.setdefault(clock(d), (d, a, lab, c[0]))
    return [found[k] for k in sorted(found)]


def service_type(label: str) -> str:
    """'X2 523' -> 'X2', 'Øresundståg 1073' -> 'Øresundståg', 'EST 9039 ...' -> 'EST'."""
    toks = label.split()
    keep = [t for t in toks if not re.fullmatch(r"\d{3,}", t)]
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
    manual = re.search(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})\s*$", svc)
    if manual:
        svc = svc[:manual.start()].strip()

    frm, pa = resolve(m["a"], args.yes)
    to, pb = resolve(m["b"], args.yes)
    today = dt.date.today().isoformat()

    if manual:                                             # the user's own times
        d, a = (f"{int(x.split(':')[0]):02d}:{x.split(':')[1]}" for x in manual.groups())
        dur = (int(a[:2]) * 60 + int(a[3:]) - int(d[:2]) * 60 - int(d[3:])) % 1440
        e = {"from": frm, "to": to, "dep": d, "arr": a, "service": svc or "?",
             "mode": next((f for f in ("ferry", "bus") if f in flags), "train"),
             "night": "night" in flags or (dur >= 300 and a < d), "checked": today, "source": "manual"}
        print(f"  {frm} -> {to}  {d}-{a}  {e['service']}  ({e['mode']}{', night' if e['night'] else ''}) - not looked up")
        return save(e, args)

    if "*" in svc:                                         # every direct train
        print(f"  Collecting direct trains {frm} -> {to} on {args.date:%a %-d.%-m.%Y} ...")
        deps = find_all(pa, pb, svc, args.date, args)
        if not deps:
            print("  No direct trains found. Check the names with '*' alone, or give times yourself.")
            return status("no direct trains found")
        kinds = Counter(service_type(lab) for _, _, lab, _ in deps)
        show = deps if len(deps) <= 12 else deps[:6] + [None] + deps[-3:]
        for x in show:
            print("    ..." if x is None else f"    {clock(x[0])}-{clock(x[1])}  {x[2]}")
        print("  " + ", ".join(f"{k}: {n}" for k, n in kinds.most_common()))
        name = kinds.most_common(1)[0][0]
        name = ask(f"  Name for these trains [{name}]: ", name, args.yes)
        e = {"from": frm, "to": to, "service": name, "mode": mode_of([x[3] for x in deps]),
             "night": all(is_night(d, a) for d, a, _, _ in deps),
             "times": [f"{clock(d)}-{clock(a)}" for d, a, _, _ in deps],
             "checked": today, "source": "transitous"}
        print(f"  {len(deps)} departures, {e['times'][0]} ... {e['times'][-1]}")
        return save(e, args)

    print(f"  Looking for {svc} {frm} -> {to} on {args.date:%a %-d.%-m.%Y} ...")
    r = find_train(pa, pb, svc, args.date, near, args)
    if not r:
        print(f"  {svc} was not found between {frm} and {to} that day.")
        print("  Try another date (--date), '*' to list the direct trains, or give the times yourself:")
        print(f"     {frm} -> {to} : {svc} HH:MM-HH:MM")
        return status(f"{svc} not found on {args.date:%-d.%-m.}")
    c, first, last, tz_a, tz_b = r
    for i, l in enumerate(c):
        mark = "*" if first <= i <= last else " "
        print(f"   {mark} {T.parse_t(l['startTime']).astimezone(tz_a):%H:%M}-"
              f"{T.parse_t(l['endTime']).astimezone(tz_b):%H:%M}  {T.label(l)}"
              f"  ({l.get('from', {}).get('name', '?')} -> {l.get('to', {}).get('name', '?')})")
    span = c[first:last + 1]
    if first > 0 or last < len(c) - 1:
        print(f"  Note: {svc} does not cover the whole way; the lines without * are other trains.")
        if yes("  Store the whole chain as one leg?", args.yes, default=True):
            span = c
    d = T.parse_t(span[0]["startTime"]).astimezone(tz_a)
    a = T.parse_t(span[-1]["endTime"]).astimezone(tz_b)
    name = svc if span == c[first:last + 1] else " + ".join(T.label(l) for l in span)
    e = {"from": frm, "to": to, "dep": clock(d), "arr": clock(a), "service": name,
         "mode": mode_of(span), "night": is_night(d, a), "checked": today, "source": "transitous"}
    return save(e, args)


def save(e: dict, args) -> bool:
    old = existing(e["from"], e["to"], e["service"])
    print("  " + entry_text(e).strip().replace("\n", "\n  "))
    what = (f"{len(e['times'])} departures {e['times'][0]} … {e['times'][-1]}" if "times" in e
            else f"{e['dep']}-{e['arr']}") + f"  {e['service']}" + (" (your own times)" if e["source"] == "manual" else "")
    if old is not None:
        print("  This train is already in legs.yaml:\n  " + old.group(0).strip())
        if not yes("  Replace it?", args.yes):
            return status("kept the existing entry")
    elif not yes("  Add to legs.yaml?", args.yes):
        return status("skipped")
    write_entry(e, old)
    print("  Saved.")
    LOG["status"] = ("updated: " if old is not None else "added: ") + what
    return True


def main():
    ap = argparse.ArgumentParser(prog="add_leg.py", description=__doc__.split("\n\n")[0],
                                 epilog=__doc__.split("\n", 2)[2], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("leg", nargs="*", help='e.g. "Stockholm -> Malmö : X2 523"')
    ap.add_argument("--date", help="travel date to look the train up on, YYYY-MM-DD (default: next Tuesday)")
    ap.add_argument("--file", metavar="PAIRS.TXT",
                    help="read legs from a file, one per line ('#' starts a comment); implies --yes "
                         "and prints a summary at the end")
    ap.add_argument("--yes", action="store_true", help="don't ask, accept the first answer")
    ap.add_argument("--build", action="store_true", help="run build.py afterwards")
    ap.add_argument("--pause", type=float, default=1.0, help="seconds between Transitous requests")
    argv = [f"--{a}" if re.fullmatch(r"(date|pause|file)=.*", a) else a for a in sys.argv[1:]]
    args = ap.parse_args(argv)
    today = dt.date.today()
    args.date = dt.date.fromisoformat(args.date) if args.date else today + dt.timedelta(days=(1 - today.weekday()) % 7 or 7)

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
    if added and (args.build or (not args.leg and not args.yes and yes("Rebuild the graph and map now?", False))):
        subprocess.run([sys.executable, str(ROOT / "build.py")], check=False)
    elif added:
        print("Run  python3 build.py  to rebuild the graph and map.")


def run_file(lines: list[str], args) -> None:
    print(f"{len(lines)} legs from {args.file}, travel date {args.date:%a %-d.%-m.%Y}\n")
    results = []
    for n, ln in enumerate(lines, 1):
        print(f"[{n}/{len(lines)}] {ln}")
        LOG["status"] = None
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
    bad = [r for r in results if not r[1]]
    width = max(len(r[0]) for r in results)
    print("=" * 72)
    print(f"Summary: {len(good)} added or updated, {len(bad)} not added, {len(LOG['places'])} new places")
    if good:
        print("\nAdded or updated:")
        for ln, _, st in good:
            print(f"  {ln:<{width}}  {st}")
    if bad:
        print("\nNot added - check by hand or give the times yourself (A -> B : name HH:MM-HH:MM):")
        for ln, _, st in bad:
            print(f"  {ln:<{width}}  {st}")
    if LOG["places"]:
        print("\nNew places in data/places.yaml - check the station, country and capital flag:")
        for p in LOG["places"]:
            print(f"  {p}")
    if good:
        if args.build:
            print()
            subprocess.run([sys.executable, str(ROOT / "build.py")], check=False)
        else:
            print("\nRun  python3 build.py  to rebuild the graph and map.")


if __name__ == "__main__":
    main()
