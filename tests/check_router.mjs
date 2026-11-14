// Does the in-browser router (src/router.js) find the same journeys as the build (IDEA-21)?
//
// For every map in out/ (network*.json) and every travel date and start time on it, work out
// the journeys with router.js - with and without night trains, fastest and alternatives - and
// compare them with what build.py precomputed: the same legs at the same times, the same
// changes, hotel nights, door-to-door time and CO2. Any difference means the two routers have
// drifted apart; the weekly workflow then holds the update back, like a lost capital.
//
//   node tests/check_router.mjs [out]        (after python3 build.py)
import { createRequire } from "node:module";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
const require = createRequire(import.meta.url);
const R = require("../src/router.js");

const out = process.argv[2] || "out";
const src = readFileSync(join(out, "site", "router-data.js"), "utf8");
const net = R.loadNetwork(JSON.parse(src.slice(src.indexOf("=") + 1, src.lastIndexOf(";"))));

const FIELDS = ["capital", "label", "is_capital", "depart", "arrive", "door_to_door_min", "arrive_abs", "tz_shift",
                "changes", "nights_on_board", "hotel_nights", "stays", "has_issue", "co2", "co2_flight", "steps"];
const norm = r => {
  if (!r) return r;
  if (r.same_as_default) return { capital: r.capital, same_as_default: true };
  const o = {};
  for (const k of FIELDS) if (k in r) o[k] = r[k];
  if (r.alternatives && r.alternatives.length) o.alternatives = r.alternatives.map(norm);
  return o;
};
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

let checked = 0;
const problems = [];
for (const f of readdirSync(out).filter(f => /^network(-[a-z-]+)?\.json$/.test(f)).sort()) {
  const page = JSON.parse(readFileSync(join(out, f), "utf8"));
  const J = new R.Journeys(net, page.origin);
  const def = R.hm(page.default_start);
  const t0 = Date.now();
  for (const date of page.dates) {
    const v = page.variants[date];
    const want = [[page.default_start, v], ...Object.entries(v.starts || {})];
    for (const [t, sv] of want) {
      const got = J.variant(date, R.hm(t), def);
      for (const key of ["yes", "no"]) {
        if (!sv[key]) continue;
        const where = `${page.origin} ${date} ${t} ${key === "yes" ? "with" : "without"} night trains`;
        for (const list of ["routes", "city_routes", "unreached", "unreached_cities"]) {
          const a = (sv[key][list] || []).map(x => typeof x === "string" ? x : norm(x));
          const b = (got[key][list] || []).map(x => typeof x === "string" ? x : norm(x));
          checked += a.length;
          if (same(a, b)) continue;
          const byA = new Map(a.map(x => [x.capital || x, x])), byB = new Map(b.map(x => [x.capital || x, x]));
          const names = [...new Set([...byA.keys(), ...byB.keys()])];
          const diff = names.filter(n => !same(byA.get(n), byB.get(n)));
          if (!diff.length) { problems.push(`${where}: ${list} in another order`); continue; }
          for (const n of diff.slice(0, 5)) {
            const x = byA.get(n), y = byB.get(n);
            const keys = x && y && typeof x === "object" ? Object.keys({ ...x, ...y }).filter(k => !same(x[k], y[k])) : ["missing"];
            problems.push(`${where}: ${list} ${n} differs (${keys.join(", ")})` +
              (x && y && keys[0] !== "missing" ? `\n    build:  ${JSON.stringify(x[keys[0]])}\n    router: ${JSON.stringify(y[keys[0]])}` :
               `\n    build: ${x ? "yes" : "no"}, router: ${y ? "yes" : "no"}`));
          }
          if (diff.length > 5) problems.push(`${where}: ${list} ... and ${diff.length - 5} more`);
        }
      }
    }
  }
  console.log(`${page.origin}: ${page.dates.length} dates x ${1 + (page.starts || []).filter(t => t !== page.default_start).length} start times checked in ${((Date.now() - t0) / 1000).toFixed(1)} s`);
}
if (problems.length) {
  console.log(`\nThe in-browser router differs from the build in ${problems.length} place(s):\n` + problems.slice(0, 60).join("\n"));
  process.exit(1);
}
console.log(`OK: ${checked} journeys and unreached places the same in both routers.`);
