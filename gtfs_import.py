#!/usr/bin/env python3
"""Turn Amtrak's and Flix/Greyhound's GTFS feeds into data/us/legs.yaml (IDEA-25, D-67).

    python3 gtfs_import.py                       # both feeds -> data/us/legs.yaml, print a report
    python3 gtfs_import.py --dry-run             # report only, write nothing
    python3 gtfs_import.py --start 2026-12-01 --days 120
    python3 gtfs_import.py --all-bus-legs        # no Flix/Greyhound leg marked `alternative`

Which stops belong to which place is set in data/us/places.yaml: `amtrak: [codes]` (Amtrak
stop_id = station code) and `flix: [stop ids]`. Every trip gives a leg between every pair of
places it calls at, in order - so a through train stays one train (as routes_to_pairs.py --all).
A stop where the trip only sets down (pickup_type 1) is not a departure, one where it only picks
up (drop_off_type 1) is not an arrival.

Times. GTFS clock times count from the service day in the *agency's* time zone: Amtrak gives
every agency America/New_York (so its Chicago times are an hour ahead of the timetable), Flix
gives UTC. Each time is turned into a moment and then into the clock time at the stop, as
legs.yaml wants: dep local at `from`, arr local at `to`, `days: N` when the arrival is more
than a day later by the clock (D-63). Which zone gives the clock time is set per feed:
- Amtrak: the feed's own stop_timezone. Amtrak gives Arizona stops America/Denver and builds its
  Eastern times from the Arizona clock times as if Arizona kept summer time, so reading them back
  through America/Denver gives the Arizona clock (Sunset Limited at Maricopa: 07:35 in winter,
  06:35 from 14.3.2027, an hour earlier as its Los Angeles time stays the same).
- Flix: the place's `tz:` (Flix's stop_timezone has mistakes, e.g. Vancouver BC = America/Phoenix).

Days. calendar.txt and calendar_dates.txt are read for the window --start .. --start+--days
(default: today, 120 days). The dates a leg leaves on (local) become `runs` + `valid_from` /
`valid_to`; a missing date (a holiday) splits the period, a date on an odd weekday becomes an
entry of its own. Entries that differ only in their times are merged into `times: [...]`.

Buses. Amtrak Thruway buses are always kept. Flix/Greyhound legs *to* a place no train serves
(the bus-only capitals, D-67) are ordinary legs. Those to a place trains serve too are marked
`alternative: true`: the maps leave them out - otherwise a bus-only capital becomes a bus hub and
Chicago -> Washington goes by Greyhound via Columbus - and the page uses them only when the
visitor asks for faster buses (D-68). --all-bus-legs makes them all ordinary legs.
Commuter rail in Amtrak's feed (MARC, Shore Line East) is left out.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).parent
FEEDS_DIR = ROOT / "amtrak_source_data_for_git_to_ignore"
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY = dt.timedelta(days=1)

FEEDS = [
    {"name": "amtrak", "path": FEEDS_DIR / "GTFS", "key": "amtrak", "clock_tz": "stop",
     "skip_agencies": {"1230", "1238"},          # Shore Line East, MARC (commuter rail)
     "skip_routes": set()},
    {"name": "flix", "path": FEEDS_DIR / "gtfs_generic_us", "key": "flix", "clock_tz": "place",
     "skip_agencies": set(), "skip_routes": set()},
    # VIA Rail Canada (Open Government Licence - Canada): times in Toronto time, the agency's zone, as GTFS says
    # (checked against The Canadian's timetable at Sioux Lookout, Winnipeg, Edmonton). AC is the Montreal airport
    # shuttle bus. Toronto - New York (the Maple Leaf) is in Amtrak's feed too, but there Amtrak sells no ride into
    # Toronto (pickup/drop-off 1), so it comes from VIA - only legs with a Canadian end, the US part is Amtrak's.
    {"name": "via", "path": FEEDS_DIR / "viarail", "key": "via", "clock_tz": "place",
     "skip_agencies": set(), "skip_routes": {"AC"}, "needs_country": "CA"},
]


# --- reading a feed --------------------------------------------------------
class Feed:
    """A GTFS feed in a folder or a .zip; rows as dicts."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.zip = zipfile.ZipFile(self.path) if self.path.suffix == ".zip" else None

    def has(self, name: str) -> bool:
        if self.zip:
            return name in self.zip.namelist()
        return (self.path / name).exists()

    def rows(self, name: str):
        if not self.has(name):
            return []
        if self.zip:
            f = io.TextIOWrapper(self.zip.open(name), encoding="utf-8-sig")
        else:
            f = open(self.path / name, encoding="utf-8-sig", newline="")
        with f:
            yield from csv.DictReader(f)


