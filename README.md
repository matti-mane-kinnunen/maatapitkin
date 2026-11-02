# Maata pitkin

Overland journeys from Helsinki to the European capitals, by train, ferry and bus.

**Maps.** One page per origin, listed under `origins` in places.yaml: `index.html` (Helsinki),
`stockholm.html`, `copenhagen.html`; each links to the others at the top.

**Purpose.** To help people wondering how to plan an Interrail trip get over the first fear
that train travel is difficult and slow: a map that shows it can be done, how long it takes,
and a sensible way to do it. It is not a journey planner – for booking, use the operators,
bahn.de or Transitous. So the network is a curated backbone of good trains, journeys are
realistic rather than optimal to the minute, and the map has to stay readable on a phone.
This started from a hand-made Graphviz graph (MaataPitkin v1.9, April 2023, kept in data/) and replaces it
with data, a journey router and an interactive map.

See DECISIONS.md for what was decided and why.

```
data/legs.yaml        every leg: from, to, dep+arr (or times: [...] or every: N), service, mode, night, runs, valid_from/to
data/places.yaml      coordinates, capitals, change times per station, routing settings
data/basemap.geojson  country outlines for the map (Natural Earth, public domain)
build.py              builds everything in out/
check_timetables.py   re-checks the legs against Transitous and writes a report
coverage_check.py     which European countries, links and ferries Transitous has timetables for
add_leg.py            adds trains one at a time: "A -> B : train", looked up in Transitous
src/journeys.py       loading, validation and the journey router
src/make_map.py       interactive map page (out/map.html)
src/transitous.py     talking to the Transitous API (used by the checker and add_leg.py)
```

## Use

```
pip install pyyaml
python build.py             # travel date = next Monday
python build.py --date 2026-11-17
python build.py transfer=15        # minimum change time in minutes (default 10)
python build.py night=01           # a wait past 01:00 counts as a hotel night (default 03)
python build.py start=08:00        # leave Helsinki in the morning (default 17:00, the evening train)
python build.py dates=2026-12-08,2026-12-11,2026-12-12   # travel dates to switch between on the map
python build.py starts=06:00,17:00  # morning / evening switch on the map (default 06:00 and the start time)
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

- `routes.md` – the fastest journey to every capital, with full itineraries, waits and hotel nights,
  and a table of the journeys without night trains.
- `map.html` – an interactive map with the journeys.
- `network.json` – everything above as data.

## Automatic weekly update

Every Monday at 03:00 (Finnish winter time) GitHub Actions looks up next week's trains,
rebuilds the map for Tue, Fri, Sat and Sun, checks it and publishes it at
https://matti-mane-kinnunen.github.io/maatapitkin/ – embed it with

```html
<iframe src="https://matti-mane-kinnunen.github.io/maatapitkin/" style="width:100%;height:1600px;border:0"></iframe>
```

- Add a connection: edit `pairs.txt` (on github.com or locally + push); the map is updated
  within minutes.
- Run it now: Actions → *Update map* → *Run workflow*.
- If an update looks broken (far fewer trains), it is not published and an issue is opened.
- If the lookup finds something that needs you (a line lost its trains, an impossibly fast leg,
  a new place), an issue lists just that; GitHub emails it. No email means nothing to do.
- `git pull` before editing locally – the workflow commits the new timetable data.
- A full run stops starting new lines after 4 hours; the lines it didn't reach keep last
  week's data and are looked up first next time.

Links to a journey: `…/maatapitkin/#lisbon/sat/no-night/fewestchanges` – place, then
optionally the day (`tue`, `fri`, `sat`, `sun`), `no-night`, `morning`, and the journey option. The
map's *Copy link* button gives the link for whatever is on screen.

## Safety net before each commit

`.githooks/pre-commit` refuses a commit when a YAML file doesn't read or a pairs.txt line isn't
`A -> B : train`. Turn it on once per clone:

```
git config core.hooksPath .githooks
```

