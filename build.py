#!/usr/bin/env python3
"""Build everything from data/: route table (out/routes.md), map (out/map.html), data (out/network.json).

    python build.py                # writes out/
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
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))
from journeys import DAY, Router, fmt_clock, fmt_dur, hm, load, utc_offset  # noqa: E402

def main():
    ap = argparse.ArgumentParser(
        prog="build.py",
        description="Build the Maata pitkin journeys from data/legs.yaml and data/places.yaml:\n"
                    "out/routes.md, the interactive map out/map.html and out/network.json.",
        epilog="Every option can also be written as key=value without dashes, for example:\n"
               "  python3 build.py transfer=15\n"
               "  python3 build.py night=01\n"
               "  python3 build.py start=08:00     # leave Helsinki in the morning\n"
               "  python3 build.py dates=2026-12-08,2026-12-11   # travel dates to switch between on the map\n"
               "  python3 build.py starts=06:00,17:00   # departure times to switch between on the map\n"
               "  python3 build.py transfer=20 night=2:30 date=2026-11-17\n\n"
               "transfer sets the normal change time. Stations with a longer change time in\n"
               "places.yaml keep their own (longer at Paris, London, Madrid, Istanbul; shorter at small border stations).\n"
               "night sets the hour a wait must pass through to count as a hotel night.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="travel date YYYY-MM-DD (default: settings.start_date or next Monday)")
    ap.add_argument("--dates", metavar="D1,D2,...",
                    help="travel dates to offer on the map, YYYY-MM-DD,... (default: settings.travel_dates, or the "
                         "travel date and the Friday, Saturday and Sunday after it)")
    ap.add_argument("--transfer", type=int, metavar="N",
                    help="minimum change time in minutes (default: settings.min_transfer, 10)")
    ap.add_argument("--start", metavar="T",
                    help="leave Helsinki from this time on the travel date, 24 h (default: settings.start_time, 17:00)")
    ap.add_argument("--starts", metavar="T1,T2",
                    help="departure times to switch between on the map, e.g. 06:00,17:00 (default: "
                         "settings.start_times, or 06:00 and the start time)")
    ap.add_argument("--only", metavar="ORIGIN",
                    help="build only the map from this origin (quicker for testing; summary.json is not written)")
    ap.add_argument("--night", metavar="T",
                    help="time the night begins, 24 h: 03, 3, 0300 or 03:00 (default: settings.night_point, 03:00)")
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
    if args.start is not None:
        m = re.fullmatch(r"(\d{1,2})(?::?(\d{2}))?", args.start.strip())
        if not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
            ap.error(f"start must be a time like 17, 0800 or 08:00 (got {args.start!r})")
        net.settings["start_time"] = f"{int(m.group(1)):02d}:{m.group(2) or '00'}"
    # one map page per origin (IDEA-04): the first is index.html, the others e.g. stockholm.html
    origins = net.settings.get("origins") or {net.settings.get("origin", "Helsinki"): {"page": "index.html"}}
    pages = [{"name": o, "page": c.get("page") or f"{slugify(o)}.html"} for o, c in origins.items()]
    if args.only and args.only not in origins:
        ap.error(f"only: {args.only!r} is not one of the origins ({', '.join(origins)})")
    summaries = {}
    for k, (origin, cfg) in enumerate(origins.items()):
        if origin not in net.places:
            ap.error(f"origin {origin!r} is not in places.yaml")
        if args.only and origin != args.only:
            continue
        cfg = dict(cfg or {}, page=pages[k]["page"])
        summaries[origin] = build_origin(net, warnings, args, ap, origin, cfg, pages, main_origin=(k == 0))
    if args.only:
        print("Built one map only - out/summary.json not written.")
        return
    # a small summary, committed every week, so the next run can tell if something broke;
    # the first origin at the top level (as before), the others under "origins"
    first, *others = summaries
    summary = dict(summaries[first], origins={o: summaries[o] for o in others})
    (ROOT / "out" / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")


def compact_route(r: dict) -> dict:
    """The map's copy of a journey, without what the page can rebuild from the timetable
    (station names, services, dates as text): a leg is ["l", leg, dep, arr], a hotel night or
    a change ["s"/"c", place, from, to, nights]. Keeps the page small (FIX: 9 MB -> ~4 MB)."""
    if r.get("same_as_default"):
        return r
    out = {k: v for k, v in r.items() if k not in ("steps", "depart_txt", "arrive_txt", "signature", "alternatives")}
    out["steps"] = [["l", x["i"], x["dep"], x["arr"]] if x["kind"] == "leg"
                    else [x["kind"][0], x["place"], x["t0"], x["t1"], x.get("nights", 0)] for x in r["steps"]]
    if r.get("alternatives"):
        out["alternatives"] = [compact_route(a) for a in r["alternatives"]]
    return out


def compact_variants(variants: dict) -> dict:
    def one(v):
        o = {k: x for k, x in v.items() if k not in ("yes", "no", "starts")}
        for key in ("yes", "no"):
            if key in v:
                o[key] = {**v[key], "routes": [compact_route(r) for r in v[key]["routes"]],
                          "city_routes": [compact_route(r) for r in v[key]["city_routes"]]}
        if "starts" in v:
            o["starts"] = {t: one(sv) for t, sv in v["starts"].items()}
        return o
    return {d: one(v) for d, v in variants.items()}


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def build_origin(net, warnings, args, ap, origin: str, cfg: dict, pages: list, main_origin: bool) -> dict:
    """Journeys, route table and map page for one origin (IDEA-04). Returns its summary."""
    s = dict(net.settings)
    for k in ("start_time", "start_times"):                # an origin may have its own start times
        if k in cfg and not (k == "start_time" and args.start is not None) and not (k == "start_times" and args.starts):
            s[k] = cfg[k]
    today = dt.date.today()
    start_date = dt.date.fromisoformat(str(args.date or s.get("start_date") or
                                           (today + dt.timedelta(days=(7 - today.weekday()) % 7 or 7))))
    version = (f"leave {origin} {start_date:%a %-d.%-m.%Y} from {s.get('start_time', '00:00')}"
               f" · generated {today:%-d.%-m.%Y}")

    outdir = ROOT / "out"
    outdir.mkdir(exist_ok=True)
    suffix = "" if main_origin else "-" + slugify(origin)    # routes-stockholm.md, network-stockholm.json
    start = hm(s.get("start_time", "00:00"))
    ALTERNATIVES = [("Fewest changes", "changes", lambda c, h, t: (c, t, h)),
                    ("Fewest hotel nights", "hotel_nights", lambda c, h, t: (h, t, c))]
    max_extra = int(float(s.get("alternative_max_extra_hours", 12)) * 60)

    def compute(night_trains: bool, date: dt.date, start: int = start):
        """All journeys (fastest + alternatives) leaving on `date` from `start`, with or without night trains."""
        router = Router(net, date, night_trains=night_trains)

        def when(t: int) -> str:
            return f"{router.date_of(t):%a %-d.%-m.} {fmt_clock(t)}"

        def build_route(cap: str, j: list | None = None) -> dict | None:
            j = j if j is not None else router.journey(cap)
            if not j:
                return None
            legs = [x for x in j if x["kind"] == "leg"]
            first_dep, arr = legs[0]["dep"], legs[-1]["arr"]
            # clock times are local; door to door is corrected for the time-zone difference
            shift = (utc_offset(net.places[cap], router.date_of(arr), arr % DAY)
                     - utc_offset(net.places[origin], router.date_of(first_dep), first_dep % DAY))
            steps = []
            for st in j:
                if st["kind"] != "leg":
                    steps.append({"kind": st["kind"], "place": st["place"], "from_t": when(st["from"]),
                                  "to_t": when(st["to"]), "minutes": st["to"] - st["from"],
                                  "nights": st.get("nights", 0), "t0": st["from"], "t1": st["to"]})
                    continue
                leg = st["leg"]
                steps.append({"kind": "leg", "i": leg.idx, "from": leg.frm, "to": leg.to, "service": leg.service,
                              "mode": leg.mode, "night": leg.night, "dep": st["dep"], "arr": st["arr"],
                              "dep_txt": when(st["dep"]), "arr_txt": when(st["arr"]),
                              "timed": leg.timed, "issue": leg.issue, "note": leg.note})
            return {"capital": cap, "depart": first_dep, "arrive": arr,
                    "depart_txt": when(first_dep), "arrive_txt": when(arr),
                    "door_to_door_min": arr - first_dep - shift,
                    "arrive_abs": arr - shift,              # arrival in the origin's clock, for sorting
                    "tz_shift": shift,
                    "changes": sum(1 for x in steps if x["kind"] in ("change", "stay")),
                    "nights_on_board": sum(1 for x in legs if x["leg"].night),
                    "hotel_nights": sum(x["nights"] for x in steps if x["kind"] == "stay"),
                    "stays": [x["place"] for x in steps if x["kind"] == "stay"],
                    "has_issue": any(x.get("issue") for x in steps),
                    "signature": [(x["i"], x["dep"]) for x in steps if x["kind"] == "leg"],
                    "steps": steps}

        front = router.pareto(origin, start)
        router.search(origin, start, "fastest")          # last: the main table uses the fastest search

        def journey_with_alternatives(place: str) -> dict | None:
            r = build_route(place)
            if not r:
                return None
            r["label"] = "Fastest"
            r["capital"] = place                     # the destination's name (capital or not)
            r["is_capital"] = bool(net.places[place].get("capital"))
            r["alternatives"], seen = [], [r["signature"]]
            for name, field_, order in ALTERNATIVES:
                ok = [l for l in front.get(place, []) if l[2] <= r["arrive"] + max_extra]
                if not ok:
                    continue
                c, h, t, lid = min(ok, key=lambda l: order(*l[:3]))
                alt = build_route(place, router.pareto_journey(lid))
                if alt and alt[field_] < r[field_] and alt["signature"] not in seen:
                    alt["label"] = name
                    r["alternatives"].append(alt)
                    seen.append(alt["signature"])
            return r

        routes, city_routes, unreached, unreached_cities = [], [], [], []
        for place in net.places:
            if place == origin:
                continue
            r = journey_with_alternatives(place)
            if r is None:
                (unreached if net.places[place].get("capital") else unreached_cities).append(place)
                continue
            (routes if r["is_capital"] else city_routes).append(r)
        routes.sort(key=lambda r: r["arrive_abs"])
        city_routes.sort(key=lambda r: r["arrive_abs"])
        return router, routes, city_routes, unreached, unreached_cities

    # travel dates to offer on the map: the travel date first
    if args.dates:
        dates = [dt.date.fromisoformat(x.strip()) for x in args.dates.split(",") if x.strip()]
    elif s.get("travel_dates"):
        dates = [dt.date.fromisoformat(str(x)) for x in s["travel_dates"]]
    else:
        dates = [start_date] + [start_date + dt.timedelta(days=k) for k in range(1, 7)
                                if (start_date + dt.timedelta(days=k)).weekday() in (4, 5, 6)]
    dates = [start_date] + [d for d in dict.fromkeys(dates) if d != start_date]
    start_time = fmt_clock(start)
    # departure times to switch between on the map (D-32); the start time is the default
    def clock_arg(x: str) -> str:
        m = re.fullmatch(r"(\d{1,2})(?::?(\d{2}))?", str(x).strip())
        if not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
            ap.error(f"start times must look like 06:00 or 17 (got {x!r})")
        return f"{int(m.group(1)):02d}:{m.group(2) or '00'}"
    raw = args.starts.split(",") if args.starts else s.get("start_times") or ["06:00", start_time]
    starts = sorted({clock_arg(x) for x in raw if str(x).strip()} | {start_time})

    def one_variant(d: dt.date, t: str) -> dict:
        v = {"version": f"leave {origin} {d:%a %-d.%-m.%Y} from {t} · generated {today:%-d.%-m.%Y}"}
        for key, nt in (("yes", True), ("no", False)):
            _, rs, crs, un, unc = compute(nt, d, hm(t))
            v[key] = {"routes": rs, "city_routes": crs, "unreached": un, "unreached_cities": unc}
        return v

    def other_start(d: dt.date, t: str, base: dict) -> dict:
        """Journeys when you may leave from `t` (earlier than the default start).
        For each place: the earliest arrival from `t`, on the latest departure that still
        makes it. Where leaving early doesn't arrive sooner, the default journey is kept
        and marked same_as_default."""
        v = {"version": f"leave {origin} {d:%a %-d.%-m.%Y} from {t} · generated {today:%-d.%-m.%Y}"}
        for key, nt in (("yes", True), ("no", False)):
            ev = {r["capital"]: r for r in base[key]["routes"] + base[key]["city_routes"]}
            router = Router(net, d, night_trains=nt)
            router.search(origin, hm(t), "fastest")
            best = {}                                   # place -> (first departure, arrival)
            for p in net.places:
                j = router.journey(p) if p != origin else None
                if j:
                    legs = [x for x in j if x["kind"] == "leg"]
                    best[p] = (legs[0]["dep"], legs[-1]["arr"])
            open_ = {p for p, (_, a) in best.items() if p not in ev or a < ev[p]["arrive"]}
            # move the start later as long as the arrival stays the same
            while open_:
                t2 = min(best[p][0] for p in open_) + 1
                router.search(origin, t2, "fastest")
                for p in list(open_):
                    j = router.journey(p)
                    legs = [x for x in j if x["kind"] == "leg"] if j else []
                    if legs and legs[-1]["arr"] == best[p][1]:
                        best[p] = (max(best[p][0], legs[0]["dep"]), best[p][1])
                    else:
                        open_.discard(p)
            # build each place's journey (with alternatives) from the start that was found
            gain = {p for p, (_, a) in best.items() if p not in ev or a < ev[p]["arrive"]}
            found: dict[str, dict] = {}
            for st in sorted({best[p][0] for p in gain}):
                _, rs, crs, _, _ = compute(nt, d, st)
                for r in rs + crs:
                    if r["capital"] in gain and best[r["capital"]][0] == st:
                        found[r["capital"]] = r
            rs, crs, un, unc = [], [], [], []
            for p in net.places:
                if p == origin:
                    continue
                r = found.get(p) or (dict(ev[p], same_as_default=True) if p in ev else None)
                if r is None:
                    (un if net.places[p].get("capital") else unc).append(p)
                else:
                    (rs if r["is_capital"] else crs).append(r)
            rs.sort(key=lambda r: r["arrive_abs"])
            crs.sort(key=lambda r: r["arrive_abs"])
            # unchanged journeys are stored as a reference only; the map fills them in (keeps the page small)
            stub = lambda r: {"capital": r["capital"], "same_as_default": True} if r.get("same_as_default") else r
            v[key] = {"routes": [stub(r) for r in rs], "city_routes": [stub(r) for r in crs],
                      "unreached": un, "unreached_cities": unc}
        return v

    variants = {}
    for d in dates:
        v = {"label": f"{d:%a %-d.%-m.}", **one_variant(d, start_time)}
        v["starts"] = {t: (other_start(d, t, v) if t < start_time else one_variant(d, t))
                       for t in starts if t != start_time}
        variants[d.isoformat()] = v
    router, routes, city_routes, unreached, _ = compute(True, start_date)
    day_routes, day_city_routes, day_unreached = (variants[start_date.isoformat()]["no"][k]
                                                  for k in ("routes", "city_routes", "unreached"))

    # --- route table -----------------------------------------------------------
    md = [f"# Journeys from {origin}", "",
          f"_{version}. Change {router.min_transfer} min (more at some stations), ferry check-in "
          f"{router.ferry_checkin} min, Eurostar {router.eurostar_checkin} min. A wait "
          f"past {fmt_clock(router.night_point)} is a hotel stay; no departures before {fmt_clock(router.morning)} after a hotel night. "
          f"Between {fmt_clock(router.quiet[0])} and {fmt_clock(router.quiet[1])} only night trains and ferries run. "
          f"Clock times are local; door-to-door times are corrected for time zones._", "",
          "| Capital | Depart | Arrive | Door to door | Changes | Night trains/ferries | Hotel nights (where) | Alternatives |",
          "|---|---|---|---|---|---|---|---|"]
    for r in routes:
        flag = " ⚠" if r["has_issue"] else ""
        where = f"{r['hotel_nights']} ({', '.join(r['stays'])})" if r["stays"] else "0"
        md.append(f"| {r['capital']}{flag} | {r['depart_txt']} | {r['arrive_txt']} | "
                  f"{fmt_dur(r['door_to_door_min'])} | {r['changes']} | {r['nights_on_board']} | {where} | "
                  + "; ".join(f"{a['label'].lower()}: {fmt_dur(a['door_to_door_min'])}, {a['changes']} ch., "
                              f"{a['hotel_nights']} hotel" for a in r["alternatives"]) + " |")
    md += ["", "## Without night trains", "",
           "_Night trains and night buses left out; night ferries still used._", "",
           "| Capital | Arrive | Door to door | Changes | Hotel nights (where) | Compared with night trains |",
           "|---|---|---|---|---|---|"]
    fast = {r["capital"]: r for r in routes}
    for r in day_routes:
        where = f"{r['hotel_nights']} ({', '.join(r['stays'])})" if r["stays"] else "0"
        f = fast.get(r["capital"])
        diff = (r["door_to_door_min"] - f["door_to_door_min"]) if f else None
        md.append(f"| {r['capital']} | {r['arrive_txt']} | {fmt_dur(r['door_to_door_min'])} | {r['changes']} | {where} | "
                  + ("same" if diff == 0 else f"+{fmt_dur(diff)}" if diff and diff > 0 else "–") + " |")
    if day_unreached:
        md += ["", "Not reachable without night trains: " + ", ".join(day_unreached)]
    other = [t for t in starts if t != start_time]
    if other:
        t2 = other[0]
        alt = {r["capital"]: r for r in variants[start_date.isoformat()]["starts"][t2]["yes"]["routes"]}
        md += ["", f"## Leaving from {t2} instead of {start_time}", "",
               "| Capital | Leave | Arrive | Door to door | Compared with " + start_time + " |", "|---|---|---|---|---|"]
        for r in routes:
            a = alt.get(r["capital"])
            if not a:
                md.append(f"| {r['capital']} | – | – | – | not reachable |")
                continue
            if a.get("same_as_default"):
                md.append(f"| {r['capital']} | – | – | – | no gain: take the {start_time} journey |")
                continue
            diff = a["arrive_abs"] - r["arrive_abs"]
            md.append(f"| {r['capital']} | {a['depart_txt']} | {a['arrive_txt']} | {fmt_dur(a['door_to_door_min'])} | "
                      + ("same arrival" if diff == 0 else f"arrives {fmt_dur(abs(diff))} {'earlier' if diff < 0 else 'later'}") + " |")
    md += ["", "## Other cities", "", "| City | Arrive | Door to door | Changes | Hotel nights |", "|---|---|---|---|---|"]
    for r in city_routes:
        md.append(f"| {r['capital']} | {r['arrive_txt']} | {fmt_dur(r['door_to_door_min'])} | "
                  f"{r['changes']} | {r['hotel_nights']} |")
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
    (outdir / f"routes{suffix}.md").write_text("\n".join(md) + "\n")

    # --- data for the map ---------------------------------------------------------
    legs_json = [{"i": l.idx, "from": l.frm, "to": l.to, "service": l.service, "mode": l.mode,
                  "night": l.night, "highlight": l.highlight, "issue": l.issue, "note": l.note,
                  "dep": fmt_clock(l.dep) if l.timed else None,
                  "arr": fmt_clock(l.arr) if l.timed else None,
                  "duration": l.duration, "checked": l.checked,
                  "duration_true": l.duration - (
                      (utc_offset(net.places[l.to], start_date, ((l.dep or 0) + l.duration) % DAY)
                       - utc_offset(net.places[l.frm], start_date, (l.dep or 0) % DAY))
                      if l.frm in net.places and l.to in net.places else 0)} for l in net.legs]
    (outdir / f"network{suffix}.json").write_text(json.dumps({
        "origin": origin, "pages": pages, "start_date": start_date.isoformat(), "version": version, "places": net.places, "not_covered": net.not_covered,
        "legs": legs_json, "dates": [d.isoformat() for d in dates], "variants": compact_variants(variants),
        "starts": starts, "default_start": start_time,
        "settings": {"min_transfer": router.min_transfer, "ferry_checkin": router.ferry_checkin,
                     "eurostar_checkin": router.eurostar_checkin, "night_point": fmt_clock(router.night_point),
                     "quiet": f"{fmt_clock(router.quiet[0])}–{fmt_clock(router.quiet[1])}",
                     "start": s.get("start_time", "00:00"),
                     "morning": fmt_clock(router.morning)}, "warnings": warnings,
    }, ensure_ascii=False, indent=1))

    import make_map
    make_map.build(ROOT, f"network{suffix}.json", cfg.get("page", "index.html"), fragment=main_origin)

    # a small summary, committed every week, so the next run can tell if something broke
    summary = {
        "generated": today.isoformat(), "dates": [d.isoformat() for d in dates],
        "departures": len(net.legs), "warnings": len(warnings),
        "capitals": {k: {"with_night_trains": len(v["yes"]["routes"]), "without": len(v["no"]["routes"])}
                     for k, v in variants.items()},
        "places_reached": {k: len(v["yes"]["routes"]) + len(v["yes"]["city_routes"]) for k, v in variants.items()},
        # names too, so the weekly check can say what went missing (first travel date)
        "reached": {"capitals": sorted(r["capital"] for r in variants[dates[0].isoformat()]["yes"]["routes"]),
                    "capitals_without_night_trains": sorted(r["capital"] for r in variants[dates[0].isoformat()]["no"]["routes"]),
                    "places": sorted(r["capital"] for r in variants[dates[0].isoformat()]["yes"]["routes"]
                                     + variants[dates[0].isoformat()]["yes"]["city_routes"])},
    }

    print(f"From {origin}: {len(net.legs)} legs, {len(routes)} capitals reached, {len(unreached)} unreached, "
          f"{len(warnings)} warnings -> {outdir}/")
    if main_origin:
        for w in warnings:
            print("  !", w)
    return summary


if __name__ == "__main__":
    main()