def gtfs_date(s: str) -> dt.date:
    return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def service_dates(feed: Feed, first: dt.date, last: dt.date) -> dict[str, set[dt.date]]:
    """service_id -> the dates (in the window) it runs, from calendar.txt and calendar_dates.txt."""
    out: dict[str, set[dt.date]] = defaultdict(set)
    for r in feed.rows("calendar.txt"):
        a, b = max(gtfs_date(r["start_date"]), first), min(gtfs_date(r["end_date"]), last)
        days = {i for i, w in enumerate(["monday", "tuesday", "wednesday", "thursday", "friday",
                                         "saturday", "sunday"]) if r[w] == "1"}
        d = a
        while d <= b:
            if d.weekday() in days:
                out[r["service_id"]].add(d)
            d += DAY
    for r in feed.rows("calendar_dates.txt"):
        d = gtfs_date(r["date"])
        if not first <= d <= last:
            continue
        if r["exception_type"] == "1":
            out[r["service_id"]].add(d)
        elif r["exception_type"] == "2":
            out[r["service_id"]].discard(d)
    return out


def gtfs_secs(t: str) -> int:
    h, m, s = (int(x) for x in t.strip().split(":"))
    return h * 3600 + m * 60 + s


def moment(day: dt.date, secs: int, agency_tz: ZoneInfo) -> dt.datetime:
    """A GTFS time on a service day: counted from 'noon minus 12 h' in the agency's zone (so
    a DST change day comes out right), returned as an aware datetime."""
    noon = dt.datetime.combine(day, dt.time(12), agency_tz)
    return (noon - dt.timedelta(hours=12) + dt.timedelta(seconds=secs)).astimezone(dt.timezone.utc)


# --- dates -> runs / valid_from / valid_to ------------------------------------
def fmt_runs(days: set[int]) -> str | None:
    """{0..4} -> 'mon-fri', {5, 6} -> 'sat,sun', all -> None (daily)."""
    if len(days) == 7:
        return None
    parts, run = [], []
    for d in range(7):
        if d in days:
            run.append(d)
        if run and (d not in days or d == 6):
            parts.append(WEEKDAYS[run[0]] if len(run) == 1 else
                         f"{WEEKDAYS[run[0]]},{WEEKDAYS[run[1]]}" if len(run) == 2 else
                         f"{WEEKDAYS[run[0]]}-{WEEKDAYS[run[-1]]}")
            run = []
    return ",".join(parts)


def compress(dates: set[dt.date]) -> list[tuple[str | None, dt.date, dt.date]]:
    """Dates a leg runs on -> [(runs, valid_from, valid_to)]. The weekdays are those the leg
    runs on at least half the time in its period; a missing date of such a weekday splits the
    period; a date on another weekday becomes a one-day entry."""
    if not dates:
        return []
    ds = sorted(dates)
    lo, hi = ds[0], ds[-1]
    possible, seen = [0] * 7, [0] * 7
    d = lo
    while d <= hi:
        possible[d.weekday()] += 1
        d += DAY
    for d in ds:
        seen[d.weekday()] += 1
    wd = {i for i in range(7) if seen[i] and seen[i] * 2 >= possible[i]}
    out, start, prev = [], None, None
    d = lo
    while d <= hi:
        if d.weekday() in wd:
            if d in dates:
                start = start or d
                prev = d
            elif start:
                out.append((fmt_runs(wd), start, prev))
                start = None
        d += DAY
    if start:
        out.append((fmt_runs(wd), start, prev))
    for d in ds:
        if d.weekday() not in wd:
            out.append((WEEKDAYS[d.weekday()], d, d))
    # a period shorter than a week only runs on the weekdays it actually has; and where the
    # period runs on every day it covers, `runs` says nothing more (one Saturday: no `runs`)
    fixed = []
    for runs, a, b in out:
        days = {(a + dt.timedelta(days=i)).weekday() for i in range((b - a).days + 1)}
        if (b - a).days < 6:
            runs = fmt_runs({x.weekday() for x in ds if a <= x <= b})
        rule = set(range(7)) if runs is None else {WEEKDAYS.index(w) for w in _expand(runs)}
        fixed.append((None if days <= rule else runs, a, b))
    return fixed


