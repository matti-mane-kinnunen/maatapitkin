# Maata pitkin

Overland journeys to the capitals in Europe and around the Mediterranean by train, ferry and bus – an interactive map for each
starting city, updated every week.

**Maps.** https://matti-mane-kinnunen.github.io/maatapitkin/ – one page per origin, listed under
`origins` in places.yaml: `index.html` (Helsinki), `stockholm.html` (Tågsemester),
`copenhagen.html` (Togferie), `london.html` (Train holiday), `berlin.html` (Zugurlaub), `paris.html`
(Voyage en train), `rome.html` (Viaggio in treno). Each map is in its city's language – Finnish, Swedish, Danish, English, German,
French, Italian (D-53) – links to the others at the
top, has a short user guide at the end, and under each stretch of trains a *Check on bahn.de* link
that opens Deutsche Bahn's planner at that departure (D-55).

**Purpose.** To help people wondering how to plan an Interrail trip get over the first fear
that train travel is difficult and slow: a map that shows it can be done, how long it takes,
and a sensible way to do it. It is not a journey planner – for booking, use the operators,
bahn.de or Transitous. So the network is a curated backbone of good trains, journeys are
realistic rather than optimal to the minute, and the map has to stay readable on a phone.
This started from a hand-made Graphviz graph (MaataPitkin v1.9, April 2023, kept as data/original_MaataPitkin_v1.9.dot) and replaces it
with data, a journey router and interactive maps.

See DECISIONS.md for what was decided and why, BACKLOG.md for what is still open.

```
pairs.txt             the connections ("A -> B : *" or own times) – the main input (pairs.example.txt: the format)
data/legs.yaml        every leg: from, to, dep+arr (or times: [...] or every: N), service, mode, night, runs
data/places.yaml      coordinates, capitals, DB station numbers (db:), change times per station, the maps (origins), routing and CO2 settings
data/names.yaml       place names in each map's language (Tukholma, Köpenhamn, København …), D-50
data/i18n/<lang>.yaml page texts per language (en master; fi, sv, da, de, fr, it), D-53 – check_i18n.py lists gaps
src/guide/<lang>.html the user guide per language
data/basemap.geojson  country outlines for the map (Natural Earth, public domain)
data/sources/         route lists (Eurostar, Frecce, railjet …) used with routes_to_pairs.py
static/               files copied into the site as they are (link-preview pictures)
build.py              builds every map, route table and summary in out/ (class Journeys: the journeys;
                      routes_markdown, network_json, summary_of: the outputs; build_origin joins them, FIX-16)
add_leg.py            looks pairs.txt lines up in Transitous and writes legs.yaml (new places get a DB station number)
fill_db_ids.py        adds missing DB station numbers to places.yaml (one-off; add_leg.py does new places)
tidy_legs.py          legs.yaml entries that no pairs.txt line looks after any more; --apply removes them
lookup_report.py      from the lookup log, only what needs a person (the weekly issue)
check_build.py        is the new map at least as good as last week's? (holds the update back if not)
routes_to_pairs.py    route lists ('Madrid – Zaragoza – Barcelona') -> pairs.txt lines
check_timetables.py   re-checks the legs against Transitous and writes a report
coverage_check.py     which European countries, links and ferries Transitous has timetables for
src/journeys.py       loading, validation and the journey router
tests/                routing tests (python3 -m unittest discover -s tests) and the browser check of the built pages (check_pages.py)
src/make_map.py       the map pages (out/site/) from src/map_template.html (the page: HTML, CSS and JavaScript)
src/i18n.py           page texts in the map's language (data/i18n/), with English as the fallback
src/co2.py            rough CO2 per journey vs flying
src/transitous.py     talking to the Transitous API (used by add_leg.py and the checker)
src/db_stations.py    DB station numbers from Trainline's open station list (for bahn.de links, D-54)
.github/weekly_issue.py  one issue per week for the workflow's reports (D-49)
.githooks/pre-commit  refuses broken YAML, malformed pairs.txt lines and failing routing tests (git config core.hooksPath .githooks)
.github/workflows/update-map.yml  the weekly update (below)
```

## Use

