"""Tests for the routing rules in src/journeys.py (FIX-15).

Each test builds a tiny made-up network - places A, B, C with a few legs - and checks
one rule: change times, hotel nights, the morning rule, quiet hours, night trains and
ferries, run days, the search objectives. The data goes through the real load(), so
the legs.yaml formats (dep/arr, times, every, runs) are tested too.

Run:  python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from journeys import DAY, Router, load, overnight, utc_offset  # noqa: E402

TUESDAY = dt.date(2026, 11, 17)
SETTINGS = {                                  # as in data/places.yaml
    "min_transfer": 20, "ferry_checkin": 45, "eurostar_checkin": 60,
    "night_point": "01:00", "morning_departure": "06:00", "min_hotel_stay": "8:00",
    "quiet_hours": "00:00-05:00", "max_stay_nights": 6,
}


def network(legs: list[dict], places: dict | None = None, **settings):
    """Load a made-up network: places A, B, C (Germany) unless given."""
    pl = {k: {"lat": 50.0 + i, "lon": 8.0, "country": "DE"} for i, k in enumerate("ABC")}
    for name, extra in (places or {}).items():
        pl.setdefault(name, {"lat": 50.0, "lon": 9.0, "country": "DE"}).update(extra)
    with tempfile.TemporaryDirectory() as d:
        Path(d, "places.yaml").write_text(yaml.safe_dump({"settings": {**SETTINGS, **settings}, "places": pl}))
        Path(d, "legs.yaml").write_text(yaml.safe_dump({"legs": legs}))
        net, warnings = load(Path(d))
    assert not warnings, warnings
    return net


def leg(frm, to, dep, arr, service="T", **kw):
    return {"from": frm, "to": to, "dep": dep, "arr": arr, "service": service, **kw}


def clock(t: int) -> str:
    """Router minutes -> 'day N HH:MM' (day 1 = the start date)."""
    return f"day {t // DAY + 1} {t % DAY // 60:02d}:{t % 60:02d}"


def trip(net, to="C", start="06:00", objective="fastest", night_trains=True, date=TUESDAY):
    """Search from A; return (arrival, changes, hotel nights) for `to`, or None."""
    r = Router(net, date, night_trains=night_trains)
    h, m = map(int, start.split(":"))
    best = r.search("A", h * 60 + m, objective)
    if to not in best:
        return None
    c, nights, t = r._lab[best[to]]
    return clock(t), c, nights


def departures(net, to="C", start="06:00", **kw):
    """The departure clock of every leg of the journey, e.g. ['day 1 08:00', 'day 1 10:30']."""
    r = Router(net, TUESDAY, **kw)
    h, m = map(int, start.split(":"))
    r.search("A", h * 60 + m)
    return [clock(s["dep"]) for s in r.journey(to) if s["kind"] == "leg"]


class Changes(unittest.TestCase):
    def test_direct(self):
        net = network([leg("A", "C", "08:00", "10:00")])
        self.assertEqual(trip(net), ("day 1 10:00", 0, 0))

    def test_min_transfer(self):
        # arrive 10:00; 10:15 is too soon with 20 min, 10:30 works
        net = network([leg("A", "B", "08:00", "10:00", "T1"),
                       leg("B", "C", "10:15", "11:00", "T2"), leg("B", "C", "10:30", "11:15", "T3")])
        self.assertEqual(trip(net), ("day 1 11:15", 1, 0))

    def test_station_min_transfer(self):
        # a station's own change time wins (Valga, Mockava: planned same-platform connections)
        net = network([leg("A", "B", "08:00", "10:00", "T1"),
                       leg("B", "C", "10:15", "11:00", "T2"), leg("B", "C", "10:30", "11:15", "T3")],
                      places={"B": {"min_transfer": 10}})
        self.assertEqual(trip(net), ("day 1 11:00", 1, 0))

    def test_stay_on_the_same_train(self):
        # same service, leaves when it arrives: no change time, no change counted
        net = network([leg("A", "B", "08:00", "10:00", "IC 1"), leg("B", "C", "10:00", "11:00", "IC 1")])
        self.assertEqual(trip(net), ("day 1 11:00", 0, 0))

    def test_ferry_checkin(self):
        # 45 min before a ferry: arrive 10:00, the 10:30 ferry is missed, the 11:00 one is not
        net = network([leg("A", "B", "08:00", "10:00"),
                       leg("B", "C", "10:30", "12:00", "F1", mode="ferry"),
                       leg("B", "C", "11:00", "12:30", "F2", mode="ferry")])
        self.assertEqual(trip(net), ("day 1 12:30", 1, 0))

    def test_port_ferry_checkin(self):
        # a port next to the station may have its own check-in (Villa San Giovanni 30)
        net = network([leg("A", "B", "08:00", "10:00"),
                       leg("B", "C", "10:30", "12:00", "F1", mode="ferry"),
                       leg("B", "C", "11:00", "12:30", "F2", mode="ferry")],
                      places={"B": {"ferry_checkin": 30}})
        self.assertEqual(trip(net), ("day 1 12:00", 1, 0))

    def test_eurostar_checkin(self):
        # 60 min before Eurostar (service EST...): arrive 10:00, 10:45 missed, 11:01 caught
        net = network([leg("A", "B", "08:00", "10:00"),
                       leg("B", "C", "10:45", "13:00", "EST 9010"), leg("B", "C", "11:01", "13:20", "EST 9012")])
        self.assertEqual(trip(net), ("day 1 13:20", 1, 0))


class HotelNights(unittest.TestCase):
    def test_overnight_wait_is_a_hotel_night(self):
        net = network([leg("A", "B", "18:00", "21:00"), leg("B", "C", "07:00", "09:00", "T2")])
        self.assertEqual(trip(net), ("day 2 09:00", 1, 1))

    def test_journey_shows_the_stay(self):
        net = network([leg("A", "B", "18:00", "21:00"), leg("B", "C", "07:00", "09:00", "T2")])
        r = Router(net, TUESDAY)
        r.search("A", 6 * 60)
        stays = [s for s in r.journey("C") if s["kind"] == "stay"]
        self.assertEqual([(s["place"], s["nights"]) for s in stays], [("B", 1)])

    def test_no_departure_before_the_morning(self):
        # after a hotel night nothing leaves before 06:00: the 05:30 train is skipped
        net = network([leg("A", "B", "18:00", "20:00"),
                       leg("B", "C", "05:30", "07:00", "T2"), leg("B", "C", "06:30", "08:00", "T3")])
        self.assertEqual(departures(net), ["day 1 18:00", "day 2 06:30"])

    def test_place_morning_departure(self):
        # Budapest 05:00 (IDEA-03): a place may let you leave earlier
        net = network([leg("A", "B", "18:00", "20:00"),
                       leg("B", "C", "05:30", "07:00", "T2"), leg("B", "C", "06:30", "08:00", "T3")],
                      places={"B": {"morning_departure": "05:00"}})
        self.assertEqual(departures(net), ["day 1 18:00", "day 2 05:30"])

    def test_min_hotel_stay(self):
        # arrive 01:30: at least 8 h in the hotel, so not 06:30 but 10:00 (FIX-07)
        net = network([leg("A", "B", "22:00", "01:30", "N1", night=True),
                       leg("B", "C", "06:30", "08:00", "T2"), leg("B", "C", "10:00", "11:30", "T3")])
        self.assertEqual(departures(net, start="20:00"), ["day 1 22:00", "day 2 10:00"])

    def test_quiet_hours(self):
        # no ordinary train runs 00:00-05:00: the 02:00 local train is never boarded
        net = network([leg("A", "B", "20:00", "21:30"),
                       leg("B", "C", "02:00", "02:40", "T2"), leg("B", "C", "06:10", "06:50", "T3")])
        self.assertEqual(departures(net, start="19:00"), ["day 1 20:00", "day 2 06:10"])
        self.assertEqual(trip(net, start="19:00")[2], 1)       # and that wait is a hotel night

    def test_quiet_hours_at_the_start(self):
        # also the very first train: leaving home at midnight, the 02:00 is not taken, the 06:10 is
        # (the morning rule does not apply at home, so this checks the quiet hours alone)
        net = network([leg("A", "C", "02:00", "02:40", "T1"), leg("A", "C", "06:10", "06:50", "T2")])
        self.assertEqual(trip(net, start="00:00"), ("day 1 06:50", 0, 0))

    def test_late_arrival_needs_eight_hours(self):
        # arrive 23:00: 06:10 is under 8 h in the hotel, so the train a day later
        net = network([leg("A", "B", "21:00", "23:00"), leg("B", "C", "06:10", "06:50", "T3")])
        self.assertEqual(departures(net, start="20:00"), ["day 1 21:00", "day 3 06:10"])

    def test_max_stay_nights(self):
        # a train only on Saturdays: from Tuesday that is 4 nights' wait (Tue, Wed, Thu, Fri) -
        # allowed with 6 (and with 4), not with 3
        legs = [leg("A", "B", "08:00", "10:00"), leg("B", "C", "09:00", "11:00", "SAT", runs="sat")]
        self.assertEqual(trip(network(legs)), ("day 5 11:00", 1, 4))
        self.assertEqual(trip(network(legs, max_stay_nights=4)), ("day 5 11:00", 1, 4))
        self.assertIsNone(trip(network(legs, max_stay_nights=3)))


class NightServices(unittest.TestCase):
    def test_night_train_same_evening_is_no_hotel_night(self):
        net = network([leg("A", "B", "08:00", "18:00"), leg("B", "C", "22:00", "07:00", "NJ", night=True)])
        self.assertEqual(trip(net), ("day 2 07:00", 1, 0))

    def test_night_ferry_after_midnight(self):
        # wait at the port for a 02:30 ferry: the night is spent on board (Palermo -> Tunis)
        net = network([leg("A", "B", "18:00", "22:00"),
                       leg("B", "C", "02:30", "14:00", "F", mode="ferry", night=True)])
        self.assertEqual(trip(net), ("day 2 14:00", 1, 0))

    def test_without_night_trains(self):
        # night trains are left out, night ferries stay
        net = network([leg("A", "C", "22:00", "07:00", "NJ", night=True),
                       leg("A", "B", "22:00", "07:00", "F", mode="ferry", night=True)])
        r = Router(net, TUESDAY, night_trains=False)
        best = r.search("A", 20 * 60)
        self.assertNotIn("C", best)
        self.assertIn("B", best)

    def test_hidden_night_train_in_a_list(self):
        # one entry with day trains and one through the night: load() marks that one as night
        net = network([{"from": "A", "to": "C", "service": "IC",
                        "times": ["08:00-12:00", "22:11-08:21"]}])
        self.assertEqual([l.night for l in net.legs], [False, True])
        self.assertTrue(overnight(22 * 60 + 11, 10 * 60 + 10))
        self.assertFalse(overnight(23 * 60 + 13, 90))           # 23:13-00:43 is too short


class DataFormats(unittest.TestCase):
    def test_every(self):
        # every 60 min 06:00-09:00, 45 min each: from 07:10 the next is 08:00
        net = network([{"from": "A", "to": "C", "service": "Bus", "mode": "bus",
                        "every": 60, "first": "06:00", "last": "09:00", "duration": "0:45"}])
        self.assertEqual(len(net.legs), 4)
        self.assertEqual(trip(net, start="07:10"), ("day 1 08:45", 0, 0))

    def test_runs_weekdays(self):
        # 'mon-fri': starting on a Saturday you leave on Monday - at home, so no hotel nights
        net = network([leg("A", "C", "08:00", "10:00", runs="mon-fri")])
        self.assertEqual(trip(net), ("day 1 10:00", 0, 0))                     # Tuesday
        self.assertEqual(trip(net, date=dt.date(2026, 11, 21)), ("day 3 10:00", 0, 0))   # Saturday

    def test_time_zones(self):
        # Helsinki is an hour ahead of Berlin, also in winter
        fi, de = {"country": "FI"}, {"country": "DE"}
        self.assertEqual(utc_offset(fi, TUESDAY, 12 * 60) - utc_offset(de, TUESDAY, 12 * 60), 60)


class Objectives(unittest.TestCase):
    def setUp(self):
        # slow direct train, or a faster pair with a change
        self.net = network([leg("A", "C", "08:00", "20:00", "SLOW"),
                            leg("A", "B", "08:00", "09:00", "T1"), leg("B", "C", "09:30", "12:00", "T2")])

    def test_fastest(self):
        self.assertEqual(trip(self.net), ("day 1 12:00", 1, 0))

    def test_fewest_changes(self):
        self.assertEqual(trip(self.net, objective="fewest_changes"), ("day 1 20:00", 0, 0))

    def test_fewest_hotel_nights(self):
        # the fast way needs a hotel night, the slow one does not
        net = network([leg("A", "B", "08:00", "21:00", "T1"), leg("B", "C", "07:00", "08:00", "T2"),
                       leg("A", "C", "10:00", "23:30", "SLOW")])
        self.assertEqual(trip(net, start="07:00")[0], "day 1 23:30")       # fastest: no night needed anyway
        self.assertEqual(trip(net, start="07:00", objective="fewest_hotels")[2], 0)

    def test_pareto_keeps_the_trade_offs(self):
        r = Router(self.net, TUESDAY)
        found = sorted((t, c) for c, h, t, _ in r.pareto("A", 6 * 60)["C"])
        self.assertEqual(found, [(12 * 60, 1), (20 * 60, 0)])


if __name__ == "__main__":
    unittest.main()
