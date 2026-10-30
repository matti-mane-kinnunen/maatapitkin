"""Load the leg/place data and build complete journeys from Helsinki.

A journey is built for a real travel date: each leg runs on the days its timetable
says (weekdays, validity period), changes take a realistic minimum time that depends
on the station, and any wait that spans the night becomes an explicit hotel stay
with a sensible earliest departure next morning.

Times inside the router are minutes since 00:00 on the start date (day 1).
"""
from __future__ import annotations

import datetime as dt
import heapq
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DAY = 1440
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def hm(s: str) -> int:
    h, m = str(s).strip().split(":")
    return int(h) * 60 + int(m)


def fmt_clock(t: int) -> str:
    t %= DAY
    return f"{t // 60:02d}:{t % 60:02d}"


def fmt_dur(mins: int) -> str:
    return f"{mins // 60} h {mins % 60:02d} min"


def norm_service(s: str) -> str:
    return re.sub(r"\s+", "", str(s or "")).upper()


def parse_weekdays(spec) -> set[int] | None:
    """'mon-fri', 'daily', 'sat,sun', 'tue-thu,sat' -> {0..6}. None = every day."""
    if not spec or str(spec).lower() in ("daily", "all"):
        return None
    out: set[int] = set()
    for part in str(spec).lower().replace(" ", "").split(","):
        if "-" in part:
            a, b = (WEEKDAYS.index(x[:3]) for x in part.split("-"))
            out |= {d % 7 for d in range(a, b + 1 if b >= a else b + 8)}
        else:
            out.add(WEEKDAYS.index(part[:3]))
    return out


@dataclass
class Leg:
    idx: int
    frm: str
    to: str
    service: str
    mode: str = "train"
    dep: int | None = None          # clock minutes
    arr: int | None = None          # clock minutes (may be < dep: next day)
    duration: int = 0               # minutes travelling
    night: bool = False
    highlight: str | None = None
    note: str | None = None
    issue: str | None = None
    checked: str | None = None
    group: int = -1                 # index of the legs.yaml entry this departure came from
    group_size: int = 1             # number of departures in that entry
    weekdays: set[int] | None = None
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None

    @property
    def timed(self) -> bool:
        return self.dep is not None

    def runs_on(self, d: dt.date) -> bool:
        if self.valid_from and d < self.valid_from:
            return False
        if self.valid_to and d > self.valid_to:
            return False
        return self.weekdays is None or d.weekday() in self.weekdays


@dataclass
class Network:
    places: dict
    legs: list[Leg]
    settings: dict
    not_covered: dict = field(default_factory=dict)

    @property
    def capitals(self) -> list[str]:
        return [p for p, v in self.places.items() if v.get("capital")]


def _date(v):
    if v is None or isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v))


def load(data_dir: Path) -> tuple[Network, list[str]]:
    """Return the network and a list of validation warnings."""
    pl = yaml.safe_load((data_dir / "places.yaml").read_text())
    lg = yaml.safe_load((data_dir / "legs.yaml").read_text())
    places = pl["places"]
    defaults = lg.get("defaults", {})
    warnings: list[str] = []
    legs: list[Leg] = []
    for i, raw in enumerate(lg["legs"]):
        r = {**defaults, **raw}
        for end in ("from", "to"):
            if r[end] not in places:
                warnings.append(f"leg {i}: unknown place '{r[end]}' - add it to places.yaml")

        # One entry can hold one departure (dep/arr), a list of departures
        # (times: ["06:12-10:47", ...]) or a pattern (every: 30, first, last, duration).
        if "times" in r:
            slots = []
            for t in r["times"]:
                d, a_ = str(t).replace("–", "-").split("-")
                slots.append((hm(d), hm(a_)))
        elif "every" in r:
            step, first, last = int(r["every"]), hm(r.get("first", "06:00")), hm(r.get("last", "22:00"))
            dur = hm(r["duration"])
            slots = [(t, (t + dur) % DAY) for t in range(first, last + 1, step)]
        elif "dep" in r and "arr" in r:
            slots = [(hm(r["dep"]), hm(r["arr"]))]
        elif "duration" in r:
            slots = [None]
        else:
            warnings.append(f"leg {i} {r['from']}->{r['to']}: needs dep+arr, times, every or duration")
            continue

        for slot in slots:
            leg = Leg(idx=len(legs), frm=r["from"], to=r["to"], service=str(r.get("service", "")),
                      mode=r.get("mode", "train"), night=bool(r.get("night")),
                      highlight=r.get("highlight"), note=r.get("note"), issue=r.get("issue"),
                      checked=str(r.get("checked", "")), weekdays=parse_weekdays(r.get("runs")),
                      valid_from=_date(r.get("valid_from")), valid_to=_date(r.get("valid_to")),
                      group=i, group_size=len(slots))
            if slot is None:
                leg.duration = hm(r["duration"])
            else:
                leg.dep, leg.arr = slot
                leg.duration = (leg.arr - leg.dep) % DAY + DAY * int(r.get("days", 0))
            legs.append(leg)
        if r.get("issue"):
            warnings.append(f"{r['from']} -> {r['to']} ({r.get('service', '')}): {r['issue']}")
    return Network(places, legs, pl.get("settings", {}), pl.get("not_yet_covered", {})), warnings


