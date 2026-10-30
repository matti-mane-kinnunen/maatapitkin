#!/usr/bin/env python3
"""Build everything from data/: Graphviz graph, route table, map data.

    python build.py                # writes out/
    python build.py --no-emphasis  # draw the graph exactly like the hand-made one
    python build.py transfer=15    # minimum change time 15 min (stations with a longer
                                   # change time in places.yaml keep theirs)
    python build.py night=01       # a wait through 01:00 counts as a hotel night (default 03)
    python build.py transfer=20 night=2:30 date=2026-11-17
"""
from __future__ import annotations

import argparse
import re
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))
from journeys import DAY, Router, fmt_clock, fmt_dur, hm, load  # noqa: E402

NIGHT = "turquoise3"
HIGHLIGHT = {"sto-ham-night": "darkorange1"}
DAY_NAMES = ["one", "two", "three", "four", "five", "six", "seven", "eight"]


def q(s: str) -> str:
    return '"' + str(s).replace('"', r'\"') + '"'


def edge_label(leg, dep: int | None) -> str:
    if leg.timed:
        lab = f"{fmt_clock(leg.dep)}\n{leg.service}\n{fmt_clock(leg.arr)}"
    else:
        lab = f"{leg.service}\n~{leg.duration // 60}:{leg.duration % 60:02d}"
    if leg.note:
        lab += f"\n{leg.note}"
    if leg.issue:
        lab += "\n(!)"
    return lab


