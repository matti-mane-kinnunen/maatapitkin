// The JavaScript half of tests/test_router_cases.py: reads the cases (each with its network as
// router_data.export writes it) on stdin, runs src/router.js, writes the answers as JSON.
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
const require = createRequire(import.meta.url);
const R = require("../src/router.js");

const clock = t => `day ${Math.floor(t / R.DAY) + 1} ${String(Math.floor((t % R.DAY) / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
const cases = JSON.parse(readFileSync(0, "utf8"));
const out = cases.map(c => {
  const net = R.loadNetwork(c.data);
  const r = new R.Router(net, c.date, { nightTrains: c.night_trains, minTransfer: c.min_transfer ?? undefined, avoid: c.avoid, alternatives: c.alternatives });
  const start = R.hm(c.start);
  if (c.via) {                                    // a stopover (IDEA-21 step 3): as stopover_answer in the .py
    const res = r.stopover("A", c.via, c.to, start, c.nights ?? 1, c.leave ? R.hm(c.leave) : null);
    if (res.fail) return { expect: null, fail: res.fail };
    const j = res.steps, legs = j.filter(s => s.kind === "leg"), so = j.find(s => s.kind === "stopover");
    return { expect: [clock(legs[legs.length - 1].arr), j.filter(s => s.kind === "change" || s.kind === "stay").length,
                      j.reduce((n, s) => n + (s.kind === "stay" ? s.nights : 0), 0)],
             departures: legs.map(s => clock(s.dep)), stays: j.filter(s => s.kind === "stay").map(s => [s.place, s.nights]),
             stopover: [so.place, so.nights, clock(so.from), clock(so.to)], fail: null };
  }
  r.search("A", start, c.objective);
  const ans = { expect: null, departures: null, stays: null };
  const l = r.label(c.to);
  if (l) {
    ans.expect = [clock(l[2]), l[0], l[1]];
    const j = r.journey(c.to);
    ans.departures = j.filter(s => s.kind === "leg").map(s => clock(s.dep));
    ans.stays = j.filter(s => s.kind === "stay").map(s => [s.place, s.nights]);
  }
  ans.pareto = (r.pareto("A", start).get(c.to) || []).map(([c_, h, t]) => [clock(t), c_, h]);
  return ans;
});
process.stdout.write(JSON.stringify(out));