class Router:
    """Earliest-arrival search with realistic changes and overnight stays.

    Rules (all configurable in places.yaml `settings`, per-place overrides allowed):
      * change between trains: `min_transfer` (place may override, e.g. Paris needs
        a cross-city transfer between stations)
      * staying on the same train (same service number, dep == arr): no change time
      * ferry: `ferry_checkin` before departure; Eurostar: `eurostar_checkin`
      * if the wait at a place spans the night (contains `night_point`, 03:00), it is a
        hotel stay: the next departure must be at or after `morning_departure` (07:00)
        unless it is a night train/ferry you board the same evening
      * `max_stay_nights`: never wait more than this many nights at one place
    """

    def __init__(self, net: Network, start_date: dt.date):
        self.net = net
        self.start_date = start_date
        s = net.settings
        self.min_transfer = int(s.get("min_transfer", 10))
        self.ferry_checkin = int(s.get("ferry_checkin", 30))
        self.eurostar_checkin = int(s.get("eurostar_checkin", 45))
        self.night_point = hm(s.get("night_point", "03:00"))
        self.morning = hm(s.get("morning_departure", "07:00"))
        self.max_nights = int(s.get("max_stay_nights", 2))
        self.out: dict[str, list[Leg]] = {}
        for leg in net.legs:
            self.out.setdefault(leg.frm, []).append(leg)

    def date_of(self, t: int) -> dt.date:
        return self.start_date + dt.timedelta(days=t // DAY)

    # -- connection rules ---------------------------------------------------
    def change_time(self, place: str, incoming: Leg | None, nxt: Leg) -> int:
        if incoming is None:
            return 0
        if (incoming.timed and nxt.timed and norm_service(incoming.service) == norm_service(nxt.service)
                and incoming.arr == nxt.dep):
            return 0                                          # stay on the same train
        if nxt.mode == "ferry":
            return self.ferry_checkin
        if norm_service(nxt.service).startswith(("EST", "ES")):
            return self.eurostar_checkin
        # a station's own change time is a minimum: it can lengthen, never shorten, the default
        return max(self.min_transfer, int(self.net.places.get(place, {}).get("min_transfer", 0)))

    def is_stay(self, arrival: int, dep: int) -> bool:
        """Does the wait [arrival, dep] contain the night point (default 03:00)?"""
        first = (arrival - self.night_point + DAY - 1) // DAY * DAY + self.night_point
        return arrival < first <= dep

    def board(self, arrival: int, ready: int, leg: Leg, first_leg: bool = False) -> int | None:
        """First departure of `leg` the traveller can realistically take."""
        if not leg.timed:
            t = ready
            if not first_leg and self.is_stay(arrival, t):
                t = max(t, (t // DAY) * DAY + self.morning)
            return t
        for k in range(0, self.max_nights + 2):
            t = (ready // DAY + k) * DAY + leg.dep
            if t < ready or not leg.runs_on(self.date_of(t)):
                continue
            if not first_leg and self.is_stay(arrival, t):
                if (t - arrival) // DAY >= self.max_nights:
                    return None
                if t % DAY < self.morning:                     # no 05:00 starts after a hotel night
                    continue
            return t
        return None

    # -- search ----------------------------------------------------------------
    OBJECTIVES = {
        "fastest":        lambda c, h, t: (t, c, h),
        "fewest_changes": lambda c, h, t: (c, t, h),
        "fewest_hotels":  lambda c, h, t: (h, t, c),
    }

    def nights_between(self, a: int, b: int) -> int:
        """How many night points (03:00) lie in the wait (a, b]."""
        first = (a - self.night_point) // DAY * DAY + self.night_point + DAY
        return 0 if first > b else (b - first) // DAY + 1

    def search(self, origin: str, start: int = 0, objective: str = "fastest"):
        """Dijkstra over states (place, incoming leg).

        Each state carries (changes, hotel nights, arrival time); `objective` decides
        which of them is minimised first (the others break ties)."""
        key = self.OBJECTIVES[objective]
        lab = {(origin, -1): (0, 0, start)}
        parent: dict = {(origin, -1): None}
        pq = [(key(0, 0, start), origin, -1)]
        while pq:
            k, node, inc = heapq.heappop(pq)
            c, h, t = lab[(node, inc)]
            if key(c, h, t) < k:
                continue
            inc_leg = self.net.legs[inc] if inc >= 0 else None
            for leg in self.out.get(node, []):
                dep = self.board(t, t + self.change_time(node, inc_leg, leg), leg, first_leg=inc_leg is None)
                if dep is None:
                    continue
                same_train = inc_leg is not None and self.change_time(node, inc_leg, leg) == 0 and dep == t
                nc = c + (0 if inc_leg is None or same_train else 1)
                nh = h + (self.nights_between(t, dep) if inc_leg is not None else 0)
                nt = dep + leg.duration
                st = (leg.to, leg.idx)
                if st not in lab or key(nc, nh, nt) < key(*lab[st]):
                    lab[st] = (nc, nh, nt)
                    parent[st] = ((node, inc), dep)
                    heapq.heappush(pq, (key(nc, nh, nt), leg.to, leg.idx))
        best: dict[str, tuple] = {}
        for st, l in lab.items():
            if st[0] not in best or key(*l) < key(*lab[best[st[0]]]):
                best[st[0]] = st
        self._lab, self._parent, self._best = lab, parent, best
        self._dist = {st: l[2] for st, l in lab.items()}
        return best

    def _steps(self, legs: list[dict]) -> list[dict]:
        steps = []
        for i, s in enumerate(legs):
            if i:
                prev = legs[i - 1]
                n = self.nights_between(prev["arr"], s["dep"])
                if n:
                    steps.append({"kind": "stay", "place": s["leg"].frm, "from": prev["arr"],
                                  "to": s["dep"], "nights": n})
                elif s["dep"] - prev["arr"] > 0 or s["leg"].service != prev["leg"].service:
                    steps.append({"kind": "change", "place": s["leg"].frm, "from": prev["arr"], "to": s["dep"]})
            steps.append({"kind": "leg", **s})
        return steps

    def journey(self, place: str) -> list[dict] | None:
        """Ordered list of steps: {'kind': 'leg'|'stay'|'change', ...} for the last search."""
        if place not in self._best:
            return None
        legs = []
        state = self._best[place]
        while self._parent.get(state):
            (prev, dep) = self._parent[state]
            legs.append({"leg": self.net.legs[state[1]], "dep": dep, "arr": self._dist[state]})
            state = prev
        legs.reverse()
        return self._steps(legs)

    # -- all sensible trade-offs ------------------------------------------------
    def pareto(self, origin: str, start: int = 0, horizon_days: int = 10):
        """Keep every journey that is not beaten on all three of arrival time, changes
        and hotel nights. Returns {place: [label, ...]}; use pareto_journey(label)."""
        labels = [(0, 0, start, (origin, -1), None, None)]      # c, h, t, state, parent id, dep
        at_state: dict = {(origin, -1): [0]}
        pq = [(start, 0)]
        limit = start + horizon_days * DAY
        while pq:
            t, lid = heapq.heappop(pq)
            c, h, _, (node, inc), _, _ = labels[lid]
            if lid not in at_state.get((node, inc), []):
                continue                                         # dominated after it was queued
            inc_leg = self.net.legs[inc] if inc >= 0 else None
            for leg in self.out.get(node, []):
                ct = self.change_time(node, inc_leg, leg)
                dep = self.board(t, t + ct, leg, first_leg=inc_leg is None)
                if dep is None:
                    continue
                same_train = inc_leg is not None and ct == 0 and dep == t
                nc = c + (0 if inc_leg is None or same_train else 1)
                nh = h + (self.nights_between(t, dep) if inc_leg is not None else 0)
                nt = dep + leg.duration
                if nt > limit:
                    continue
                st = (leg.to, leg.idx)
                cur = at_state.setdefault(st, [])
                if any(labels[o][0] <= nc and labels[o][1] <= nh and labels[o][2] <= nt for o in cur):
                    continue
                cur[:] = [o for o in cur if not (nc <= labels[o][0] and nh <= labels[o][1] and nt <= labels[o][2])]
                labels.append((nc, nh, nt, st, lid, dep))
                cur.append(len(labels) - 1)
                heapq.heappush(pq, (nt, len(labels) - 1))
        self._plabels = labels
        out: dict[str, list] = {}
        for st, ids in at_state.items():
            for i in ids:
                out.setdefault(st[0], []).append(i)
        return {p: [(labels[i][0], labels[i][1], labels[i][2], i) for i in ids] for p, ids in out.items()}

    def pareto_journey(self, label_id: int) -> list[dict]:
        legs = []
        lid = label_id
        while self._plabels[lid][4] is not None:
            c, h, t, st, parent, dep = self._plabels[lid]
            legs.append({"leg": self.net.legs[st[1]], "dep": dep, "arr": t})
            lid = parent
        legs.reverse()
        return self._steps(legs)

    def leg_departure(self, leg: Leg) -> int:
        """When this leg would be taken after reaching its start as early as possible."""
        s = self._best.get(leg.frm)
        if s is None:                                        # start not reachable from origin
            return self.board(0, 0, leg, first_leg=True) or leg.dep or 0
        inc = self.net.legs[s[1]] if s[1] >= 0 else None
        arr = self._dist[s]
        t = self.board(arr, arr + self.change_time(leg.frm, inc, leg), leg, first_leg=inc is None)
        return t if t is not None else arr
