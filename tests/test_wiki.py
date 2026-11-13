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


class CleanLeftovers(unittest.TestCase):
    """What the first full run (13.11.2026) left in the texts."""
    def test_footnote_marks(self):
        self.assertEqual(fw.clean("Lontoo [1] on Englannin pääkaupunki."), "Lontoo on Englannin pääkaupunki.")

    def test_pronunciations(self):
        self.assertEqual(fw.clean("Kraków (IPA: [ˈkrakuf]) is the chief city."), "Kraków is the chief city.")
        self.assertEqual(fw.clean("Bratislava /ˈbracislaʋa/ on Slovakian pääkaupunki."), "Bratislava on Slovakian pääkaupunki.")

    def test_nested_brackets(self):
        self.assertEqual(fw.clean("Abrantes (uh-BRUHN-t(ih)sh, /ɐ.ˈbɾɐ̃.tɨʃ/) municipality has 34,336 residents."),
                         "Abrantes municipality has 34,336 residents.")
        self.assertEqual(fw.clean("Patras (Modern Greek: Πάτρα, Classical Greek: Πάτραι (pl.)) is a port."), "Patras is a port.")

    def test_other_scripts(self):
        self.assertEqual(fw.clean("Casablanca (arabiska: الدارالبيضاء) är en stad."), "Casablanca är en stad.")

    def test_plain_brackets_kept(self):
        self.assertEqual(fw.clean("It lies on the River Tagus (Rio Tejo)."), "It lies on the River Tagus (Rio Tejo).")

    def test_listings_end_the_text(self):
        self.assertEqual(fw.clean("Abrantes lies on the Tagus. 1 Welcome Center, ☏ +351 241 330 100. 10:00–13:00 daily."),
                         "Abrantes lies on the Tagus.")
        self.assertEqual(fw.clean("Koblenz liegt am Rhein. Tourist-Info, lun.–dim.: 10 h – 18 h. (dernière mise à jour: fév. 2018)"),
                         "Koblenz liegt am Rhein.")

    def test_disambiguation_notes(self):
        self.assertEqual(fw.clean("For alternative betydninger, se Split (flertydig). (Se også artikler, som begynder med Split) "
                                  "Split er en kroatisk by i Dalmatien."), "Split er en kroatisk by i Dalmatien.")


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


class PickTheTown(unittest.TestCase):
    """13.11.2026 full run: stations, provinces and districts won on distance alone."""
    ent = staticmethod(PickItem.ent)

    def with_desc(self, lat, lon, label, desc, voy=False):
        e = self.ent(lat, lon, voy, label); e["descriptions"] = {"en": {"value": desc}}; return e

    def test_station_loses_to_the_city(self):
        p = {"lat": 50.107, "lon": 8.663}
        found = fw.pick(p, {"Q1": self.with_desc(50.107, 8.663, "Frankfurt (Main) Hbf", "main railway station in Frankfurt, Germany"),
                            "Q2": self.with_desc(50.11, 8.68, "Frankfurt am Main", "city in Hesse, Germany", True)}, ("Frankfurt", "Frankfurt am Main"))
        self.assertEqual(found["wd"], "Q2")

    def test_province_loses_to_the_city(self):
        p = {"lat": 45.429, "lon": 10.983}
        found = fw.pick(p, {"Q1": self.with_desc(45.43, 10.98, "Province of Verona", "one of seven provinces in the Italian region Veneto", True),
                            "Q2": self.with_desc(45.44, 10.99, "Verona", "Italian comune", True)}, ("Verona",))
        self.assertEqual(found["wd"], "Q2")

    def test_exact_name_beats_a_closer_district(self):
        p = {"lat": 48.718, "lon": 9.108}
        found = fw.pick(p, {"Q1": self.with_desc(48.75, 9.16, "Stuttgart-Süd", "human settlement in Germany"),
                            "Q2": self.with_desc(48.78, 9.18, "Stuttgart", "capital of Baden-Württemberg, Germany", True)}, ("Stuttgart",))
        self.assertEqual(found["wd"], "Q2")

    def test_capital_of_a_region_is_still_a_town(self):
        p = {"lat": 41.118, "lon": 16.869}
        found = fw.pick(p, {"Q1": self.with_desc(41.12, 16.87, "Bari", "Italian city, capital of the Apulia region", True)}, ("Bari",))
        self.assertEqual(found["wd"], "Q1")


if __name__ == "__main__":
    unittest.main()
