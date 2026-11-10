"""Tests de non-régression pour la logique du Radar."""
import unittest

from scripts.radar_logic import (
    detect_text_language, event_parts, same_event, evidence_level,
)


class RadarLogicTests(unittest.TestCase):
    def test_spy_family_synonyms_are_same_event(self):
        a = "'Spy x Family' Gets Season 4, Second Anime Movie in 2027"
        b = "Spy×Family Anime Gets 4th Season, Theatrical Film in 2027"
        self.assertTrue(same_event(a, b))

    def test_same_franchise_different_event_is_not_merged(self):
        a = "Spy x Family Gets Season 4 in 2027"
        b = "Spy x Family Manga Announces New Movie in 2027"
        self.assertFalse(same_event(a, b))

    def test_different_seasons_are_not_merged(self):
        self.assertFalse(same_event(
            "Spy x Family Gets Season 3 in 2027",
            "Spy x Family Gets Season 4 in 2027",
        ))

    def test_unrelated_franchises_are_not_merged(self):
        self.assertFalse(same_event(
            "One Piece Gets Season 4 in 2027",
            "Spy x Family Gets Season 4 in 2027",
        ))

    def test_event_parts_normalize_ordinal_and_movie_synonyms(self):
        _, facets = event_parts(
            "Spy×Family gets 4th season and theatrical film in 2027"
        )
        self.assertIn("season:4", facets)
        self.assertIn("film", facets)
        self.assertIn("year:2027", facets)

    def test_summary_language_is_detected_independently_of_title(self):
        self.assertEqual(
            detect_text_language("La nouvelle saison est annoncée pour cette année"),
            "fr",
        )
        self.assertEqual(
            detect_text_language("The new season has been announced for this year"),
            "en",
        )
        self.assertEqual(detect_text_language("Spy x Family"), "und")

    def test_media_coverage_is_not_truth_confirmation(self):
        self.assertEqual(evidence_level(1), "single_publisher_signal")
        self.assertEqual(evidence_level(2), "multi_media_reported")


if __name__ == "__main__":
    unittest.main()
