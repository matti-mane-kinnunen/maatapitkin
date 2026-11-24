"""whats_changed.py (IDEA-08): reading the route tables and listing the changes."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from whats_changed import compare, parse  # noqa: E402

OLD = """# Journeys from Helsinki

_leave Helsinki Tue 17.11.2026 from 17:00 · generated 13.11.2026._

| Capital | Depart | Arrive | Door to door | Changes | Night trains/ferries | Hotel nights (where) | Alternatives |
|---|---|---|---|---|---|---|---|
| Tallinn | Wed 18.11. 07:30 | Wed 18.11. 09:30 | 2 h 00 min | 0 | 0 | 0 |  |
| Sofia | Tue 17.11. 17:35 | Sat 21.11. 20:41 | 99 h 06 min | 10 | 2 | 1 (Budapest) |  |
| Kyiv | Wed 18.11. 07:30 | Fri 20.11. 09:49 | 50 h 19 min | 6 | 1 | 1 (Vilnius) |  |

## Without night trains

| Capital | Arrive | Door to door | Changes | Hotel nights (where) | Compared with night trains |
|---|---|---|---|---|---|
| Tallinn | Wed 18.11. 09:30 | 2 h 00 min | 0 | 0 |  |

## Leaving from 05:00 instead of 17:00

| Capital | Leave | Arrive | Door to door | Compared with 17:00 |
|---|---|---|---|---|
| Tallinn | Tue 17.11. 07:30 | Tue 17.11. 09:30 | 2 h 00 min | same |

## Other cities

| City | Arrive | Door to door | Changes | Hotel nights |
|---|---|---|---|---|
| Tampere | Tue 17.11. 18:53 | 1 h 53 min | 0 | 0 |
"""

NEW = (OLD.replace("17.11.2026", "24.11.2026")
          .replace("99 h 06 min", "97 h 10 min")         # Sofia 1 h 56 faster
          .replace("2 h 00 min | 0 | 0 |  |\n| Sofia", "2 h 20 min | 0 | 0 |  |\n| Sofia")  # Tallinn +20 min: below the limit
          .replace("| Kyiv | Wed 18.11. 07:30 | Fri 20.11. 09:49 | 50 h 19 min | 6 | 1 | 1 (Vilnius) |  |\n", "")
          .replace("| Tallinn | Wed 18.11. 09:30 | 2 h 00 min | 0 | 0 |  |",
                   "| Tallinn | Wed 18.11. 09:30 | 2 h 00 min | 0 | 0 |  |\n| Riga | Wed 18.11. 16:44 | 9 h 14 min | 2 | 0 |  |")
          .replace("1 h 53 min", "9 h 53 min"))         # other cities are not compared


class TestWhatsChanged(unittest.TestCase):
    def test_parse(self):
        p = parse(OLD)
        self.assertEqual(p["origin"], "Helsinki")
        self.assertEqual(str(p["date"]), "2026-11-17")
        self.assertEqual(p["modes"]["main"]["times"], {"Tallinn": 120, "Sofia": 5946, "Kyiv": 3019})
        self.assertEqual(p["modes"]["main"]["label"], "from 17:00")
        self.assertEqual(p["modes"]["other"]["label"], "from 05:00")
        self.assertNotIn("Tampere", str(p["modes"]))

    def test_compare(self):
        lines = compare(parse(OLD), parse(NEW), 30)
        self.assertEqual(lines, [
            "- from 17:00, **faster:** Sofia −1 h 56 (99 h 06 → 97 h 10)",
            "- from 17:00, **no longer reachable:** Kyiv",
            "- without night trains, **now reachable:** Riga (9 h 14)",
        ])

    def test_start_time_changed(self):
        new = parse(NEW.replace("from 05:00 instead", "from 06:00 instead"))
        self.assertIn("- from 06:00: start time changed (was from 05:00) – not compared",
                      compare(parse(OLD), new, 30))


if __name__ == "__main__":
    unittest.main()
