#!/usr/bin/env python3
"""Open every built map page in a real browser and check it works (FIX-14).

    python3 tests/check_pages.py out/site        # Markdown report; exit 1 if something is wrong

For each map page (index.html, stockholm.html, ...):
  * the page loads without JavaScript errors and has its language (<html lang>)
  * no unfilled text markers ({{key}}, __ORIGIN__, __GUIDE__) and no "undefined" / "NaN"
  * every journey - each travel day x start time x with / without night trains, the
    alternatives too - can be opened from its link (#rome/2026-11-17/no-night/0600),
    shows its timetable, and each "Check on bahn.de" link starts at a departure of
    that journey on the right date
  * the controls (night trains, start time, travel day, arrive by, search, copy link)
    can be used without errors

Needs Playwright:  pip install playwright && python3 -m playwright install chromium
The weekly workflow runs it after the build, next to check_build.py: a problem holds
the update back, like a lost capital does.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

# Runs inside the page: open every journey from its link and check what is shown.
# Returns {journeys, links, problems: [..]}.
CHECK_JOURNEYS = r"""
() => {
  const problems = [], P = s => { if (problems.length < 200) problems.push(s); };
  const two = n => String(n).padStart(2, "0");
  let journeys = 0, links = 0;
  const dates = (typeof VARS !== "undefined" && VARS) ? Object.keys(VARS) : [curDate];
  for (const date of dates) {
    for (const start of [DEF_START, ...STARTS.filter(t => t !== DEF_START)]) {
      for (const night of [true, false]) {
        const sv = varOf(date, start), v = sv && sv[night ? "yes" : "no"];
        if (!v) continue;
        for (const r of [...v.routes, ...(v.city_routes || [])]) {
          const opts = [null, ...(r.alternatives || []).map(a => slug(a.label))];
          for (const opt of opts) {
            const h = "#" + [slug(r.capital), date, night ? "night" : "no-night", start.replace(":", ""), opt]
              .filter(Boolean).join("/");
            const where = `${r.capital} ${date} ${start}${night ? "" : " no-night"}${opt ? " " + opt : ""}`;
            try {
              history.replaceState(null, "", h);
              fromHash();
            } catch (e) { P(`${where}: ${e.message}`); continue; }
            journeys++;
            if (!curRoute || curRoute.capital !== r.capital) { P(`${where}: not selected`); continue; }
            if (curDate !== date || curStart !== start || (F.nightTrains === false) === night) P(`${where}: wrong view`);
            const legs = curRoute.steps.filter(s => s.kind === "leg");
            const shown = document.querySelectorAll("#steps li:not(.dayhead):not(.pause):not(.stay):not(.bahn)").length;
            if (!legs.length || shown !== legs.length) P(`${where}: ${shown} rows for ${legs.length} legs`);
            const text = document.querySelector(".itin").innerText;
            for (const bad of ["undefined", "NaN", "{{", "__ORIGIN", "null"])
              if (text.includes(bad)) P(`${where}: shows "${bad}"`);
            for (const a of document.querySelectorAll("#steps li.bahn a")) {
              links++;
              const u = decodeURIComponent(a.href.split("#")[1] || "");
              const m = u.match(/so=([^&]*)&zo=([^&]*)&soid=A=1@L=(\d+)@&zoid=A=1@L=(\d+)@&hd=(\d{4}-\d\d-\d\d)T(\d\d:\d\d):00&hza=D$/);
              if (!m) { P(`${where}: bad bahn.de link ${u}`); continue; }
              const leg = legs.find(s => s.from === m[1] && s.dep_txt.endsWith(m[6]));
              if (!leg) { P(`${where}: bahn.de link ${m[1]} ${m[6]} matches no departure`); continue; }
              const d = new Date(date + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() + Math.floor(leg.dep / 1440));
              const want = `${d.getUTCFullYear()}-${two(d.getUTCMonth() + 1)}-${two(d.getUTCDate())}`;
              if (m[5] !== want) P(`${where}: bahn.de link date ${m[5]}, departure on ${want}`);
            }
          }
        }
      }
    }
  }
  return { journeys, links, problems };
}
"""

STATIC = r"""
() => ({
  lang: document.documentElement.lang, netLang: NET.lang || "en",
  hasI18n: !!(NET.i18n && Object.keys(NET.i18n).length),
  html: document.documentElement.outerHTML.match(/\{\{\w+\}\}|__ORIGIN(_FROM)?__|__GUIDE__/g) || [],
  text: ["undefined", "NaN"].filter(w => document.body.innerText.includes(w)),
})
"""

CONTROLS = [   # (what, selector) - clicked one after another; a JavaScript error counts as a problem
    ("night trains: avoid", '#f-night button[data-n="0"]'),
    ("night trains: allowed", '#f-night button[data-n="1"]'),
    ("first start time", "#f-start button:nth-of-type(1)"),
    ("second travel day", "#f-date button:nth-of-type(2)"),
    ("arrive by day 3", "#f-day button:nth-of-type(3)"),
    ("no hotel nights", "#f-nohotel"),
    ("other cities", "#f-cities"),
    ("all connections", "#f-alllegs"),
    ("copy link", "#share"),
    ("user guide link", "#guide-link"),
]


def check_page(browser, path: Path) -> tuple[list[str], str]:
    problems: list[str] = []
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="en-GB")
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    page.goto(path.resolve().as_uri())
    page.wait_for_timeout(1000)

    s = page.evaluate(STATIC)
    if s["netLang"] != "en" and s["lang"] != s["netLang"]:
        problems.append(f'<html lang="{s["lang"]}"> but the map\'s language is {s["netLang"]}')
    if not s["hasI18n"]:
        problems.append("no page texts (NET.i18n) in the page")
    if s["html"]:
        problems.append(f"unfilled markers: {', '.join(sorted(set(s['html'])))}")
    if s["text"]:
        problems.append(f"page shows: {', '.join(s['text'])}")

    t0 = time.monotonic()
    j = page.evaluate(CHECK_JOURNEYS)
    secs = time.monotonic() - t0
    problems += j["problems"]

    page.evaluate("() => { history.replaceState(null, '', location.pathname); fromHash(); }")
    for what, sel in CONTROLS:
        el = page.query_selector(sel)
        if el is None:
            continue            # a page without that control (e.g. one travel day)
        try:
            el.click(timeout=3000)
            page.wait_for_timeout(150)
        except Exception as e:  # noqa: BLE001 - report any click failure
            problems.append(f"control '{what}': {str(e).splitlines()[0]}")
    page.fill("#q", "zzzz")
    page.fill("#q", "")
    problems += [f"JavaScript error: {e}" for e in dict.fromkeys(errors)]
    ctx.close()
    summary = f"{j['journeys']} journeys, {j['links']} bahn.de links ({secs:.0f} s)"
    return problems, summary


def main() -> int:
    site = Path(sys.argv[1] if len(sys.argv) > 1 else "out/site")
    pages = sorted(p for p in site.glob("*.html") if "const NET" in p.read_text(errors="ignore")[:4_000_000])
    if not pages:
        print(f"## Page check\n\nNo map pages found in {site}.")
        return 1
    lines, bad = ["## Page check", ""], 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for p in pages:
            problems, summary = check_page(browser, p)
            bad += len(problems)
            lines.append(f"- **{p.name}**: {summary} – " + ("OK" if not problems else f"{len(problems)} problem(s)"))
            lines += [f"  - {x}" for x in problems[:20]] + ([f"  - … and {len(problems) - 20} more"] if len(problems) > 20 else [])
        browser.close()
    lines += ["", "All pages work." if not bad else f"**{bad} problem(s) – the update is held back.**"]
    print("\n".join(lines))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
