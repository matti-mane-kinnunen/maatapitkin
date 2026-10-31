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
| D-16 | Time zones in door-to-door times | 31.10.2026 | Accepted |
| D-17 | Trains that do not run every day | – | Superseded by D-24 |
| D-18 | The map fits itself to the data; labels never overlap | 31.10.2026 | Accepted |
| D-19 | Capitals are coloured by arrival day | 31.10.2026 | Accepted |
| D-20 | Zoom and pan on the map | 31.10.2026 | Accepted |
| D-21 | Show day boundaries and hotel nights on the selected journey | 31.10.2026 | Accepted |
| D-22 | A connection's departures on hover | 31.10.2026 | Accepted |
| D-23 | Search and filter the destinations | 31.10.2026 | Accepted |
| D-24 | Look trains up on sample days and record the days they run | 31.10.2026 | Accepted |
| D-25 | No ordinary travel at night (quiet hours 00:00–05:00) | 31.10.2026 | Accepted |
| D-26 | Journeys leave Helsinki with the evening train | 31.10.2026 | Accepted |
| D-27 | Journeys with or without night trains | 31.10.2026 | Accepted |
| D-28 | Several travel dates on the map | 31.10.2026 | Accepted |

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

**See also** D-25 (quiet hours).

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
**Date:** 31.10.2026 · **Status:** Accepted

**Decision.** All clock times stay local, as on tickets and timetables. Door-to-door times and
the journey times in the departures box are corrected for time zones (each place gets its
country's zone, Central European Time unless listed; summer time is handled). The arrivals
list is sorted by the real arrival moment.

**Effect.** Stockholm 12 h 55 → 13 h 55, London and Lisbon +2 h, Ankara −1 h; the Turku–
Stockholm night ferry takes 10 h 35, not 9 h 35. The routing itself was already right:
connections compare times at the same place, in that place's zone.

## D-17 Trains that do not run every day
**Status:** Superseded by D-24

`add_leg.py` looks trains up on one travel date and stores them as if they ran daily. Seasonal
trains (Snälltåget) and weekday-only services can be wrong. Options: query several dates and
derive `runs:`, or keep adding `runs:` / `valid_from/to` by hand.

## D-18 The map fits itself to the data; labels never overlap
**Date:** 31.10.2026 · **Status:** Accepted

**Context.** With the network grown to 113 places, Casablanca and Marrakech fell outside the
fixed map area, and labels ran into each other (Pristina/Sofia, Strasbourg/Offenburg,
Vienna/Bratislava).

**Decision.**
- The map area is fitted to all places in the data plus a margin (wider on the east for
  labels). Capitals without connections are included if they lie within 4° of the network;
  farther ones (Reykjavik) do not stretch the map and stay in the "not covered" list. The
  country outlines (`data/basemap.geojson`) now cover lat 25–72, lon −32–50.
- Each label tries up to eight spots around its marker and takes the first that overlaps no
  other label or marker. Helsinki and the capitals always get a label (earliest arrivals
  first); capitals without connections only where there is room; other cities only along the
  selected route and while hovered.
- Click targets of places that sit almost on top of each other are moved just beside the
  marker so every place stays clickable.

**Why.** The map should stay readable as pairs.txt grows, without hand-tuning positions.

## D-19 Capitals are coloured by arrival day
**Date:** 31.10.2026 · **Status:** Accepted

**Decision.** Each reached capital's marker is coloured by the day it is reached (day 1 =
the travel date), like the day clusters of the original graph. Arrival day is ordered, so it
uses one hue, light to dark (blue, so it does not clash with the orange route highlight);
days 6 and later share the darkest step. Dark mode has its own steps, with later days
brighter. Both ramps were checked with the dataviz validator (monotone lightness, visible
steps, contrast with the map). The day is also written out – in the legend with its date,
in the arrivals list and in the tooltip – so the colour is never the only cue.

**Why.** Shows at a glance how far you get in one, two or three days.

## D-20 Zoom and pan on the map
**Date:** 31.10.2026 · **Status:** Accepted

**Decision.** The map zooms (mouse wheel or trackpad pinch around the pointer, double-click,
+ / − buttons, up to 8×) and pans by dragging; "Fit" shows the whole map again. On a phone,
pinch zooms; one finger pans once zoomed in, and at full view it scrolls the page as before.
Labels, markers and lines keep their size on screen, so zooming in spreads crowded areas
out; labels are laid out again for the visible part, and from 2× the other cities get labels
where there is room. A drag that starts on a city pans – it never opens an itinerary.

**Why.** Central Europe and Italy were too dense to read at one scale. Zooming the drawing
itself (no map tiles) keeps the page self-contained and sharp at any zoom.

## D-21 Show day boundaries and hotel nights on the selected journey
**Date:** 31.10.2026 · **Status:** Accepted

**Decision.** On the selected journey, a numbered badge marks where each new day begins: on
the line where midnight passes on board (night train or ferry), or under the station if it
passes while waiting there. A bed badge marks each hotel night. Badges on a line slide along
it to stay clear of other badges; labels move out of the way of badges. Hovering a badge
explains it ("Day 3 begins on the night train Hamburg → Basel"). The itinerary below the map
is split into the same days with headings ("Day 2 · Tue 3.11.").

**Why.** The journey reads as daily stages, like the day clusters of the original graph, and
shows at a glance where the nights are spent.

## D-22 A connection's departures on hover
**Date:** 31.10.2026 · **Status:** Accepted

**Decision.** Hovering a line between two places (tapping it on a phone) shows its trains:
per service the number of departures, how often it runs (rounded, e.g. "every 30 min"), the
typical journey time, the departure times (shortened when there are many), "+1" for arrival
the next day, and when the timetable was last checked. Where lines lie on top of each other,
the box lists all of them (at most three) and all of them are highlighted. An invisible
12 px strip along each line makes thin lines easy to hit; places and labels stay on top, so
a click on a place still opens its itinerary.

