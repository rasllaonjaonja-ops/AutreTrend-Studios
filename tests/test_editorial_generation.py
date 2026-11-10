"""Tests du contrat de génération éditoriale assistée."""
import unittest
from scripts.generate_editorial import valid_posts, valid_synthesis
from scripts.radar_logic import detect_text_language
from scripts.quality_check import valid_editorial_queue


class EditorialGenerationTests(unittest.TestCase):
    def setUp(self):
        self.posts = {
            "facebook": "Cette actualité apporte une nouvelle information importante pour les lecteurs de manga et mérite que l’on prenne un instant pour comprendre ce qui a réellement été annoncé aujourd’hui. Nous faisons le point sans ajouter de détails absents des sources, afin que chacun puisse se faire un avis éclairé. Notre rédaction distingue les annonces confirmées des éléments encore rapportés, pour donner aux lecteurs un aperçu utile et fidèle des informations disponibles.",
            "instagram": "Une nouvelle à découvrir pour les amateurs de manga et d’animation. Voici les informations connues à ce stade, sans ajouter de détails qui ne sont pas encore confirmés. On vous résume l’essentiel pour suivre cette actualité. Prenez le temps de découvrir les éléments annoncés et de partager votre point de vue avec la communauté.",
            "tiktok": "Vous avez vu passer cette annonce ? Voici ce que l’on sait réellement pour le moment, et les détails qu’il faudra encore vérifier avant de tirer des conclusions. On garde les faits, on écarte les suppositions et on attend les précisions fiables pour la suite.",
            "x": "Une nouvelle information à suivre pour les fans de manga et d’anime : voici ce qui est annoncé à ce stade, sans extrapoler sur la suite.",
            "threads": "Cette annonce mérite qu’on s’y arrête un instant. Les informations disponibles donnent déjà une première idée de ce qui se prépare, mais certains détails restent à confirmer. Quel aspect vous intéresse le plus ? On préfère prendre le temps de distinguer les faits des interprétations avant de tirer des conclusions.",
            "youtube": {"title": "Actualité manga : les informations essentielles à retenir", "description": "Dans cette vidéo, nous revenons sur les informations actuellement disponibles autour de cette annonce, en distinguant les faits confirmés des éléments qui demandent encore une vérification. Nous présentons les éléments utiles avec prudence, sans ajouter de détails absents des sources consultées, afin de proposer un point clair aux amateurs de manga et d’animation."},
            "telegram": "Une nouvelle actualité manga vient d’être repérée. Voici les premiers éléments disponibles et les points qui restent à confirmer avant de considérer l’annonce comme entièrement établie. Nous mettrons les informations à jour lorsque des précisions fiables seront disponibles. Notre priorité reste de transmettre une information claire, utile et fidèle aux sources.",
            "pinterest": {"title": "Actualité manga : les informations essentielles à retenir", "description": "Retrouvez les principaux éléments de cette actualité manga dans un résumé clair et facile à consulter. Les informations encore incertaines sont signalées afin de ne pas confondre rumeur et annonce confirmée. Cette présentation aide à retrouver les faits utiles et à suivre les prochaines précisions sans amplifier les éléments qui restent à vérifier."},
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

    def test_enforces_editorial_word_and_character_targets(self):
        too_short = dict(self.posts)
        too_short["facebook"] = " ".join(["actualité"] * 69)
        self.assertFalse(valid_posts(too_short))
        too_long_x = dict(self.posts)
        too_long_x["x"] = "x" * 261
        self.assertFalse(valid_posts(too_long_x))
        short_video_title = dict(self.posts)
        short_video_title["youtube"] = {**self.posts["youtube"], "title": "Titre trop court"}
        self.assertFalse(valid_posts(short_video_title))

    def test_requires_a_french_cross_source_synthesis(self):
        synthesis = {
            "key_facts": ["Le studio a annoncé une nouvelle saison dans son communiqué officiel."],
            "reported_but_unconfirmed": ["La date exacte de diffusion reste à confirmer."],
            "coverage_summary": "Plusieurs médias reprennent cette annonce, mais leur couverture ne constitue pas une confirmation indépendante supplémentaire.",
            "editorial_context": "Cette information intéresse les lecteurs francophones qui suivent cette adaptation et souhaitent distinguer les faits des spéculations."
        }
        self.assertTrue(valid_synthesis(synthesis))
        missing_facts = dict(synthesis)
        missing_facts["key_facts"] = []
        self.assertFalse(valid_synthesis(missing_facts))
        english_summary = dict(synthesis)
        english_summary["coverage_summary"] = "Several outlets are reporting the same announcement without independent confirmation."
        self.assertFalse(valid_synthesis(english_summary))


    def test_accepts_safe_fallback_queue_when_ai_is_not_configured(self):
        queue = {
            "ai_generation_status": "blocked_configuration",
            "ai_generated_count": 0,
            "items": [{
                "title": "Sujet de secours",
                "human_review_required": True,
                "publication_allowed": False,
            }],
        }
        self.assertTrue(valid_editorial_queue(queue))

    def test_rejects_fallback_queue_that_claims_publication_allowed(self):
        queue = {
            "ai_generation_status": "blocked_configuration",
            "ai_generated_count": 0,
            "items": [{
                "title": "Sujet non sécurisé",
                "human_review_required": True,
                "publication_allowed": True,
            }],
        }
        self.assertFalse(valid_editorial_queue(queue))

    def test_generated_queue_requires_eight_social_variants(self):
        queue = {
            "ai_generation_status": "generated",
            "ai_generated_count": 1,
            "items": [{
                "title": "Sujet rédigé",
                "human_review_required": True,
                "publication_allowed": False,
                "social_posts": {
                    "facebook": "Texte",
                    "instagram": "Texte",
                    "tiktok": "Texte",
                    "x": "Texte",
                    "threads": "Texte",
                    "youtube": {"title": "Titre", "description": "Texte"},
                    "telegram": "Texte",
                    "pinterest": {"title": "Titre", "description": "Texte"},
                },
            }],
        }
        self.assertTrue(valid_editorial_queue(queue))
        queue["items"][0]["social_posts"].pop("tiktok")
        self.assertFalse(valid_editorial_queue(queue))

    def test_partial_generation_allows_only_unwritten_fallback_items(self):
        complete = {
            "facebook": "Texte", "instagram": "Texte", "tiktok": "Texte",
            "x": "Texte", "threads": "Texte", "telegram": "Texte",
            "youtube": {"title": "Titre", "description": "Texte"},
            "pinterest": {"title": "Titre", "description": "Texte"},
        }
        queue = {
            "ai_generation_status": "partial",
            "ai_generated_count": 1,
            "items": [
                {"human_review_required": True, "publication_allowed": False, "social_posts": complete},
                {"human_review_required": True, "publication_allowed": False},
            ],
        }
        self.assertTrue(valid_editorial_queue(queue))
        queue["ai_generated_count"] = 2
        self.assertFalse(valid_editorial_queue(queue))

    def test_french_headline_and_summary_detection(self):
        self.assertEqual(detect_text_language("La saison 4 de cette série est confirmée"), "fr")
        self.assertEqual(detect_text_language("The fourth season of this series is confirmed"), "en")


if __name__ == "__main__":
    unittest.main()