```
pip install pyyaml
python build.py             # travel date = next Monday
python build.py --date 2026-11-17
python build.py transfer=15        # minimum change time in minutes (default: settings, 20)
python build.py night=02           # a wait past 02:00 counts as a hotel night (default: settings, 01:00)
python build.py start=08:00        # leave in the morning (default: each origin's start_time)
python build.py dates=2026-12-08,2026-12-11,2026-12-12   # travel dates to switch between on the map
python build.py starts=06:00,17:00  # morning / evening switch on the map (default: each origin's start_times)
python build.py only=Copenhagen     # build just one origin's map (quick test; summary.json not written)
python build.py --help             # all options
python add_leg.py "Stockholm -> Malmö : X2 523"   # add a train, looked up in Transitous
python add_leg.py "Copenhagen -> Malmö : *"       # all direct trains of the day as one entry
python add_leg.py                                 # add several, one per line
python add_leg.py --file pairs.txt --build        # a whole list; summary at the end, then rebuild
python add_leg.py --file pairs.txt --new          # only lines not in legs.yaml yet (quick)
python add_leg.py --file pairs.txt --oldest-first --budget 240
                                                  # oldest data first, stop starting lines after 240 min
python add_leg.py "A -> B : name every 60 07:00-21:00 2:17"          # your own regular departures
python add_leg.py "A -> B : name every 30 06:00-22:30 0:45 mon-fri"  # ...only on weekdays
python add_leg.py --file pairs.txt --date 2026-12-03 --days tue,fri,sat,sun
                                                  # sample week and days (default: next week, tue,sat,sun)
python check_timetables.py  # needs internet; compares legs.yaml with live timetables
python tidy_legs.py         # legs.yaml entries no pairs.txt line looks after; --apply removes covered old trains
python routes_to_pairs.py routes.txt   # route lists ('Madrid – Zaragoza – Barcelona') -> pairs.txt lines; --append adds them
```

Outputs in `out/`:

- `site/` – the map pages and pictures, as published on GitHub Pages (not committed).
- `routes.md`, `routes-<origin>.md` – the fastest journey from each origin to every capital, with full
  itineraries, waits and hotel nights, and a table of the journeys without night trains.
- `summary.json` – what each map reaches; the weekly check compares it with last week's.
- `map.html`, `network*.json` – the Helsinki map as a fragment, and the data behind each map (not committed).

## Automatic weekly update

Every Monday at 03:00 (Finnish winter time) GitHub Actions looks up next week's trains,
rebuilds the map for Tue, Fri, Sat and Sun, checks it and publishes it at
https://matti-mane-kinnunen.github.io/maatapitkin/ (Helsinki), with `stockholm.html`,
`copenhagen.html`, `london.html`, `berlin.html`, `paris.html` and `rome.html` next to it.

**In a blog post** (Blogger: *HTML view*), a link that opens the map full screen works best – a blog
column is too narrow for the map and the list side by side:

```html
<p><a href="https://matti-mane-kinnunen.github.io/maatapitkin/" target="_blank" rel="noopener">
  <img src="https://matti-mane-kinnunen.github.io/maatapitkin/preview-helsinki.png"
       alt="Map of train journeys from Helsinki to capitals in Europe and around the Mediterranean" style="width:100%;height:auto"></a></p>
<p><a href="https://matti-mane-kinnunen.github.io/maatapitkin/" target="_blank" rel="noopener">Open the map full screen</a></p>
```

or embed the map itself (it fits itself to the width, but is tall):

```html
<iframe src="https://matti-mane-kinnunen.github.io/maatapitkin/" style="width:100%;height:1600px;border:0"></iframe>
<p><a href="https://matti-mane-kinnunen.github.io/maatapitkin/" target="_blank" rel="noopener">Open the map full screen</a></p>
```