def _expand(runs: str) -> list[str]:
    out = []
    for part in runs.split(","):
        if "-" in part:
            i, j = (WEEKDAYS.index(x) for x in part.split("-"))
            out += WEEKDAYS[i:j + 1]
        else:
            out.append(part)
    return out


# --- the import ----------------------------------------------------------------
def stop_map(places: dict, key: str) -> dict[str, str]:
    out = {}
    for name, v in places.items():
        for sid in v.get(key) or []:
            if str(sid) in out:
                raise SystemExit(f"{key} stop {sid} is in both {out[str(sid)]} and {name}")
            out[str(sid)] = name
    return out


def service_name(feed: str, route: dict, trip: dict) -> str:
    if feed == "amtrak":
        name = route.get("route_long_name") or route.get("route_short_name") or "Amtrak"
        if name == "Amtrak Thruway Connecting Service":
            name = "Amtrak Thruway"
        num = (trip.get("trip_short_name") or "").strip()
        return f"{name} {num}".strip()
    if feed == "via":
        num = (trip.get("trip_short_name") or "").strip()
        named = {"1": "The Canadian", "2": "The Canadian", "14": "Ocean", "15": "Ocean"}.get(num)
        return f"VIA {num}" + (f" {named}" if named else "")
    return route.get("route_short_name") or route.get("route_long_name") or feed


