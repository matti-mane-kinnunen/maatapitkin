"""Tests for gtfs_import.py (IDEA-25, D-67): a tiny made-up GTFS feed in a temporary folder.

Checks the time zones (Amtrak's Eastern-time feed, Arizona read through America/Denver, Flix's
UTC feed), days, pickup/drop-off rules, a place with two stops, and how run dates become
runs / valid_from / valid_to.

Run:  python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import gtfs_import as G  # noqa: E402

PLACES = {
    "Chicago": {"tz": "America/Chicago", "amtrak": ["CHI"], "flix": ["f-chi"]},
    "Denver": {"tz": "America/Denver", "amtrak": ["DEN"]},
    "Boston": {"tz": "America/New_York", "amtrak": ["BOS", "BBY"]},
    "Maricopa": {"tz": "America/Phoenix", "amtrak": ["MRC"]},
    "Madison": {"tz": "America/Chicago", "flix": ["f-msn"]},
}
D = dt.date


def write(folder: Path, files: dict[str, str]):
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (folder / name).write_text(text.strip() + "\n")


def amtrak_feed(folder: Path, stop_times: str, calendar: str = "s1,1,1,1,1,1,1,1,20261101,20271231",
                calendar_dates: str = "", trips: str = "", stops_extra: str = ""):
    write(folder, {
        "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\n51,Amtrak,x,America/New_York",
        "routes.txt": "route_id,agency_id,route_short_name,route_long_name,route_type\n"
                      "r1,51,,California Zephyr,2\nr2,51,,Amtrak Thruway Connecting Service,3",
        "trips.txt": "route_id,service_id,trip_id,trip_short_name\n" + (trips or "r1,s1,t1,5"),
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon,stop_timezone\n"
                     "CHI,Chicago,0,0,America/Chicago\nDEN,Denver,0,0,America/Denver\n"
                     "BOS,Boston,0,0,America/New_York\nBBY,Back Bay,0,0,America/New_York\n"
                     "MRC,Maricopa,0,0,America/Denver\nXXX,Nowhere,0,0,America/Chicago\n" + stops_extra,
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type,drop_off_type\n" + stop_times,
        "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n" + calendar,
        "calendar_dates.txt": "service_id,date,exception_type\n" + calendar_dates,
    })


def run(folder: Path, first=D(2026, 12, 7), last=D(2026, 12, 13), all_bus=False, feeds=None):
    feeds = feeds or [{"name": "amtrak", "path": folder, "key": "amtrak", "clock_tz": "stop",
                       "skip_agencies": set(), "skip_routes": set()}]
    entries, report = G.build_legs(PLACES, first, last, all_bus, feeds)
    return entries, report


class TestTimes(unittest.TestCase):
    def test_eastern_feed_gives_local_times_and_days(self):
        with tempfile.TemporaryDirectory() as d:
            # Zephyr: Chicago 14:00 CST = 15:00 Eastern; Denver 07:56 MST next morning = 33:56 Eastern
            amtrak_feed(Path(d), "t1,15:00:00,15:00:00,CHI,1,0,0\nt1,33:56:00,33:56:00,DEN,2,0,0")
            e, _ = run(Path(d))
            (k, times), = e.items()
            self.assertEqual(k[:5], ("Chicago", "Denver", "California Zephyr 5", "train", 0))
            self.assertEqual(times, [("14:00", "07:56")])
            self.assertEqual((k[5], k[6], k[7]), (None, D(2026, 12, 7), D(2026, 12, 13)))

    def test_two_days_by_the_clock(self):
        with tempfile.TemporaryDirectory() as d:
            amtrak_feed(Path(d), "t1,15:00:00,15:00:00,CHI,1,0,0\nt1,63:00:00,63:00:00,DEN,2,0,0")
            e, _ = run(Path(d))
            (k, times), = e.items()
            # Mon 14:00 CST -> Wed 13:00 MST: 47 h by the clock = "14:00-13:00" + 1 day (as in D-63)
            self.assertEqual(k[4], 1)
            self.assertEqual(times, [("14:00", "13:00")])

    def test_arizona_read_through_denver_both_seasons(self):
        with tempfile.TemporaryDirectory() as d:
            # bus 8902 from Maricopa: raw 9:45 in winter, 8:45 in summer -> 07:45 / 06:45 Arizona time
            amtrak_feed(Path(d), "w,9:45:00,9:45:00,MRC,1,0,0\nw,10:45:00,10:45:00,CHI,2,0,0\n"
                                 "s,8:45:00,8:45:00,MRC,1,0,0\ns,9:45:00,9:45:00,CHI,2,0,0",
                        calendar="sw,1,1,1,1,1,1,1,20261101,20270313\nss,1,1,1,1,1,1,1,20270315,20271231",
                        trips="r2,sw,w,8902\nr2,ss,s,8902")
            e, _ = run(Path(d), D(2027, 3, 8), D(2027, 3, 20))
            got = sorted((k[6], t) for k, ts in e.items() for t in ts)
            self.assertEqual(got[0], (D(2027, 3, 8), ("07:45", "09:45")))     # winter: 10:45 EST = 09:45 CST
            self.assertEqual(got[-1][1], ("06:45", "08:45"))                   # summer: 9:45 EDT = 08:45 CDT

    def test_flix_utc_feed_uses_place_tz(self):
        with tempfile.TemporaryDirectory() as d:
            write(Path(d), {
                "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\nFLIXBUS-us,FlixBus,x,UTC",
                "routes.txt": "agency_id,route_id,route_short_name,route_long_name,route_type\nFLIXBUS-us,R,FlixBus 2548,x,3",
                "trips.txt": "route_id,trip_id,service_id\nR,t,s",
                "stops.txt": "stop_id,stop_name,stop_lat,stop_lon,stop_timezone\nf-chi,C,0,0,America/Phoenix\nf-msn,M,0,0,",
                "stop_times.txt": "trip_id,stop_id,arrival_time,departure_time,stop_sequence\nt,f-chi,15:00:00,15:00:00,1\nt,f-msn,18:25:00,18:25:00,2",
                "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\ns,1,1,1,1,1,1,1,20261201,20261231",
            })
            feeds = [{"name": "flix", "path": Path(d), "key": "flix", "clock_tz": "place",
                      "skip_agencies": set(), "skip_routes": set()}]
            e, _ = run(Path(d), feeds=feeds)
            (k, times), = e.items()
            self.assertEqual(times, [("09:00", "12:25")])   # 15:00 UTC = 09:00 CST (wrong stop_timezone ignored)


class TestTrips(unittest.TestCase):
    def test_pickup_and_drop_off_rules(self):
        with tempfile.TemporaryDirectory() as d:
            # Denver is set-down only (pickup 1): no Denver -> Boston leg; Chicago -> Denver stays
            amtrak_feed(Path(d), "t1,10:00:00,10:00:00,CHI,1,0,0\nt1,12:00:00,12:00:00,DEN,2,1,0\n"
                                 "t1,14:00:00,14:00:00,BOS,3,0,0")
            e, _ = run(Path(d))
            self.assertEqual(sorted((k[0], k[1]) for k in e), [("Chicago", "Boston"), ("Chicago", "Denver")])

    def test_two_stops_of_one_place_shortest_ride(self):
        with tempfile.TemporaryDirectory() as d:
            amtrak_feed(Path(d), "t1,10:00:00,10:00:00,CHI,1,0,0\nt1,20:00:00,20:00:00,BBY,2,0,0\n"
                                 "t1,20:10:00,20:10:00,BOS,3,0,0\nt1,20:30:00,20:30:00,XXX,4,0,0")
            e, _ = run(Path(d))
            (k, times), = e.items()
            self.assertEqual((k[0], k[1], times), ("Chicago", "Boston", [("09:00", "20:00")]))


class TestStations(unittest.TestCase):
    def test_state_from_the_basemap(self):
        find = G.state_finder(ROOT / "data" / "us" / "basemap.geojson")
        self.assertEqual(find(-89.364, 40.149), "IL")      # Lincoln, Illinois (Amtrak LCN)
        self.assertEqual(find(-96.713, 40.816), "NE")      # Lincoln, Nebraska
        self.assertEqual(find(-123.098, 49.274), "BC")     # Vancouver, BC
        self.assertIsNone(find(-140.0, 30.0))              # the Pacific


class TestDates(unittest.TestCase):
    def test_fmt_runs(self):
        self.assertIsNone(G.fmt_runs(set(range(7))))
        self.assertEqual(G.fmt_runs({0, 1, 2, 3, 4}), "mon-fri")
        self.assertEqual(G.fmt_runs({5, 6}), "sat,sun")
        self.assertEqual(G.fmt_runs({0, 3, 5}), "mon,thu,sat")
        self.assertEqual(G.fmt_runs({1, 2, 3, 5}), "tue-thu,sat")
        # what the router reads back
        sys.path.insert(0, str(ROOT / "src"))
        from journeys import parse_weekdays
        for days in ({0, 1, 2, 3, 4}, {5, 6}, {0, 3, 5}, {1, 2, 3, 5}, {6}):
            self.assertEqual(parse_weekdays(G.fmt_runs(days)), days)

    def test_holiday_splits_the_period_and_odd_day_stands_alone(self):
        daily = {D(2026, 12, 1) + dt.timedelta(days=i) for i in range(31)} - {D(2026, 12, 25)}
        self.assertEqual(G.compress(daily), [(None, D(2026, 12, 1), D(2026, 12, 24)),
                                             (None, D(2026, 12, 26), D(2026, 12, 31))])
        weekdays = {d for d in daily if d.weekday() < 5} | {D(2026, 12, 12)}      # + one Saturday
        self.assertEqual(G.compress(weekdays), [("mon-fri", D(2026, 12, 1), D(2026, 12, 24)),
                                                (None, D(2026, 12, 28), D(2026, 12, 31)),        # Mon-Thu, every day it covers
                                                (None, D(2026, 12, 12), D(2026, 12, 12))])

    def test_calendar_dates_remove_and_add(self):
        with tempfile.TemporaryDirectory() as d:
            amtrak_feed(Path(d), "t1,15:00:00,15:00:00,CHI,1,0,0\nt1,16:00:00,16:00:00,DEN,2,0,0",
                        calendar="s1,1,1,1,1,1,0,0,20261101,20271231",
                        calendar_dates="s1,20261209,2\ns1,20261212,1")
            dates = G.service_dates(G.Feed(Path(d)), D(2026, 12, 7), D(2026, 12, 13))["s1"]
            self.assertEqual(sorted(dates), [D(2026, 12, 7), D(2026, 12, 8), D(2026, 12, 10),
                                             D(2026, 12, 11), D(2026, 12, 12)])


if __name__ == "__main__":
    unittest.main()
