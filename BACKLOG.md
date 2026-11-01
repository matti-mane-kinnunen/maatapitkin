# Small issues to fix and ideas to implement

One place for loose ends, so they can be referred to by ID (e.g. "let's do FIX-01").
IDs are never reused. When something is done, set **Status** to *done* with the date and,
if it led to a decision, the D-number in DECISIONS.md. Purpose and scope: see D-37.

- **FIX** – something small that is wrong or could be better in the code or the workflow
- **DATA** – timetable data to check by hand (Transitous cannot, or the times are old)
- **IDEA** – a new feature or a bigger change

## Small issues to fix

| ID | Added | What | Notes | Status |
|---|---|---|---|---|
| FIX-01 | 1.11.2026 | The station check (D-33) is a little generous between nearby cities. | "Frankfurt → Koblenz" includes a 44-min ICE, probably the high-speed line to Montabaur, 22 km from Koblenz – within the 25 km limit. It does not affect Luxembourg (via Brussels and Paris). Tighten the limit for short pairs, or check the stop name too. | open |
| FIX-02 | 1.11.2026 | GitHub warns that the Node 20 actions are deprecated. | Update `actions/checkout`, `setup-python`, `upload-pages-artifact`, `deploy-pages` to current versions and pin each to a commit SHA (supply-chain hygiene). | open |
| FIX-03 | 1.11.2026 | Run-day text is clumsy: "mon-fri,sat" instead of "mon-sat"; summary shows "(mon-Sat 1)". | Cosmetic, in add_leg.py (`runs_spec`, `runs_text`). | open |
| FIX-04 | 1.11.2026 | The Hague and Cairnryan have no incoming journey. | Cairnryan: no train exists (bus from Stranraer/Ayr); The Hague: no line to it. Add a line or remove the place. | open |
| FIX-05 | 1.11.2026 | "Tanger" mixes two ports. | Algeciras ferries land at Tanger Med, ~40 km from the city; the Tarifa ferry lands in Tanger Ville. Make Tanger Med a place of its own with a bus/train to Tanger. | open |
| FIX-06 | 1.11.2026 | 21 "partial" trains from the 2023 graph remain. | The `*` line has them, but not on every day they claim (e.g. NJ 471 Hamburg–Basel on Sundays). `python3 tidy_legs.py` lists them; check by hand, then remove or give the missing days as own times. | open |

## Data to check by hand

| ID | Added | What | Notes | Status |
|---|---|---|---|---|
| DATA-01 | 1.11.2026 | Own-time lines with 2023 times, where Transitous has no trains. | Rome → Syracuse (ICN 1959), Madrid → Badajoz → Abrantes → Lisbon, Sofia → Istanbul, Istanbul → Ankara, Bucharest → Chișinău. Marked "check by hand" in pairs.txt. | open |
| DATA-02 | 1.11.2026 | Tarifa ferry and FRS shuttle bus times are rough. | Sources disagree; now every 2 h 09:00–21:00 (ferry) and 07:45–19:45 (bus). Matti knows the real pattern from 2026. | open |
| DATA-03 | 1.11.2026 | Three own-time lines have "?" as the service name. | Patras → Athens (bus), Bari → Durrës (ferry), Durrës → Tirana (bus): find operator and current times. | open |
| DATA-04 | 1.11.2026 | Madrid → Santiago / Vitoria: run days approximate. | Trainline and Rome2Rio disagree a little on how many trains run each day. | open |
| DATA-05 | 1.11.2026 | Tallinn → Valga has only one train (Elron 10:22). | The `*` line found no direct trains in run #7; check whether Elron runs more direct Tallinn–Valga trains and add them as own times. | open |
| DATA-06 | 1.11.2026 | Transitous is thin on Renfe long-distance trains from Madrid. | Madrid → Valencia has only 2 departures (in reality many more); Algeciras, Santiago, Vitoria, San Sebastián needed own times. Consider own times for the most important Spanish lines. | open |

## Ideas

| ID | Added | What | Notes | Status |
|---|---|---|---|---|
| IDEA-01 | 1.11.2026 | High-speed backbone from route lists. | `routes_to_pairs.py` gives 31 lines from Interrail's AVE list (~24 min more per weekly run); then TGV, ICE, Frecciarossa. Add one list at a time and watch run time and page size (D-37). | open |
| IDEA-02 | 31.10.2026 | Morning train Helsinki → Turku for the 08:45 Viking day ferry. | Would make the morning option (D-32) useful westwards; today only the Baltic capitals gain from leaving in the morning. | open |
| IDEA-03 | 31.10.2026 | Day trains for the no-night-train mode. | E.g. Hamburg/Offenburg → Basel, Rome → Sicily, Budapest → Bucharest, so more capitals are reachable without night trains. | open |
| IDEA-04 | 1.11.2026 | A second origin, e.g. London. | Needs lines in both directions (`routes_to_pairs.py --both`) and its own page (`…/maatapitkin/london/`). A few origins at most (D-37). | open |
| IDEA-05 | 31.10.2026 | Compare travel days side by side. | E.g. "Lisbon: Tue 52 h, Sat 61 h" – which weekday to travel. | open |
| IDEA-06 | 31.10.2026 | Booking links. | A link per leg to the operator's booking page (VR, SJ, DB, ÖBB, ferries …). | open |
| IDEA-07 | 31.10.2026 | CO₂ per journey. | Rough figures per mode and km, compared with flying. | open |
| IDEA-08 | 31.10.2026 | "What changed this week" on the map. | E.g. "Sofia 2 h faster, Valletta unreachable" – from the weekly check; good blog material. | open |
| IDEA-09 | 31.10.2026 | Add pairs from the browser. | A GitHub issue form ("From / To / Service") that a workflow turns into a pairs.txt line. | open |
| IDEA-10 | 1.11.2026 | Load each travel day's data only when chosen. | Needed if the map grows beyond ~200 places (page now 3.9 MB, keep under ~8 MB; D-37). | open |