**Why.** The map should show not only the fastest journey but what each connection offers –
the information that is in legs.yaml.

## D-23 Search and filter the destinations
**Date:** 31.10.2026 · **Status:** Accepted

**Decision.** Above the arrivals list: a search box (any place, also by alias – "Wien" finds
Vienna – ignoring accents; `/` focuses it, Enter opens the first match, Esc clears), "Arrive
by" day buttons, "No hotel nights" and "Include other cities". The list is capitals only by
default; a search also lists other cities, and places without a journey with the reason
("trains leave from here, none arrive"). "No hotel nights" also accepts a destination whose
fewest-hotel-nights alternative has none, and clicking it opens that alternative. Places
that do not pass the filters fade on the map. Filter settings are remembered per browser
(localStorage); nothing is shared or stored elsewhere.

**Why.** With 35 capitals and 70 other places the list and map needed a quick way to answer
"what can I reach in three days without a hotel?" and "is Gothenburg in the data?".

**Consequence noticed.** Göteborg has trains out but none in (`Stockholm -> Göteborg : *`
found nothing); the search now makes such gaps visible.

## D-24 Look trains up on sample days and record the days they run
**Date:** 31.10.2026 · **Status:** Accepted (settles D-17)

**Decision.** `add_leg.py` looks every line up on sample days of one week – Tuesday
(standing for Mon–Fri), Saturday and Sunday by default; `--days tue,fri,sat,sun` adds Friday
(Tuesday then stands for Mon–Thu); `--date` picks the week (default: next week). A train
found on every sample day is stored as daily; otherwise the entry gets `runs`
(`mon-fri`, `sat`, `mon-fri,sat` …). One request can therefore become several legs.yaml
entries (daily / Mon–Fri / Sat …); a rerun replaces all of them and keeps a name given by
hand. A train that runs at different times on different days gets one entry per time.
`check_timetables.py` checks each leg on a day it runs.

**Why.** Journeys should differ by travel date for real; until now every train was assumed
to run daily.

**Limits.** Fridays and Mondays are assumed to be like Tuesday unless Friday is sampled;
holidays and seasons are not detected (a second run with a `--date` in another season
would be needed). Mind the timetable change in mid-December when choosing `--date`.
A full pairs.txt run makes about three times as many requests.

## D-25 No ordinary travel at night (quiet hours 00:00–05:00)
**Date:** 31.10.2026 · **Status:** Accepted (extends D-06)

**Context.** With the run-day data, the router found journeys that rode ordinary trains in
the middle of the night (Malmö 23:53 → a 02:35 local train → Copenhagen 03:10 → wait until
06:22) without counting a hotel night, because the Copenhagen wait started after 03:00.

**Decision.** Between 00:00 and 05:00 (`quiet_hours` in places.yaml) only night trains and
night ferries may depart. A wait that touches the quiet hours before an ordinary train is a
hotel night, even if it does not pass 03:00. The map's hotel badges come from the router's
own count, so they always match.

**Why.** Nobody plans a trip through stations at night; the map must not suggest it.

## D-26 Journeys leave Helsinki with the evening train
**Date:** 31.10.2026 · **Status:** Accepted

**Context.** Once the data had all Helsinki–Turku trains, journeys started with the first
train of the day (05:26) and the day ferry, which made door-to-door times look longer and
did not match how the trip is actually planned.

**Decision.** Journeys leave Helsinki from 17:00 (`start_time` in places.yaml), i.e. with the
evening train and the night ferry, as in the original v1.9 graph. `build.py start=HH:MM`
chooses another start time.

## D-27 Journeys with or without night trains
**Date:** 31.10.2026 · **Status:** Accepted

**Context.** Not everyone wants to sleep on a train: they can be noisy, private space is
limited and the beds are short.

**Decision.** `build.py` computes every journey twice – with night trains, and without night
trains and night buses. Night ferries are always allowed (a cabin is close to a hotel room,
and Helsinki–Stockholm depends on it). The map has a switch "Night trains: allowed / avoid";
fastest, fewest changes and fewest hotel nights work in both modes, together with the
filters. Destinations that need a night train are faded and listed as "Not reachable without
night trains"; routes.md has a "Without night trains" table comparing the two.
A departure now counts as a night service on its own (runs through 01:00–05:00 and takes at
least 3 h), so a night train inside a `*` list of day trains is recognised too.

**Consequences.** On 31.10.2026, without night trains: most capitals the same or a few hours
later with a hotel night (Paris +30 min via Köln, Rome +5 h 50 via Hamburg); Bratislava,
Ljubljana and Tirana +24 h; Bern, Valletta, Bucharest, Chișinău, Sofia and Ankara not
reachable – their key links (Hamburg–Basel, Rome–Sicily, Budapest–Bucharest) exist only as
night trains in the data. Adding day trains to pairs.txt fixes that.

## D-28 Several travel dates on the map
**Date:** 31.10.2026 · **Status:** Accepted

**Decision.** `build.py` computes the journeys for several departure days – by default the
travel date and the Friday, Saturday and Sunday after it; `dates=…` or `travel_dates` in
places.yaml choose others – each with and without night trains. The map has a "Leave"
selector next to the night-train switch; the list, map, legend dates, itineraries and
filters follow it, and the choice is remembered per browser.

**Why.** With run days in the data (D-24), journeys really differ by departure day
(e.g. Paris 41 h on Tuesday, 45 h leaving on Saturday).

**Consequences.** The map page grows with each date (about 1 MB per date with both modes);
four dates give about 4 MB.

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
