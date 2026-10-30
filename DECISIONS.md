# Maata pitkin – decision log

What we decided, why, and what follows from it. Newest decisions go at the end; the
table below is the index. When a decision is changed, don't rewrite the old entry:
add a new one and mark the old one **Superseded by D-xx**.

**Statuses:** Accepted · Superseded · Open (still to decide)

| # | Decision | Date | Status |
|---|---|---|---|
| D-01 | Keep a curated network of connections, fill in the trains automatically | 30.10.2026 | Accepted |
| D-02 | YAML data files are the single source of truth | 30.10.2026 | Accepted |
| D-03 | Transitous is the timetable source | 30.10.2026 | Accepted |
| D-04 | Build real journeys for a travel date, not sums of leg durations | 30.10.2026 | Accepted |
| D-05 | Realistic change times, longer at some stations | 30.10.2026 | Accepted |
| D-06 | A wait through the night is a hotel night | 30.10.2026 | Accepted |
| D-07 | Show alternatives only when they are worth it | 30.10.2026 | Accepted |
| D-08 | A connection holds all its departures, not one train | 30.10.2026 | Accepted |
| D-09 | Add trains as `A -> B : train`; pairs.txt is the main input | 30.10.2026 | Accepted |
| D-10 | The checker reports; people decide what changes | 30.10.2026 | Accepted |
| D-11 | Guard against wrong places when names are looked up | 30–31.10.2026 | Accepted |
| D-12 | The interactive map is the main output | 30.10.2026 | Accepted |
| D-13 | Remove the Graphviz graph | 31.10.2026 | Accepted |
| D-14 | Git workflow: Claude commits on the Mac, Matti pushes | 30.10.2026 | Accepted |
| D-15 | Which places count as capitals | 30.10.2026 | Accepted |
| D-16 | Time zones in door-to-door times | – | Open |
| D-17 | Trains that do not run every day | – | Open |

---

## D-01 Keep a curated network of connections, fill in the trains automatically
**Date:** 30.10.2026 · **Status:** Accepted

**Context.** The first version (MaataPitkin v1.9, April 2023) was built by hand: pick sensible
connections, look up trains on bahn.de and others, draw them in Graphviz. It looked good but
could not be kept up to date. The alternative was to ask a journey planner for complete
Helsinki → capital journeys.

**Decision.** Keep the human part – which city-to-city connections make sense, which ferries,
where to stop overnight – and automate the rest: the trains and times for each connection,
and how they combine into journeys.

**Why.** Journey planners do not plan multi-day trips with hotel stops, often skip ferries, and
do not know the preference for direct, sensible routes. The hand-picked network is the
valuable part of the old work; the timetables are the part that goes stale.

**Consequences.** The network grows by adding lines to pairs.txt (D-09). Full journeys from a
planner can still be used to cross-check results.

## D-02 YAML data files are the single source of truth
**Date:** 30.10.2026 · **Status:** Accepted

**Decision.** `data/legs.yaml` holds every connection and its departures; `data/places.yaml`
holds every place (coordinates, country, capital flag, change time, aliases) and the routing
settings. Everything else – routes.md, the map, network.json – is generated from them.

**Why.** Text files are easy to read, edit by hand, review in git and fix. The 83 arrows of the
v1.9 graph were converted into legs.yaml as the starting data; the original .dot file is kept
in `data/` for reference.

## D-03 Transitous is the timetable source
**Date:** 30.10.2026 · **Status:** Accepted

**Context.** Options were bahn.de (its old API was shut down; the unofficial `db-vendo-client`
replaces it, rate-limited), operator websites, or Transitous – a free, community-run
European journey planner (MOTIS) with an open API.

**Decision.** Use Transitous for looking up and checking trains (`src/transitous.py`).

**Why.** Free, open, covers most of Europe in one API, no scraping.

**Consequences.**
- Transitous is blocked from Claude's sandbox, so every tool that talks to it runs in
  Terminal on Matti's Mac.
