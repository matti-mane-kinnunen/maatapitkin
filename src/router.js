/* Maata pitkin - the journey router in the browser (IDEA-21).

   A port of src/journeys.py (Router) and build.py (Journeys: route, with_alternatives,
   compute, variant, earlier_start), so the map can work out journeys for settings the
   weekly build did not cover: any date, any start time, another change time, no ferries
   or no buses. Python stays the reference:
     - tests/test_router_cases.py runs the same small cases through both routers,
     - tests/check_router.mjs compares this router with every map's precomputed journeys.
   Keep the two in step: a rule changed in journeys.py must change here too.

   Times are minutes since 00:00 on the travel date (day 1), as in journeys.py; Python's
   // and % are floor division and floored modulo, written fdiv() and mod() here. */
(function (root) {
"use strict";
const DAY = 1440;
const fdiv = (a, b) => Math.floor(a / b);
const mod = (a, b) => { const r = a % b; return r < 0 ? r + b : r; };
const hm = s => { const [h, m] = String(s).trim().split(":"); return parseInt(h, 10) * 60 + parseInt(m, 10); };
const clock = t => { t = mod(t, DAY); return String(fdiv(t, 60)).padStart(2, "0") + ":" + String(t % 60).padStart(2, "0"); };
const normService = s => String(s || "").replace(/\s+/g, "").toUpperCase();
const dayNum = iso => { const [y, m, d] = String(iso).split("-").map(Number); return Date.UTC(y, m - 1, d) / 864e5; };
const isoOf = dn => new Date(dn * 864e5).toISOString().slice(0, 10);
const weekday = dn => mod(dn + 3, 7);                     // Monday 0, as Python's date.weekday()
const cmp = (a, b) => {                                   // Python tuple comparison (nested too)
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    const x = a[i], y = b[i];
    if (Array.isArray(x)) { const c = cmp(x, y); if (c) return c; }
    else if (x !== y) return x < y ? -1 : 1;
  }
  return a.length - b.length;
};

/* A binary heap ordered like Python's heapq on tuples. */
class Heap {
  constructor() { this.a = []; }
  get size() { return this.a.length; }
  push(x) {
    const a = this.a; a.push(x); let i = a.length - 1;
    while (i > 0) { const p = (i - 1) >> 1; if (cmp(a[i], a[p]) >= 0) break; [a[i], a[p]] = [a[p], a[i]]; i = p; }
  }
  pop() {
    const a = this.a, top = a[0], last = a.pop();
    if (a.length) {
      a[0] = last; let i = 0;
      for (;;) {
        const l = 2 * i + 1, r = l + 1; let m = i;
        if (l < a.length && cmp(a[l], a[m]) < 0) m = l;
        if (r < a.length && cmp(a[r], a[m]) < 0) m = r;
        if (m === i) break;
        [a[i], a[m]] = [a[m], a[i]]; i = m;
      }
    }
    return top;
  }
}

/* --- time zones (journeys.utc_offset) -------------------------------------------- */
const FMT = {};
function offsetAt(tz, ms) {                              // minutes ahead of UTC at an instant
  const f = FMT[tz] || (FMT[tz] = new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23",
    year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric" }));
  const p = {};
  for (const x of f.formatToParts(new Date(ms))) p[x.type] = x.value;
  const local = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour % 24, +p.minute);
  return Math.round((local - fdiv(ms, 60000) * 60000) / 60000);
}
/* Offset at a local date and clock time, like Python's datetime.combine(d, t, zone) (fold=0):
   an ambiguous time (autumn) takes the earlier, summer offset; a time in the spring gap the
   offset before the change. */
function utcOffset(net, place, dn, clk) {
  const p = net.places[place] || {};
  const tz = p.tz || net.tz[String(p.country || "").toUpperCase()] || "Europe/Berlin";   // a place's own tz wins (Canaries)
  const local = (dn * DAY + clk) * 60000;
  const before = offsetAt(tz, local - 12 * 3600e3), after = offsetAt(tz, local + 12 * 3600e3);
  if (before === after) return before;
  const okB = offsetAt(tz, local - before * 60000) === before, okA = offsetAt(tz, local - after * 60000) === after;
  return okA && !okB ? after : before;
}

/* --- the network (router_data.export) ------------------------------------------------- */
function loadNetwork(data) {
  const legs = [];
  for (const g of data.legs) for (const [dep, arr, duration, night] of g.x)
    legs.push({ idx: legs.length, frm: g.f, to: g.t, service: g.s, mode: g.m || "train", dep, arr, duration,
                night: !!night, timed: dep != null, weekdays: g.w ? new Set(g.w) : null,
                vf: g.vf ? dayNum(g.vf) : null, vt: g.vt ? dayNum(g.vt) : null,
                highlight: g.h || null, note: g.n || null, issue: g.is || null, checked: g.c || "" });
  for (const l of legs) {                        // worked out once: the router asks for these all the time
    l.ns = normService(l.service);
    l.eurostar = l.ns.startsWith("EST") || l.ns.startsWith("ES");
  }
  return { places: data.places, settings: data.settings || {}, tz: data.tz || {}, legs };
}
const runsOn = (leg, dn) => !(leg.vf != null && dn < leg.vf) && !(leg.vt != null && dn > leg.vt)
  && (leg.weekdays === null || leg.weekdays.has(weekday(dn)));

const OBJECTIVES = {
  fastest: (c, h, t) => [t, c, h],
  fewest_changes: (c, h, t) => [c, t, h],
  fewest_hotels: (c, h, t) => [h, t, c],
};

/* --- journeys.Router -------------------------------------------------------------------
   opt: nightTrains (default true), minTransfer (replaces the general change time; stations
   with their own keep it, as build.py transfer=N), avoid: ["ferry", "bus"]. */
class Router {
  constructor(net, startDate, opt = {}) {
    this.net = net;
    this.nightTrains = opt.nightTrains !== false;
    this.startDay = typeof startDate === "number" ? startDate : dayNum(startDate);
    const s = net.settings;
    this.minTransfer = parseInt(opt.minTransfer ?? s.min_transfer ?? 10, 10);
    this.ferryCheckin = parseInt(s.ferry_checkin ?? 30, 10);
    this.eurostarCheckin = parseInt(s.eurostar_checkin ?? 45, 10);
    this.busTransfer = s.bus_transfer != null ? parseInt(s.bus_transfer, 10) : null;   // D-67; unset = min_transfer
    this.nightPoint = hm(s.night_point ?? "03:00");
    this.morning = hm(s.morning_departure ?? "07:00");
    this.minStay = hm(s.min_hotel_stay ?? "0:00");
    this.maxNights = parseInt(s.max_stay_nights ?? 2, 10);
    const [q0, q1] = String(s.quiet_hours ?? "00:00-05:00").replace("–", "-").split("-");
    this.quiet = [hm(q0), hm(q1)];
    const avoid = new Set(opt.avoid || []);
    this.out = new Map();
    // only departures that can run in the next search_days days (as journeys.py; US, D-67)
    const last = this.startDay + parseInt(s.search_days ?? 14, 10);
    for (const leg of net.legs) {
      if (!this.nightTrains && leg.night && leg.mode !== "ferry") continue;
      if ((leg.vt != null && leg.vt < this.startDay) || (leg.vf != null && leg.vf > last)) continue;
      if (avoid.has(leg.mode)) continue;
      if (!this.out.has(leg.frm)) this.out.set(leg.frm, []);
      this.out.get(leg.frm).push(leg);
    }
  }
  dayOf(t) { return this.startDay + fdiv(t, DAY); }

  changeTime(place, incoming, nxt) {
    if (!incoming) return 0;
    if (incoming.timed && nxt.timed && incoming.ns === nxt.ns && incoming.arr === nxt.dep) return 0;   // same train
    const here = this.net.places[place] || {};
    if (nxt.mode === "ferry") return parseInt(here.ferry_checkin ?? this.ferryCheckin, 10);
    if (nxt.eurostar) return this.eurostarCheckin;
    if ((incoming.mode === "bus" || nxt.mode === "bus") && ("bus_transfer" in here || this.busTransfer !== null))
      return parseInt(here.bus_transfer ?? this.busTransfer, 10);
    return "min_transfer" in here ? parseInt(here.min_transfer, 10) : this.minTransfer;
  }
  morningAt(place) {
    const here = this.net.places[place] || {};
    return "morning_departure" in here ? hm(here.morning_departure) : this.morning;
  }
  inQuiet(t) { const m = mod(t, DAY); return this.quiet[0] <= m && m < this.quiet[1]; }
  overlapsQuiet(a, b) {
    for (let d = fdiv(a, DAY) - 1; d < fdiv(b, DAY) + 1; d++)
      if (Math.max(a, d * DAY + this.quiet[0]) < Math.min(b, d * DAY + this.quiet[1])) return true;
    return false;
  }
  nightsBetween(a, b) {
    const first = fdiv(a - this.nightPoint, DAY) * DAY + this.nightPoint + DAY;
    return first > b ? 0 : fdiv(b - first, DAY) + 1;
  }
  stayNights(a, b, nxt = null) {
    if (nxt && nxt.night && this.inQuiet(b)) {
      const cut = fdiv(b, DAY) * DAY + this.quiet[0] - 1;
      return cut > a ? this.nightsBetween(a, cut) : 0;
    }
    let n = this.nightsBetween(a, b);
    if (n === 0 && b > a && !(nxt && nxt.night) && this.overlapsQuiet(a, b)) n = 1;
    return n;
  }
  isStay(arrival, dep, nxt) { return this.stayNights(arrival, dep, nxt) > 0; }

  board(arrival, ready, leg, firstLeg = false) {
    if (!leg.timed) {
      let t = ready;
      if (!leg.night && this.inQuiet(t)) t = fdiv(t, DAY) * DAY + this.quiet[1];
      if (!firstLeg && this.isStay(arrival, t, leg))
        t = Math.max(t, fdiv(t, DAY) * DAY + this.morningAt(leg.frm), arrival + this.minStay);
      return t;
    }
    for (let k = 0; k < this.maxNights + 2; k++) {
      const t = (fdiv(ready, DAY) + k) * DAY + leg.dep;
      if (t < ready || !runsOn(leg, this.dayOf(t))) continue;
      if (!leg.night && this.inQuiet(t)) continue;
      if (!firstLeg && this.isStay(arrival, t, leg)) {
        if (fdiv(t - arrival, DAY) >= this.maxNights) return null;
        if (mod(t, DAY) < this.morningAt(leg.frm)) continue;
        if (t - arrival < this.minStay) continue;
      }
      return t;
    }
    return null;
  }

  /* Dijkstra over states (place, incoming leg), as Router.search. */
  search(origin, start = 0, objective = "fastest") {
    // a state (place, incoming leg) is known by the leg alone (the place is where it arrives); -1: home
    const key = OBJECTIVES[objective], legs = this.net.legs;
    const lab = new Map([[-1, { node: origin, inc: -1, l: [0, 0, start] }]]);
    const parent = new Map([[-1, null]]);
    const pq = new Heap();
    pq.push([key(0, 0, start), origin, -1]);
    while (pq.size) {
      const [k, node, inc] = pq.pop();
      const [c, h, t] = lab.get(inc).l;
      if (cmp(key(c, h, t), k) < 0) continue;
      const incLeg = inc >= 0 ? legs[inc] : null;
      for (const leg of this.out.get(node) || []) {
        const ct = this.changeTime(node, incLeg, leg);
        const dep = this.board(t, t + ct, leg, incLeg === null);
        if (dep === null) continue;
        const same = incLeg !== null && ct === 0 && dep === t;
        const nc = c + (incLeg === null || same ? 0 : 1);
        const nh = h + (incLeg !== null ? this.stayNights(t, dep, leg) : 0);
        const nt = dep + leg.duration;
        const st = leg.idx, old = lab.get(st);
        if (!old || cmp(key(nc, nh, nt), key(...old.l)) < 0) {
          if (old) old.l = [nc, nh, nt]; else lab.set(st, { node: leg.to, inc: leg.idx, l: [nc, nh, nt] });
          parent.set(st, [inc, dep]);
          pq.push([key(nc, nh, nt), leg.to, leg.idx]);
        }
      }
    }
    const best = new Map();
    for (const [st, v] of lab) {
      const b = best.get(v.node);
      if (b === undefined || cmp(key(...v.l), key(...lab.get(b).l)) < 0) best.set(v.node, st);
    }
    this._lab = lab; this._parent = parent; this._best = best;
    return best;
  }
  label(place) { const st = this._best.get(place); return st === undefined ? null : this._lab.get(st).l; }

  _steps(legs) {
    const steps = [];
    legs.forEach((s, i) => {
      if (i) {
        const prev = legs[i - 1], n = this.stayNights(prev.arr, s.dep, s.leg);
        if (n) steps.push({ kind: "stay", place: s.leg.frm, from: prev.arr, to: s.dep, nights: n });
        else if (s.dep - prev.arr > 0 || s.leg.service !== prev.leg.service)
          steps.push({ kind: "change", place: s.leg.frm, from: prev.arr, to: s.dep });
      }
      steps.push({ kind: "leg", ...s });
    });
    return steps;
  }
  journey(place) {
    let st = this._best.get(place);
    if (st === undefined) return null;
    const legs = [];
    while (this._parent.get(st)) {
      const [prev, dep] = this._parent.get(st), v = this._lab.get(st);
      legs.push({ leg: this.net.legs[v.inc], dep, arr: v.l[2] });
      st = prev;
    }
    legs.reverse();
    return this._steps(legs);
  }

  /* Every journey not beaten on all of arrival, changes and hotel nights (Router.pareto).
     Returns Map place -> [[c, h, t, label id], ...]. */
  pareto(origin, start = 0, horizonDays = 10) {
    const legs = this.net.legs;
    const labels = [[0, 0, start, origin, -1, null, null]];        // c, h, t, node, inc, parent, dep
    const atState = new Map([[-1, [0]]]);                          // state = incoming leg, as in search()
    const pq = new Heap();
    pq.push([start, 0]);
    const limit = start + horizonDays * DAY;
    while (pq.size) {
      const [t, lid] = pq.pop();
      const [c, h, , node, inc] = labels[lid];
      if (!(atState.get(inc) || []).includes(lid)) continue;
      const incLeg = inc >= 0 ? legs[inc] : null;
      for (const leg of this.out.get(node) || []) {
        const ct = this.changeTime(node, incLeg, leg);
        const dep = this.board(t, t + ct, leg, incLeg === null);
        if (dep === null) continue;
        const same = incLeg !== null && ct === 0 && dep === t;
        const nc = c + (incLeg === null || same ? 0 : 1);
        const nh = h + (incLeg !== null ? this.stayNights(t, dep, leg) : 0);
        const nt = dep + leg.duration;
        if (nt > limit) continue;
        const st = leg.idx;
        if (!atState.has(st)) atState.set(st, []);
        let cur = atState.get(st);
        if (cur.some(o => labels[o][0] <= nc && labels[o][1] <= nh && labels[o][2] <= nt)) continue;
        cur = cur.filter(o => !(nc <= labels[o][0] && nh <= labels[o][1] && nt <= labels[o][2]));
        labels.push([nc, nh, nt, leg.to, leg.idx, lid, dep]);
        cur.push(labels.length - 1);
        atState.set(st, cur);
        pq.push([nt, labels.length - 1]);
      }
    }
    this._plabels = labels;
    const out = new Map();
    for (const ids of atState.values()) for (const i of ids) {
      const p = labels[i][3];
      if (!out.has(p)) out.set(p, []);
      out.get(p).push([labels[i][0], labels[i][1], labels[i][2], i]);
    }
    return out;
  }
  paretoJourney(lid) {
    const legs = [];
    while (this._plabels[lid][5] !== null) {
      const [, , t, , inc, parent, dep] = this._plabels[lid];
      legs.push({ leg: this.net.legs[inc], dep, arr: t });
      lid = parent;
    }
    legs.reverse();
    return this._steps(legs);
  }
}

/* --- co2.py ------------------------------------------------------------------------------- */
const rad = x => x * Math.PI / 180;
function km(a, b) {
  const h = Math.sin((rad(b.lat) - rad(a.lat)) / 2) ** 2
    + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin((rad(b.lon) - rad(a.lon)) / 2) ** 2;
  return 6371 * 2 * Math.asin(Math.sqrt(h));
}
const pyRound = x => { const r = Math.round(x); return (r - x === 0.5 && r % 2) ? r - 1 : r; };   // half to even
function co2(net, legs, origin, dest) {
  const cfg = net.settings.co2 || {}, f = cfg.factors || {}, P = net.places;
  if (!["rail", "coach", "ferry", "flight"].every(k => k in f)) return null;
  const nordic = new Set(cfg.nordic_countries || ["FI", "SE", "NO"]);
  const factor = l => {
    if (l.mode === "ferry") return f.ferry;
    if (l.mode === "bus") return f.coach;
    if ("rail_nordic" in f) {
      const a = P[l.frm] || {}, b = P[l.to] || {};
      if (nordic.has(a.country) && nordic.has(b.country)) return f.rail_nordic;
    }
    const svc = String(l.service || "").toUpperCase().replace(/ /g, "");
    if ((svc.startsWith("EST") || svc.startsWith("EUROSTAR")) && "international_rail" in f) return f.international_rail;
    if ("rail_diesel" in f) {        // US: diesel, except between two places on electrified lines (D-67)
      const el = new Set(cfg.electric_places || []);
      if (!(el.has(l.frm) && el.has(l.to))) return f.rail_diesel;
    }
    return f.rail;
  };
  const rf = parseFloat(cfg.route_factor ?? 1.2);
  const out = { co2: pyRound(legs.reduce((s, l) => s + (P[l.frm] && P[l.to] ? factor(l) * km(P[l.frm], P[l.to]) * rf : 0), 0)) };
  if (!((P[dest] || {}).no_flights || (P[origin] || {}).no_flights))
    out.co2_flight = P[origin] && P[dest] ? pyRound(km(P[origin], P[dest]) * parseFloat(cfg.flight_uplift ?? 1.08) * f.flight) : 0;
  return out;
}

/* --- build.py Journeys ----------------------------------------------------------------------
   Routes come out in the page's compact form (build.py compact_route): a leg is
   ["l", leg, dep, arr], a hotel night or change ["s"/"c", place, from, to, nights]. */
const ALTERNATIVES = [["Fewest changes", "changes", (c, h, t) => [c, t, h]],
                      ["Fewest hotel nights", "hotel_nights", (c, h, t) => [h, t, c]]];

class Journeys {
  constructor(net, origin, opt = {}) {
    this.net = net; this.origin = origin; this.opt = opt;      // opt: minTransfer, avoid (Router options)
    this.maxExtra = Math.trunc(parseFloat(net.settings.alternative_max_extra_hours ?? 12) * 60);
    this.loops = new Set();
  }
  router(date, nightTrains) { return new Router(this.net, date, { ...this.opt, nightTrains }); }

  route(router, cap, j = null) {
    const net = this.net, origin = this.origin;
    j = j !== null ? j : router.journey(cap);
    if (!j || !j.length) return null;
    const legs = j.filter(x => x.kind === "leg");
    const firstDep = legs[0].dep, arr = legs[legs.length - 1].arr;
    const visited = [legs[0].leg.frm, ...legs.map(x => x.leg.to)];
    if (new Set(visited).size < visited.length) this.loops.add(cap);
    const shift = utcOffset(net, cap, router.dayOf(arr), mod(arr, DAY))
                - utcOffset(net, origin, router.dayOf(firstDep), mod(firstDep, DAY));
    const steps = j.map(st => st.kind === "leg" ? ["l", st.leg.idx, st.dep, st.arr]
                                                : [st.kind[0], st.place, st.from, st.to, st.nights || 0]);
    const r = { capital: cap, depart: firstDep, arrive: arr, door_to_door_min: arr - firstDep - shift,
      arrive_abs: arr - shift, tz_shift: shift,
      changes: j.filter(x => x.kind === "change" || x.kind === "stay").length,
      nights_on_board: legs.filter(x => x.leg.night).length,
      hotel_nights: j.reduce((s, x) => s + (x.kind === "stay" ? x.nights : 0), 0),
      stays: j.filter(x => x.kind === "stay").map(x => x.place),
      has_issue: legs.some(x => !!x.leg.issue),
      ...(co2(net, legs.map(x => x.leg), origin, cap) || {}), steps };
    Object.defineProperty(r, "signature", { value: legs.map(x => x.leg.idx + "@" + x.dep).join(","), enumerable: false });
    return r;
  }

  withAlternatives(router, front, place, j = null) {
    const r = this.route(router, place, j);
    if (!r) return null;
    r.label = "Fastest";
    r.capital = place;
    r.is_capital = !!this.net.places[place].capital;
    r.alternatives = [];
    const seen = [r.signature];
    for (const [name, field, order] of ALTERNATIVES) {
      const ok = (front.get(place) || []).filter(l => l[2] <= r.arrive + this.maxExtra);
      if (!ok.length) continue;
      let alt = null;
      for (const l of ok.slice().sort((a, b) => cmp(order(...a), order(...b))).slice(0, 20)) {
        const pj = router.paretoJourney(l[3]);
        const pl = pj.filter(x => x.kind === "leg").map(x => x.leg);
        const visited = [pl[0].frm, ...pl.map(x => x.to)];
        if (new Set(visited).size === visited.length) { alt = this.route(router, place, pj); break; }
      }
      if (alt && alt[field] < r[field] && !seen.includes(alt.signature)) {
        alt.label = name;
        r.alternatives.push(alt);
        seen.push(alt.signature);
      }
    }
    return r;
  }

  /* All journeys leaving on `date` from `start` (minutes), with or without night trains. */
  compute(nightTrains, date, start, journeys = null) {
    const net = this.net, origin = this.origin;
    const router = this.router(date, nightTrains);
    const front = router.pareto(origin, start);
    if (journeys !== null) {
      const out = new Map();
      for (const [place, j] of journeys) { const r = this.withAlternatives(router, front, place, j); if (r) out.set(place, r); }
      return out;
    }
    router.search(origin, start, "fastest");
    const routes = [], cityRoutes = [], unreached = [], unreachedCities = [];
    for (const place of Object.keys(net.places)) {
      if (place === origin) continue;
      const r = this.withAlternatives(router, front, place);
      if (r === null) { (net.places[place].capital ? unreached : unreachedCities).push(place); continue; }
      (r.is_capital ? routes : cityRoutes).push(r);
    }
    routes.sort((a, b) => a.arrive_abs - b.arrive_abs);
    cityRoutes.sort((a, b) => a.arrive_abs - b.arrive_abs);
    return { routes, city_routes: cityRoutes, unreached, unreached_cities: unreachedCities };
  }

  /* Leaving from `start`, earlier than the default start: for each place the earliest arrival
     on the latest departure that still makes it; where that is no sooner than `base` (the
     default start's journeys), the default journey is kept, marked same_as_default. */
  earlierStart(nightTrains, date, start, base) {
    const net = this.net, origin = this.origin;
    const ev = new Map([...base.routes, ...base.city_routes].map(r => [r.capital, r]));
    const router = this.router(date, nightTrains);
    router.search(origin, start, "fastest");
    const best = new Map(), jbest = new Map();
    for (const p of Object.keys(net.places)) {
      const j = p !== origin ? router.journey(p) : null;
      if (j && j.length) {
        const legs = j.filter(x => x.kind === "leg");
        best.set(p, [legs[0].dep, legs[legs.length - 1].arr]); jbest.set(p, j);
      }
    }
    const open = new Set([...best].filter(([p, [, a]]) => !ev.has(p) || a < ev.get(p).arrive).map(([p]) => p));
    while (open.size) {
      const t2 = Math.min(...[...open].map(p => best.get(p)[0])) + 1;
      router.search(origin, t2, "fastest");
      for (const p of [...open]) {
        const j = router.journey(p), legs = j ? j.filter(x => x.kind === "leg") : [];
        if (legs.length && legs[legs.length - 1].arr === best.get(p)[1]) {
          if (legs[0].dep >= best.get(p)[0]) { best.set(p, [legs[0].dep, best.get(p)[1]]); jbest.set(p, j); }
        } else open.delete(p);
      }
    }
    const gain = [...best].filter(([p, [, a]]) => !ev.has(p) || a < ev.get(p).arrive).map(([p]) => [p, jbest.get(p)]);
    const found = this.compute(nightTrains, date, start, gain);
    const routes = [], cityRoutes = [], unreached = [], unreachedCities = [];
    for (const p of Object.keys(net.places)) {
      if (p === origin) continue;
      const r = found.get(p) || (ev.has(p) ? { ...ev.get(p), same_as_default: true } : null);
      if (r === null) (net.places[p].capital ? unreached : unreachedCities).push(p);
      else (r.is_capital ? routes : cityRoutes).push(r);
    }
    routes.sort((a, b) => a.arrive_abs - b.arrive_abs);
    cityRoutes.sort((a, b) => a.arrive_abs - b.arrive_abs);
    return { routes, city_routes: cityRoutes, unreached, unreached_cities: unreachedCities };
  }

  /* Journeys with and without night trains for a date and start, as one map variant
     (build.py variant / earlier_start). `defaultStart`: the map's main start time. */
  variant(date, start, defaultStart) {
    const v = {};
    for (const [key, nt] of [["yes", true], ["no", false]]) {
      if (start < defaultStart) v[key] = this.earlierStart(nt, date, start, this.compute(nt, date, defaultStart));
      else v[key] = this.compute(nt, date, start);
    }
    return v;
  }
}

const API = { DAY, hm, clock, dayNum, isoOf, weekday, utcOffset, loadNetwork, runsOn, Router, Journeys, co2 };
if (typeof module !== "undefined" && module.exports) module.exports = API;
else root.MPRouter = API;
})(typeof self !== "undefined" ? self : this);
