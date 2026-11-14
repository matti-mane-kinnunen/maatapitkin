"""The same routing cases through both routers (IDEA-21): src/journeys.py and src/router.js.

Each case in tests/router_cases.yaml is loaded with the real load(), searched with the Python
Router, exported as the browser gets it (src/router_data.export) and searched again by the
JavaScript router in Node (tests/router_cases.mjs). Both must give the expected answer, so the
two routers cannot drift apart unnoticed. Without Node the JavaScript half is skipped (with a
note), so the Python half still runs anywhere.

Run:  python3 -m unittest discover -s tests -v      (or python3 tests/test_router_cases.py)
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))
from journeys import DAY, Router, load  # noqa: E402
from router_data import export  # noqa: E402
from test_journeys import SETTINGS  # noqa: E402

TUESDAY = "2026-11-17"
CASES = yaml.safe_load((HERE / "router_cases.yaml").read_text())


def clock(t: int) -> str:
    return f"day {t // DAY + 1} {t % DAY // 60:02d}:{t % 60:02d}"


def hm(s: str) -> int:
    h, m = str(s).split(":")
    return int(h) * 60 + int(m)


def network(case: dict):
    """The case's network, loaded with the real load() (as tests/test_journeys.py does)."""
    pl = {k: {"lat": 50.0 + i, "lon": 8.0, "country": "DE"} for i, k in enumerate("ABC")}
    for name, extra in (case.get("places") or {}).items():
        pl.setdefault(name, {"lat": 50.0, "lon": 9.0, "country": "DE"}).update(extra)
    settings = {**SETTINGS, **(case.get("settings") or {})}
    with tempfile.TemporaryDirectory() as d:
        Path(d, "places.yaml").write_text(yaml.safe_dump({"settings": settings, "places": pl}))
        Path(d, "legs.yaml").write_text(yaml.safe_dump({"legs": case["legs"]}))
        net, warnings = load(Path(d))
    assert not warnings, warnings
    return net


def python_answer(case: dict) -> dict:
    """What journeys.py says: {expect, departures, stays, pareto} for the case's destination."""
    net = network(case)
    if case.get("min_transfer") is not None:                 # the visitor's own change time = transfer=N
        net.settings["min_transfer"] = case["min_transfer"]
    r = Router(net, dt.date.fromisoformat(str(case.get("date", TUESDAY))), night_trains=case.get("night_trains", True))
    for mode in case.get("avoid") or []:                     # avoid ferries / buses: those legs left out
        r.out = {p: [l for l in ls if l.mode != mode] for p, ls in r.out.items()}
    start, to = hm(case.get("start", "06:00")), case.get("to", "C")
    best = r.search("A", start, case.get("objective", "fastest"))
    out: dict = {"expect": None, "departures": None, "stays": None}
    if to in best:
        c, h, t = r._lab[best[to]]
        out["expect"] = [clock(t), c, h]
        j = r.journey(to)
        out["departures"] = [clock(s["dep"]) for s in j if s["kind"] == "leg"]
        out["stays"] = [[s["place"], s["nights"]] for s in j if s["kind"] == "stay"]
    front = r.pareto("A", start).get(to, [])
    out["pareto"] = sorted([clock(t), c, h] for c, h, t, _ in front)
    return out


def javascript_answers() -> list[dict] | None:
    """What router.js says for every case (None without Node)."""
    node = shutil.which("node")
    if not node:
        return None
    payload = []
    for case in CASES:
        payload.append({"data": export(network(case)), "date": str(case.get("date", TUESDAY)),
                        "start": case.get("start", "06:00"), "to": case.get("to", "C"),
                        "objective": case.get("objective", "fastest"), "night_trains": case.get("night_trains", True),
                        "min_transfer": case.get("min_transfer"), "avoid": case.get("avoid") or []})
    p = subprocess.run([node, str(HERE / "router_cases.mjs")], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=120)
    if p.returncode:
        raise RuntimeError("router_cases.mjs failed:\n" + p.stderr)
    return json.loads(p.stdout)


class BothRouters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = javascript_answers()
        if cls.js is None:
            print("\n(no node: only the Python router checked)", file=sys.stderr)

    def check(self, i: int, case: dict):
        for who, ans in (("journeys.py", python_answer(case)), ("router.js", self.js[i] if self.js else None)):
            if ans is None:
                continue
            with self.subTest(router=who):
                for field in ("expect", "departures", "stays", "pareto"):
                    if field in case:
                        want = case[field]
                        got = sorted(ans[field]) if field == "pareto" else ans[field]
                        self.assertEqual(got, sorted(want) if field == "pareto" else want,
                                         f"{who}: {case['name']} ({field})")


for _i, _case in enumerate(CASES):
    _name = "test_%02d_%s" % (_i, "".join(ch if ch.isalnum() else "_" for ch in _case["name"])[:50])
    setattr(BothRouters, _name, lambda self, i=_i, c=_case: self.check(i, c))


if __name__ == "__main__":
    unittest.main()