- It lacks some data: Spain–Portugal, Turkey, Greece and most ferries had no timetables in our
  checks, and Romania, Moldova and Croatia–Slovenia showed buses only. These connections get
  manually entered times (`A -> B : name HH:MM-HH:MM ferry`). `coverage_check.py` and
  `out/coverage.md` track what is covered.
- Be polite: requests are spaced out (`--pause`), and the tools identify themselves.

## D-04 Build real journeys for a travel date, not sums of leg durations
**Date:** 30.10.2026 · **Status:** Accepted

**Decision.** The router builds journeys for a real travel date (default: next Monday):
it waits for the next departure, respects the days a train runs (`runs`, `valid_from/to`),
and finds the earliest arrival with a shortest-path search on clock times (Dijkstra over
place + incoming train, so staying on the same train needs no change).

**Why.** The point is realistic, complete journeys with waits, changes and overnight stays –
"how long is each leg" is not enough.

## D-05 Realistic change times, longer at some stations
**Date:** 30.10.2026 · **Status:** Accepted

**Decision.** Default minimum change 10 min. Ferries need 30 min check-in, Eurostar 45 min.
Stations where you change between stations have their own, longer time: Paris 60, London 60,
Istanbul 60, Madrid 40. A station's time is a minimum (since 30.10.2026): a larger
`transfer=N` on the command line applies everywhere.

**Why.** Tight connections in the data must not produce journeys nobody could make.

## D-06 A wait through the night is a hotel night
**Date:** 30.10.2026 · **Status:** Accepted

**Decision.** A wait that runs through 03:00 (`night_point`, or `night=T` on the command line)
is a hotel night. After a hotel night nothing departs before 06:00. Nobody waits more than 2
nights in one place. Night trains and night ferries count as nights on board, not hotel
nights.

**Why / history.** First set to 07:00; changed to 06:00 the same day because the 06:20 AVE
from Barcelona made Madrid and Lisbon unreachable – 06:00 is still a realistic start after a
hotel.

## D-07 Show alternatives only when they are worth it
**Date:** 30.10.2026 · **Status:** Accepted

**Decision.** Besides the fastest journey, each destination may get "fewest changes" and
"fewest hotel nights". The router keeps every journey not beaten on all three of arrival time,
changes and hotel nights (a Pareto search), and shows an alternative only if it really saves a
change or a night and is at most 12 h slower (`alternative_max_extra_hours`).

**Why.** The first version picked alternatives that saved one change by waiting a whole day
(e.g. all day in Stockholm for the night train). The 12 h limit removes those.

## D-08 A connection holds all its departures, not one train
**Date:** 30.10.2026 · **Status:** Accepted

**Context.** After the timetable update, journeys to Bern, Rome and Brussels got a day longer:
with one train per connection, a few minutes' shift broke the change (arrive Basel 08:21, the
only Bern train 08:30).

**Decision.** One legs.yaml entry can hold a list of departures (`times: [...]`) or a pattern
(`every: 30, first, last, duration`). `A -> B : *` fills it with all direct trains of the day.

**Why.** Frequent routes (Eurostar, Öresundståg, Swiss IC) should be typed once and give the
router real choice.

## D-09 Add trains as `A -> B : train`; pairs.txt is the main input
**Date:** 30.10.2026 · **Status:** Accepted

**Decision.** `add_leg.py` takes `A -> B : X2 523`, `A -> B : *`, `A -> B : EST*` or
`A -> B : name HH:MM-HH:MM ferry`, looks the train up in Transitous and writes legs.yaml.
`--file pairs.txt` processes a whole list and ends with a summary; `--new` skips lines already
in the data; rerunning updates entries in place and keeps names given by hand (entries remember
their request, `query: "*"`).

**Why.** Editing legs.yaml by hand was tedious; a list of city pairs is how the network is
actually thought about.

**Consequences.** `*` takes only direct trains and skips buses unless the line says `bus`.
Removing a line from pairs.txt does not remove its trains – delete the entry in legs.yaml.

## D-10 The checker reports; people decide what changes
**Date:** 30.10.2026 · **Status:** Accepted