def make_dot(net, router, fastest_legs: set[int], version: str, emphasis: bool) -> str:
    # one arrow per legs.yaml entry: an entry with many departures is drawn once
    groups: dict[int, list] = {}
    for leg in net.legs:
        groups.setdefault(leg.group, []).append(leg)
    by_day: dict[int, list] = {}
    for members in groups.values():
        used = [l for l in members if l.idx in fastest_legs]
        rep = min(used or members, key=router.leg_departure)
        day = router.leg_departure(rep) // DAY + 1
        by_day.setdefault(day, []).append((rep, members))

    capitals = [c for c in net.capitals]
    out = [f"digraph MaataPitkin {{",
           f'  {" , ".join(q(c) for c in capitals)} [shape="box" style="filled" color="grey" fontsize="20"];',
           "  graph [",
           f'    label = "From Finland to European capitals by train and ferry\\n'
           f'For somewhat direct travel; generated from data/legs.yaml\\n'
           f'Matti Kinnunen - {version}" fontsize="50";',
           "    rankdir=LR;", "  ]", ""]
    for day in sorted(by_day):
        name = DAY_NAMES[day - 1] if day <= len(DAY_NAMES) else str(day)
        out += [f"  subgraph cluster_day{day} {{", '    color=black; fontsize="30";',
                f'    label = "Day {name}";', '    node [fontsize="20" shape="box"];']
        for leg, members in by_day[day]:
            if len(members) > 1:
                deps = sorted(l.dep for l in members)
                lab = (f"{leg.service}\n{len(members)} departures\n{fmt_clock(deps[0])}–{fmt_clock(deps[-1])}"
                       f"\n{leg.duration // 60}:{leg.duration % 60:02d} h")
            else:
                lab = edge_label(leg, None)
            attrs = [f"label={q(lab)}"]
            color = HIGHLIGHT.get(leg.highlight) or (NIGHT if leg.night else None)
            if color:
                attrs.append(f'color="{color}"')
            if leg.mode in ("ferry", "local"):
                attrs.append('style="dashed"')
            if emphasis and any(l.idx in fastest_legs for l in members):
                attrs.append('penwidth="3"')
            out.append(f"    {q(leg.frm)} -> {q(leg.to)} [{' '.join(attrs)}];")
        out += ["  }", ""]

    legend = [("Day train", ""), ("Night train", f'color="{NIGHT}"'), ("Ferry", 'style="dashed"'),
              ("Night ferry", f'style="dashed" color="{NIGHT}"'),
              ("After the Stockholm-Hamburg\\nnight train", 'color="darkorange1"')]
    if emphasis:
        legend.append(("Fastest route\\nto a capital", 'penwidth="3"'))
    out += ["  subgraph cluster_legend {", '    color=black; fontsize="30"; label="Legend";',
            '    node [fontsize="20" shape="box"];']
    out += [f'    From -> To [label="{lab}" {a}];' for lab, a in legend]
    out += ['    Capital [shape="box" style="filled" color="grey" fontsize="20"];',
            '    Issue [label="(!) = known data issue,\\nsee routes.md"];', "  }", "}"]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(
        prog="build.py",
        description="Build the Maata pitkin journeys from data/legs.yaml and data/places.yaml:\n"
                    "the Graphviz graph, out/routes.md and the interactive map out/map.html.",
        epilog="Every option can also be written as key=value without dashes, for example:\n"
               "  python3 build.py transfer=15\n"
               "  python3 build.py night=01\n"
               "  python3 build.py transfer=20 night=2:30 date=2026-11-17\n\n"
               "transfer sets the normal change time. Stations with a longer change time in\n"
               "places.yaml (Paris, London, Madrid, Istanbul) keep the longer one.\n"
               "night sets the hour a wait must pass through to count as a hotel night.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="travel date YYYY-MM-DD (default: settings.start_date or next Monday)")
    ap.add_argument("--transfer", type=int, metavar="N",
                    help="minimum change time in minutes (default: settings.min_transfer, 10)")
    ap.add_argument("--night", metavar="T",
                    help="time the night begins, 24 h: 03, 3, 0300 or 03:00 (default: settings.night_point, 03:00)")
    ap.add_argument("--no-emphasis", action="store_true", help="don't draw the fastest routes thicker in the graph")
    ap.add_argument("--version", default=None, metavar="TEXT", help="text for the graph title (default: travel date and today)")
    # accept key=value as well as --key value
    argv = [f"--{a}" if re.fullmatch(r"[a-z][a-z-]*=.*", a) else a for a in sys.argv[1:]]
    args = ap.parse_args(argv)

    net, warnings = load(ROOT / "data")
    if args.transfer is not None:
        if args.transfer < 0:
            ap.error("transfer must be 0 or more minutes")
        net.settings["min_transfer"] = args.transfer
    if args.night is not None:
        m = re.fullmatch(r"(\d{1,2})(?::?(\d{2}))?", args.night.strip())
        if not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
            ap.error(f"night must be a time like 03, 3, 0300 or 03:00 (got {args.night!r})")
        net.settings["night_point"] = f"{int(m.group(1)):02d}:{m.group(2) or '00'}"
    s = net.settings
    origin = s.get("origin", "Helsinki")
    today = dt.date.today()
    start_date = dt.date.fromisoformat(str(args.date or s.get("start_date") or
                                           (today + dt.timedelta(days=(7 - today.weekday()) % 7 or 7))))
    router = Router(net, start_date)
    router.search(origin, hm(s.get("start_time", "00:00")))
    version = args.version or f"travel date {start_date:%a %-d.%-m.%Y} · generated {today:%-d.%-m.%Y}"

    def when(t: int) -> str:
        return f"{router.date_of(t):%a %-d.%-m.} {fmt_clock(t)}"

    outdir = ROOT / "out"
    outdir.mkdir(exist_ok=True)

    # --- journeys to capitals ---------------------------------------------
    start = hm(s.get("start_time", "00:00"))

    def build_route(cap: str, j: list | None = None) -> dict | None:
        j = j if j is not None else router.journey(cap)
        if not j:
            return None
        legs = [x for x in j if x["kind"] == "leg"]
        first_dep, arr = legs[0]["dep"], legs[-1]["arr"]
        steps = []
        for st in j:
            if st["kind"] != "leg":
                steps.append({"kind": st["kind"], "place": st["place"], "from_t": when(st["from"]),
                              "to_t": when(st["to"]), "minutes": st["to"] - st["from"],
                              "nights": st.get("nights", 0)})
                continue
            leg = st["leg"]
            steps.append({"kind": "leg", "i": leg.idx, "from": leg.frm, "to": leg.to, "service": leg.service,
                          "mode": leg.mode, "night": leg.night, "dep": st["dep"], "arr": st["arr"],
                          "dep_txt": when(st["dep"]), "arr_txt": when(st["arr"]),
                          "timed": leg.timed, "issue": leg.issue, "note": leg.note})
        return {"capital": cap, "depart": first_dep, "arrive": arr,
                "depart_txt": when(first_dep), "arrive_txt": when(arr),
                "door_to_door_min": arr - first_dep,
                "changes": sum(1 for x in steps if x["kind"] in ("change", "stay")),
                "nights_on_board": sum(1 for x in legs if x["leg"].night),
                "hotel_nights": sum(x["nights"] for x in steps if x["kind"] == "stay"),
                "stays": [x["place"] for x in steps if x["kind"] == "stay"],
                "has_issue": any(x.get("issue") for x in steps),
                "signature": [(x["i"], x["dep"]) for x in steps if x["kind"] == "leg"],
                "steps": steps}

    ALTERNATIVES = [("Fewest changes", "changes", lambda c, h, t: (c, t, h)),
                    ("Fewest hotel nights", "hotel_nights", lambda c, h, t: (h, t, c))]
    max_extra = int(float(s.get("alternative_max_extra_hours", 12)) * 60)
    front = router.pareto(origin, start)
    router.search(origin, start, "fastest")          # the graph and main table use the fastest

    routes, fastest_legs, unreached = [], set(), []
    for cap in net.capitals:
        if cap == origin:
            continue
        r = build_route(cap)
        if not r:
            unreached.append(cap)
            continue
        fastest_legs.update(x["i"] for x in r["steps"] if x["kind"] == "leg")
        r["label"] = "Fastest"
        r["alternatives"], seen = [], [r["signature"]]
        for name, field_, order in ALTERNATIVES:
            ok = [l for l in front.get(cap, []) if l[2] <= r["arrive"] + max_extra]
            if not ok:
                continue
            c, h, t, lid = min(ok, key=lambda l: order(*l[:3]))
            alt = build_route(cap, router.pareto_journey(lid))
            if alt and alt[field_] < r[field_] and alt["signature"] not in seen:
                alt["label"] = name
                r["alternatives"].append(alt)
                seen.append(alt["signature"])
        routes.append(r)
    routes.sort(key=lambda r: r["arrive"])

    # --- Graphviz -----------------------------------------------------------
    dot = make_dot(net, router, fastest_legs, version, not args.no_emphasis)
    (outdir / "maatapitkin.dot").write_text(dot)
    if shutil.which("dot"):
        for fmt in ("svg", "png"):
            subprocess.run(["dot", f"-T{fmt}", str(outdir / "maatapitkin.dot"),
                            "-o", str(outdir / f"maatapitkin.{fmt}")], check=True)
    else:
        print("graphviz 'dot' not found - only the .dot file was written")

    # --- route table -----------------------------------------------------------
    md = [f"# Journeys from {origin}", "",
          f"_{version}. Change {router.min_transfer} min (more at some stations), ferry check-in "
          f"{router.ferry_checkin} min, Eurostar {router.eurostar_checkin} min. A wait "
          f"past {fmt_clock(router.night_point)} is a hotel stay; no departures before {fmt_clock(router.morning)} after a hotel night._", "",
          "| Capital | Depart | Arrive | Door to door | Changes | Night trains/ferries | Hotel nights (where) | Alternatives |",
          "|---|---|---|---|---|---|---|---|"]
    for r in routes:
        flag = " ⚠" if r["has_issue"] else ""
        where = f"{r['hotel_nights']} ({', '.join(r['stays'])})" if r["stays"] else "0"
        md.append(f"| {r['capital']}{flag} | {r['depart_txt']} | {r['arrive_txt']} | "
                  f"{fmt_dur(r['door_to_door_min'])} | {r['changes']} | {r['nights_on_board']} | {where} | "
                  + "; ".join(f"{a['label'].lower()}: {fmt_dur(a['door_to_door_min'])}, {a['changes']} ch., "
                              f"{a['hotel_nights']} hotel" for a in r["alternatives"]) + " |")
    md += ["", "## Itineraries", ""]

    def summary(x):
        return (f"{fmt_dur(x['door_to_door_min'])}, arrive {x['arrive_txt']}, {x['changes']} changes, "
                f"{x['hotel_nights']} hotel nights")

    for r0 in routes:
      for r in [r0] + r0["alternatives"]:
        title = r0["capital"] if r is r0 else f"{r0['capital']} — {r['label'].lower()}"
        md.append(f"### {title}{' ⚠' if r['has_issue'] else ''}")
        md.append(f"_{r['label']}: {summary(r)}_")
        md.append("")
        for x in r["steps"]:
            if x["kind"] == "leg":
                md.append(f"- {x['dep_txt']} → {x['arr_txt']}  **{x['from']} → {x['to']}**  {x['service']}"
                          f"{'  (night)' if x['night'] else ''}{'  ⚠ ' + x['issue'] if x['issue'] else ''}")
            elif x["kind"] == "stay":
                md.append(f"- 🛏 Overnight in {x['place']} ({x['from_t']} → {x['to_t']})")
            elif x["minutes"] >= 90:
                md.append(f"- Wait {fmt_dur(x['minutes'])} in {x['place']}")
        md.append("")
    md += ["## Capitals not reachable with the current legs", ""]
    md += [f"- {c}" for c in unreached + list(net.not_covered)] or ["- none"]
    md += ["", "## Data issues", ""] + ([f"- {w}" for w in warnings] or ["- none"])
    (outdir / "routes.md").write_text("\n".join(md) + "\n")

    # --- data for the map ---------------------------------------------------------
    legs_json = [{"i": l.idx, "from": l.frm, "to": l.to, "service": l.service, "mode": l.mode,
                  "night": l.night, "highlight": l.highlight, "issue": l.issue, "note": l.note,
                  "dep": fmt_clock(l.dep) if l.timed else None,
                  "arr": fmt_clock(l.arr) if l.timed else None,
                  "duration": l.duration} for l in net.legs]
    (outdir / "network.json").write_text(json.dumps({
        "origin": origin, "version": version, "places": net.places, "not_covered": net.not_covered,
        "legs": legs_json, "routes": routes,
        "settings": {"min_transfer": router.min_transfer, "ferry_checkin": router.ferry_checkin,
                     "eurostar_checkin": router.eurostar_checkin, "night_point": fmt_clock(router.night_point),
                     "morning": fmt_clock(router.morning)}, "unreached": unreached, "warnings": warnings,
    }, ensure_ascii=False, indent=1))

    import make_map
    make_map.build(ROOT)

    print(f"{len(net.legs)} legs, {len(routes)} capitals reached, {len(unreached)} unreached, "
          f"{len(warnings)} warnings -> {outdir}/")
    for w in warnings:
        print("  !", w)


if __name__ == "__main__":
    main()
