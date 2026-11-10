"""Tests du contrat de génération éditoriale assistée."""
import unittest
from scripts.generate_editorial import valid_posts
from scripts.radar_logic import detect_text_language


class EditorialGenerationTests(unittest.TestCase):
    def setUp(self):
        self.posts = {
            "facebook": "Une actualité manga à découvrir.",
            "instagram": "Une légende courte.",
            "tiktok": "Accroche et script.",
            "x": "Un message bref.",
            "threads": "Une question à la communauté.",
            "youtube": {"title": "Actualité manga", "description": "Description."},
            "telegram": "Une brève.",
            "pinterest": {"title": "Guide manga", "description": "Description."},
        }

    def test_requires_all_eight_platform_variants(self):
        self.assertTrue(valid_posts(self.posts))
        incomplete = dict(self.posts)
        incomplete.pop("tiktok")
        self.assertFalse(valid_posts(incomplete))

    def test_video_and_pin_formats_must_be_structured(self):
        malformed = dict(self.posts)
        malformed["youtube"] = "Titre et description en une seule chaîne"
        self.assertFalse(valid_posts(malformed))

    def test_french_headline_and_summary_detection(self):
        self.assertEqual(detect_text_language("La saison 4 de cette série est confirmée"), "fr")
        self.assertEqual(detect_text_language("The fourth season of this series is confirmed"), "en")


if __name__ == "__main__":
    unittest.main()
