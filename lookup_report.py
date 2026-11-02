#!/usr/bin/env python3
"""From an add_leg.py log, keep only what needs a person (D-38).

    python3 add_leg.py --file pairs.txt ... | tee lookup.log
    python3 tidy_legs.py --apply | tee tidy.log
    python3 lookup_report.py lookup.log tidy.log > attention.md     # empty when nothing needs you

Reported: lines that lost their trains ("removed N old entries") or failed with an error,
"Impossibly fast" legs, new places and guessed names, and lines left for next time.
Not reported in weekly runs: lines that never find direct trains and had nothing to lose -
they are in the full log every week and would only be noise. In a quick run after a push
(only new lines), every line that found nothing is reported: you just added it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SECTIONS = {                      # heading in the add_leg.py summary -> title in the report
    "Not added": "Lines that lost their trains, failed, or (new lines) found nothing",
    "Impossibly fast": "Impossibly fast – probably a wrong place",
    "New places": "New places – check the station, country and capital flag",
    "Names I guessed": "Names guessed – fix pairs.txt if wrong",
}


def tidy_report(log: str) -> list[str]:
    """What tidy_legs.py --apply removed (its 'orphaned', 'covered', 'moved', 'expired' lists)."""
    if not re.search(r"Removed \d+ entr", log):
        return []
    removed, current = [], None
    for line in log.splitlines():
        m = re.match(r"^(orphaned|covered|moved|expired|partial|no-star|keep) \(\d+\):", line)
        if m:
            current = m.group(1) if m.group(1) in ("orphaned", "covered", "moved", "expired") else None
            continue
        if current and line.startswith("  ") and line.strip():
            removed.append(f"{line.strip()} ({current})")
    return removed


def report(log: str, tidy_log: str = "") -> str:
    text = log.split("=" * 72, 1)[-1]                 # the summary at the end of the log
    new_only = "Only new lines (--new)" in log        # after a push: every line is new, report all failures
    found: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        if line and not line.startswith(" "):
            current = next((k for k in SECTIONS if line.startswith(k)), None)
            continue
        if current and line.strip():
            item = line.strip()
            if current == "Not added" and not new_only and not re.search(r"removed \d+ old entr|error", item):
                continue                              # never had trains: nothing lost
            found.setdefault(current, []).append(re.sub(r"\s{2,}", " — ", item))
    later = re.search(r"(\d+) left for next time", text)
    out = []
    for key, title in SECTIONS.items():
        if found.get(key):
            out += [f"### {title}", ""] + [f"- {x}" for x in found[key]] + [""]
    if later:
        out += [f"_{later.group(1)} lines were left for next time (time budget); they go first next week._", ""]
    removed = tidy_report(tidy_log)
    if removed:
        out += ["### Removed from legs.yaml by tidy_legs.py (no pairs.txt line looks after them any more)", ""] + \
               [f"- {x}" for x in removed] + [""]
    return "\n".join(out)


if __name__ == "__main__":
    log = Path(sys.argv[1]).read_text(encoding="utf-8") if len(sys.argv) > 1 else sys.stdin.read()
    tidy = Path(sys.argv[2]).read_text(encoding="utf-8") if len(sys.argv) > 2 and Path(sys.argv[2]).exists() else ""
    print(report(log, tidy), end="")