def import_feed(cfg: dict, places: dict, first: dt.date, last: dt.date, report: dict):
    """Yield (from, to, service, mode, feed, dep_local, arr_local) for every leg departure."""
    feed = Feed(cfg["path"])
    stops = stop_map(places, cfg["key"])
    tz_place = {p: ZoneInfo(v["tz"]) for p, v in places.items()}
    stop_tz = {}                       # stop_id -> zone that gives the clock time there
    for s in feed.rows("stops.txt"):
        if s["stop_id"] in stops:
            own = s.get("stop_timezone") if cfg.get("clock_tz") == "stop" else None
            stop_tz[s["stop_id"]] = ZoneInfo(own) if own else tz_place[stops[s["stop_id"]]]
    agencies = {a.get("agency_id", ""): ZoneInfo(a["agency_timezone"]) for a in feed.rows("agency.txt")}
    default_tz = next(iter(agencies.values()))
    routes = {r["route_id"]: r for r in feed.rows("routes.txt")
              if r.get("agency_id", "") not in cfg["skip_agencies"] and r["route_id"] not in cfg["skip_routes"]}
    trips = {t["trip_id"]: t for t in feed.rows("trips.txt") if t["route_id"] in routes}
    sdates = service_dates(feed, first, last)
    calls: dict[str, list] = defaultdict(list)
    seen_stops = set()
    for st in feed.rows("stop_times.txt"):
        if st["trip_id"] in trips and st["stop_id"] in stops:
            seen_stops.add(st["stop_id"])
            calls[st["trip_id"]].append(st)
    report[cfg["name"]] = r = {"trips": len(trips), "trips_with_2_places": 0, "no_dates": 0,
                               "unused_stops": sorted(f"{stops[s]} {s}" for s in set(stops) - seen_stops),
                               "clock_backwards": []}
    for tid, sts in calls.items():
        sts.sort(key=lambda s: int(s["stop_sequence"]))
        if len({stops[s["stop_id"]] for s in sts}) < 2:
            continue
        r["trips_with_2_places"] += 1
        trip = trips[tid]
        route = routes[trip["route_id"]]
        dates = sdates.get(trip["service_id"])
        if not dates:
            r["no_dates"] += 1
            continue
        atz = agencies.get(route.get("agency_id", ""), default_tz)
        mode = "train" if route["route_type"] == "2" else "bus"
        service = service_name(cfg["name"], route, trip)
        # one leg per pair of places; where a place has two stops on the trip (Boston Back Bay
        # and South Station, Santa Fe's two bus stops) take the shortest ride between them
        best: dict[tuple[str, str], tuple] = {}
        for i, a in enumerate(sts):
            if a.get("pickup_type") == "1":
                continue
            pa = stops[a["stop_id"]]
            for b in sts[i + 1:]:
                pb = stops[b["stop_id"]]
                if pb == pa or b.get("drop_off_type") == "1":
                    continue
                need = cfg.get("needs_country")
                if need and need not in (places[pa].get("country"), places[pb].get("country")):
                    continue
                dep_s, arr_s = gtfs_secs(a["departure_time"]), gtfs_secs(b["arrival_time"])
                cand = (arr_s - dep_s, arr_s, a["stop_id"], b["stop_id"], dep_s)
                if (pa, pb) not in best or cand < best[(pa, pb)]:
                    best[(pa, pb)] = cand
        geom = report.setdefault("geom", {})
        for (pa, pb), (_, arr_s, sa, sb, dep_s) in best.items():
            if trip.get("shape_id"):                     # candidate tracks; trains first (see map_layers)
                cand = geom.setdefault((pa, pb), [])
                if len(cand) < 6 and all(c[1] != trip["shape_id"] for c in cand):
                    cand.append((cfg["name"], trip["shape_id"], sa, sb, mode))
            for day in dates:
                dep = moment(day, dep_s, atz).astimezone(stop_tz[sa])
                arr = moment(day, arr_s, atz).astimezone(stop_tz[sb])
                yield pa, pb, service, mode, cfg["name"], dep, arr


