"""Tests de non-régression pour la logique du Radar."""
import unittest

from scripts.verify_sources import (
    Links, MAX_PREPUBLICATIONS, SOCIAL_NETWORKS, enrich_source_reports,
    age_hours_for_sampling, verification_rank,
)
from scripts.radar_logic import (
    detect_text_language, event_parts, same_event, same_franchise,
    diversify_queue, evidence_level, coverage_score,
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

    def test_live_action_format_words_do_not_merge_unrelated_films(self):
        self.assertFalse(same_event(
            "Paradox Live THE MOVIE Anime Film Slated for 2027, Reveals Super Teaser Visual",
            "Mashle Live-Action Film Teaser Reveals Mackenyu Cast as Mash, Yuichi Fukuda Directs",
        ))
        self.assertFalse(same_event(
            "Mashle: Magic and Muscles Live-Action Film Adaptation Announced",
            "Japanese Horror Manga Noah Of The Blood Sea Set For Feature Adaptation As Tyrus Pictures Options Rights",
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

    def test_franchise_matching_is_conservative(self):
        self.assertTrue(same_franchise("Spy x Family Season 4 announced", "Spy x Family new movie announced"))
        self.assertTrue(same_franchise("Dandadan anime trailer", "Dandadan season 2 announced"))
        self.assertFalse(same_franchise("Blue Lock season 3", "Blue Exorcist season 3"))
        self.assertFalse(same_franchise("One Piece season 3", "One Punch Man season 3"))

    def test_editorial_queue_limits_repeated_franchises(self):
        items = [
            {"title": "Spy x Family Season 4 announced", "score": 95},
            {"title": "Spy x Family new movie announced", "score": 90},
            {"title": "Spy x Family game announced", "score": 85},
            {"title": "Frieren Season 2 announced", "score": 80},
        ]
        selected = diversify_queue(items, limit=4, max_per_franchise=2)
        self.assertEqual([item["score"] for item in selected], [95, 90, 80])

    def test_daily_output_is_three_editorial_posts_for_eight_networks(self):
        self.assertEqual(MAX_PREPUBLICATIONS, 3)
        self.assertEqual(len(SOCIAL_NETWORKS), 8)
        self.assertEqual(set(SOCIAL_NETWORKS), {
            "facebook", "instagram", "tiktok", "x",
            "threads", "youtube", "telegram", "pinterest",
        })

    def test_official_link_labels_normalize_whitespace(self):
        parser = Links()
        parser.feed('<a href="https://example.com/official">  Official   announcement\n details </a>')
        self.assertEqual(parser.links[0]["label"], "Official announcement details")

    def test_editorial_reports_keep_original_rss_summaries_and_dates(self):
        trend_articles = [
            {"title": "Annonce anime", "url": "https://media.example/news", "source": "Media"},
            {"title": "Annonce relayée", "url": "https://other.example/news", "source": "Other"},
        ]
        radar_items = {
            "https://media.example/news": {
                "summary": "Le studio annonce une nouvelle saison dans un communiqué.",
                "publisher": "Media Publisher",
                "published_at": "2026-11-10T08:00:00+00:00",
                "language": "fr",
                "summary_status": "available",
                "date_status": "known",
            }
        }
        reports = enrich_source_reports(trend_articles, radar_items)
        self.assertEqual(reports[0]["summary"], "Le studio annonce une nouvelle saison dans un communiqué.")
        self.assertEqual(reports[0]["publisher"], "Media Publisher")
        self.assertEqual(reports[0]["published_at"], "2026-11-10T08:00:00+00:00")
        self.assertEqual(reports[1]["summary"], "")
        self.assertEqual(reports[1]["summary_status"], "missing")

    def test_verification_sample_prioritizes_fresh_articles_and_defers_unknown_dates(self):
        from datetime import datetime, timezone
        now = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
        fresh = {"published_at": "2026-11-11T08:00:00+00:00", "score": 50}
        older = {"published_at": "2026-11-08T08:00:00+00:00", "score": 99}
        unknown = {"published_at": "", "score": 100}
        stale = {"published_at": "2026-08-01T08:00:00+00:00", "score": 100}
        ordered = sorted([unknown, stale, older, fresh], key=lambda item: verification_rank(item, now))
        self.assertEqual(ordered, [fresh, older, unknown, stale])
        self.assertEqual(age_hours_for_sampling(fresh["published_at"], now), 4)
        self.assertIsNone(age_hours_for_sampling(stale["published_at"], now))

    def test_media_coverage_is_not_truth_confirmation(self):
        self.assertEqual(evidence_level(1), "single_publisher_signal")
        self.assertEqual(evidence_level(2), "multi_media_reported")
        self.assertEqual(
            evidence_level(1, 1),
            "first_party_feed_present_needs_review",
        )
        self.assertGreater(coverage_score(1, 1), coverage_score(1, 0))
        self.assertLessEqual(coverage_score(4, 3), 100)


if __name__ == "__main__":
    unittest.main()
