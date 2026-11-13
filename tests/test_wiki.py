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

    def test_short_start_takes_one_long_sentence_more(self):
        long = "This sentence about the old town is long " + "and winding " * 22 + "up the hill."
        out = fw.clean("Lisbon is the capital of Portugal. " + long + " Another one.")
        self.assertTrue(out.startswith("Lisbon is the capital of Portugal. This sentence"))
        self.assertLessEqual(len(out), fw.HARD_MAX)

    def test_leftover_punctuation_tidied(self):
        self.assertEqual(fw.clean("Inklusive den Portugisiske Riviera,. Byen er gammel ."), "Inklusive den Portugisiske Riviera. Byen er gammel.")

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

    def test_heading_matched_by_its_beginning(self):
        page = {**self.SHORT, "extract": "Lissabon är Portugals huvudstad.\n\n== Fakta om Lissabon ==\nEn gammal stad vid Tejo med sju kullar."}
        e = fw.from_page(page, "wikivoyage", "sv", "x")
        self.assertEqual(e["section"], "Fakta om Lissabon")

    def test_whole_section_used_with_sub_sections(self):
        page = {**self.SHORT, "extract": "Lisbon is the capital of Portugal.\n\n== Understand ==\nShort.\n\n"
                                         "=== History ===\nVery old.\n\n== Get in ==\nBy plane."}
        e = fw.from_page(page, "wikivoyage", "en", "x")
        self.assertEqual(e["text"], "Lisbon is the capital of Portugal. Short. Very old.")

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


class PickItem(unittest.TestCase):
    """Wikidata item chosen by distance, preferring one with a Wikivoyage article."""
    BREST = {"lat": 48.388, "lon": -4.480}

    @staticmethod
    def ent(lat, lon, voy=False, label="x"):
        return {"claims": {"P625": [{"mainsnak": {"datavalue": {"value": {"latitude": lat, "longitude": lon}}}}]},
                "sitelinks": {"enwikivoyage": {"title": label}} if voy else {}, "labels": {"en": {"value": label}}}

    def test_far_namesake_rejected(self):
        found = fw.pick(self.BREST, {"Q1": self.ent(52.09, 23.69, True, "Brest, Belarus"), "Q2": self.ent(48.39, -4.49, False, "Brest")})
        self.assertEqual(found["wd"], "Q2")

    def test_nothing_near(self):
        self.assertIsNone(fw.pick(self.BREST, {"Q1": self.ent(52.09, 23.69, True)}))

    def test_wikivoyage_article_preferred_among_near_items(self):
        monaco = {"lat": 43.739, "lon": 7.420}
        found = fw.pick(monaco, {"Q1": self.ent(43.739, 7.421, False, "Monaco (quarter)"), "Q2": self.ent(43.733, 7.417, True, "Monaco")})
        self.assertEqual(found["wd"], "Q2")
        self.assertLess(found["km"], 2)

    def test_item_without_coordinates_ignored(self):
        self.assertIsNone(fw.pick(self.BREST, {"Q1": {"claims": {}, "sitelinks": {}}}))


if __name__ == "__main__":
    unittest.main()