def build_legs(places: dict, first: dt.date, last: dt.date, all_bus: bool, feeds=FEEDS):
    report: dict = {}
    # (from, to, service, mode, feed, dep "HH:MM", arr "HH:MM", days) -> local departure dates
    groups: dict[tuple, set[dt.date]] = defaultdict(set)
    backwards = defaultdict(int)
    for cfg in feeds:
        if not Feed(cfg["path"]).has("stop_times.txt"):
            report[cfg["name"]] = {"missing": str(cfg["path"])}
            continue
        for pa, pb, service, mode, name, dep, arr in import_feed(cfg, places, first, last, report):
            # by the local clock: how many minutes from departure to arrival
            clock = (arr.replace(tzinfo=None) - dep.replace(tzinfo=None)).total_seconds() // 60
            if clock < 0:            # a short hop westwards across a zone: legs.yaml cannot say it
                backwards[(pa, pb, service)] += 1
                continue
            key = (pa, pb, service, mode, name, dep.strftime("%H:%M"), arr.strftime("%H:%M"), int(clock // 1440))
            groups[key].add(dep.date())
    # the same departure under two names (Sunset Limited 2 carries the Texas Eagle 422 through
    # cars): one leg, both names
    same: dict[tuple, list[tuple]] = defaultdict(list)
    for k, dates in groups.items():
        same[(k[0], k[1], k[3], k[4], k[5], k[6], k[7], frozenset(dates))].append(k)
    for ks in same.values():
        if len(ks) > 1:
            ks.sort(key=lambda k: k[2])
            dates = groups.pop(ks[0])
            for k in ks[1:]:
                groups.pop(k)
            k0 = ks[0]
            groups[(k0[0], k0[1], " / ".join(k[2] for k in ks), *k0[3:])] = dates
    for k, n in backwards.items():
        report.setdefault("clock_backwards", []).append(f"{k[0]} -> {k[1]} ({k[2]}): {n} departures")
    train_places = {k[0] for k in groups if k[3] == "train"} | {k[1] for k in groups if k[3] == "train"}
    entries: dict[tuple, list[tuple[str, str]]] = defaultdict(list)
    alt_bus = 0
    for (pa, pb, service, mode, name, dep, arr, days), dates in groups.items():
        # a bus to a place trains also serve: kept, but marked `alternative` - the maps leave it out
        # unless the visitor asks for faster buses (D-68; before that these were dropped)
        alt = name == "flix" and not all_bus and pb in train_places
        alt_bus += alt
        for runs, a, b in compress(dates):
            entries[(pa, pb, service, mode, days, runs, a, b, alt)].append((dep, arr))
    report["bus_legs_alternative"] = alt_bus
    report["train_places"] = sorted(train_places)
    return entries, report


# --- writing legs.yaml ------------------------------------------------------------
def q(v) -> str:
    if isinstance(v, (int, bool)) and not isinstance(v, bool):
        return str(v)
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, dt.date):
        return v.isoformat()
    s = str(v)
    plain = s.replace(" ", "").replace(".", "").replace("-", "").isalnum() and not s[:1].isdigit()
    return s if plain and s.lower() not in ("yes", "no", "on", "off", "true", "false", "null") else json.dumps(s, ensure_ascii=False)


def to_yaml(entries: dict, origin: str, header: str) -> str:
    def order(k):
        return (k[0] != origin, k[0], k[1], k[3], min(t[0] for t in entries[k]), k[2], k[6])
    lines = [header, "legs:"]
    last_from = None
    for k in sorted(entries, key=order):
        pa, pb, service, mode, days, runs, a, b, alt = k
        if pa != last_from:
            lines.append(f"\n  # --- from {pa} ---")
            last_from = pa
        times = sorted(set(entries[k]))
        f = [f"from: {q(pa)}", f"to: {q(pb)}"]
        if len(times) == 1:
            f += [f'dep: "{times[0][0]}"', f'arr: "{times[0][1]}"']
        else:
            f.append("times: [" + ", ".join(f'"{d}-{a_}"' for d, a_ in times) + "]")
        if days:
            f.append(f"days: {days}")
        f += [f"service: {q(service)}", f"mode: {mode}"]
        if runs:
            f.append(f"runs: {q(runs)}")
        f += [f"valid_from: {a.isoformat()}", f"valid_to: {b.isoformat()}"]
        if alt:
            f.append("alternative: true")
        lines.append("  - {" + ", ".join(f) + "}")
    return "\n".join(lines) + "\n"


# --- the map's rail-map layers (IDEA-25 prototype): track shapes, the network, the stations ----
def simplify(pts: list, tol: float) -> list:
    """Douglas-Peucker on [lon, lat] points (tolerance in degrees), iterative."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        (x1, y1), (x2, y2) = pts[i], pts[j]
        dx, dy = x2 - x1, y2 - y1
        n2 = dx * dx + dy * dy
        best, bk = -1.0, -1
        for k in range(i + 1, j):
            x, y = pts[k]
            if n2 == 0:
                d = (x - x1) ** 2 + (y - y1) ** 2
            else:
                t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / n2))
                d = (x - x1 - t * dx) ** 2 + (y - y1 - t * dy) ** 2
            if d > best:
                best, bk = d, k
        if bk > 0 and best > tol * tol:
            keep[bk] = True
            stack += [(i, bk), (bk, j)]
    return [p for p, k in zip(pts, keep) if k]


def read_shapes(feed: Feed, wanted: set | None = None) -> dict[str, list]:
    pts: dict[str, list] = defaultdict(list)
    for r in feed.rows("shapes.txt"):
        if wanted is None or r["shape_id"] in wanted:
            pts[r["shape_id"]].append((int(r["shape_pt_sequence"]), float(r["shape_pt_lon"]), float(r["shape_pt_lat"])))
    return {k: [[x, y] for _, x, y in sorted(v)] for k, v in pts.items()}


def cut(shape: list, a: tuple, b: tuple, max_off: float = 0.15) -> list:
    """The part of a shape between the points nearest to stop a and (after it) stop b; nothing if
    the shape does not pass within max_off degrees (~15 km) of both - some Flix shapes cover only
    part of the trip, and a straight jump to them looks worse than the plain arc."""
    if not shape:
        return []
    d2 = lambda i, p: (shape[i][0] - p[0]) ** 2 + (shape[i][1] - p[1]) ** 2
    i = min(range(len(shape)), key=lambda k: d2(k, a))
    j = min(range(i, len(shape)), key=lambda k: d2(k, b))
    if j <= i or d2(i, a) > max_off ** 2 or d2(j, b) > max_off ** 2:
        return []
    return shape[i:j + 1]


def r3(pts: list) -> list:
    return [[round(x, 3), round(y, 3)] for x, y in pts]


ABBR = {"Alabama": "AL", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO", "Connecticut": "CT",
        "Delaware": "DE", "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Idaho": "ID", "Illinois": "IL",
        "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
        "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
        "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
        "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
        "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
        "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
        "British Columbia": "BC", "Ontario": "ON", "Québec": "QC", "Manitoba": "MB", "Alberta": "AB", "Saskatchewan": "SK",
        "New Brunswick": "NB", "Nova Scotia": "NS", "Prince Edward Island": "PE", "Newfoundland and Labrador": "NL"}


# stations right on a state line, where the simplified outlines give the wrong side (Amtrak stop_id -> state)
STATE_FIX = {"VAN": "WA"}      # Vancouver, Washington, across the Columbia from Portland


def state_finder(basemap: Path):
    """lon, lat -> 'IL' etc. from the outlines in basemap.geojson (ray casting; None outside)."""
    polys = []
    if basemap.exists():
        for f in json.loads(basemap.read_text())["features"]:
            ab = ABBR.get(f["properties"].get("name"))
            g = f["geometry"]
            for poly in ([g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]):
                xs = [p[0] for p in poly[0]]; ys = [p[1] for p in poly[0]]
                polys.append((ab, (min(xs), min(ys), max(xs), max(ys)), poly))
    def inside(x, y, ring):
        c = False
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                c = not c
        return c
    def find(lon, lat):
        best = None
        for ab, (a, b, c, d), poly in polys:
            if a <= lon <= c and b <= lat <= d and inside(lon, lat, poly[0]) and not any(inside(lon, lat, h) for h in poly[1:]):
                return ab
        # on the coast, just outside the simplified outline: the nearest outline point's state
        for ab, (a, b, c, d), poly in polys:
            for x, y in poly[0]:
                dd = (x - lon) ** 2 + (y - lat) ** 2
                if dd < 0.25 and (best is None or dd < best[0]):
                    best = (dd, ab)
        return best[1] if best else None
    return find


def map_layers(places: dict, report: dict, feeds=FEEDS, tol: float = 0.01, basemap: Path | None = None) -> dict:
    """{geom: {"A>B": [[lon, lat], ...]}, rail: [polyline, ...], stations: [[name, lon, lat, rank], ...]}
    - geom: the track (or road) of each connection, cut from the shape of a trip that makes it
    - rail: every Amtrak train route, once - shapes snapped to a 0.01 degree grid so shared track
      is drawn one time, then joined back into lines
    - stations: Amtrak train stations that are not places, with the number of trips calling (labels
      go to the busiest first)"""
    by_feed = {c["name"]: c for c in feeds}
    out: dict = {"geom": {}, "rail": [], "stations": []}
    stops_xy = {}
    for name, c in by_feed.items():
        f = Feed(c["path"])
        for s in f.rows("stops.txt"):
            stops_xy[(name, s["stop_id"])] = (float(s["stop_lon"]), float(s["stop_lat"]))
    want = defaultdict(set)
    for cands in report.get("geom", {}).values():
        for fname, sid, *_ in cands:
            want[fname].add(sid)
    shapes = {fname: read_shapes(Feed(by_feed[fname]["path"]), ids) for fname, ids in want.items()}
    for (pa, pb), cands in report.get("geom", {}).items():
        for fname, sid, sa, sb, mode in sorted(cands, key=lambda c: c[4] != "train"):   # a train's track first
            part = cut(shapes[fname].get(sid, []), stops_xy[(fname, sa)], stops_xy[(fname, sb)])
            if len(part) >= 2:
                out["geom"][f"{pa}>{pb}"] = r3(simplify(part, tol))
                break
    # the whole train network (Amtrak, VIA Rail) and its stations, from every feed that has trains
    grid = lambda p: (round(p[0] * 100), round(p[1] * 100))
    edges: set = set()
    calls = defaultdict(int)
    stn_rows = []
    for fname in ("amtrak", "via"):
        if fname not in by_feed or not Feed(by_feed[fname]["path"]).has("stop_times.txt"):
            continue
        cfg = by_feed[fname]
        fd = Feed(cfg["path"])
        routes = {r["route_id"]: r for r in fd.rows("routes.txt")
                  if r["route_type"] == "2" and r.get("agency_id", "") not in cfg["skip_agencies"]
                  and r["route_id"] not in cfg["skip_routes"]}
        trips = {t["trip_id"]: t for t in fd.rows("trips.txt") if t["route_id"] in routes}
        sids = {t["shape_id"] for t in trips.values() if t.get("shape_id")}
        for pts in read_shapes(fd, sids).values():
            g = [grid(p) for p in pts]
            g = [q for k, q in enumerate(g) if k == 0 or q != g[k - 1]]
            for u, v in zip(g, g[1:]):
                edges.add((u, v) if u < v else (v, u))
        taken = {str(c) for v in places.values() for c in v.get(cfg["key"]) or []}
        fcalls = defaultdict(int)
        for st in fd.rows("stop_times.txt"):
            if st["trip_id"] in trips:
                fcalls[st["stop_id"]] += 1
        for s in fd.rows("stops.txt"):
            if s["stop_id"] in fcalls and s["stop_id"] not in taken and "Border" not in s["stop_name"]:
                name = s["stop_name"]
                for suffix in (" Amtrak Station", " Amtrak Bus Stop", " Amtrak", " Union Station", " Station"):
                    if name.endswith(suffix):
                        name = name[: -len(suffix)]
                stn_rows.append([name.strip(), round(float(s["stop_lon"]), 3), round(float(s["stop_lat"]), 3),
                                 fcalls[s["stop_id"]], s["stop_id"] if fname == "amtrak" else f"{fname}:{s['stop_id']}"])
    adj = defaultdict(set)
    for u, v in edges:
        adj[u].add(v)
        adj[v].add(u)
    used = set()
    def walk(u, v):
        line = [u, v]
        used.add((u, v) if u < v else (v, u))
        while len(adj[v]) == 2:
            w = next(x for x in adj[v] if x != line[-2])
            e = (v, w) if v < w else (w, v)
            if e in used:
                break
            used.add(e)
            line.append(w)
            v = w
        return line
    for u in sorted(adj, key=lambda n: len(adj[n]) == 2):         # start at ends and junctions
        for v in sorted(adj[u]):
            if ((u, v) if u < v else (v, u)) not in used:
                line = walk(u, v)
                out["rail"].append(r3(simplify([[x / 100, y / 100] for x, y in line], tol)))
    out["stations"] = stn_rows
    # a station whose name is also a place's (Lincoln IL / Lincoln NE) or another station's (Springfield MA /
    # Springfield VA) gets its state: "Lincoln, IL"
    taken_names = {n.lower() for n, v in places.items()} | {a.lower() for v in places.values() for a in v.get("aliases") or []}
    count = defaultdict(int)
    for st in out["stations"]:
        count[st[0].lower()] += 1
    state = state_finder(basemap or ROOT / "data" / "us" / "basemap.geojson")
    fix = STATE_FIX
    for st in out["stations"]:
        if st[0].lower() in taken_names or count[st[0].lower()] > 1:
            ab = fix.get(st[4]) or state(st[1], st[2])
            if ab:
                st[0] = f"{st[0]}, {ab}"
    out["stations"] = [st[:4] for st in sorted(out["stations"], key=lambda x: -x[3])]
    return out


def feed_version(path: Path) -> str:
    f = Feed(path)
    for r in f.rows("feed_info.txt"):
        return r.get("feed_version") or f"{r.get('feed_start_date', '')}-{r.get('feed_end_date', '')}"
    return "?"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(ROOT / "data" / "us"), help="network folder (places.yaml; legs.yaml is written here)")
    ap.add_argument("--start", default=dt.date.today().isoformat(), help="first travel date (default today)")
    ap.add_argument("--days", type=int, default=120, help="how many days of timetable to import (default 120)")
    ap.add_argument("--all-bus-legs", action="store_true", help="Flix/Greyhound legs to places that have trains too as ordinary legs, not `alternative`")
    ap.add_argument("--dry-run", action="store_true", help="print the report, write nothing")
    args = ap.parse_args(argv)

    data = Path(args.data)
    pl = yaml.safe_load((data / "places.yaml").read_text())
    places = pl["places"]
    first = dt.date.fromisoformat(args.start)
    last = first + dt.timedelta(days=args.days - 1)
    entries, report = build_legs(places, first, last, args.all_bus_legs)

    origin = (pl.get("settings") or {}).get("origin", "")
    versions = ", ".join(f"{c['name']} {feed_version(c['path'])}" for c in FEEDS if Feed(c["path"]).has("feed_info.txt"))
    header = (f"# GENERATED by gtfs_import.py on {dt.date.today().isoformat()} - do not edit by hand, run it again.\n"
              f"# Feeds: {versions}. Timetable window {first} .. {last}.\n"
              f"# Format as data/legs.yaml; times are local at each end (tz: in places.yaml).\n"
              f"window: {{from: {first}, to: {last}}}   # the imported days; the page's 'valid until' (build.py)\n"
              f"defaults:\n  checked: {dt.date.today().isoformat()}\n  source: gtfs\n")
    text = to_yaml(entries, origin, header)

    n_dep = sum(len(set(v)) for v in entries.values())
    print(f"window {first} .. {last}: {len(entries)} legs.yaml entries, {n_dep} departures")
    for name in ("amtrak", "flix", "via"):
        r = report.get(name, {})
        if "missing" in r:
            print(f"  {name}: feed not found at {r['missing']}")
            continue
        print(f"  {name}: {r.get('trips', 0)} trips, {r.get('trips_with_2_places', 0)} call at 2+ places, "
              f"{r.get('no_dates', 0)} of them do not run in the window")
        if r.get("unused_stops"):
            print(f"    stops in places.yaml no trip calls at: {', '.join(r['unused_stops'])}")
    print(f"  Flix/Greyhound legs to places with trains, marked alternative: {report['bus_legs_alternative']}")
    for line in report.get("clock_backwards", []):
        print(f"  left out (arrives earlier by the clock than it leaves): {line}")
    reached = {k[1] for k in entries} | {k[0] for k in entries}
    missing = [p for p, v in places.items() if v.get("capital") and p not in reached]
    print(f"  capitals with no leg: {', '.join(missing) or 'none'}")
    layers = map_layers(places, report, basemap=data / "basemap.geojson")
    print(f"  map layers: {len(layers['geom'])} connections with a track, {len(layers['rail'])} rail lines "
          f"({sum(len(l) for l in layers['rail'])} points), {len(layers['stations'])} other stations")
    if not args.dry_run:
        (data / "map_layers.json").write_text(json.dumps(layers, separators=(",", ":")) + "\n")
        (data / "legs.yaml").write_text(text)
        print(f"wrote {data / 'legs.yaml'} ({len(text.splitlines())} lines)")


if __name__ == "__main__":
    main()
