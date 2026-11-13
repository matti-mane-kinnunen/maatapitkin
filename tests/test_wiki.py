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


class FromPage(unittest.TestCase):
    SAMPLE = {"pageid": 1, "title": "Lissabon", "revisions": [{"revid": 123456}],
              "extract": "Die bunte Metropole Lissabon ist die Hauptstadt Portugals.\n\nDie Stadt liegt auf sieben "
                         "Hügeln am Tejo, wo er in den Atlantik mündet, und hat viel zu bieten." + " Mehr Text." * 15
                         + "\n\n== Hintergrund ==\nGeschichte.\n\n== Anreise ==\nZug."}
    SHORT = {"pageid": 2, "title": "Lisbon", "revisions": [{"revid": 7}],
             "extract": "Lisbon is the capital of Portugal.\n\n\n== Districts ==\nMany.\n\n\n== Understand ==\n\n"
                        "=== History ===\nLisbon is one of the oldest cities in Western Europe.\n\n== Get in ==\nBy train."}

    def test_entry_has_credit_and_revision(self):
        e = fw.from_page(self.SAMPLE, "wikivoyage", "de", "2026-11-13")
        self.assertEqual(e["url"], "https://de.wikivoyage.org/wiki/Lissabon")
        self.assertEqual(e["revid"], 123456)
        self.assertEqual(e["source"], "wikivoyage")
        self.assertEqual(e["fetched"], "2026-11-13")

    def test_long_intro_alone(self):
        e = fw.from_page(self.SAMPLE, "wikivoyage", "de", "x")
        self.assertIn("Portugals. Die Stadt", e["text"])
        self.assertNotIn("Geschichte", e["text"])
        self.assertNotIn("section", e)

    def test_short_intro_gets_the_background_section(self):
        e = fw.from_page(self.SHORT, "wikivoyage", "en", "x")
        self.assertEqual(e["text"], "Lisbon is the capital of Portugal. Lisbon is one of the oldest cities in Western Europe.")
        self.assertEqual(e["section"], "Understand")

    def test_empty_section_never_takes_the_next_one(self):
        page = {**self.SHORT, "extract": "Lisbon is the capital of Portugal.\n\n== Understand ==\n\n== Get in ==\nBy plane: the airport is 7 km out."}
        e = fw.from_page(page, "wikivoyage", "en", "x")
        self.assertIsNone(e)            # intro alone is a stub; 'Get in' must not be used

    def test_wikipedia_takes_the_intro_only(self):
        e = fw.from_page(self.SHORT, "wikipedia", "en", "x")
        self.assertIsNone(e)            # 34 characters, no sections taken on Wikipedia: a stub

    def test_disambiguation_page_skipped(self):
        self.assertIsNone(fw.from_page({**self.SAMPLE, "pageprops": {"disambiguation": ""}}, "wikipedia", "de", "x"))

    def test_missing_page_skipped(self):
        self.assertIsNone(fw.from_page({"title": "X", "missing": True}, "wikivoyage", "de", "x"))

    def test_stub_skipped(self):
        self.assertIsNone(fw.from_page({**self.SAMPLE, "extract": "Lissabon."}, "wikivoyage", "de", "x"))


if __name__ == "__main__":
    unittest.main()
