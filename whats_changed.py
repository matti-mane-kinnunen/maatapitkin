#!/usr/bin/env python3
"""What changed since last week (IDEA-08): door-to-door times per capital, this run against an earlier one.

Reads the route tables the weekly run commits (out/routes*.md, out/us/routes*.md) - each map's
main start time, without night trains, and the other start time, all for the coming Tuesday -
and lists the capitals whose time changed by --min minutes or more, and those newly reached or
lost. Timetable updates, new lines in pairs.txt and rule changes all show up here alike.

    python3 whats_changed.py                    # working tree against last week's weekly update
    python3 whats_changed.py --base 512b221     # against any commit
    python3 whats_changed.py --base A --new B   # between two commits (e.g. around the timetable change)
    python3 whats_changed.py --min 60
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
FILES = ("out/routes*.md", "out/us/routes*.md")
WEEKLY = "Weekly update: trains for the week of "


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def minutes(text: str) -> int | None:
    m = re.fullmatch(r"(\d+) h (\d+) min", text.strip())
    return int(m[1]) * 60 + int(m[2]) if m else None


def hm(mins: int) -> str:
    sign = "−" if mins < 0 else ""
    mins = abs(mins)
    return f"{sign}{mins // 60} h {mins % 60:02d}" if mins >= 60 else f"{sign}{mins} min"


def parse(text: str) -> dict:
    """One routes*.md -> {origin, date, modes: {mode: {label, times: {capital: minutes}}}}."""
    out = {"origin": None, "date": None, "modes": {}}
    mode, label, col = None, None, None
    for line in text.splitlines():
        if line.startswith("# Journeys from "):
            out["origin"] = line[len("# Journeys from "):].strip()
        elif line.startswith("_leave ") and out["date"] is None:
            m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4}) from (\d\d:\d\d)", line)
            if m:
                out["date"] = dt.date(int(m[3]), int(m[2]), int(m[1]))
                mode, label = "main", f"from {m[4]}"
        elif line.startswith("## "):
            head = line[3:].strip()
            if head == "Without night trains":
                mode, label = "nonight", "without night trains"
            elif head.startswith("Leaving from "):
                mode, label = "other", "from " + head.split()[2]
            else:
                mode = None            # Other cities, itineraries, ...
            col = None
        elif mode and line.startswith("| Capital "):
            cells = [c.strip() for c in line.strip("|").split("|")]
            col = cells.index("Door to door") if "Door to door" in cells else None
            out["modes"][mode] = {"label": label, "times": {}}
        elif mode and col is not None and line.startswith("| ") and not line.startswith("|---"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            t = minutes(cells[col]) if len(cells) > col else None
            if t is not None:
                out["modes"][mode]["times"][cells[0]] = t
    return out


def read_maps(ref: str | None) -> dict:
    """{origin: parsed} from the working tree (ref None) or a commit."""
    maps = {}
    if ref is None:
        paths = [p for pat in FILES for p in sorted(ROOT.glob(pat))]
        texts = [(str(p.relative_to(ROOT)), p.read_text()) for p in paths]
    else:
        names = git("ls-tree", "-r", "--name-only", ref, "out/").split()
        names = [n for n in names if re.fullmatch(r"out/(us/)?routes(-[\w-]+)?\.md", n)]
        texts = [(n, git("show", f"{ref}:{n}")) for n in names]
    for name, text in texts:
        p = parse(text)
        if p["origin"]:
            p["file"] = name
            maps[p["origin"]] = p
    return maps


def last_week(before: dt.date) -> str | None:
    """The newest weekly update commit for an earlier travel week than `before`."""
    for line in git("log", "--format=%h %s", f"--grep={WEEKLY}").splitlines():
        sha, subject = line.split(" ", 1)
        try:
            week = dt.date.fromisoformat(subject.split(WEEKLY, 1)[1].strip()[:10])
        except (IndexError, ValueError):
            continue
        if week < before:
            return sha
    return None


def compare(old: dict, new: dict, limit: int) -> list[str]:
    lines = []
    for mode in ("main", "nonight", "other"):
        o, n = old["modes"].get(mode), new["modes"].get(mode)
        if not o or not n:
            continue
        label = n["label"]
        if o["label"] != n["label"]:
            lines.append(f"- {label}: start time changed (was {o['label']}) – not compared")
            continue
        ot, nt = o["times"], n["times"]
        diffs = sorted(((nt[c] - ot[c], c) for c in nt.keys() & ot.keys() if abs(nt[c] - ot[c]) >= limit))
        items = [f"{c} {hm(d)} ({hm(ot[c])} → {hm(nt[c])})" for d, c in diffs if d < 0]
        if items:
            lines.append(f"- {label}, **faster:** " + "; ".join(items))
        items = [f"{c} +{hm(d)} ({hm(ot[c])} → {hm(nt[c])})" for d, c in reversed(diffs) if d > 0]
        if items:
            lines.append(f"- {label}, **slower:** " + "; ".join(items))
        gained = sorted(nt.keys() - ot.keys())
        if gained:
            lines.append(f"- {label}, **now reachable:** " + "; ".join(f"{c} ({hm(nt[c])})" for c in gained))
        lost = sorted(ot.keys() - nt.keys())
        if lost:
            lines.append(f"- {label}, **no longer reachable:** " + "; ".join(lost))
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", help="commit to compare with (default: last week's weekly update)")
    ap.add_argument("--new", help="commit to compare (default: the working tree)")
    ap.add_argument("--min", type=int, default=30, help="smallest change to list, minutes (default 30)")
    args = ap.parse_args()

    new = read_maps(args.new)
    if not new:
        sys.exit("No route tables (out/routes*.md) found.")
    date = min(m["date"] for m in new.values() if m["date"])
    base = args.base or last_week(date)
    if not base:
        print("## What changed\n\nNo earlier weekly update to compare with.")
        return
    old = read_maps(base)
    old_date = min((m["date"] for m in old.values() if m["date"]), default=None)
    when = f"Tue {old_date:%d.%m.%Y}" if old_date else base

    print(f"## What changed since {when}\n")
    print(f"_Door-to-door times to capitals for Tue {date:%d.%m.%Y}, compared with {when} "
          f"(commit {git('rev-parse', '--short', base).strip()}); changes of {args.min} min or more. "
          "Timetables, new lines and rule changes all show here._\n")
    quiet = []
    for origin, n in new.items():
        if origin not in old:
            print(f"### {origin}\n\n- new map\n")
            continue
        lines = compare(old[origin], n, args.min)
        if lines:
            print(f"### {origin}\n")
            print("\n".join(lines) + "\n")
        else:
            quiet.append(origin)
    if quiet:
        print(f"No changes of {args.min} min or more: {', '.join(quiet)}.")


if __name__ == "__main__":
    main()