(`git commit --no-verify` skips it in an emergency.)

## How journeys are built

Each journey is built for a real travel date, not just by adding up leg durations:

- A leg runs only on its `runs` weekdays and inside `valid_from`/`valid_to`.
- A change takes `min_transfer` minutes (20), or a station's own time: longer where you change station (Paris 60 min, London 60, Madrid 40, Istanbul 60), shorter at small border stations with planned connections (Valga, Riga, Mockava, Abrantes 10). Staying on the same train needs no change time. Ferries need 45 min check-in (30 at Villa San Giovanni) and Eurostar 60 min.
- A wait that runs through 01:00 counts as a **hotel night**. After a hotel night, nothing departs before 06:00. No one waits more than 2 nights at one place.
- Night trains and night ferries count as nights on board, not hotel nights.

- Besides the fastest journey, each capital can get two alternatives: **fewest changes** and
  **fewest hotel nights**. They are shown only when they really save a change or a night and are at most
  `alternative_max_extra_hours` (12 h) slower. The router keeps every journey that is not beaten on all
  of arrival time, changes and hotel nights, and picks the alternatives from those.

All of these settings are in `places.yaml` → `settings`.

## CO2 estimates

Each journey on the map shows a rough CO₂ figure and compares it with flying, e.g.
*"CO₂ about 110 kg – roughly 65 % less than flying (about 300 kg)"*. It is meant to reassure, not to
account: the numbers are rounded (kg to 5 or 10, percentages to 5 %).

**Source.** The UK government's greenhouse gas conversion factors (DESNZ, 2026, full set), in kg CO₂e
per passenger-km. They are open, documented and published every year (not every factor is renewed every
year: in 2026 rail and coach were, flights and ferries were not); the values and the rows they come
from are in `places.yaml` → `settings` → `co2`.

| Mode | kg CO₂e per passenger-km | DESNZ row |
|---|---|---|
| Train | 0.031 | Rail, national rail |
| Eurostar | 0.011 | Rail, international rail |
| Bus | 0.039 | Coach |
| Ferry | 0.019 | Ferry, foot passenger |
| Flight | 0.126 | Short-haul, economy, with the non-CO₂ effects at altitude (+70 %) |

**Method.**
- Journey: for each train, bus or ferry leg, the factor × the straight-line distance between the two
  places × 1.2 (tracks, roads and sea routes are longer than the straight line; the map stores no
  track geometry).
- Flight: a direct flight between the same two cities, straight-line distance + 8 % (indirect routes,
  holding patterns), short-haul economy factor including the non-CO₂ effects – as the UK government's own
  journey comparisons do. DESNZ counts all of Europe and North Africa as short-haul.
- Places with no flights at all (Kyiv – Ukrainian airspace is closed) get `no_flights: true` and show the
  journey's figure without a comparison.

**Rough spots, in both directions.**
- One train factor for all of Europe. Electric trains in Sweden, France, Switzerland or Austria emit much
  less; diesel lines (parts of the Baltics, Poland, the Balkans) more. The UK average is a middle value,
  so for most journeys the saving is probably *understated*. [EcoPassenger](https://uic.org/ecopassenger)
  (UIC/IFEU) accounts for each country's electricity mix and is good for checking a route by hand.
- A cabin on a night train or a night ferry takes more space per passenger than a seat; the factors do
  not separate that.
- The ferry factor is an average for foot passengers; long overnight crossings (Marseille – Algiers,
  21–23 h) on big cruise ferries probably emit more per passenger-km.
- Getting to and from airports and stations is left out on both sides.

To update the factors (once a year, DATA-12), download the new set (2026 came only as the full set) from
[gov.uk](https://www.gov.uk/government/collections/government-conversion-factors-for-company-reporting),
read the same rows and change the numbers in `places.yaml`.

## Next steps

Open work is tracked in [BACKLOG.md](BACKLOG.md) (FIX, DATA and IDEA items), and the choices made
along the way in [DECISIONS.md](DECISIONS.md).

