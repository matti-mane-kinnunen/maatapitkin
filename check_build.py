#!/usr/bin/env python3
"""Sanity check after a weekly update: is the new map at least as good as last week's?

Compares out/summary.json (just built) with the committed one from the previous run.
Prints a Markdown report; exit code 1 means "do not publish" (e.g. Transitous was down
or a timetable is missing, so far fewer trains were found).

    python3 check_build.py              # compare with the last commit
    python3 check_build.py --max-drop 20
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent


def first(d: dict):
    return d[sorted(d)[0]] if d else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--max-drop", type=float, default=15, help="largest allowed drop in departures, %% (default 15)")
    args = ap.parse_args()

    new = json.loads((ROOT / "out" / "summary.json").read_text())
    try:
        old = json.loads(subprocess.run(["git", "show", "HEAD:out/summary.json"], cwd=ROOT,
                                        capture_output=True, text=True, check=True).stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        old = None

    problems, lines = [], [f"## Map update check", "",
                           f"Travel dates: {', '.join(new['dates'])} · departures in the data: **{new['departures']}**", ""]
    nc = first(new["capitals"])
    lines += ["| Leaving | Capitals reached | Without night trains | Places reached |", "|---|---|---|---|"]
    for d in new["dates"]:
        c = new["capitals"][d]
        lines.append(f"| {d} | {c['with_night_trains']} | {c['without']} | {new['places_reached'][d]} |")
    lines.append("")

    if old is None:
        lines.append("No earlier summary to compare with – first run, nothing to check against.")
    else:
        oc = first(old["capitals"])
        drop = 100 * (old["departures"] - new["departures"]) / max(1, old["departures"])
        lines.append(f"Last run ({old['generated']}): {old['departures']} departures, "
                     f"{oc['with_night_trains']} capitals reached.")
        if drop > args.max_drop:
            problems.append(f"departures dropped by {drop:.0f}% ({old['departures']} → {new['departures']}); "
                            "Transitous may have been down or missing a timetable")
        if nc["with_night_trains"] < oc["with_night_trains"]:
            problems.append(f"fewer capitals reached ({oc['with_night_trains']} → {nc['with_night_trains']})")
        if nc["without"] < oc["without"] - 2:
            problems.append(f"fewer capitals reached without night trains ({oc['without']} → {nc['without']})")
        if new["warnings"] > old["warnings"]:
            problems.append(f"more data warnings ({old['warnings']} → {new['warnings']})")

    lines.append("")
    if problems:
        lines += ["**Not published** – the map stays as it was:", ""] + [f"- {p}" for p in problems] + \
                 ["", "If this is expected (e.g. you removed lines), run the workflow by hand with *force* on."]
    else:
        lines.append("**OK** – published.")
    print("\n".join(lines))
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
