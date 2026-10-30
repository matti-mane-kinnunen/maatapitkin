#!/usr/bin/env python3
"""Re-check every timed leg in data/legs.yaml against Transitous (https://transitous.org).

Transitous is a free, community-run European journey planner (MOTIS). For each leg it
asks for connections from the leg's start to its end around the stored departure time
on a chosen date, and reports whether the stored train still exists and how the times
compare. It never edits legs.yaml - you review the report and update the data by hand.

    python check_timetables.py                       # next Tuesday, all legs
    python check_timetables.py --date 2026-11-17     # a specific travel date
    python check_timetables.py --only Hamburg        # legs touching Hamburg
    python check_timetables.py --modes train,ferry   # ferries too (coverage varies)

Writes out/check_report.md. Please keep the request rate low; Transitous is volunteer-run.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))
from journeys import fmt_clock, load, norm_service  # noqa: E402

API = "https://api.transitous.org"
UA = "maatapitkin-timetable-check/0.1 (https://github.com/manethemean)"
TZ = {"FI": "Europe/Helsinki", "EE": "Europe/Tallinn", "LV": "Europe/Riga", "LT": "Europe/Vilnius",
      "PL": "Europe/Warsaw", "RO": "Europe/Bucharest", "MD": "Europe/Chisinau", "BG": "Europe/Sofia",
      "GR": "Europe/Athens", "TR": "Europe/Istanbul", "GB": "Europe/London", "IE": "Europe/Dublin",
      "PT": "Europe/Lisbon"}                       # everything else: Central European Time


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


def transit_legs(it: dict) -> list[dict]:
    return [l for l in it.get("legs", []) if l.get("mode") not in ("WALK", "BIKE", "CAR")]


def label(l: dict) -> str:
    return " ".join(str(l[k]) for k in ("displayName", "routeShortName", "tripShortName") if l.get(k)) or l.get("mode", "?")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="travel date YYYY-MM-DD (default: next Tuesday)")
    ap.add_argument("--only", help="only legs whose start or end contains this text")
    ap.add_argument("--modes", default="train", help="comma list of leg modes to check")
    ap.add_argument("--window", type=int, default=90, help="minutes before the stored departure to search from")
    ap.add_argument("--pause", type=float, default=1.5, help="seconds between requests")
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
        tz = tz_of(a)
        stored = dt.datetime.combine(date, dt.time(leg.dep // 60, leg.dep % 60), tz)
        params = {"fromPlace": f"{a['lat']},{a['lon']}", "toPlace": f"{b['lat']},{b['lon']}",
                  "time": (stored - dt.timedelta(minutes=args.window)).isoformat(),
                  "arriveBy": "false", "numItineraries": 6}
        print(f"[{n}/{len(legs)}] {leg.frm} -> {leg.to} {fmt_clock(leg.dep)} {leg.service}", flush=True)
        try:
            res = plan(params)
        except Exception as e:                                   # network, HTTP, JSON
            rows.append((leg, "error", str(e)[:120], "", ""))
            time.sleep(args.pause)
            continue
        its = res.get("itineraries", [])
        if not its:
            rows.append((leg, "no result", "Transitous found no connection (missing feed?)", "", ""))
        else:
            want = norm_service(leg.service)
            def score(it):
                tl = transit_legs(it) or it.get("legs", [])
                dep = parse_t(tl[0]["startTime"]).astimezone(tz)
                same = any(want and want in norm_service(label(x)) for x in tl)
                return (not same, abs((dep - stored).total_seconds()))
            best = min(its, key=score)
            tl = transit_legs(best) or best.get("legs", [])
            dep = parse_t(tl[0]["startTime"]).astimezone(tz)
            arr = parse_t(tl[-1]["endTime"]).astimezone(tz_of(b))
            found = " + ".join(label(x) for x in tl)
            stored_dur = leg.duration
            dur = int((arr - dep).total_seconds() // 60)
            same_train = not score(best)[0]
            shift = int((dep - stored).total_seconds() // 60)
            if same_train and abs(shift) <= 5 and abs(dur - stored_dur) <= 10:
                status = "ok"
            elif same_train:
                status = "times changed"
            else:
                status = "different service"
            delta = f"dep {shift:+d} min, duration {dur - stored_dur:+d} min"
            rows.append((leg, status, found, f"{dep:%H:%M}–{arr:%H:%M}", delta))
        time.sleep(args.pause)

    out = ROOT / "out" / "check_report.md"
    out.parent.mkdir(exist_ok=True)
    lines = [f"# Timetable check against Transitous — travel date {date}", "",
             f"Checked {dt.datetime.now():%Y-%m-%d %H:%M}. `ok` = same service, times within 5/10 min.", "",
             "| Leg | Stored | Status | Transitous | Times | Difference |", "|---|---|---|---|---|---|"]
    order = {"error": 0, "no result": 1, "different service": 2, "times changed": 3, "ok": 4}
    for leg, status, found, times, delta in sorted(rows, key=lambda r: order.get(r[1], 9)):
        lines.append(f"| {leg.frm} → {leg.to} | {fmt_clock(leg.dep)}–{fmt_clock(leg.arr)} {leg.service} | "
                     f"**{status}** | {found} | {times} | {delta} |")
    out.write_text("\n".join(lines) + "\n")
    counts = {s: sum(1 for r in rows if r[1] == s) for s in order}
    print("\n" + ", ".join(f"{v} {k}" for k, v in counts.items() if v), "->", out)


if __name__ == "__main__":
    main()
