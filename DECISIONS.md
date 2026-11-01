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
| D-29 | Weekly automatic update, published on GitHub Pages | 31.10.2026 | Accepted |

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

## D-29 Weekly automatic update, published on GitHub Pages
**Date:** 31.10.2026 · **Status:** Accepted

**Context.** The map is embedded in Matti's blog; copying it by hand after every timetable
change is tedious and easy to forget.

**Decision.**
- A GitHub Actions workflow (`.github/workflows/update-map.yml`) runs every Monday at 01:00
  UTC (03:00 Finnish winter time): it looks up next week's trains for every line in
  pairs.txt (Tue, Fri, Sat, Sun), builds the map for those four days, checks it, commits the
  timetable data and publishes the map on GitHub Pages
  (https://matti-mane-kinnunen.github.io/maatapitkin/). The blog embeds that page.
- It also runs when pairs.txt changes (only the new lines are looked up, so new connections
  appear within minutes) and by hand ("Run workflow", with options to refresh everything or
  to publish despite a failed check).
- `check_build.py` holds the update back – the old map stays online – if departures drop by
  more than 15 %, fewer capitals are reached, or warnings grow; the workflow then opens an
  issue (GitHub e-mails it).
- Generated map files are not committed any more (they would grow the repository by ~10 MB
  a week); only the data, routes.md and a small summary.json are.

**Why GitHub Actions.** It reaches Transitous (Claude's environments cannot), does not
depend on the Mac being awake, and every update is a reviewable, revertible commit.

**Consequences.** Pull before editing locally (`git pull`), since the workflow commits too.
A full lookup takes a few hours; the job limit is six hours – if the network grows past
that, drop Friday from the sample days or split the run.

---

## D-30 Shareable links to a journey
**Date:** 31.10.2026 · **Status:** Accepted

**Context.** Blog readers want to send each other a specific journey, e.g. "Lisbon, leaving
on Saturday, without night trains".

**Decision.** The address after `#` holds the whole view: destination, travel day, night-train
mode and journey option – `#lisbon/sat/no-night/fewestchanges`. Everything after the place is
optional. The map keeps the address up to date as you click, and a "Copy link" button copies
it (inside the blog's iframe it copies the map's own address; if the browser blocks the
clipboard, the link is shown for copying by hand). A link given in the address wins over the
filters remembered in the browser.

**Why a weekday, not a date.** The dates move every week; `sat` keeps working after each
update and still means "the Saturday shown on the map". A full date (`2026-12-12`) is
accepted too and falls back to the same weekday.

**Consequences.** Old `#lisbon` links still work. The blog's iframe can point straight at a
journey, e.g. `.../maatapitkin/#rome/fri`.

---

## D-31 Weekly lookup within a time budget, oldest first
**Date:** 31.10.2026 · **Status:** Accepted

**Context.** A full lookup takes hours and grows with pairs.txt; a GitHub job is killed
after six hours and then commits nothing.

**Decision.** `add_leg.py --file pairs.txt --oldest-first --budget 240` looks up new lines
first, then the ones checked longest ago (by the `checked:` date in legs.yaml), and starts no
new line after 240 minutes. Lines not reached keep their earlier data. The weekly and the
full manual runs use this; runs started by a pairs.txt change still look up only new lines.

**Why.** Timetables change little from week to week, so a leg checked two weeks ago is
nearly always right; a run that always finishes is worth more than one that is complete but
sometimes killed. Considered: dropping Friday from the sample days (loses data), or splitting
the run into parallel jobs (more requests at once to a free community service).

**Consequences.** The job summary says how many lines were left for next time. If that number
stays high week after week, raise the budget (up to ~300) or trim pairs.txt. After the big
timetable change in December, start one or two extra manual runs so every line is refreshed
quickly.

---

## D-32 Morning or evening departure from Helsinki
**Date:** 31.10.2026 · **Status:** Accepted

**Context.** Every journey starts from 17:00 (D-26). Some readers would rather leave in the
morning, and for some destinations a morning start arrives a day earlier.

**Decision.** The map has a "From: morning / evening" switch (and `morning` in links). The
morning journeys allow leaving from 06:00 and give, for each place, the earliest arrival on
the latest departure that still makes it – no one is sent off at 06:26 to wait all day for
the same evening ferry. Where leaving in the morning doesn't arrive sooner, the evening
journey is shown and says so. Times are set with `build.py starts=06:00,17:00` or
`start_times` in places.yaml; the default start (17:00) stays the main one in routes.md,
summary.json and the weekly check.

**Why.** "Earliest arrival" alone picks the first train of the day even when it gains
nothing. The latest departure is found by moving the start later as long as the arrival
stays the same – a few extra searches per place rather than one per Helsinki departure.

**Consequences.** The build takes about 30 s instead of 5 s. Unchanged journeys are stored
as references, so the page stays about the same size. With today's data, only Tallinn, Riga
and Vilnius gain from a morning start; a morning Helsinki → Turku train (for the 08:45 day
ferry to Stockholm) is the obvious missing piece.

**Update 1.11.2026 (IDEA-02).** The morning option starts at 05:00 instead of 06:00 (`start_times` in places.yaml), so IC 941 Helsinki 05:26 → Turku 07:39 reaches the 08:45 Viking day ferry: Stockholm the same evening (18:55) and most of western Europe 2–14 h sooner. The latest-departure rule keeps everyone else on later trains.

---

## D-33 A "direct train" must really run from A to B
**Date:** 31.10.2026 · **Status:** Accepted

**Context.** Before deciding whether an answer is one direct train, the lookup drops walks and
city transport at both ends – and buses counted as city transport. So "AVE Madrid → Málaga,
then a bus to Algeciras" was stored as an AVE Madrid → Algeciras arriving at Málaga's time,
and the same mechanism produced the Tarifa trains, Helsinki → Tampere in 3 minutes, Madrid →
Santiago by Madrid commuter train and about 100 other impossible departures.

**Decision.**
- A train counts for A → B only if its first stop is near A and its last stop near B: within
  40 % of the A–B distance, at least 8 and at most 25 km (Istanbul Halkalı is 22 km out;
  Malmö → Copenhagen is 28 km in all). Applies to `*` lookups, single trains and
  check_timetables.py.
- The lookup says which answers it left out and where they really end
  ("Not counted … Málaga María Zambrano (3×)").
- When a `*` lookup gets answers from Transitous but none is a real direct train, the old
  entries for that line are removed (they were wrong, or the train is gone). If Transitous
  gives no answers at all, the old entries are kept.

**Why.** The stations' coordinates are in every answer, so this check is exact where a speed
or name rule would only guess.

**Consequences.** The next full lookup replaces the wrong departures. Lines that only ever
had wrong data get removed; the job summary lists them. Madrid → Algeciras should keep the
real Alvia 08:30–13:59; if it doesn't, give it by hand in pairs.txt.

---

## D-34 Namesakes and impossible speeds when adding legs
**Date:** 31.10.2026 · **Status:** Accepted

**Context.** "Bucharest -> Ruse" put Ruse at Ruše in Slovenia (the same letters without
accents): wrong map position and wrong time zone. Nothing warned about it.

**Decision.**
- A new place is looked up with the other end of the leg in mind: of namesakes, the one
  nearest to it wins (Ruse, Bulgaria, 65 km from Bucharest).
- When namesakes are far apart, the summary says which one was taken and where the others
  are ("Names I guessed").
- A leg that would need more than 300 km/h in a straight line (time zones corrected) is
  flagged in the summary as "Impossibly fast" – usually a wrong place.
- Data: Ruše → Ruse (BG, main station 43.821, 25.955) for the Bucharest – Ruse – Sofia legs
  (1095 10:46–13:40, IC 463 14:25–20:41, checked against BDŽ and Seat61).

**Consequences.** Lines whose both places are new still have nothing to compare with; the
summary warning is the safety net there.

---

## D-35 Every leg comes from a pairs.txt line
**Date:** 1.11.2026 · **Status:** Accepted

**Context.** 256 of 564 entries in legs.yaml had no pairs.txt line: 66 `*` lines and 18
own-time lines added with add_leg.py, and 78 single trains from the original v1.9 graph
(2023 times). The weekly run only refreshes pairs.txt lines, so these silently went stale.

**Decision.**
- pairs.txt is the list of everything: the add_leg.py lines were copied in, the original
  graph's pairs got `*` lines, and its connections stored as one leg ("ICE 228 + RE1") and
  ferries got own-time lines. Rome → Vatican (metro, no timetable) stays only in legs.yaml.
- `tidy_legs.py` lists entries no line looks after and, with `--apply`, removes old single
  trains that a `*` line covers (same time and days), that have moved (the `*` line has the
  pair's current trains, none at that time), or that have expired. 21 removed now; 8 changed
  arrivals in the comparison, all from TGV 6077 Paris – Marseille, which now leaves at 14:10
  and not on Sundays.
- "Partial" trains (the `*` line has them, but not on every day they claim, e.g. NJ 471 not
  on Sunday) are kept until checked by hand: removing them made 28 arrivals later, and a
  missing day can be a gap in Transitous rather than a real change.
- When add_leg.py replaces an entry, a hand-written note is kept. Service names must not
  contain the words ferry, bus, train or night (they are read as flags): "Croatia Ferry 53"
  became "Croatia Ferries 53".

**Consequences.** After the next lookup has added the 39 new `*` lines, run
`python3 tidy_legs.py --apply` again to drop the old trains they cover. pairs.txt now has
about 190 lines; the weekly time budget (D-31) spreads the lookups over more than one week
if needed.

---

## D-36 More time for changes, with exceptions at small stations
**Date:** 1.11.2026 · **Status:** Accepted

**Context.** Matti wants journeys with comfortable margins: 10 min changes and 30 min ferry
check-in were tight, and Eurostar's passport control is unpredictable.

**Decision.**
- Settings: change 20 min (was 10), ferry check-in 45 min (was 30; includes getting from the
  station to the port), Eurostar 60 min (was 45), a wait past 01:00 is a hotel night (was
  03:00). No departure before 06:00 after a hotel night (unchanged).
- A station's own `min_transfer` now wins in both directions (before it could only lengthen):
  longer where you change station (Paris, London, Madrid, Istanbul), shorter at small border
  stations whose connections are planned and often on the same platform: Valga, Riga,
  Mockava, Abrantes 10 min. Rome's 15 min was dropped (20 applies).
- A port may have its own `ferry_checkin`: Villa San Giovanni 30 min (the foot-passenger
  boats leave next to the station). Bari stays 45 (the port is a few km away).

**Consequences.** No destination is lost; 141 of 962 arrivals are later. Tirana and Durrës
are a day later (the Bari ferry 30 min after the train), Messina 19 h later and Florence
later (NJ 471 – Milan at Basel was a 12 min change). `build.py transfer=N` now sets the
normal change time but not at stations with their own.

---

## D-37 Purpose: an encouraging map, not a journey planner
**Date:** 1.11.2026 · **Status:** Accepted

**Context.** Growing the network from published route lists (e.g. Interrail's AVE routes)
raised the question of how big pairs.txt and the map should get, and whether to go
"every city to every city".

**Decision.** The map's purpose is to help people wondering how to plan an Interrail trip
get over the first fear that train travel is difficult and slow. It is not a journey planner
(that would be re-implementing Transitous or bahn.de). Choices follow from that:
- pairs.txt is a curated backbone of good trains, not complete coverage.
- Journeys are realistic, with comfortable margins (D-36), not optimal to the minute.
- The map must stay readable and light enough for a phone and a blog iframe.
- `routes_to_pairs.py` turns route lists into pairs.txt lines: neighbouring stops plus the
  whole way (so through trains count as one train), one direction unless `--both`, and it
  only prints suggestions unless `--append`.

**Limits to keep in mind.** About 47 s of lookup per `*` line: up to ~300 lines are refreshed
every week, ~600 within two weeks; Transitous is a free community service, so stay below
roughly 500–600 lines. The page (3.9 MB at 127 places) should stay under ~8 MB; beyond about
200 places, load each travel day's data on demand. A second origin (e.g. London) needs lines
in both directions and its own page; a few origins are fine, all-to-all is out of scope.

---

## D-38 An issue only when the lookup needs a person
**Date:** 1.11.2026 · **Status:** Accepted

**Context.** Transitous data is uneven (Spanish long-distance trains were missing as direct
trains; wrong stations slipped through before D-33). Reading the full lookup log every Monday
is too much to do reliably.

**Decision.** `lookup_report.py` reduces the log to what needs a person: lines that lost their
trains ("removed N old entries") or failed with an error, "Impossibly fast" legs, new places,
guessed names, and lines left for next time. The workflow opens a GitHub issue with that list
(GitHub emails it) and adds it to the job summary. A quiet week opens nothing. Lines that never
find direct trains and had nothing to lose are not reported. A held-back map still gets its
own issue (D-29), now naming the capitals and places it would lose.

**Why an issue.** It needs no extra secrets or services (the workflow's own GITHUB_TOKEN with
`issues: write`), it emails the owner, and it can be closed when handled – a small to-do list.
The report text comes from timetable data, so it is passed to `gh` as a file, never pasted
into the shell script.

---

## D-39 A hotel night lasts at least 8 hours
**Date:** 1.11.2026 · **Status:** Accepted

**Context.** Journeys sometimes arrived in the middle of the night and counted a short wait as
a hotel night, e.g. Köln 03:14 → 06:39 (3 h 25) on the way to Lisbon (FIX-07).

**Decision.** After a hotel night the next departure must be at least `min_hotel_stay` (8 h)
after arriving, as well as no earlier than `morning_departure` (06:00): arrive 01:00, leave 09:00
at the earliest; arrive 21:00, leave 06:00. Matti's rule: enough for at least a short sleep.

**Consequences.** No destination lost; 87 of 976 arrivals later (Helsinki map, 3.11.), the
largest in the no-night-train mode (Lisbon, Porto, Faro +1 day). With night trains the router
now prefers a night on board over a short hotel stop where one exists.

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
