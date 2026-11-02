"""Rough CO2 per journey, compared with a direct flight (IDEA-07, D-41).

Deliberately simple - the map reassures, it does not account:
  * every leg: factor for its mode (kg CO2e per passenger-km) x straight-line distance x route_factor
    (tracks and sea routes are longer than the straight line; we store no geometry)
  * the flight: straight-line distance x flight_uplift (indirect routes, holding) x the short-haul
    economy factor *with* the non-CO2 effects at altitude (radiative forcing), as the UK
    government's journey comparisons do (all of Europe and North Africa is short-haul for DESNZ)
Factors come from settings.co2 in places.yaml (source and year noted there)."""
from __future__ import annotations

import math


def km(a: dict, b: dict) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


class CO2:
    def __init__(self, cfg: dict | None, places: dict):
        self.cfg = cfg or {}
        self.places = places
        f = self.cfg.get("factors") or {}
        self.on = all(k in f for k in ("rail", "coach", "ferry", "flight"))

    def factor(self, leg) -> float:
        f = self.cfg["factors"]
        if leg.mode == "ferry":
            return f["ferry"]
        if leg.mode == "bus":
            return f["coach"]
        svc = str(leg.service or "").upper().replace(" ", "")
        if svc.startswith(("EST", "EUROSTAR")) and "international_rail" in f:
            return f["international_rail"]         # Eurostar: the source's own international-rail figure
        return f["rail"]

    def leg_kg(self, leg) -> float:
        a, b = self.places.get(leg.frm), self.places.get(leg.to)
        if not a or not b:
            return 0.0
        return self.factor(leg) * km(a, b) * float(self.cfg.get("route_factor", 1.2))

    def flight_kg(self, origin: str, dest: str) -> float:
        a, b = self.places.get(origin), self.places.get(dest)
        if not a or not b:
            return 0.0
        return km(a, b) * float(self.cfg.get("flight_uplift", 1.08)) * self.cfg["factors"]["flight"]

    def journey(self, legs: list, origin: str, dest: str) -> dict | None:
        """{'co2': kg by train/bus/ferry, 'co2_flight': kg flying direct} - or None if not set up."""
        if not self.on:
            return None
        out = {"co2": round(sum(self.leg_kg(l) for l in legs))}
        if not (self.places.get(dest, {}).get("no_flights") or self.places.get(origin, {}).get("no_flights")):
            out["co2_flight"] = round(self.flight_kg(origin, dest))   # places with no_flights: no comparison
        return out
