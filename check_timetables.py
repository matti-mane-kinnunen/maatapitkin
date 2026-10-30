#!/usr/bin/env python3
"""Re-check every timed leg in data/legs.yaml against Transitous (https://transitous.org).

Transitous is a free, community-run European journey planner (MOTIS). For each leg it
asks for connections from the leg's start to its end around the stored departure time
on a chosen date, finds your train in the answer by its number, and compares the
local departure and arrival times. It never edits legs.yaml - you review the report.

    python3 check_timetables.py                       # next Tuesday, all legs
    python3 check_timetables.py --date 2026-11-17     # a specific travel date
    python3 check_timetables.py --only Hamburg        # legs touching Hamburg
    python3 check_timetables.py --modes train,ferry   # ferries too (coverage varies)
    python3 check_timetables.py --debug               # print the raw legs Transitous returns

Writes out/check_report.md. Please keep the request rate low; Transitous is volunteer-run.
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
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))
from journeys import fmt_clock, load  # noqa: E402

API = "https://api.transitous.org"
UA = "maatapitkin-timetable-check/0.2 (https://github.com/matti-mane-kinnunen/maatapitkin)"
TZ = {"FI": "Europe/Helsinki", "EE": "Europe/Tallinn", "LV": "Europe/Riga", "LT": "Europe/Vilnius",
      "PL": "Europe/Warsaw", "RO": "Europe/Bucharest", "MD": "Europe/Chisinau", "BG": "Europe/Sofia",
      "GR": "Europe/Athens", "TR": "Europe/Istanbul", "GB": "Europe/London", "IE": "Europe/Dublin",
      "PT": "Europe/Lisbon"}                       # everything else: Central European Time
# City transport at either end of an answer (metro to the station etc.) is trimmed off.
URBAN = {"WALK", "BIKE", "CAR", "SUBWAY", "METRO", "TRAM", "SUBURBAN", "BUS", "CABLE_CAR",
         "FUNICULAR", "AERIAL_LIFT", "ODM", "FLEX", "RENTAL"}
NO_GO = {"AIRPLANE", "AIR", "FLIGHT"}


def tz_of(place: dict) -> ZoneInfo:
    return ZoneInfo(TZ.get(place.get("country"), "Europe/Berlin"))


def get(path: str, params: dict) -> dict:
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


_plan_path = None


def plan(params: dict) -> dict:
    """Call the MOTIS plan endpoint, discovering which API version the server speaks."""
    global _plan_path
    candidates = [_plan_path] if _plan_path else [f"/api/v{v}/plan" for v in (5, 4, 3, 2, 1)]
    last = None
    for path in candidates:
        try:
            res = get(path, params)
            _plan_path = path
            return res
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (404, 410):
                continue
            raise
    raise last


def parse_t(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def label(l: dict) -> str:
    parts = []
    for k in ("displayName", "routeShortName", "tripShortName"):
        v = str(l.get(k) or "").strip()
        if v and v not in parts and not any(v in p for p in parts):
            parts.append(v)
    return " ".join(parts) or l.get("mode", "?")


def numbers(text: str) -> set[str]:
    """Train numbers in a service name: digit groups of 3+ digits, leading zeros dropped.
    'EN 000345' -> {'345'}, 'ICE 228 + RE1' -> {'228'}, '20N 060471' -> {'60471'}."""
    return {d.lstrip("0") for d in re.findall(r"\d+", str(text)) if len(d.lstrip("0")) >= 3}


def same_number(a: str, b: str) -> bool:
    """NJ471 = 40471 = 060471: operators add prefixes, so compare as suffixes."""
    short, long_ = sorted((a, b), key=len)
    return long_.endswith(short) and len(short) >= 3


def core(legs: list[dict]) -> list[dict]:
    """Drop walking and city transport at both ends of the answer."""
    legs = [l for l in legs if l.get("mode") != "WALK"]
    while legs and legs[0].get("mode") in URBAN and len(legs) > 1:
        legs = legs[1:]
    while legs and legs[-1].get("mode") in URBAN and len(legs) > 1:
        legs = legs[:-1]
    return legs


def clock_diff(found: dt.datetime, stored_min: int) -> int:
    d = (found.hour * 60 + found.minute - stored_min) % 1440
    return d - 1440 if d > 720 else d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="travel date YYYY-MM-DD (default: next Tuesday)")
    ap.add_argument("--only", help="only legs whose start or end contains this text")
    ap.add_argument("--modes", default="train", help="comma list of leg modes to check")
    ap.add_argument("--window", type=int, default=45, help="minutes before the stored departure to search from")
    ap.add_argument("--pause", type=float, default=1.5, help="seconds between requests")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    net, _ = load(ROOT / "data")
    today = dt.date.today()
    date = dt.date.fromisoformat(args.date) if args.date else today + dt.timedelta(days=(1 - today.weekday()) % 7 or 7)
    modes = set(args.modes.split(","))
    legs = [l for l in net.legs if l.timed and l.mode in modes
            and (not args.only or args.only.lower() in (l.frm + l.to).lower())]

    rows = []
    for n, leg in enumerate(legs, 1):
        a, b = net.places[leg.frm], net.places[leg.to]
        tz_a, tz_b = tz_of(a), tz_of(b)
        stored = dt.datetime.combine(date, dt.time(leg.dep // 60, leg.dep % 60), tz_a)
        params = {"fromPlace": f"{a['lat']},{a['lon']}", "toPlace": f"{b['lat']},{b['lon']}",
                  "time": (stored - dt.timedelta(minutes=args.window)).isoformat(),
                  "arriveBy": "false", "numItineraries": 8}
        print(f"[{n}/{len(legs)}] {leg.frm} -> {leg.to} {fmt_clock(leg.dep)} {leg.service}", flush=True)
        try:
            res = plan(params)
        except Exception as e:                                   # network, HTTP, JSON
            rows.append((leg, "error", str(e)[:120], "", ""))
            time.sleep(args.pause)
            continue
        its = [it for it in res.get("itineraries", [])
               if not any(l.get("mode") in NO_GO for l in it.get("legs", []))]
        if args.debug:
            for it in its:
                print("   ", " | ".join(f"{l.get('mode')} {label(l)} {l['startTime'][11:16]}-{l['endTime'][11:16]}"
                                      for l in it.get("legs", [])))
        if not its:
            rows.append((leg, "no data", "Transitous has no connection here (timetable missing?)", "", ""))
            time.sleep(args.pause)
            continue

        want = numbers(leg.service)
        best = None                                  # (rank, itinerary core legs, matched?)
        for it in its:
            c = core(it.get("legs", []))
            if not c:
                continue
            matched = any(same_number(w, f) for x in c for w in want for f in numbers(label(x)))
            dep = parse_t(c[0]["startTime"]).astimezone(tz_a)
            arr = parse_t(c[-1]["endTime"]).astimezone(tz_b)
            off = abs(clock_diff(dep, leg.dep)) + abs(clock_diff(arr, leg.arr))
            rank = (not matched, len(c), off)
            if best is None or rank < best[0]:
                best = (rank, c, matched, dep, arr)
        _, c, matched, dep, arr = best
        dd, da = clock_diff(dep, leg.dep), clock_diff(arr, leg.arr)
        if matched and abs(dd) <= 5 and abs(da) <= 5:
            status = "ok"
        elif matched:
            status = "times changed"
        elif abs(dd) <= 10 and abs(da) <= 10 and len(c) == 1:
            status = "renumbered?"
        else:
            status = "not found"
        found = " + ".join(label(x) for x in c)
        rows.append((leg, status, found, f"{dep:%H:%M}–{arr:%H:%M}", f"dep {dd:+d}, arr {da:+d} min"))
        time.sleep(args.pause)

    out = ROOT / "out" / "check_report.md"
    out.parent.mkdir(exist_ok=True)
    order = ["error", "no data", "not found", "renumbered?", "times changed", "ok"]
    explain = {"ok": "your train, same times (±5 min)",
               "times changed": "your train (same number), different times",
               "renumbered?": "a direct train at your times but with another number",
               "not found": "your train is not in Transitous for this date; best alternative shown",
               "no data": "Transitous has no timetable for this connection - check by hand",
               "error": "the request failed"}
    lines = [f"# Timetable check against Transitous — travel date {date:%a %-d.%-m.%Y}", "",
             f"Checked {dt.datetime.now():%Y-%m-%d %H:%M}. Times are local at each end.", ""]
    lines += [f"- **{s}**: {sum(1 for r in rows if r[1] == s)} — {explain[s]}" for s in order
              if any(r[1] == s for r in rows)]
    lines += ["", "| Leg | Stored | Status | Transitous | Times | Difference |", "|---|---|---|---|---|---|"]
    for leg, status, found, times, delta in sorted(rows, key=lambda r: order.index(r[1])):
        lines.append(f"| {leg.frm} → {leg.to} | {fmt_clock(leg.dep)}–{fmt_clock(leg.arr)} {leg.service} | "
                     f"**{status}** | {found} | {times} | {delta} |")
    out.write_text("\n".join(lines) + "\n")
    print("\n" + ", ".join(f"{sum(1 for r in rows if r[1] == s)} {s}" for s in order
                           if any(r[1] == s for r in rows)), "->", out)


if __name__ == "__main__":
    main()
