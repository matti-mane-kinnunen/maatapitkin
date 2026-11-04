"""DB station numbers (EVA) for places, from Trainline's open station list (IDEA-14).

The numbers let the map link a journey to a ready search on bahn.de. Source:
https://github.com/trainline-eu/stations (ODbL), downloaded to .cache/ and refreshed monthly.

    find(name, place, aliases) -> {"db": 8011160, "station": "Berlin Hbf", "km": 0.1,
                                   "city": False, "sure": True, "why": "..."} or None
A city-wide number (PARIS 8796001: every station in Paris) is used when the city has
several stations with DB numbers, as the map shows cities, not stations (D-45).
"""
from __future__ import annotations

import csv
import math
import time
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "trainline-stations.csv"
URL = "https://raw.githubusercontent.com/trainline-eu/stations/master/stations.csv"
MAX_AGE_DAYS = 30
NEAR_KM = 10        # look for stations this close to the place's coordinates
SURE_KM = 3         # a name match closer than this needs no checking

_rows: list[dict] | None = None


def words(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return "".join(c if c.isalnum() else " " for c in s).split()


def km(lat1, lon1, lat2, lon2) -> float:
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


def rows() -> list[dict]:
    """Stations with a DB number (downloads the list if missing or older than a month)."""
    global _rows
    if _rows is not None:
        return _rows
    old = not CACHE.exists() or time.time() - CACHE.stat().st_mtime > MAX_AGE_DAYS * 86400
    if old:
        CACHE.parent.mkdir(exist_ok=True)
        try:
            print("  downloading Trainline's station list (16 MB)...")
            tmp = CACHE.with_suffix(".tmp")
            urllib.request.urlretrieve(URL, tmp)
            tmp.replace(CACHE)
        except Exception as e:      # offline: use the old copy if there is one
            if not CACHE.exists():
                print(f"  could not download the station list ({e}) - no DB numbers")
                _rows = []
                return _rows
    out = []
    with CACHE.open(encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if not r.get("db_id") or not r.get("latitude"):
                continue
            out.append({"id": r["id"], "name": r["name"], "db": int(r["db_id"]),
                        "lat": float(r["latitude"]), "lon": float(r["longitude"]),
                        "country": r["country"], "city": r["is_city"] == "t",
                        "main": r["is_main_station"] == "t", "parent": r["parent_station_id"],
                        "names": {r["name"]} | {r[k] for k in r if k.startswith("info:") and r[k]}})
    _rows = out
    return out


MAIN_WORDS = {"hbf", "hauptbahnhof", "centrale", "central", "centraal", "centralstation", "c", "h",
              "asema", "glowny", "hlavni", "sbb", "cff", "ffs", "ville", "station", "gare"}
BUS_WORDS = {"autobusni", "avtobusna", "autobus", "bus", "busstation", "zob", "kolodvor", "p", "r"}


def _match(row: dict, names: list[str]) -> str:
    """How the station's name fits the place's: 'exact' (Ljubljana), 'main' (Bern Hbf),
    'prefix' (Salerno Irno), 'bus' (Split Autobusni Kolodvor) or '' (another name)."""
    best = ""
    rank = {"": 0, "bus": 1, "prefix": 2, "main": 3, "exact": 4}
    for rn in row["names"]:
        w = words(rn)
        for n in names:
            nw = words(n)
            if not nw or w[:len(nw)] != nw:
                continue
            rest = w[len(nw):]
            got = ("exact" if not rest else "bus" if set(rest) & BUS_WORDS
                   else "main" if set(rest) <= MAIN_WORDS or row["main"] else "prefix")
            if rank[got] > rank[best]:
                best = got
    return best


def _named(row: dict, names: list[str]) -> bool:
    return _match(row, names) in ("exact", "main")


def find(name: str, place: dict, aliases: list[str] | None = None) -> dict | None:
    lat, lon = place["lat"], place["lon"]
    names = [name] + list(aliases or []) + list(place.get("aliases") or [])
    cands = [(km(lat, lon, r["lat"], r["lon"]), r) for r in rows()
             if (not place.get("country") or r["country"] == place["country"])]
    cands = [(d, r) for d, r in cands if d <= NEAR_KM * (2 if r["city"] else 1)]
    if not cands:
        return None
    stations = [(d, r) for d, r in cands if not r["city"]]
    # several stations with DB numbers in a city with a city-wide number -> the city
    for d, r in sorted(cands, key=lambda x: x[0]):
        if r["city"] and _named(r, names):
            kids = [s for _, s in stations if s["parent"] == r["id"]]
            if len(kids) >= 2:
                return {"db": r["db"], "station": r["name"], "km": round(d, 1), "city": True,
                        "sure": True, "why": f"city-wide ({len(kids)} stations)"}
            break

    penalty = {"exact": 0, "main": 0.5, "prefix": 3, "bus": 6, "": 4}
    stations = [(d, r) for d, r in cands if not r["city"] or not any(
        s["parent"] == r["id"] for _, s in stations)] or stations   # single-station "cities" count as stations

    def score(x):
        d, r = x
        return d + penalty[_match(r, names)] - (0.5 if r["main"] else 0)
    if not stations:
        return None
    d, r = min(stations, key=score)
    m = _match(r, names)
    sure = m in ("exact", "main") and d <= SURE_KM
    why = "" if sure else "check: " + ", ".join(x for x in [
        "" if m in ("exact", "main") else ("name differs" if not m else f"{m} name"),
        f"{d:.1f} km away" if d > SURE_KM else ""] if x)
    return {"db": r["db"], "station": r["name"], "km": round(d, 1), "city": False, "sure": sure, "why": why}