**Decision.** `check_timetables.py` compares legs with Transitous and writes a report; it never
edits the data. Updates are applied after review (48 legs updated on 30.10.2026, each marked
`checked:`). Trains are matched by number (EN345 = "EN 000345", NJ471 = 40471), metro and walks
at the ends are ignored, and local clock times are compared.

**Why.** The first run reported 53 of 77 trains as "different service" because of naming
differences. Automatic edits would have spread those errors into the data.

## D-11 Guard against wrong places when names are looked up
**Date:** 30–31.10.2026 · **Status:** Accepted

**Context.** Typos in pairs.txt created duplicate and wrong places (Tallin, Warsw, "Osko" in
Poland, ": Nice"). Later, correctly spelt names were matched to the wrong place: Porto → Porto
Alegre, Genoa → Canada, Tirana → a street in Sofia.

**Decision.**
- places.yaml lists aliases (Vienna: [Wien], Munich: [München], Prague: [Praha] …).
- A misspelt known city is matched to it (Tallin → Tallinn); `--file` lists every guess,
  interactive use asks first.
- A new place is accepted only if the station name resembles what was typed, it lies in
  Europe or around the Mediterranean (lat 27–72, lon −32–45), and a station in the town of
  that name is preferred.
- Malformed lines get an error instead of a guess.

**Consequences.** Always read the "Names I guessed" and "New places" parts of the summary.
Wrong places are fixed by hand in places.yaml (seven were on 31.10.2026).

## D-12 The interactive map is the main output
**Date:** 30.10.2026 · **Status:** Accepted

**Decision.** `out/map.html` is a single self-contained page: country outlines from Natural
Earth, no map tiles (the published page may not load external images). The left list shows
arrivals to capitals; every capital and city on the map shows its journey on hover and opens
the itinerary on click, with tabs for alternatives. It is also published as the "Maata pitkin"
page in claude.ai.

**Why.** Easier to explore and share than a static graph; works offline.

## D-13 Remove the Graphviz graph
**Date:** 31.10.2026 · **Status:** Accepted

**Decision.** `build.py` no longer generates the day-by-day .dot/.svg/.png graph.

**Why.** With 1,500 departures it became too cluttered to be of practical use; the map and
routes.md replace it. Graphviz is no longer needed.

## D-14 Git workflow: Claude commits on the Mac, Matti pushes
**Date:** 30.10.2026 · **Status:** Accepted

**Decision.** The repository is github.com/matti-mane-kinnunen/maatapitkin. The working copy
is ~/Code/maatapitkin; Claude works and commits there through the linked folder, Matti reviews
and pushes from Terminal (`git push --follow-tags`). Versions are tagged (v0.1 on 31.10.2026).

**Why.** Claude's environment has no GitHub login; Matti's Mac does. Data changes from Matti's
own runs are committed only after he has looked at them.

## D-15 Which places count as capitals
**Date:** 30.10.2026 · **Status:** Accepted

**Decision.** `capital: true` in places.yaml. Taken over from v1.9 with small changes: Amsterdam
is the capital of the Netherlands (The Hague is kept as seat of government, not a capital);
Belfast and the Vatican are included. Capitals with no connections yet are listed under
`not_yet_covered` and shown dashed on the map; when a connection is added they move over
automatically.

## D-16 Time zones in door-to-door times
**Status:** Open

Journey times are computed from local clock times, so connections are right but door-to-door
totals ignore time-zone changes (London −1 h, Bucharest/Sofia/Athens +1 h from Central
Europe). Options: store a time zone per place and convert, or accept it for now.

## D-17 Trains that do not run every day
**Status:** Open

`add_leg.py` looks trains up on one travel date and stores them as if they ran daily. Seasonal
trains (Snälltåget) and weekday-only services can be wrong. Options: query several dates and
derive `runs:`, or keep adding `runs:` / `valid_from/to` by hand.

---

## Template for a new decision

```
## D-xx Title in a few words
**Date:** d.m.yyyy · **Status:** Accepted

**Context.** What problem or question came up.

**Decision.** What we do.

**Why.** The reasons, and what else was considered.

**Consequences.** What follows – new work, limits, things to watch.
```
