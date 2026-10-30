#!/usr/bin/env python3
"""Which European countries and links does Transitous have timetables for?

Asks Transitous for one typical journey in every European country (two big cities
by main-line train) and for the international links and ferries this project needs,
then prints a table: trains / ferry / buses only / nothing.

    python3 coverage_check.py                  # next Tuesday
    python3 coverage_check.py --date 2026-11-17
    python3 coverage_check.py --only links     # just the links and ferries

Writes out/coverage.md. About 50-70 requests, a minute or two.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))
import transitous as T  # noqa: E402

# (code, country, from, (lat, lon), to, (lat, lon), time zone)
COUNTRIES = [
    ("FI", "Finland", "Helsinki", (60.172, 24.941), "Tampere", (61.498, 23.773), "Europe/Helsinki"),
    ("SE", "Sweden", "Stockholm", (59.330, 18.058), "Gothenburg", (57.709, 11.973), "Europe/Stockholm"),
    ("NO", "Norway", "Oslo", (59.911, 10.753), "Bergen", (60.390, 5.333), "Europe/Oslo"),
    ("DK", "Denmark", "Copenhagen", (55.673, 12.565), "Aarhus", (56.150, 10.204), "Europe/Copenhagen"),
    ("IS", "Iceland", "Reykjavik", (64.146, -21.942), "Selfoss", (63.933, -20.997), "Atlantic/Reykjavik"),
    ("EE", "Estonia", "Tallinn", (59.440, 24.737), "Tartu", (58.373, 26.708), "Europe/Tallinn"),
    ("LV", "Latvia", "Riga", (56.946, 24.114), "Daugavpils", (55.871, 26.519), "Europe/Riga"),
    ("LT", "Lithuania", "Vilnius", (54.670, 25.285), "Kaunas", (54.887, 23.911), "Europe/Vilnius"),
    ("PL", "Poland", "Warsaw", (52.229, 21.003), "Krakow", (50.068, 19.947), "Europe/Warsaw"),
    ("DE", "Germany", "Berlin", (52.525, 13.369), "Hamburg", (53.553, 10.007), "Europe/Berlin"),
    ("NL", "Netherlands", "Amsterdam", (52.379, 4.900), "Rotterdam", (51.925, 4.469), "Europe/Amsterdam"),
    ("BE", "Belgium", "Brussels", (50.836, 4.336), "Antwerp", (51.217, 4.421), "Europe/Brussels"),
    ("LU", "Luxembourg", "Luxembourg", (49.600, 6.134), "Ettelbruck", (49.847, 6.104), "Europe/Luxembourg"),
    ("FR", "France", "Paris", (48.844, 2.374), "Lyon", (45.760, 4.859), "Europe/Paris"),
    ("CH", "Switzerland", "Zurich", (47.378, 8.540), "Bern", (46.949, 7.439), "Europe/Zurich"),
    ("AT", "Austria", "Vienna", (48.185, 16.376), "Salzburg", (47.813, 13.046), "Europe/Vienna"),
    ("LI", "Liechtenstein", "Vaduz", (47.141, 9.521), "Feldkirch", (47.240, 9.598), "Europe/Vaduz"),
    ("IT", "Italy", "Milan", (45.486, 9.204), "Rome", (41.901, 12.501), "Europe/Rome"),
    ("SM", "San Marino", "San Marino", (43.936, 12.447), "Rimini", (44.064, 12.574), "Europe/San_Marino"),
    ("MC", "Monaco", "Monaco", (43.739, 7.420), "Nice", (43.704, 7.262), "Europe/Monaco"),
    ("MT", "Malta", "Valletta", (35.898, 14.514), "Mosta", (35.909, 14.426), "Europe/Malta"),
    ("ES", "Spain", "Madrid", (40.407, -3.691), "Barcelona", (41.379, 2.140), "Europe/Madrid"),
    ("PT", "Portugal", "Lisbon", (38.768, -9.099), "Porto", (41.149, -8.585), "Europe/Lisbon"),
    ("AD", "Andorra", "Andorra la Vella", (42.507, 1.522), "Barcelona", (41.379, 2.140), "Europe/Andorra"),
    ("GB", "Great Britain", "London", (51.528, -0.134), "Manchester", (53.477, -2.231), "Europe/London"),
    ("GB-NIR", "Northern Ireland", "Belfast", (54.596, -5.917), "Derry", (54.996, -7.312), "Europe/London"),
    ("IE", "Ireland", "Dublin", (53.346, -6.294), "Cork", (51.902, -8.458), "Europe/Dublin"),
    ("CZ", "Czechia", "Prague", (50.083, 14.435), "Brno", (49.191, 16.613), "Europe/Prague"),
    ("SK", "Slovakia", "Bratislava", (48.159, 17.106), "Košice", (48.723, 21.268), "Europe/Bratislava"),
    ("HU", "Hungary", "Budapest", (47.500, 19.083), "Debrecen", (47.520, 21.629), "Europe/Budapest"),
    ("SI", "Slovenia", "Ljubljana", (46.058, 14.511), "Maribor", (46.562, 15.656), "Europe/Ljubljana"),
    ("HR", "Croatia", "Zagreb", (45.805, 15.979), "Split", (43.504, 16.442), "Europe/Zagreb"),
    ("BA", "Bosnia and Herzegovina", "Sarajevo", (43.859, 18.413), "Mostar", (43.343, 17.807), "Europe/Sarajevo"),
    ("RS", "Serbia", "Belgrade", (44.809, 20.454), "Novi Sad", (45.265, 19.830), "Europe/Belgrade"),
    ("ME", "Montenegro", "Podgorica", (42.430, 19.259), "Bar", (42.093, 19.100), "Europe/Podgorica"),
    ("XK", "Kosovo", "Pristina", (42.663, 21.164), "Peja", (42.659, 20.288), "Europe/Belgrade"),
    ("MK", "North Macedonia", "Skopje", (41.996, 21.431), "Bitola", (41.031, 21.335), "Europe/Skopje"),
    ("AL", "Albania", "Tirana", (41.328, 19.818), "Durrës", (41.323, 19.441), "Europe/Tirane"),
    ("GR", "Greece", "Athens", (38.003, 23.721), "Thessaloniki", (40.644, 22.930), "Europe/Athens"),
    ("BG", "Bulgaria", "Sofia", (42.712, 23.321), "Plovdiv", (42.134, 24.741), "Europe/Sofia"),
    ("RO", "Romania", "Bucharest", (44.447, 26.075), "Brașov", (45.661, 25.618), "Europe/Bucharest"),
    ("MD", "Moldova", "Chișinău", (47.003, 28.861), "Bălți", (47.762, 27.929), "Europe/Chisinau"),
    ("UA", "Ukraine", "Kyiv", (50.441, 30.489), "Lviv", (49.840, 24.000), "Europe/Kyiv"),
    ("TR", "Turkey", "Istanbul", (40.993, 29.037), "Ankara", (39.936, 32.844), "Europe/Istanbul"),
    ("CY", "Cyprus", "Nicosia", (35.173, 33.364), "Limassol", (34.707, 33.022), "Asia/Nicosia"),
]

# international links and ferries that matter for journeys from Helsinki
LINKS = [
    ("ferry", "Helsinki - Tallinn", "Helsinki", (60.155, 24.920), "Tallinn", (59.444, 24.766), "Europe/Helsinki"),
    ("ferry", "Helsinki - Stockholm", "Helsinki", (60.165, 24.966), "Stockholm", (59.352, 18.106), "Europe/Helsinki"),
    ("ferry", "Turku - Stockholm", "Turku", (60.435, 22.220), "Stockholm", (59.317, 18.087), "Europe/Helsinki"),
    ("ferry", "Helsinki - Travemünde", "Helsinki", (60.209, 25.192), "Travemünde", (53.950, 10.869), "Europe/Helsinki"),
    ("rail", "Tallinn - Riga", "Tallinn", (59.440, 24.737), "Riga", (56.946, 24.114), "Europe/Tallinn"),
    ("rail", "Vilnius - Warsaw", "Vilnius", (54.670, 25.285), "Warsaw", (52.229, 21.003), "Europe/Vilnius"),
    ("rail", "Copenhagen - Hamburg", "Copenhagen", (55.673, 12.565), "Hamburg", (53.553, 10.007), "Europe/Copenhagen"),
    ("rail", "Madrid - Lisbon", "Madrid", (40.407, -3.691), "Lisbon", (38.768, -9.099), "Europe/Madrid"),
    ("rail", "Sofia - Istanbul", "Sofia", (42.712, 23.321), "Istanbul", (41.013, 28.765), "Europe/Sofia"),
    ("rail", "Bucharest - Sofia", "Bucharest", (44.447, 26.075), "Sofia", (42.712, 23.321), "Europe/Bucharest"),
    ("rail", "Bucharest - Chișinău", "Bucharest", (44.447, 26.075), "Chișinău", (47.003, 28.861), "Europe/Bucharest"),
    ("rail", "Budapest - Belgrade", "Budapest", (47.500, 19.083), "Belgrade", (44.809, 20.454), "Europe/Budapest"),
    ("rail", "Zagreb - Ljubljana", "Zagreb", (45.805, 15.979), "Ljubljana", (46.058, 14.511), "Europe/Zagreb"),
    ("rail", "Thessaloniki - Sofia", "Thessaloniki", (40.644, 22.930), "Sofia", (42.712, 23.321), "Europe/Athens"),
    ("ferry", "Holyhead - Dublin", "Holyhead", (53.308, -4.631), "Dublin", (53.346, -6.200), "Europe/London"),
    ("ferry", "Bari - Patras", "Bari", (41.130, 16.860), "Patras", (38.247, 21.733), "Europe/Rome"),
    ("ferry", "Ancona - Split", "Ancona", (43.620, 13.505), "Split", (43.504, 16.442), "Europe/Rome"),
    ("ferry", "Pozzallo - Valletta", "Pozzallo", (36.727, 14.849), "Valletta", (35.893, 14.517), "Europe/Rome"),
]

RAIL = {"RAIL", "HIGHSPEED_RAIL", "LONG_DISTANCE", "NIGHT_RAIL", "REGIONAL_RAIL", "REGIONAL_FAST_RAIL",
        "SUBURBAN", "TRAIN"}
ROAD = {"BUS", "COACH"}


def main_leg(it: dict) -> dict | None:
    """The longest transit leg of a journey: what really carries you."""
    best, longest = None, -1
    for l in it.get("legs", []):
        if l.get("mode") in ("WALK", "BIKE", "CAR"):
            continue
        d = (T.parse_t(l["endTime"]) - T.parse_t(l["startTime"])).total_seconds()
        if d > longest:
            best, longest = l, d
    return best


def classify(its: list[dict]) -> tuple[str, str]:
    kinds = []
    for it in its:
        if any(l.get("mode") in T.NO_GO for l in it.get("legs", [])):
            continue
        m = main_leg(it)
        if not m:
            continue
        mode = m.get("mode")
        kind = "trains" if mode in RAIL else "ferry" if mode == "FERRY" else "buses only" if mode in ROAD else mode.lower()
        dur = T.parse_t(it["legs"][-1]["endTime"]) - T.parse_t(it["legs"][0]["startTime"])
        kinds.append((kind, f"{T.label(m)} ({int(dur.total_seconds() // 3600)} h {int(dur.total_seconds() % 3600 // 60):02d})"))
    if not kinds:
        return "nothing", ""
    for want in ("trains", "ferry"):
        for k, ex in kinds:
            if k == want:
                return k, ex
    return kinds[0]


def check(frm, a, to, b, tz, date, pause):
    for hour in (8, 14):                    # second try in the afternoon if the morning is empty
        t = dt.datetime.combine(date, dt.time(hour, 0), ZoneInfo(tz))
        res = T.plan({"fromPlace": f"{a[0]},{a[1]}", "toPlace": f"{b[0]},{b[1]}", "time": t.isoformat(),
                      "arriveBy": "false", "numItineraries": 6})
        time.sleep(pause)
        kind, ex = classify(res.get("itineraries", []))
        if kind != "nothing":
            return kind, ex
    return "nothing", ""


SYMBOL = {"trains": "✓ trains", "ferry": "✓ ferry", "buses only": "~ buses only", "nothing": "✗ nothing", "error": "! error"}


def main():
    ap = argparse.ArgumentParser(prog="coverage_check.py", description=__doc__.split("\n\n")[0],
                                 epilog=__doc__.split("\n", 2)[2], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="travel date YYYY-MM-DD (default: next Tuesday)")
    ap.add_argument("--only", choices=["countries", "links"], help="check only one of the two lists")
    ap.add_argument("--pause", type=float, default=1.0, help="seconds between requests")
    args = ap.parse_args()
    today = dt.date.today()
    date = dt.date.fromisoformat(args.date) if args.date else today + dt.timedelta(days=(1 - today.weekday()) % 7 or 7)

    sections = []
    if args.only != "links":
        sections.append(("Countries (a typical domestic main-line journey)", COUNTRIES, True))
    if args.only != "countries":
        sections.append(("International links and ferries", LINKS, False))

    out = [f"# Transitous coverage — travel date {date:%a %-d.%-m.%Y}", "",
           f"Checked {dt.datetime.now():%Y-%m-%d %H:%M}. One journey per line, searched from 08:00 "
           "(and 14:00 if the morning gave nothing). 'Buses only' usually means the rail timetable is missing.", ""]
    totals = {}
    for title, rows, is_country in sections:
        print(f"\n{title}")
        out += [f"## {title}", "", "| | Journey | Result | Example |", "|---|---|---|---|"]
        for row in rows:
            first = row[0]
            name = f"{row[1]}" if is_country else row[1]
            journey = f"{row[2]} → {row[4]}"
            print(f"  {name:<24} {journey:<34}", end=" ", flush=True)
            try:
                kind, ex = check(row[2], row[3], row[4], row[5], row[6], date, args.pause)
            except Exception as e:                    # network, HTTP, JSON
                kind, ex = "error", str(e)[:60]
            totals[kind] = totals.get(kind, 0) + 1
            print(f"{SYMBOL[kind]:<15} {ex}")
            label = f"{name} ({first})" if is_country else name
            out.append(f"| {label} | {journey} | {SYMBOL[kind]} | {ex} |")
        out.append("")

    summary = ", ".join(f"{n} {k}" for k, n in sorted(totals.items(), key=lambda x: list(SYMBOL).index(x[0])))
    print(f"\n{summary}")
    path = ROOT / "out" / "coverage.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(out + [f"**Total:** {summary}", ""]))
    print(f"-> {path}")


if __name__ == "__main__":
    main()
