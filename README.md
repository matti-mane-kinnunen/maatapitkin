# Maata pitkin

Overland journeys from Helsinki to the European capitals, by train, ferry and bus.
This started from a hand-made Graphviz graph (MaataPitkin v1.9, April 2023, kept in data/) and replaces it
with data, a journey router and an interactive map.

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
python build.py --help             # all options
python add_leg.py "Stockholm -> Malmö : X2 523"   # add a train, looked up in Transitous
python add_leg.py "Copenhagen -> Malmö : *"       # all direct trains of the day as one entry
python add_leg.py                                 # add several, one per line
python add_leg.py --file pairs.txt --build        # a whole list; summary at the end, then rebuild
python add_leg.py --file pairs.txt --new          # only lines not in legs.yaml yet (quick)
python check_timetables.py  # needs internet; compares legs.yaml with live timetables
```

Outputs in `out/`:

- `routes.md` – the fastest journey to every capital, with full itineraries, waits and hotel nights.
- `map.html` – an interactive map with the journeys.
- `network.json` – everything above as data.

## How journeys are built

Each journey is built for a real travel date, not just by adding up leg durations:

- A leg runs only on its `runs` weekdays and inside `valid_from`/`valid_to`.
- A change takes `min_transfer` minutes, or longer where you change station (Paris 60 min, London 60, Madrid 40, Istanbul 60). Staying on the same train needs no change time. Ferries need 30 min check-in and Eurostar 45 min.
- A wait that runs through 03:00 counts as a **hotel night**. After a hotel night, nothing departs before 06:00. No one waits more than 2 nights at one place.
- Night trains and night ferries count as nights on board, not hotel nights.

- Besides the fastest journey, each capital can get two alternatives: **fewest changes** and
  **fewest hotel nights**. They are shown only when they really save a change or a night and are at most
  `alternative_max_extra_hours` (12 h) slower. The router keeps every journey that is not beaten on all
  of arrival time, changes and hotel nights, and picks the alternatives from those.

All of these settings are in `places.yaml` → `settings`.

## Next steps

1. **Fix the 6 flagged legs** (`build.py` prints them).
2. **Let corridors carry several departures.** Today each leg is a single train. Turning a leg into a *corridor* (e.g. Hamburg → Munich) with all its departures that day, filled in by the checker from Transitous, lets the router choose between them. You keep deciding which corridors are sensible.
3. **Add the missing capitals**, starting with Tallinn, Riga and Vilnius, then the western Balkans.