**Link previews** (Facebook, LinkedIn, WhatsApp, Slack …): each page carries Open Graph tags – title,
a one-line description with the number of capitals, and a picture, `static/preview-<origin>.png`
(1200 × 630). The pictures are made by hand, not every week: refresh them when a map is added or the
network changes a lot (ask Claude, or screenshot the map). Facebook keeps a preview once a link has
been shared; to refresh it, paste the link into the
[Sharing Debugger](https://developers.facebook.com/tools/debug/) and press *Scrape again*.

- Add a connection: edit `pairs.txt` (on github.com or locally + push); a run starts by itself,
  looks up only the new lines, and the map is updated when it finishes (lookup, build and page check).
- Run it now: Actions → *Update map* → *Run workflow*.
- If an update looks broken (far fewer trains), it is not published and an issue is opened.
- Before publishing, a real browser opens every map and every journey in it – each travel day,
  start time, with and without night trains, the alternatives – and checks that the timetable
  shows, every bahn.de link starts at a departure of that journey, the controls work and there
  are no JavaScript errors (`tests/check_pages.py`, FIX-14; ~2 min per map). A problem holds the
  update back like a lost capital. Locally: `pip install playwright && python3 -m playwright
  install chromium`, then `python3 tests/check_pages.py out/site`.
- If the lookup finds something that needs you (a line lost its trains, an impossibly fast leg,
  a new place), an issue lists just that; GitHub emails it. No email means nothing to do.
  There is one issue per week: later runs that week add a comment only when they find something
  new, and last week's issue is closed.
- `git pull` before editing locally – the workflow commits the new timetable data.
- A full run stops starting new lines after 4 hours; the lines it didn't reach keep last
  week's data and are looked up first next time.

Links to a journey: `…/maatapitkin/#lisbon/sat/no-night/fewestchanges` – place, then
optionally the day (`tue`, `fri`, `sat`, `sun`), `no-night`, `morning`, and the journey option. The
map's *Copy link* button gives the link for whatever is on screen.

## Safety net before each commit

`.githooks/pre-commit` refuses a commit when a YAML file doesn't read, a pairs.txt line isn't
`A -> B : train`, or – when `src/journeys.py` or `tests/` change – the routing tests fail. Turn it on
once per clone:

```
git config core.hooksPath .githooks
```

(`git commit --no-verify` skips it in an emergency.)

**Routing tests** (FIX-15): `tests/test_journeys.py` checks the router's rules one by one on tiny
made-up networks – change times (per station, ferry and Eurostar check-in), hotel nights, the morning
rule (and a place's own, Budapest 05:00), the 8-hour minimum hotel stay, quiet hours, night trains and
ferries, run days, `every`/`times` entries, the search objectives. Run them with

```
python3 -m unittest discover -s tests -v
```

The weekly workflow runs them first and stops if one fails. When you change a rule on purpose, change
its test too.

## How journeys are built

Each journey is built for a real travel date, not just by adding up leg durations:

- A leg runs only on its `runs` weekdays and inside `valid_from`/`valid_to`.
- A change takes `min_transfer` minutes (20), or a station's own time: longer where you change station (Paris 60 min, London 60, Madrid 40, Istanbul 60), shorter at small border stations with planned connections (Valga, Riga, Mockava, Abrantes 10). Staying on the same train needs no change time. Ferries need 45 min check-in, or the port's own (Umeå 75 with the bus to Holmsund, Athens 75 to Piraeus, Villa San Giovanni 30, Tarifa 15), and Eurostar 60 min.
- A wait that runs through 01:00 counts as a **hotel night**, and lasts at least 8 hours (`min_hotel_stay`: arrive 01:30, leave 09:30 at the earliest). After a hotel night, nothing departs before 06:00 – or a place's own `morning_departure` (Budapest 05:00, for the only day train to Bucharest).
- Between 00:00 and 05:00 (`quiet_hours`) only night trains and night ferries run; a wait that touches those hours before an ordinary train is a hotel night too.
- No one waits more than 6 nights at one place (`max_stay_nights`): enough for a train that runs once a week.
- Night trains and night ferries count as nights on board, not hotel nights – also a ferry that leaves after midnight (Palermo 02:30): you board in the evening.

- Besides the fastest journey, each capital can get two alternatives: **fewest changes** and
  **fewest hotel nights**. They are shown only when they really save a change or a night and are at most
  `alternative_max_extra_hours` (12 h) slower. The router keeps every journey that is not beaten on all
  of arrival time, changes and hotel nights, and picks the alternatives from those.

All of these settings are in `places.yaml` → `settings`.

## CO2 estimates

Each journey on the map shows a rough CO₂ figure and compares it with flying, e.g.
*"CO₂ about 100 kg – roughly 60 % less than flying (about 260 kg)"*. It is meant to inform, not to
account: the numbers are rounded (kg to 5 or 10, percentages to 5 %). On the map, *How?* opens a short
version of this explanation under the CO₂ line.

**Source** (D-51). [Klimatsmart semester](https://klimatsmartsemester.se/sa-har-vi-raknat), Chalmers
(Jörgen Larsson), method report v5.1, factors for 2026 – one documented set for every mode, in g CO₂e per
person-km. The values are in `places.yaml` → `settings` → `co2`.

| Mode | g CO₂e per person-km | Their category |
|---|---|---|
| Electric train | 19 | El Europa (European electricity mix) |
| Electric train within FI, SE, NO | 4 | El Norden (Nordic electricity mix) |
| Bus | 30 | Diesel coach (29–32) |
| Ferry | 186 | Standard value; emissions shared between passengers and freight by revenue |
| Flight | 117 | Scheduled, economy, standard fuel, incl. high-altitude effects (×1.5) and fuel production |

**Method.**
- Journey: for each train, bus or ferry leg, the factor × the straight-line distance between the two
  places × 1.2 (tracks, roads and sea routes are longer than the straight line). A train leg between two
  places in Finland, Sweden or Norway uses the Nordic figure.
- Flight: a direct flight between the same two cities, straight-line distance (their factor is per
  great-circle km).
- Places with no flights at all (Kyiv – Ukrainian airspace is closed) get `no_flights: true` and show the
  journey's figure without a comparison.

**What it means.** Trains weigh little; **ferries weigh a lot** – per kilometre more than flying. From
Helsinki, the overnight ferry is often most of a journey's total, and Helsinki → Stockholm by ferry shows
*more* than flying. Long journeys still save 40–65 %. Ferry figures vary hugely between sources (the UK
government's 19 g is an average for foot passengers on short crossings); we use Chalmers' higher figure on
purpose, so that the map does not greenwash.

**Rough spots.** One European train figure for all electric lines (France and Switzerland are cleaner,
Poland dirtier); diesel lines (96 g) are not told apart; a cabin on a night train takes more space than a
seat; getting to and from airports and stations is left out on both sides.

To update the factors, read the new table on the Klimatsmart semester page and change the numbers in
`places.yaml` (yearly check, DATA-12).

## Visitor counts

The maps count page views with [GoatCounter](https://www.goatcounter.com) (IDEA-15, D-56):
dashboard at https://maatapitkin.goatcounter.com – views per map (`/maatapitkin/` is Helsinki,
`/maatapitkin/stockholm.html` …), where visitors came from (Facebook, the blog) and countries.
No cookies and no personal data, so no cookie banner. The page sends the request itself – the same
one GoatCounter's `count.js` would – so no outside script runs on the map. It counts only on github.io,
not in local files, automated browsers (the weekly page check) or when the browser asks not to be
tracked (Do Not Track, Global Privacy Control). The address is `settings.goatcounter` in
places.yaml; remove it to switch counting off.

## DB station numbers

Each place in `places.yaml` can have `db:`, its station number in Deutsche Bahn's planner (EVA), so that
a journey can link to a ready search on bahn.de (IDEA-14). For cities with several stations it is DB's
city-wide number (PARIS 8796001, LONDON 7096001), as the map shows cities, not stations (D-45).

The numbers come from Trainline's open station list,
[trainline-eu/stations](https://github.com/trainline-eu/stations) (Open Database License, ODbL),
downloaded to `.cache/` when needed. Places it does not cover were looked up by hand in bahn.de's own
station search. Places with no `db:` (ferry ports, islands, North Africa, Albania, Sarajevo, Andorra,
San Marino) get no bahn.de link; `db: 0` keeps a place without one.

## Next steps

Open work is tracked in [BACKLOG.md](BACKLOG.md) (FIX, DATA and IDEA items), and the choices made
along the way in [DECISIONS.md](DECISIONS.md).

