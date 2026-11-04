#!/usr/bin/env python3
"""Add DB station numbers (`db: 8011160`) to data/places.yaml (IDEA-14).

    python3 fill_db_ids.py            # show what it would add, and what needs checking
    python3 fill_db_ids.py --write    # add the sure ones to places.yaml
    python3 fill_db_ids.py --write --all   # also the unsure ones (after checking the list)

Numbers come from Trainline's open station list (src/db_stations.py). Places that already
have `db:` are left alone; write `db: 0` for a place that should get no bahn.de link.
add_leg.py does the same for each new place.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
import db_stations  # noqa: E402

PLACES = ROOT / "data" / "places.yaml"
NAMES = ROOT / "data" / "names.yaml"


def local_aliases(key: str) -> list[str]:
    names = yaml.safe_load(NAMES.read_text()) or {} if NAMES.exists() else {}
    v = names.get(key) or {}
    return [x for x in v.values() if isinstance(x, str)] if isinstance(v, dict) else []


def set_db(text: str, key: str, db: int) -> str:
    """Put `db: N` at the end of the place's one-line {...} in places.yaml, keeping comments."""
    pat = re.compile(r"^(  [\"']?" + re.escape(key) + r"[\"']?:\s*\{)(.*?)(\})(.*)$", re.M)
    m = pat.search(text)
    if not m:
        raise SystemExit(f"{key}: line not found in places.yaml")
    inner = re.sub(r",\s*db:\s*\d+", "", m.group(2))          # replace an earlier number
    return text[:m.start()] + f"{m.group(1)}{inner}, db: {db}{m.group(3)}{m.group(4)}" + text[m.end():]


def main() -> None:
    write, take_all = "--write" in sys.argv, "--all" in sys.argv
    places = (yaml.safe_load(PLACES.read_text()) or {})["places"]
    text = PLACES.read_text()
    added, check, none = [], [], []
    for key, p in places.items():
        if "db" in p:
            continue
        f = db_stations.find(key, p, local_aliases(key))
        if not f:
            none.append(key)
            continue
        line = f"{key:<18} {f['db']:<8} {f['station']} ({f['km']} km{', ' + f['why'] if f['why'] else ''})"
        if f["sure"] or take_all:
            added.append(line)
            text = set_db(text, key, f["db"])
        else:
            check.append(line)
    print(f"{'Adding' if write else 'Would add'} {len(added)}:")
    print("\n".join("  " + x for x in added))
    if check:
        print(f"\nCheck these {len(check)} (added only with --all):")
        print("\n".join("  " + x for x in check))
    if none:
        print(f"\nNo DB number found for {len(none)}: {', '.join(none)}")
    if write:
        PLACES.write_text(text)
        print("\nplaces.yaml updated.")


if __name__ == "__main__":
    main()
