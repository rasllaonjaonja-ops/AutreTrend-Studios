"""Tests du contrat de génération éditoriale assistée."""
import unittest
from scripts.generate_editorial import valid_posts
from scripts.radar_logic import detect_text_language


class EditorialGenerationTests(unittest.TestCase):
    def setUp(self):
        self.posts = {
            "facebook": "Cette actualité apporte une nouvelle information importante pour les lecteurs de manga et mérite que l’on prenne un instant pour comprendre ce qui a réellement été annoncé aujourd’hui. Nous faisons le point sans ajouter de détails absents des sources, afin que chacun puisse se faire un avis éclairé.",
            "instagram": "Une nouvelle à découvrir pour les amateurs de manga et d’animation. Voici les informations connues à ce stade, sans ajouter de détails qui ne sont pas encore confirmés. On vous résume l’essentiel pour suivre cette actualité.",
            "tiktok": "Vous avez vu passer cette annonce ? Voici ce que l’on sait réellement pour le moment, et les détails qu’il faudra encore vérifier avant de tirer des conclusions.",
            "x": "Une nouvelle information à suivre pour les fans de manga et d’anime : voici ce qui est annoncé à ce stade, sans extrapoler sur la suite.",
            "threads": "Cette annonce mérite qu’on s’y arrête un instant. Les informations disponibles donnent déjà une première idée de ce qui se prépare, mais certains détails restent à confirmer. Quel aspect vous intéresse le plus ?",
            "youtube": {"title": "Une nouvelle actualité manga à suivre", "description": "Dans cette vidéo, nous revenons sur les informations actuellement disponibles autour de cette annonce, en distinguant les faits confirmés des éléments qui demandent encore une vérification."},
            "telegram": "Une nouvelle actualité manga vient d’être repérée. Voici les premiers éléments disponibles et les points qui restent à confirmer avant de considérer l’annonce comme entièrement établie. Nous mettrons les informations à jour lorsque des précisions fiables seront disponibles.",
            "pinterest": {"title": "Actualité manga : les informations à retenir", "description": "Retrouvez les principaux éléments de cette actualité manga dans un résumé clair et facile à consulter. Les informations encore incertaines sont signalées afin de ne pas confondre rumeur et annonce confirmée."},
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

    def test_rejects_placeholder_or_thin_social_copy(self):
        shallow = dict(self.posts)
        shallow["facebook"] = "Voici une actualité manga."
        self.assertFalse(valid_posts(shallow))

    def test_rejects_x_posts_over_platform_limit(self):
        oversized = dict(self.posts)
        oversized["x"] = "Information manga " * 30
        self.assertFalse(valid_posts(oversized))

    def test_french_headline_and_summary_detection(self):
        self.assertEqual(detect_text_language("La saison 4 de cette série est confirmée"), "fr")
        self.assertEqual(detect_text_language("The fourth season of this series is confirmed"), "en")


if __name__ == "__main__":
    unittest.main()
