"""fetch_wiki.py text handling (IDEA-22), offline: no request is made here."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fetch_wiki as fw  # noqa: E402


class CleanText(unittest.TestCase):
    def test_short_text_kept_as_is(self):
        self.assertEqual(fw.clean("Lisbon is the capital of Portugal."), "Lisbon is the capital of Portugal.")

    def test_long_text_cut_at_a_sentence_end(self):
        s = "First sentence about the city. " * 30
        out = fw.clean(s)
        self.assertLessEqual(len(out), fw.MAX_CHARS)
        self.assertTrue(out.endswith("."))

    def test_control_characters_and_markup_spacing_removed(self):
        self.assertEqual(fw.clean("A\x07 city\n\n  by\tthe sea."), "A city by the sea.")

    def test_one_giant_sentence_capped(self):
        out = fw.clean("word " * 400)
        self.assertLessEqual(len(out), fw.HARD_MAX + 2)
        self.assertTrue(out.endswith("…"))


class FromSummary(unittest.TestCase):
    SAMPLE = {"type": "standard", "title": "Lissabon", "revision": "123456",
              "extract": "Lissabon ist die Hauptstadt Portugals. Die Stadt liegt am Tejo.",
              "content_urls": {"desktop": {"page": "https://de.wikivoyage.org/wiki/Lissabon"}}}

    def test_entry_has_credit_and_revision(self):
        e = fw.from_summary(self.SAMPLE, "wikivoyage", "de", "2026-11-12")
        self.assertEqual(e["url"], "https://de.wikivoyage.org/wiki/Lissabon")
        self.assertEqual(e["revid"], 123456)
        self.assertEqual(e["source"], "wikivoyage")
        self.assertEqual(e["fetched"], "2026-11-12")

    def test_disambiguation_page_skipped(self):
        self.assertIsNone(fw.from_summary({**self.SAMPLE, "type": "disambiguation"}, "wikipedia", "de", "x"))

    def test_stub_skipped(self):
        self.assertIsNone(fw.from_summary({**self.SAMPLE, "extract": "Lissabon."}, "wikivoyage", "de", "x"))


if __name__ == "__main__":
    unittest.main()
