#!/usr/bin/env python3
"""Build everything from data/: one map per origin (out/site/), route tables (out/routes*.md), data (out/network*.json).

    python build.py                # writes out/
    python build.py transfer=15    # minimum change time 15 min (stations with a longer
                                   # change time in places.yaml keep theirs)
    python build.py night=02       # a wait through 02:00 counts as a hotel night (default: settings, 01:00)
    python build.py transfer=20 night=2:30 date=2026-11-17
"""
from __future__ import annotations

import argparse
import re
import datetime as dt
import json
import multiprocessing
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import yaml

ROOT = Path(__file__).parent
# the network's folders: data/ and out/ (Europe), or data/<network>/ and out/<network>/ with network=us (D-67)
DATA = ROOT / "data"
OUT = ROOT / "out"
sys.path.insert(0, str(ROOT / "src"))
from journeys import DAY, TZ, Router, fmt_clock, fmt_dur, hm, load, utc_offset  # noqa: E402
from co2 import CO2  # noqa: E402
import i18n  # noqa: E402

def main():
    ap = argparse.ArgumentParser(
        prog="build.py",
        description="Build the Maata pitkin journeys from data/legs.yaml and data/places.yaml:\n"
                    "out/routes.md, the interactive map out/map.html and out/network.json.",
        epilog="Every option can also be written as key=value without dashes, for example:\n"
               "  python3 build.py transfer=15\n"
               "  python3 build.py night=01\n"
               "  python3 build.py start=08:00     # leave Helsinki in the morning\n"
               "  python3 build.py dates=2026-12-08,2026-12-11   # travel dates to switch between on the map\n"
               "  python3 build.py starts=06:00,17:00   # departure times to switch between on the map\n"
               "  python3 build.py transfer=20 night=2:30 date=2026-11-17\n\n"
               "transfer sets the normal change time. Stations with a longer change time in\n"
               "places.yaml keep their own (longer at Paris, London, Madrid, Istanbul; shorter at small border stations).\n"
               "night sets the hour a wait must pass through to count as a hotel night.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="travel date YYYY-MM-DD (default: settings.start_date or next Monday)")
    ap.add_argument("--dates", metavar="D1,D2,...",
                    help="travel dates to offer on the map, YYYY-MM-DD,... (default: settings.travel_dates, or the "
                         "travel date and the Friday, Saturday and Sunday after it)")
    ap.add_argument("--transfer", type=int, metavar="N",
                    help="minimum change time in minutes (default: settings.min_transfer)")
    ap.add_argument("--start", metavar="T",
                    help="leave the origin from this time on the travel date, 24 h (default: the origin's start_time, or settings.start_time)")
    ap.add_argument("--starts", metavar="T1,T2",
                    help="departure times to switch between on the map, e.g. 06:00,17:00 (default: "
                         "settings.start_times, or 06:00 and the start time)")
    ap.add_argument("--jobs", type=int, metavar="N",
                    help="work on this many maps and travel days at the same time (default: number of CPU cores)")
    ap.add_argument("--merge", action="store_true",
                    help="only join the summaries of maps built one by one (out/parts/summary-*.json, from only=) "
                         "into out/summary.json - the weekly workflow builds each map in a job of its own")
    ap.add_argument("--only", metavar="ORIGIN",
                    help="build only the map from this origin (quicker for testing; summary.json is not written)")
    ap.add_argument("--network", metavar="NAME",
                    help="build another network: data/NAME/ -> out/NAME/ (e.g. network=us, D-67; default: data/ -> out/)")
    ap.add_argument("--night", metavar="T",
                    help="time the night begins, 24 h: 01, 1, 0100 or 01:00 (default: settings.night_point)")
    # accept key=value as well as --key value
    argv = [f"--{a}" if re.fullmatch(r"[a-z][a-z-]*=.*", a) else a for a in sys.argv[1:]]
    args = ap.parse_args(argv)

    global DATA, OUT
    if args.network:
        DATA, OUT = ROOT / "data" / args.network, ROOT / "out" / args.network
        if not (DATA / "places.yaml").exists():
            ap.error(f"network: no {DATA / 'places.yaml'}")
        OUT.mkdir(parents=True, exist_ok=True)
    if args.merge:
        merge_summaries()
        return
    net, warnings = load(DATA)
    if args.transfer is not None:
        if args.transfer < 0:
            ap.error("transfer must be 0 or more minutes")
        net.settings["min_transfer"] = args.transfer
    if args.night is not None:
        m = re.fullmatch(r"(\d{1,2})(?::?(\d{2}))?", args.night.strip())
        if not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
            ap.error(f"night must be a time like 03, 3, 0300 or 03:00 (got {args.night!r})")
        net.settings["night_point"] = f"{int(m.group(1)):02d}:{m.group(2) or '00'}"
    if args.start is not None:
        m = re.fullmatch(r"(\d{1,2})(?::?(\d{2}))?", args.start.strip())
        if not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
            ap.error(f"start must be a time like 17, 0800 or 08:00 (got {args.start!r})")
        net.settings["start_time"] = f"{int(m.group(1)):02d}:{m.group(2) or '00'}"
    # one map page per origin (IDEA-04): the first is index.html, the others e.g. stockholm.html
    origins = net.settings.get("origins") or {net.settings.get("origin", "Helsinki"): {"page": "index.html"}}
    pages = [{"name": o, "page": (c or {}).get("page") or f"{slugify(o)}.html", "draft": bool((c or {}).get("draft"))}
             for o, c in origins.items()]
    if args.only and args.only not in origins:
        ap.error(f"only: {args.only!r} is not one of the origins ({', '.join(origins)})")
    jobs_list = []
    for k, (origin, cfg) in enumerate(origins.items()):
        if origin not in net.places:
            ap.error(f"origin {origin!r} is not in places.yaml")
        if args.only and origin != args.only:
            continue
        jobs_list.append((k, origin, dict(cfg or {}, page=pages[k]["page"])))
    # the whole network for the in-browser router (IDEA-21), shared by every map; a page loads it
    # only when a visitor asks for their own settings (date, time, change time, no ferries/buses)
    write_router_data(net)
    # Two rounds on the machine's cores (FIX-17): first the journeys of every map and travel day -
    # the slow part, and independent of each other - then each map's page from its days. Splitting
    # by day as well as by map keeps all cores busy even when one map is much slower than the others
    # (Helsinki and Stockholm with the morning sweep), and lets a single map (only=) use every core.
    global _JOB
    _JOB = (net, warnings, args, ap, pages, jobs_list)
    day_tasks = [(i, d) for i, (k, origin, cfg) in enumerate(jobs_list)
                 for d in origin_context(net, args, ap, origin, cfg).dates]
    n_jobs = max(1, min(args.jobs or os.cpu_count() or 1, len(day_tasks)))
    parts: dict[int, list] = {i: [] for i in range(len(jobs_list))}
    if n_jobs > 1 and hasattr(os, "fork"):
        with multiprocessing.get_context("fork").Pool(n_jobs) as pool:
            for i, part in pool.imap_unordered(_day_job, day_tasks, chunksize=1):
                parts[i].append(part)
            results = pool.map(_build_job, [(i, parts[i]) for i in range(len(jobs_list))], chunksize=1)
    else:
        for task in day_tasks:
            i, part = _day_job(task)
            parts[i].append(part)
        results = [_build_job((i, parts[i])) for i in range(len(jobs_list))]
    # each map's summary as a part (out/parts/), joined into out/summary.json - the same file whether
    # every map was built here or each in a job of its own (the weekly workflow, FIX-17)
    parts_dir = OUT / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    for origin, summ in results:
        (parts_dir / f"summary-{slugify(origin)}.json").write_text(json.dumps(summ, indent=1) + "\n")
    if args.only:
        print(f"Built one map only - its summary is in out/parts/; out/summary.json not written "
              f"(build.py --merge joins the parts once every map is built).")
        return
    merge_summaries()


def merge_summaries() -> None:
    """out/summary.json from the maps built one by one (FIX-17): the first origin in places.yaml at
    the top level, the others under "origins" - the same as a build of every map at once."""
    origins = list((yaml.safe_load((DATA / "places.yaml").read_text())["settings"].get("origins") or {}))
    parts = OUT / "parts"
    summaries = {}
    for o in origins:
        f = parts / f"summary-{slugify(o)}.json"
        if not f.exists():
            sys.exit(f"merge: {f.relative_to(ROOT)} is missing - was the map from {o} built?")
        summaries[o] = json.loads(f.read_text())
    first, *others = summaries
    summary = dict(summaries[first], origins={o: summaries[o] for o in others})
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(f"out/summary.json from {len(summaries)} maps")


def write_router_data(net) -> Path:
    """out/site/router-data.js: the network as src/router.js reads it (src/router_data.py). A script
    file, not JSON, so the page can load it with a <script> tag - also from a local file, where
    fetch() is not allowed. tests/check_router.mjs reads the same file."""
    from router_data import export
    site = OUT / "site"
    site.mkdir(parents=True, exist_ok=True)
    path = site / "router-data.js"
    path.write_text("self.MP_ROUTER_DATA=" + json.dumps(export(net), ensure_ascii=False, separators=(",", ":")) + ";\n")
    return path


def used_legs(variants: dict) -> set:
    """Every leg any journey of these variants uses (fastest and alternatives, all start times)."""
    used = set()

    def walk(r):
        if not r or r.get("same_as_default"):
            return
        used.update(x["i"] for x in r.get("steps", []) if x.get("kind") == "leg")
        for a in r.get("alternatives") or []:
            walk(a)
    for v in variants.values():
        for sv in [v, *(v.get("starts") or {}).values()]:
            for key in ("yes", "no"):
                for r in sv.get(key, {}).get("routes", []) + sv.get(key, {}).get("city_routes", []):
                    walk(r)
    return used


def compact_route(r: dict) -> dict:
    """The map's copy of a journey, without what the page can rebuild from the timetable
    (station names, services, dates as text): a leg is ["l", leg, dep, arr], a hotel night or
    a change ["s"/"c", place, from, to, nights]. Keeps the page small (FIX: 9 MB -> ~4 MB)."""
    if r.get("same_as_default"):
        return r
    out = {k: v for k, v in r.items() if k not in ("steps", "depart_txt", "arrive_txt", "signature", "alternatives")}
    out["steps"] = [["l", x["i"], x["dep"], x["arr"]] if x["kind"] == "leg"
                    else [x["kind"][0], x["place"], x["t0"], x["t1"], x.get("nights", 0)] for x in r["steps"]]
    if r.get("alternatives"):
        out["alternatives"] = [compact_route(a) for a in r["alternatives"]]
    return out


def compact_variants(variants: dict) -> dict:
    def one(v):
        o = {k: x for k, x in v.items() if k not in ("yes", "no", "starts")}
        for key in ("yes", "no"):
            if key in v:
                o[key] = {**v[key], "routes": [compact_route(r) for r in v[key]["routes"]],
                          "city_routes": [compact_route(r) for r in v[key]["city_routes"]]}
        if "starts" in v:
            o["starts"] = {t: one(sv) for t, sv in v["starts"].items()}
        return o
    return {d: one(v) for d, v in variants.items()}


_JOB = None          # set by main() before the worker processes are forked


def _day_job(task):
    """Round 1: one map's journeys for one travel day (in a worker process)."""
    i, d = task
    net, warnings, args, ap, pages, jobs_list = _JOB
    k, origin, cfg = jobs_list[i]
    c = origin_context(net, args, ap, origin, cfg)
    journeys = Journeys(net, origin, c.s, c.start)
    v, t_main, t_other = journeys.date_variant(d, c.starts, c.start_time, c.tx, c.version_line)
    return i, (d.isoformat(), v, t_main, t_other, journeys.stats)


def _build_job(task):
    """Round 2: one map's page, route table and summary from its travel days."""
    i, parts = task
    net, warnings, args, ap, pages, jobs_list = _JOB
    k, origin, cfg = jobs_list[i]
    summary = build_origin(net, warnings, args, ap, origin, cfg, pages, main_origin=(k == 0), parts=parts)
    sys.stdout.flush()      # a worker's prints are lost if the pool ends it before its buffer is written
    return origin, summary


def next_timetable_change(day: dt.date) -> dt.date:
    """The next European timetable change after `day`: the second Sunday of December (the big yearly
    change) or of June (the smaller mid-year one). Timetables looked up for one week normally hold
    until the day before (D-52)."""
    def second_sunday(year: int, month: int) -> dt.date:
        first = dt.date(year, month, 1)
        return first + dt.timedelta(days=(6 - first.weekday()) % 7 + 7)
    return min(c for y in (day.year, day.year + 1) for c in (second_sunday(y, 6), second_sunday(y, 12)) if c > day)


def local_names(lang: str, places: dict) -> dict:
    """{key: name to show} for one map's language (data/names.yaml, D-50): the language's own
    name, else `all`, else the key itself (left out). Routing, links and data keep the keys."""
    f = DATA / "names.yaml"
    names = (yaml.safe_load(f.read_text()) or {}) if f.exists() else {}
    out = {}
    for key, v in names.items():
        if key in places and isinstance(v, dict):
            shown = v.get(lang) or v.get("all")
            if shown and shown != key:
                out[key] = shown
    return out


def nearby_places(places: dict) -> dict:
    """{hub: [{name, by, time, every?|daily?, aliases?}, ...]} from data/nearby.yaml (IDEA-24, D-64):
    towns a short hop from a place on the map, shown in its itinerary, tooltip and search but not
    routed. Entries with an unknown hub or a malformed time are left out (with a message)."""
    f = DATA / "nearby.yaml"
    data = (yaml.safe_load(f.read_text()) or {}) if f.exists() else {}
    out = {}
    for hub, items in data.items():
        if hub not in places:
            print(f"nearby.yaml: {hub} is not a place in places.yaml - left out")
            continue
        for e in items or []:
            if not (isinstance(e, dict) and e.get("name") and e.get("by") in ("train", "bus", "ferry")
                    and re.fullmatch(r"\d{1,2}:\d{2}", str(e.get("time", "")))):
                print(f"nearby.yaml: {hub}: {e} needs name, by (train/bus/ferry) and time H:MM - left out")
                continue
            h, m = map(int, str(e["time"]).split(":"))
            x = {"name": str(e["name"]), "by": e["by"], "min": h * 60 + m}
            for k in ("every", "daily"):
                if isinstance(e.get(k), int):
                    x[k] = e[k]
            if e.get("aliases"):
                x["aliases"] = [str(a) for a in e["aliases"]]
            out.setdefault(hub, []).append(x)
    return out


def wiki_texts(lang: str, places: dict) -> dict:
    """{key: {text, source, url}} for one map's language (IDEA-22): data/wiki/<lang>.yaml, written
    by fetch_wiki.py, with data/wiki/overrides.yaml (<lang>: {place: {...}}) on top. Read only -
    the build never fetches. Only plain fields are passed; the page shows the text as text."""
    d = DATA / "wiki"
    f, o = d / f"{lang}.yaml", d / "overrides.yaml"
    texts = (yaml.safe_load(f.read_text()) or {}) if f.exists() else {}
    over = ((yaml.safe_load(o.read_text()) or {}).get(lang) or {}) if o.exists() else {}
    out = {}
    for key in places:
        e = {**(texts.get(key) or {}), **(over.get(key) or {})}
        if e.get("text") and str(e.get("url", "")).startswith("https://"):
            out[key] = {"text": str(e["text"]), "source": str(e.get("source", "")), "url": str(e["url"])}
    return out


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# --- one origin (IDEA-04) ---------------------------------------------------------
# build_origin() puts the pieces below together; each piece does one thing (FIX-16).

def origin_settings(net, args, cfg: dict) -> dict:
    """The general settings, with the origin's own start times (unless given on the command line)."""
    s = dict(net.settings)
    for k in ("start_time", "start_times"):                # an origin may have its own start times
        if k in cfg and not (k == "start_time" and args.start is not None) and not (k == "start_times" and args.starts):
            s[k] = cfg[k]
    return s


def first_travel_date(args, s: dict, today: dt.date) -> dt.date:
    """date= on the command line, else settings.start_date, else next Monday."""
    return dt.date.fromisoformat(str(args.date or s.get("start_date") or
                                     (today + dt.timedelta(days=(7 - today.weekday()) % 7 or 7))))


def travel_dates(args, s: dict, start_date: dt.date) -> list[dt.date]:
    """The travel dates offered on the map, the first travel date first."""
    if args.dates:
        dates = [dt.date.fromisoformat(x.strip()) for x in args.dates.split(",") if x.strip()]
    elif s.get("travel_dates"):
        dates = [dt.date.fromisoformat(str(x)) for x in s["travel_dates"]]
    else:
        dates = [start_date] + [start_date + dt.timedelta(days=k) for k in range(1, 7)
                                if (start_date + dt.timedelta(days=k)).weekday() in (4, 5, 6)]
    return [start_date] + [d for d in dict.fromkeys(dates) if d != start_date]


def start_times(args, s: dict, start_time: str, ap) -> list[str]:
    """Departure times to switch between on the map (D-32); the default start time is one of them."""
    def clock_arg(x: str) -> str:
        m = re.fullmatch(r"(\d{1,2})(?::?(\d{2}))?", str(x).strip())
        if not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
            ap.error(f"start times must look like 06:00 or 17 (got {x!r})")
        return f"{int(m.group(1)):02d}:{m.group(2) or '00'}"
    raw = args.starts.split(",") if args.starts else s.get("start_times") or ["06:00", start_time]
    return sorted({clock_arg(x) for x in raw if str(x).strip()} | {start_time})


class Journeys:
    """Every journey from one origin: the fastest to each place, its alternatives (fewest
    changes, fewest hotel nights), and the variants per travel date, start time and with or
    without night trains."""

    ALTERNATIVES = [("Fewest changes", "changes", lambda c, h, t: (c, t, h)),
                    ("Fewest hotel nights", "hotel_nights", lambda c, h, t: (h, t, c))]

    def __init__(self, net, origin: str, s: dict, start: int):
        self.net, self.origin, self.start = net, origin, start
        self.max_extra = int(float(s.get("alternative_max_extra_hours", 12)) * 60)
        self.co2 = CO2(s.get("co2"), net.places)          # rough CO2 vs flying (IDEA-07, D-41)
        self.stats = {"compute": 0, "sweep": 0, "t_sweep": 0.0, "t_compute": 0.0, "loops": set()}

    # -- one journey ------------------------------------------------------------
    def route(self, router, cap: str, j: list | None = None) -> dict | None:
        """A router journey to `cap` as the map and the route table show it."""
        net, origin = self.net, self.origin

        def when(t: int) -> str:
            return f"{router.date_of(t):%a %-d.%-m.} {fmt_clock(t)}"

        j = j if j is not None else router.journey(cap)
        if not j:
            return None
        legs = [x for x in j if x["kind"] == "leg"]
        first_dep, arr = legs[0]["dep"], legs[-1]["arr"]
        visited = [legs[0]["leg"].frm] + [x["leg"].to for x in legs]
        if len(set(visited)) < len(visited):          # e.g. Paris - London - Paris to kill time (max_stay_nights)
            self.stats["loops"].add(cap)
        # clock times are local; door to door is corrected for the time-zone difference
        shift = (utc_offset(net.places[cap], router.date_of(arr), arr % DAY)
                 - utc_offset(net.places[origin], router.date_of(first_dep), first_dep % DAY))
        steps = []
        for st in j:
            if st["kind"] != "leg":
                steps.append({"kind": st["kind"], "place": st["place"], "from_t": when(st["from"]),
                              "to_t": when(st["to"]), "minutes": st["to"] - st["from"],
                              "nights": st.get("nights", 0), "t0": st["from"], "t1": st["to"]})
                continue
            leg = st["leg"]
            steps.append({"kind": "leg", "i": leg.idx, "from": leg.frm, "to": leg.to, "service": leg.service,
                          "mode": leg.mode, "night": leg.night, "dep": st["dep"], "arr": st["arr"],
                          "dep_txt": when(st["dep"]), "arr_txt": when(st["arr"]),
                          "timed": leg.timed, "issue": leg.issue, "note": leg.note})
        return {"capital": cap, "depart": first_dep, "arrive": arr,
                "depart_txt": when(first_dep), "arrive_txt": when(arr),
                "door_to_door_min": arr - first_dep - shift,
                "arrive_abs": arr - shift,              # arrival in the origin's clock, for sorting
                "tz_shift": shift,
                "changes": sum(1 for x in steps if x["kind"] in ("change", "stay")),
                "nights_on_board": sum(1 for x in legs if x["leg"].night),
                "hotel_nights": sum(x["nights"] for x in steps if x["kind"] == "stay"),
                "stays": [x["place"] for x in steps if x["kind"] == "stay"],
                "has_issue": any(x.get("issue") for x in steps),
                "signature": [(x["i"], x["dep"]) for x in steps if x["kind"] == "leg"],
                **(self.co2.journey([x["leg"] for x in legs], origin, cap) or {}),
                "steps": steps}

    def with_alternatives(self, router, front: dict, place: str, j: list | None = None) -> dict | None:
        """The fastest journey to `place` plus the alternatives worth showing (from the Pareto front)."""
        r = self.route(router, place, j)
        if not r:
            return None
        r["label"] = "Fastest"
        r["capital"] = place                     # the destination's name (capital or not)
        r["is_capital"] = bool(self.net.places[place].get("capital"))
        r["alternatives"], seen = [], [r["signature"]]
        for name, field_, order in self.ALTERNATIVES:
            ok = [l for l in front.get(place, []) if l[2] <= r["arrive"] + self.max_extra]
            if not ok:
                continue
            alt = None
            for c, h, t, lid in sorted(ok, key=lambda l: order(*l[:3]))[:20]:
                j = router.pareto_journey(lid)
                pl = [x["leg"] for x in j if x["kind"] == "leg"]
                visited = [pl[0].frm] + [x.to for x in pl]
                if len(set(visited)) == len(visited):   # no back-and-forth to dodge a hotel night
                    alt = self.route(router, place, j)
                    break
            if alt and alt[field_] < r[field_] and alt["signature"] not in seen:
                alt["label"] = name
                r["alternatives"].append(alt)
                seen.append(alt["signature"])
        return r

    # -- all journeys for one date and start ----------------------------------------
    def compute(self, night_trains: bool, date: dt.date, start: int | None = None, only: set | None = None,
                journeys: dict | None = None):
        """All journeys (fastest + alternatives) leaving on `date` from `start`, with or without night
        trains. Returns (router, capital routes, other routes, unreached capitals, unreached others)."""
        net, origin = self.net, self.origin
        start = self.start if start is None else start
        self.stats["compute"] += 1
        router = Router(net, date, night_trains=night_trains)
        front = router.pareto(origin, start)            # all sensible trade-offs, for the alternatives

        if journeys is not None:
            # other start times: the fastest journeys were found already (latest departure that
            # still arrives first); add the alternatives from this one Pareto search (FIX-09)
            rs, crs = [], []
            for place, j in journeys.items():
                r = self.with_alternatives(router, front, place, j)
                if r:
                    (rs if r["is_capital"] else crs).append(r)
            return router, rs, crs, [], []

        router.search(origin, start, "fastest")          # the main table uses the fastest search

        routes, city_routes, unreached, unreached_cities = [], [], [], []
        for place in net.places:
            if only is not None and place not in only:      # other start times: just the places that need it
                continue
            if place == origin:
                continue
            r = self.with_alternatives(router, front, place)
            if r is None:
                (unreached if net.places[place].get("capital") else unreached_cities).append(place)
                continue
            (routes if r["is_capital"] else city_routes).append(r)
        routes.sort(key=lambda r: r["arrive_abs"])
        city_routes.sort(key=lambda r: r["arrive_abs"])
        return router, routes, city_routes, unreached, unreached_cities

    # -- variants shown on the map ------------------------------------------------
    def variant(self, d: dt.date, t: str) -> dict:
        """With and without night trains, leaving on `d` from `t`."""
        v = {}
        for key, nt in (("yes", True), ("no", False)):
            _, rs, crs, un, unc = self.compute(nt, d, hm(t))
            v[key] = {"routes": rs, "city_routes": crs, "unreached": un, "unreached_cities": unc}
        return v

    def earlier_start(self, d: dt.date, t: str, base: dict) -> dict:
        """Journeys when you may leave from `t` (earlier than the default start).
        For each place: the earliest arrival from `t`, on the latest departure that still
        makes it. Where leaving early doesn't arrive sooner, the default journey is kept
        and marked same_as_default."""
        net, origin, stats = self.net, self.origin, self.stats
        v = {}
        for key, nt in (("yes", True), ("no", False)):
            ev = {r["capital"]: r for r in base[key]["routes"] + base[key]["city_routes"]}
            router = Router(net, d, night_trains=nt)
            router.search(origin, hm(t), "fastest")
            best, jbest = {}, {}                        # place -> (first departure, arrival), its journey
            for p in net.places:
                j = router.journey(p) if p != origin else None
                if j:
                    legs = [x for x in j if x["kind"] == "leg"]
                    best[p], jbest[p] = (legs[0]["dep"], legs[-1]["arr"]), j
            open_ = {p for p, (_, a) in best.items() if p not in ev or a < ev[p]["arrive"]}
            # move the start later as long as the arrival stays the same
            ts = time.monotonic()
            while open_:
                t2 = min(best[p][0] for p in open_) + 1
                stats["sweep"] += 1
                router.search(origin, t2, "fastest")
                for p in list(open_):
                    j = router.journey(p)
                    legs = [x for x in j if x["kind"] == "leg"] if j else []
                    if legs and legs[-1]["arr"] == best[p][1]:
                        if legs[0]["dep"] >= best[p][0]:
                            best[p], jbest[p] = (legs[0]["dep"], best[p][1]), j
                    else:
                        open_.discard(p)
            stats["t_sweep"] += time.monotonic() - ts
            ts = time.monotonic()
            # the journeys the sweep found, as routes (fastest only - no second search per start time)
            gain = {p for p, (_, a) in best.items() if p not in ev or a < ev[p]["arrive"]}
            _, rs, crs, _, _ = self.compute(nt, d, hm(t), journeys={p: jbest[p] for p in gain})
            found: dict[str, dict] = {r["capital"]: r for r in rs + crs}
            stats["t_compute"] += time.monotonic() - ts
            rs, crs, un, unc = [], [], [], []
            for p in net.places:
                if p == origin:
                    continue
                r = found.get(p) or (dict(ev[p], same_as_default=True) if p in ev else None)
                if r is None:
                    (un if net.places[p].get("capital") else unc).append(p)
                else:
                    (rs if r["is_capital"] else crs).append(r)
            rs.sort(key=lambda r: r["arrive_abs"])
            crs.sort(key=lambda r: r["arrive_abs"])
            # unchanged journeys are stored as a reference only; the map fills them in (keeps the page small)
            stub = lambda r: {"capital": r["capital"], "same_as_default": True} if r.get("same_as_default") else r
            v[key] = {"routes": [stub(r) for r in rs], "city_routes": [stub(r) for r in crs],
                      "unreached": un, "unreached_cities": unc}
        return v

    def all_variants(self, dates: list, starts: list, start_time: str, tx: dict, version_line):
        """{date: {label, version, yes, no, starts: {time: {version, yes, no}}}} and the time taken
        (seconds for the default start, seconds for the other start times)."""
        variants = {}
        t_main = t_other = 0.0
        for d in dates:
            v, tm, to = self.date_variant(d, starts, start_time, tx, version_line)
            variants[d.isoformat()] = v
            t_main += tm; t_other += to
        return variants, t_main, t_other

    def date_variant(self, d: dt.date, starts: list, start_time: str, tx: dict, version_line):
        """One travel day: {label, version, yes, no, starts}, and the seconds for the default start and
        for the other start times. Travel days are independent, so they can be worked out side by side."""
        t0 = time.monotonic()
        v = {"label": f"{i18n.weekday(tx, d)} {d.day}.{d.month}.", "version": version_line(d, start_time),
             **self.variant(d, start_time)}
        t1 = time.monotonic()
        v["starts"] = {t: {"version": version_line(d, t),
                           **(self.earlier_start(d, t, v) if t < start_time else self.variant(d, t))}
                       for t in starts if t != start_time}
        return v, t1 - t0, time.monotonic() - t1

    def add_stats(self, other: dict) -> None:
        """Counts and times from a travel day worked out in another process."""
        for k, x in other.items():
            self.stats[k] = self.stats[k] | x if isinstance(x, set) else self.stats[k] + x


# --- route table (out/routes*.md) ---------------------------------------------------
def routes_markdown(origin: str, version: str, router, routes: list, city_routes: list, unreached: list,
                    variants: dict, start_date: dt.date, start_time: str, starts: list, net, warnings: list) -> str:
    day_routes, day_city_routes, day_unreached = (variants[start_date.isoformat()]["no"][k]
                                                  for k in ("routes", "city_routes", "unreached"))
    md = [f"# Journeys from {origin}", "",
          f"_{version}. Change {router.min_transfer} min (more at some stations), ferry check-in "
          f"{router.ferry_checkin} min, Eurostar {router.eurostar_checkin} min. A wait "
          f"past {fmt_clock(router.night_point)} is a hotel stay; no departures before {fmt_clock(router.morning)} after a hotel night. "
          f"Between {fmt_clock(router.quiet[0])} and {fmt_clock(router.quiet[1])} only night trains and ferries run. "
          f"Clock times are local; door-to-door times are corrected for time zones._", "",
          "| Capital | Depart | Arrive | Door to door | Changes | Night trains/ferries | Hotel nights (where) | Alternatives |",
          "|---|---|---|---|---|---|---|---|"]
    for r in routes:
        flag = " ⚠" if r["has_issue"] else ""
        where = f"{r['hotel_nights']} ({', '.join(r['stays'])})" if r["stays"] else "0"
        md.append(f"| {r['capital']}{flag} | {r['depart_txt']} | {r['arrive_txt']} | "
                  f"{fmt_dur(r['door_to_door_min'])} | {r['changes']} | {r['nights_on_board']} | {where} | "
                  + "; ".join(f"{a['label'].lower()}: {fmt_dur(a['door_to_door_min'])}, {a['changes']} ch., "
                              f"{a['hotel_nights']} hotel" for a in r["alternatives"]) + " |")
    md += ["", "## Without night trains", "",
           "_Night trains and night buses left out; night ferries still used._", "",
           "| Capital | Arrive | Door to door | Changes | Hotel nights (where) | Compared with night trains |",
           "|---|---|---|---|---|---|"]
    fast = {r["capital"]: r for r in routes}
    for r in day_routes:
        where = f"{r['hotel_nights']} ({', '.join(r['stays'])})" if r["stays"] else "0"
        f = fast.get(r["capital"])
        diff = (r["door_to_door_min"] - f["door_to_door_min"]) if f else None
        md.append(f"| {r['capital']} | {r['arrive_txt']} | {fmt_dur(r['door_to_door_min'])} | {r['changes']} | {where} | "
                  + ("same" if diff == 0 else f"+{fmt_dur(diff)}" if diff and diff > 0 else "–") + " |")
    if day_unreached:
        md += ["", "Not reachable without night trains: " + ", ".join(day_unreached)]
    other = [t for t in starts if t != start_time]
    if other:
        t2 = other[0]
        alt = {r["capital"]: r for r in variants[start_date.isoformat()]["starts"][t2]["yes"]["routes"]}
        md += ["", f"## Leaving from {t2} instead of {start_time}", "",
               "| Capital | Leave | Arrive | Door to door | Compared with " + start_time + " |", "|---|---|---|---|---|"]
        for r in routes:
            a = alt.get(r["capital"])
            if not a:
                md.append(f"| {r['capital']} | – | – | – | not reachable |")
                continue
            if a.get("same_as_default"):
                md.append(f"| {r['capital']} | – | – | – | no gain: take the {start_time} journey |")
                continue
            diff = a["arrive_abs"] - r["arrive_abs"]
            md.append(f"| {r['capital']} | {a['depart_txt']} | {a['arrive_txt']} | {fmt_dur(a['door_to_door_min'])} | "
                      + ("same arrival" if diff == 0 else f"arrives {fmt_dur(abs(diff))} {'earlier' if diff < 0 else 'later'}") + " |")
    md += ["", "## Other cities", "", "| City | Arrive | Door to door | Changes | Hotel nights |", "|---|---|---|---|---|"]
    for r in city_routes:
        md.append(f"| {r['capital']} | {r['arrive_txt']} | {fmt_dur(r['door_to_door_min'])} | "
                  f"{r['changes']} | {r['hotel_nights']} |")
    md += ["", "## Itineraries", ""]

    def summary(x):
        return (f"{fmt_dur(x['door_to_door_min'])}, arrive {x['arrive_txt']}, {x['changes']} changes, "
                f"{x['hotel_nights']} hotel nights")

    for r0 in routes:
        for r in [r0] + r0["alternatives"]:
            title = r0["capital"] if r is r0 else f"{r0['capital']} — {r['label'].lower()}"
            md.append(f"### {title}{' ⚠' if r['has_issue'] else ''}")
            md.append(f"_{r['label']}: {summary(r)}_")
            md.append("")
            for x in r["steps"]:
                if x["kind"] == "leg":
                    md.append(f"- {x['dep_txt']} → {x['arr_txt']}  **{x['from']} → {x['to']}**  {x['service']}"
                              f"{'  (night)' if x['night'] else ''}{'  ⚠ ' + x['issue'] if x['issue'] else ''}")
                elif x["kind"] == "stay":
                    md.append(f"- 🛏 Overnight in {x['place']} ({x['from_t']} → {x['to_t']})")
                elif x["minutes"] >= 90:
                    md.append(f"- Wait {fmt_dur(x['minutes'])} in {x['place']}")
            md.append("")
    md += ["## Capitals not reachable with the current legs", ""]
    md += [f"- {c}" for c in unreached + list(net.not_covered)] or ["- none"]
    md += ["", "## Data issues", ""] + ([f"- {w}" for w in warnings] or ["- none"])
    return "\n".join(md) + "\n"


# --- data for the map (out/network*.json) ---------------------------------------------
def map_legs(net, variants: dict, start_date: dt.date):
    """IDEA-12: draw only the connections this map's journeys use (any day, mode, start time,
    option); the page gets every departure of those pairs (for the hover box) and just the
    names of the other pairs, for the "all connections" switch.
    Returns (legs for the page, used pairs, used departures, other pairs)."""
    used = used_legs(variants)
    by_idx = {l.idx: l for l in net.legs}
    used_pairs = {(by_idx[i].frm, by_idx[i].to) for i in used if i in by_idx}
    drawn = [l for l in net.legs if (l.frm, l.to) in used_pairs]
    other_pairs = sorted({(l.frm, l.to, l.mode, bool(l.night)) for l in net.legs
                          if (l.frm, l.to) not in used_pairs and l.frm in net.places and l.to in net.places})
    other_pairs = [list(x) for x in {(a, b): (a, b, m, n) for a, b, m, n in other_pairs}.values()]
    legs_json = [{"i": l.idx, "from": l.frm, "to": l.to, "service": l.service, "mode": l.mode,
                  "night": l.night, "highlight": l.highlight, "issue": l.issue, "note": l.note,
                  "dep": fmt_clock(l.dep) if l.timed else None,
                  "arr": fmt_clock(l.arr) if l.timed else None,
                  "duration": l.duration, "checked": l.checked,
                  "duration_true": l.duration - (
                      (utc_offset(net.places[l.to], start_date, ((l.dep or 0) + l.duration) % DAY)
                       - utc_offset(net.places[l.frm], start_date, (l.dep or 0) % DAY))
                      if l.frm in net.places and l.to in net.places else 0)} for l in drawn]
    return legs_json, used_pairs, drawn, other_pairs


def network_json(net, warnings: list, origin: str, cfg: dict, pages: list, s: dict, origin_from: str,
                 start_date: dt.date, version: str, legs_json: list, other_pairs: list, dates: list,
                 variants: dict, starts: list, start_time: str, router) -> dict:
    """Everything the map page needs (make_map.py puts it into the page)."""
    return {
        "origin": origin, "title": cfg.get("title") or "Maata pitkin", "draft": bool(cfg.get("draft")), "pages": pages,
        "other_pairs": other_pairs, "co2": s.get("co2"), "site_url": s.get("site_url"), "goatcounter": s.get("goatcounter"),
        "repo_url": s.get("repo_url"), "tz": TZ,   # issue links (IDEA-20); calendar times (IDEA-18)
        "wiki": wiki_texts(cfg.get("lang", "en"), net.places),   # city texts (IDEA-22)
        "lang": cfg.get("lang", "en"), "origin_from": origin_from,
        "nearby": (nb := nearby_places(net.places)),   # IDEA-24
        "display": local_names(cfg.get("lang", "en"), {**net.places, **net.not_covered,
                                                       **{e["name"]: {} for v in nb.values() for e in v}}), "start_date": start_date.isoformat(),
        "valid_until": (next_timetable_change(start_date) - dt.timedelta(days=1)).isoformat(), "version": version,
        "places": net.places, "not_covered": net.not_covered,
        "legs": legs_json, "dates": [d.isoformat() for d in dates], "variants": compact_variants(variants),
        "starts": starts, "default_start": start_time,
        "settings": {"min_transfer": router.min_transfer, "ferry_checkin": router.ferry_checkin,
                     "eurostar_checkin": router.eurostar_checkin, "night_point": fmt_clock(router.night_point),
                     "quiet": f"{fmt_clock(router.quiet[0])}–{fmt_clock(router.quiet[1])}",
                     "start": s.get("start_time", "00:00"),
                     "morning": fmt_clock(router.morning)}, "warnings": warnings,
        "layers": map_layers(legs_json),
    }


def map_layers(legs_json: list) -> dict | None:
    """The rail-map layers of a network that has them (data/<network>/map_layers.json, written by
    gtfs_import.py, IDEA-25): the track of each connection the map draws, every rail line, the
    stations. make_map.py projects them."""
    f = DATA / "map_layers.json"
    if not f.exists():
        return None
    lay = json.loads(f.read_text())
    drawn = {f"{l['from']}>{l['to']}" for l in legs_json} | {f"{l['to']}>{l['from']}" for l in legs_json}
    lay["geom"] = {k: v for k, v in lay.get("geom", {}).items() if k in drawn}   # the page reverses a track if needed
    return lay


def summary_of(net, warnings: list, cfg: dict, today: dt.date, dates: list, variants: dict) -> dict:
    """A small summary, committed every week, so the next run can tell if something broke (check_build.py)."""
    first = variants[dates[0].isoformat()]
    return {
        "generated": today.isoformat(), "dates": [d.isoformat() for d in dates], "draft": bool(cfg.get("draft")),
        "departures": len(net.legs), "warnings": len(warnings),
        "capitals": {k: {"with_night_trains": len(v["yes"]["routes"]), "without": len(v["no"]["routes"])}
                     for k, v in variants.items()},
        "places_reached": {k: len(v["yes"]["routes"]) + len(v["yes"]["city_routes"]) for k, v in variants.items()},
        # names too, so the weekly check can say what went missing (first travel date)
        "reached": {"capitals": sorted(r["capital"] for r in first["yes"]["routes"]),
                    "capitals_without_night_trains": sorted(r["capital"] for r in first["no"]["routes"]),
                    "places": sorted(r["capital"] for r in first["yes"]["routes"] + first["yes"]["city_routes"])},
    }


def origin_context(net, args, ap, origin: str, cfg: dict) -> SimpleNamespace:
    """What every part of one origin's build needs: settings, travel dates, start times, texts."""
    s = origin_settings(net, args, cfg)
    today = dt.date.today()
    start_date = first_travel_date(args, s, today)
    version = (f"leave {origin} {start_date:%a %-d.%-m.%Y} from {s.get('start_time', '00:00')}"
               f" · generated {today:%-d.%-m.%Y}")
    outdir = OUT
    outdir.mkdir(exist_ok=True)

    start = hm(s.get("start_time", "00:00"))
    start_time = fmt_clock(start)
    dates = travel_dates(args, s, start_date)
    starts = start_times(args, s, start_time, ap)

    tx = i18n.texts(cfg.get("lang", "en"))                 # the map's language (IDEA-13)
    # "from Helsinki" where the language inflects the name (fi: Helsingistä); else the shown name
    origin_shown = local_names(cfg.get("lang", "en"), net.places).get(origin, origin)   # Roma, København
    origin_from = cfg.get("from") or origin_shown

    def version_line(d: dt.date, t: str) -> str:
        return i18n.t(tx, "version", origin=origin_shown, origin_from=origin_from, date=f"{i18n.weekday(tx, d)} {d.day}.{d.month}.{d.year}",
                      time=t, today=f"{today.day}.{today.month}.{today.year}")

    return SimpleNamespace(s=s, today=today, start_date=start_date, version=version, outdir=outdir,
                           start=start, start_time=start_time, dates=dates, starts=starts, tx=tx,
                           origin_shown=origin_shown, origin_from=origin_from, version_line=version_line)


def build_origin(net, warnings, args, ap, origin: str, cfg: dict, pages: list, main_origin: bool,
                 parts: list | None = None) -> dict:
    """Journeys, route table and map page for one origin (IDEA-04). Returns its summary.
    `parts`: the travel days already worked out (FIX-17), as (date, variant, seconds main,
    seconds other starts, stats); without them every day is worked out here."""
    c = origin_context(net, args, ap, origin, cfg)
    s, today, start_date, version, outdir = c.s, c.today, c.start_date, c.version, c.outdir
    suffix = "" if main_origin else "-" + slugify(origin)    # routes-stockholm.md, network-stockholm.json
    start_time, dates, starts, origin_from = c.start_time, c.dates, c.starts, c.origin_from

    journeys = Journeys(net, origin, s, c.start)
    if parts is None:
        variants, t_main, t_other = journeys.all_variants(dates, starts, start_time, c.tx, c.version_line)
    else:
        by_day = {p[0]: p for p in parts}
        variants = {d.isoformat(): by_day[d.isoformat()][1] for d in dates}      # in the order of the dates
        t_main = sum(p[2] for p in parts)
        t_other = sum(p[3] for p in parts)
        for p in parts:
            journeys.add_stats(p[4])
    router, routes, city_routes, unreached, _ = journeys.compute(True, start_date)

    (outdir / f"routes{suffix}.md").write_text(
        routes_markdown(origin, version, router, routes, city_routes, unreached, variants,
                        start_date, start_time, starts, net, warnings))

    legs_json, used_pairs, drawn, other_pairs = map_legs(net, variants, start_date)
    (outdir / f"network{suffix}.json").write_text(json.dumps(
        network_json(net, warnings, origin, cfg, pages, s, origin_from, start_date, version, legs_json,
                     other_pairs, dates, variants, starts, start_time, router),
        ensure_ascii=False, indent=1))

    import make_map
    make_map.build(ROOT, f"network{suffix}.json", cfg.get("page", "index.html"), fragment=main_origin, data=DATA, out=OUT)

    stats = journeys.stats
    print(f"From {origin}: main journeys {t_main:.0f} s; other start times {t_other:.0f} s "
          f"(sweep {stats['sweep']} searches {stats['t_sweep']:.0f} s, routes {stats['t_compute']:.0f} s)")
    if stats["loops"]:
        print(f"From {origin}: WARNING - journeys that pass the same place twice (waiting would need more than "
              f"max_stay_nights?): {', '.join(sorted(stats['loops']))}")
    print(f"From {origin}: map draws {len(used_pairs)} connections ({len(drawn)} departures), "
          f"{len(other_pairs)} connections unused")
    print(f"From {origin}: {len(net.legs)} legs, {len(routes)} capitals reached, {len(unreached)} unreached, "
          f"{len(warnings)} warnings -> {outdir}/")
    if main_origin:
        for w in warnings:
            print("  !", w)
    return summary_of(net, warnings, cfg, today, dates, variants)


if __name__ == "__main__":
    main()
