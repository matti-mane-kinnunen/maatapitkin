#!/usr/bin/env python3
"""Find legs.yaml entries that no pairs.txt line looks after, and tidy them (D-35).

    python3 tidy_legs.py           # report only
    python3 tidy_legs.py --apply   # remove the old single trains a '*' line already covers

Every entry in legs.yaml should come from a pairs.txt line, so the weekly run keeps it
fresh. Entries without one (mostly single trains from the original v1.9 graph) are sorted:

  covered     a '*' line for the same pair has this train (same time ±5 min, same days)
              - removed by --apply
  moved       a '*' line for the pair has its current trains, none at this time (the old
              train is gone or moved) - removed by --apply
  partial     the '*' line has this train, but not on all its days (e.g. not on Sundays):
              a gap in Transitous or a real change - check by hand, then remove or give the
              missing days as your own times
  expired     valid_to is in the past - removed by --apply
  no-star     no '*' line for this pair yet - add 'A -> B : *' to pairs.txt
  keep        a connection stored as one leg, a ferry or the metro - give it as your own
              times in pairs.txt (A -> B : name HH:MM-HH:MM), or leave it
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))
import add_leg as A  # noqa: E402
from journeys import hm  # noqa: E402


DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def days(runs) -> set:
    out = set()
    for part in str(runs or "daily").split(","):
        part = part.strip()
        if part == "daily":
            return set(DAYS)
        if "-" in part:
            a, b = part.split("-")
            out |= set(DAYS[DAYS.index(a):DAYS.index(b) + 1])
        elif part:
            out.add(part)
    return out


def classify():
    places, _ = A.load_places()
    lines = [ln.split("#", 1)[0].strip() for ln in (ROOT / "pairs.txt").read_text().splitlines()]
    covered = set()
    for ln in filter(None, lines):
        covered |= {m.start() for m in A.line_entries(ln, places)}
    entries = [(m, yaml.safe_load(m.group(0).strip()[2:])) for m in A.BLOCK_RE.finditer(A.LEGS.read_text())]
    star_pairs: dict = {}
    for _, d in entries:
        if d.get("query"):
            ts = d.get("times") or ([f"{d['dep']}-{d['arr']}"] if d.get("dep") else [])
            for t in ts:
                star_pairs.setdefault((d["from"], d["to"]), []).append((hm(t.split("-")[0]), days(d.get("runs"))))
    today = dt.date.today()
    out = []
    for m, d in entries:
        if m.start() in covered or d.get("source"):
            continue
        pair = (d["from"], d["to"])
        if d.get("valid_to") and dt.date.fromisoformat(str(d["valid_to"])) < today:
            kind = "expired"
        elif "+" in str(d.get("service")) or d.get("mode") in ("ferry", "local", "bus") or not d.get("dep"):
            kind = "keep"
        elif pair in star_pairs:
            dep, need = hm(str(d["dep"])), days(d.get("runs"))
            got = set().union(*[r for t, r in star_pairs[pair] if abs(t - dep) <= 5] or [set()])
            kind = "covered" if need <= got else "partial" if got else "moved"
        else:
            kind = "no-star"
        out.append((kind, m, d))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], epilog=__doc__.split("\n", 2)[2],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="remove the 'covered', 'moved' and 'expired' entries")
    args = ap.parse_args()
    rows = classify()
    for kind in ("covered", "moved", "expired", "partial", "no-star", "keep"):
        group = [r for r in rows if r[0] == kind]
        if group:
            print(f"\n{kind} ({len(group)}):")
            for _, _, d in group:
                print(f"  {d['from']} -> {d['to']} : {d.get('service')} {d.get('dep', '')}-{d.get('arr', '')}")
    gone = [m for k, m, _ in rows if k in ("covered", "moved", "expired")]
    if args.apply and gone:
        A.write_entries([], gone)
        print(f"\nRemoved {len(gone)} entries from legs.yaml. Run build.py and compare.")
    elif gone:
        print(f"\n{len(gone)} can be removed: python3 tidy_legs.py --apply")
    if any(k == "no-star" for k, _, _ in rows):
        print("For 'no-star': add 'A -> B : *' lines to pairs.txt; after the next lookup, run this again.")


if __name__ == "__main__":
    main()
