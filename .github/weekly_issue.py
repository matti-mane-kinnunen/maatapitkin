#!/usr/bin/env python3
"""One GitHub issue per week and kind, not one per run (D-49). Used by the update workflow.

    python3 .github/weekly_issue.py report "Check the timetable lookup" 2026-11-10 issue.md
    python3 .github/weekly_issue.py close "Map update held back" "Published in run …"

report: if "<kind> (week of <week>)" is open, the new report is added to it as a comment –
unless it says the same as the last one (then nothing, so no email). Otherwise the issue is
opened. Open issues of the same kind for other weeks, and duplicates of this week's, are
closed with a pointer to it. A quick run after a push reports only its new lines, so a later
report is a comment, never a replacement: the full run's findings stay in the issue.

close: closes every open issue of that kind, with the message as a comment (e.g. a held-back
map that a later run published).

Needs gh and GH_TOKEN. Report text comes from timetable data, so it is always passed as a file.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def open_issues(kind: str) -> list[dict]:
    """Open issues titled '<kind> (week of …)', newest first."""
    issues = json.loads(gh("issue", "list", "--state", "open", "--limit", "200", "--json", "number,title"))
    return sorted((i for i in issues if i["title"].startswith(f"{kind} (week of ")),
                  key=lambda i: -i["number"])


def without_run_link(text: str) -> str:
    """The report minus the 'Full log: …' line, which differs on every run."""
    return "\n".join(l for l in text.strip().splitlines() if not l.startswith("Full log:")).strip()


def report(kind: str, week: str, body_file: str) -> None:
    title = f"{kind} (week of {week})"
    new = Path(body_file).read_text()
    issues = open_issues(kind)
    this_week = [i for i in issues if i["title"] == title]
    if this_week:
        keep = this_week[0]["number"]
        seen = json.loads(gh("issue", "view", str(keep), "--json", "body,comments"))
        last = seen["comments"][-1]["body"] if seen["comments"] else seen["body"]
        if without_run_link(last) == without_run_link(new):
            print(f"#{keep} already says this - nothing added")
        else:
            gh("issue", "comment", str(keep), "--body-file", body_file)
            print(f"added to #{keep}")
    else:
        url = gh("issue", "create", "--title", title, "--body-file", body_file).strip()
        keep = int(url.rstrip("/").rsplit("/", 1)[-1])
        print(f"opened #{keep}")
    for i in issues:
        if i["number"] != keep:
            gh("issue", "close", str(i["number"]), "--comment", f"Superseded by #{keep}.")
            print(f"closed #{i['number']}")


def close(kind: str, message: str) -> None:
    for i in open_issues(kind):
        gh("issue", "close", str(i["number"]), "--comment", message)
        print(f"closed #{i['number']}")


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "report":
        report(*sys.argv[2:])
    elif len(sys.argv) == 4 and sys.argv[1] == "close":
        close(*sys.argv[2:])
    else:
        sys.exit(__doc__)
