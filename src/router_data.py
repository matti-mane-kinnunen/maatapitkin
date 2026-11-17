"""The network as the in-browser router reads it (IDEA-21): every departure of every leg,
grouped by its legs.yaml entry, plus the places and the routing settings.

The browser never parses legs.yaml itself: load() in journeys.py expands `times`/`every`
entries and marks hidden night trains, and this file writes exactly that result, so both
routers see the same departures with the same numbers (`i`, the page's leg index).
"""
from __future__ import annotations

from journeys import TZ

ROUTER_KEYS = ("min_transfer", "ferry_checkin", "eurostar_checkin", "night_point", "morning_departure",
               "min_hotel_stay", "quiet_hours", "max_stay_nights", "alternative_max_extra_hours", "co2")
PLACE_KEYS = ("lat", "lon", "country", "capital", "min_transfer", "ferry_checkin", "morning_departure", "no_flights", "tz")


def export(net) -> dict:
    """{places, settings, tz, legs: [group, ...]}; a group is one legs.yaml entry:
    {f, t, s, m?, w?, vf?, vt?, h?, n?, is?, c?, x: [[dep, arr, duration, night], ...]}
    (dep/arr None for a leg without a timetable). Expanding the groups in order gives
    the legs with the same index as net.legs."""
    groups: list[dict] = []
    last = None
    for l in net.legs:
        if l.group != last:
            g = {"f": l.frm, "t": l.to, "s": l.service, "x": []}
            if l.mode != "train":
                g["m"] = l.mode
            if l.weekdays is not None:
                g["w"] = sorted(l.weekdays)
            for k, v in (("vf", l.valid_from), ("vt", l.valid_to)):
                if v:
                    g[k] = v.isoformat()
            for k, v in (("h", l.highlight), ("n", l.note), ("is", l.issue), ("c", l.checked)):
                if v:
                    g[k] = v
            groups.append(g)
            last = l.group
        groups[-1]["x"].append([l.dep, l.arr, l.duration, 1 if l.night else 0])
    places = {name: {k: p[k] for k in PLACE_KEYS if k in p} for name, p in net.places.items()}
    settings = {k: net.settings[k] for k in ROUTER_KEYS if k in net.settings}
    return {"places": places, "settings": settings, "tz": TZ, "legs": groups}
