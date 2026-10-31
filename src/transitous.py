"""Shared helpers for talking to Transitous (https://transitous.org, MOTIS API).

Used by check_timetables.py and add_leg.py. Transitous is volunteer-run: keep the
request rate low and identify yourself with the User-Agent below.
"""
from __future__ import annotations

import datetime as dt
import math
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

API = "https://api.transitous.org"
UA = "maatapitkin/0.3 (https://github.com/matti-mane-kinnunen/maatapitkin)"
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
    """Train numbers in a service name: digit groups of 2+ digits, leading zeros dropped.
    'EN 000345' -> {'345'}, 'ICE 228 + RE1' -> {'228'}, '20N 060471' -> {'60471'}, 'EC87' -> {'87'}."""
    return {d.lstrip("0") for d in re.findall(r"\d+", str(text)) if len(d.lstrip("0")) >= 2}


def same_number(a: str, b: str) -> bool:
    """Equal numbers match. Night trains get operator prefixes (NJ471 = 40471 = 060471),
    so a 3+ digit number may also match the end of a 5+ digit one - but 577 is not 1577."""
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 3 and len(long_) >= 5 and long_.endswith(short)


def core(legs: list[dict]) -> list[dict]:
    """Drop walking and city transport at both ends of the answer."""
    legs = [l for l in legs if l.get("mode") != "WALK"]
    while legs and legs[0].get("mode") in URBAN and len(legs) > 1:
        legs = legs[1:]
    while legs and legs[-1].get("mode") in URBAN and len(legs) > 1:
        legs = legs[:-1]
    return legs


def km_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (lat1, lon1, lat2, lon2))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def near_km(pa: dict, pb: dict) -> float:
    """How close to A and B a train must start and end: 40 % of the A-B distance, 8-25 km
    (Istanbul Halkalı is 22 km out; Malmö -> Copenhagen is only 28 km in all)."""
    return min(25.0, max(8.0, 0.4 * km_between(pa["lat"], pa["lon"], pb["lat"], pb["lon"])))


def stop_km(stop: dict, place: dict) -> float | None:
    """Distance from a leg's stop to a place, or None if the answer has no coordinates."""
    if not stop or stop.get("lat") is None or stop.get("lon") is None:
        return None
    return km_between(stop["lat"], stop["lon"], place["lat"], place["lon"])


def reaches(legs: list[dict], pa: dict, pb: dict, km: float | None = None) -> bool:
    """Do these legs really run from A to B? Trimming city transport (core) can leave e.g.
    an AVE Madrid -> Málaga from an answer that ends with a bus to Algeciras (D-33)."""
    if not legs:
        return False
    km = km if km is not None else near_km(pa, pb)
    d_a, d_b = stop_km(legs[0].get("from"), pa), stop_km(legs[-1].get("to"), pb)
    return (d_a is None or d_a <= km) and (d_b is None or d_b <= km)


def clock_diff(found: dt.datetime, stored_min: int) -> int:
    d = (found.hour * 60 + found.minute - stored_min) % 1440
    return d - 1440 if d > 720 else d




def geocode(text: str) -> list[dict]:
    """Stations and places matching `text`, best first."""
    last = None
    for v in (5, 4, 3, 2, 1):
        try:
            res = get(f"/api/v{v}/geocode", {"text": text})
            return res if isinstance(res, list) else res.get("matches", res.get("results", []))
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (404, 410):
                continue
            raise
    raise last


def fold(s: str) -> str:
    """Compare names without case or accents: 'Malmö' == 'malmo'."""
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).casefold().strip()


def day_itineraries(params: dict, day_start: dt.datetime, day_end: dt.datetime,
                    pause: float = 1.0, max_requests: int = 30, stop=None):
    """Yield itineraries departing between day_start and day_end, page by page.

    Uses the API's nextPageCursor when given, otherwise steps the search time forward.
    `stop(itinerary)` may return True to end the search early."""
    seen, t, cursor = set(), day_start, None
    for _ in range(max_requests):
        q = dict(params)
        if cursor:
            q["pageCursor"] = cursor
        else:
            q["time"] = t.isoformat()
        res = plan(q)
        its = res.get("itineraries", [])
        newest = None
        for it in its:
            if any(l.get("mode") in NO_GO for l in it.get("legs", [])):
                continue
            c = core(it.get("legs", []))
            if not c:
                continue
            start = parse_t(c[0]["startTime"])
            key = (start, tuple(label(x) for x in c))
            newest = start if newest is None or start > newest else newest
            if key in seen or start > day_end:
                continue
            seen.add(key)
            yield it
            if stop and stop(it):
                return
        if newest is None:                     # nothing in this window: look later in the day
            cursor = None
            t = t + dt.timedelta(hours=2)
            if t > day_end:
                return
            time.sleep(pause)
            continue
        if newest >= day_end:
            return
        cursor = res.get("nextPageCursor")
        if not cursor:
            if newest <= t:
                newest = t + dt.timedelta(minutes=30)
            t = newest + dt.timedelta(minutes=1)
        time.sleep(pause)
