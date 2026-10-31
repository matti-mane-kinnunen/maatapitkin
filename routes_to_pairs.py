#!/usr/bin/env python3
"""Turn route lists ("Madrid – Zaragoza – Barcelona") into pairs.txt lines (D-37).

    python3 routes_to_pairs.py routes.txt            # print the new lines, change nothing
    pbpaste | python3 routes_to_pairs.py             # straight from the clipboard (Mac)
    python3 routes_to_pairs.py routes.txt --append   # add them to pairs.txt
    python3 routes_to_pairs.py routes.txt --both     # also the opposite direction
    python3 routes_to_pairs.py routes.txt --all      # every pair along each route

One route per line; stops separated by – — - -> > or ','. A last stop like
"Seville/Granada/Malaga" means one route to each. Lines without a separator (headings) are
skipped. For each route you get the stops in order (Madrid -> Zaragoza, Zaragoza ->
Barcelona) and the whole way (Madrid -> Barcelona), so a train that runs through is found
as one train. Names are matched with places.yaml and its aliases (Seville = Sevilla);
unknown names are listed - add_leg.py will look them up when the lines are pushed.
Lines that pairs.txt already has (same places, '*') are left out.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))
import add_leg as A  # noqa: E402

SEP = re.compile(r"\s*(?:–|—|->|>|,|\s-\s)\s*")


def routes(text: str) -> list[list[str]]:
    out = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("•*·-").strip()
        stops = [s.strip() for s in SEP.split(line) if s.strip()]
        if len(stops) < 2:
            continue                                    # a heading, not a route
        *head, last = stops
        for end in [x.strip() for x in last.split("/") if x.strip()]:
            out.append(head + [end])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], epilog=__doc__.split("\n", 2)[2],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?", help="text with one route per line (default: read from stdin)")
    ap.add_argument("--both", action="store_true", help="also add each pair in the opposite direction")
    ap.add_argument("--all", action="store_true", help="every pair along a route, not only neighbours and the whole way")
    ap.add_argument("--append", action="store_true", help="add the new lines to pairs.txt")
    ap.add_argument("--note", default="", help="text for the heading in pairs.txt, e.g. 'AVE, interrail.com'")
    args = ap.parse_args()
    text = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()

    places, missing = A.load_places()
    def name(s: str) -> str:
        return A.find_place(s, places) or A.find_place(s, missing) or s

    have = set()
    for ln in (ROOT / "pairs.txt").read_text(encoding="utf-8").splitlines():
        m = A.LINE_RE.match(ln.split("#", 1)[0].strip())
        if m and "*" in m["svc"]:
            have.add((name(m["a"]), name(m["b"])))

    new, unknown = [], []
    for stops in routes(text):
        st = [name(s) for s in stops]
        unknown += [s for s in st if s not in places and s not in missing and s not in unknown]
        n = len(st)
        pairs = ([(st[i], st[j]) for i in range(n) for j in range(i + 1, n)] if args.all else
                 [(st[i], st[i + 1]) for i in range(n - 1)] + ([(st[0], st[-1])] if n > 2 else []))
        if args.both:
            pairs += [(b, a) for a, b in pairs]
        for a, b in pairs:
            if a != b and (a, b) not in have:
                have.add((a, b))
                new.append(f"{a} -> {b} : *")

    if not new:
        print("Nothing new - pairs.txt has all these already.")
        return
    print("\n".join(new))
    print(f"\n{len(new)} new line{'s' if len(new) != 1 else ''}"
          f" (about {len(new) * 47 // 60} min more for a full weekly lookup)")
    if unknown:
        print("Not in places.yaml yet (looked up when pushed - check 'New places' in the run summary): "
              + ", ".join(unknown))
    if args.append:
        head = f"\n# --- {args.note or 'From a route list'} (routes_to_pairs.py) ---\n"
        with open(ROOT / "pairs.txt", "a", encoding="utf-8") as f:
            f.write(head + "\n".join(new) + "\n")
        print("Added to pairs.txt. Look it over, then commit and push.")
    else:
        print("Nothing changed. Add --append to put them in pairs.txt.")


if __name__ == "__main__":
    main()
