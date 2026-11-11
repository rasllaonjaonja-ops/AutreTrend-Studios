"""Tests du contrat de génération éditoriale assistée."""
import unittest
from scripts.generate_editorial import valid_posts, valid_synthesis, post_validation_errors, post_validation_errors
from scripts.radar_logic import detect_text_language
from scripts.quality_check import valid_editorial_queue


class EditorialGenerationTests(unittest.TestCase):
    def setUp(self):
        self.posts = {
            "facebook": "Une annonce importante vient d'être confirmée par le studio officiel. Les médias spécialisés rapportent également plusieurs précisions sur le calendrier et les éléments présentés lors de l'événement. Notre comparaison distingue les faits communs des détails encore incertains, sans reprendre mécaniquement les mêmes formulations. Cette nouvelle étape donne aux fans une raison de suivre les prochaines communications. Les premiers articles évoquent le même événement, mais certaines précisions doivent encore être rapprochées avant d'être considérées comme définitives. Nous retenons uniquement les informations qui apparaissent clairement dans les comptes rendus disponibles, et nous signalons les zones d'ombre plutôt que de les combler. Quel aspect de cette annonce attendez-vous le plus ?",
            "tiktok": "Vous avez vu cette annonce ? Le studio confirme un nouveau projet, tandis que plusieurs médias détaillent les premières informations disponibles. Attention, certains éléments restent à préciser et ne doivent pas être présentés comme définitifs. On suivra les prochaines annonces : qu'est-ce qui vous intrigue le plus ?"
        }

    def test_requires_only_facebook_and_tiktok(self):
        self.assertTrue(valid_posts(self.posts))
        incomplete = dict(self.posts)
        incomplete.pop("tiktok")
        self.assertFalse(valid_posts(incomplete))

    def test_rejects_unselected_platforms(self):
        malformed = dict(self.posts)
        malformed["instagram"] = "Plateforme non activée"
        self.assertFalse(valid_posts(malformed))

    def test_rejects_placeholder_or_thin_social_copy(self):
        shallow = dict(self.posts)
        shallow["facebook"] = "Voici une actualité manga."
        self.assertFalse(valid_posts(shallow))

    def test_rejects_legacy_x_posts_over_platform_limit(self):
        oversized = dict(self.posts)
        oversized["instagram"] = "Information manga " * 30
        self.assertFalse(valid_posts(oversized))

    def test_enforces_editorial_word_and_character_targets(self):
        too_short = dict(self.posts)
        too_short["facebook"] = " ".join(["actualité"] * 59)
        self.assertFalse(valid_posts(too_short))
        too_long_facebook = dict(self.posts)
        too_long_facebook["facebook"] = " ".join(["actualité"] * 140)
        self.assertFalse(valid_posts(too_long_facebook))

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

    def test_generated_queue_requires_two_social_variants(self):
        queue = {
            "ai_generation_status": "generated",
            "ai_generated_count": 1,
            "items": [{
                "title": "Sujet rédigé",
                "human_review_required": True,
                "publication_allowed": False,
                "ai_generation": {"provider": "Cloudflare Workers AI", "human_review_required": True},
                "social_posts": {"facebook": "Texte", "tiktok": "Texte"},
            }],
        }
        self.assertTrue(valid_editorial_queue(queue))
        queue["items"][0]["social_posts"].pop("tiktok")
        self.assertFalse(valid_editorial_queue(queue))

    def test_partial_generation_allows_only_unwritten_fallback_items(self):
        complete = {"facebook": "Texte", "tiktok": "Texte"}
        queue = {
            "ai_generation_status": "partial",
            "ai_generated_count": 1,
            "items": [
                {"human_review_required": True, "publication_allowed": False,
                 "ai_generation": {"provider": "Cloudflare Workers AI"}, "social_posts": complete},
                {"human_review_required": True, "publication_allowed": False, "social_posts": complete},
            ],
        }
        self.assertTrue(valid_editorial_queue(queue))
        queue["ai_generated_count"] = 2
        self.assertFalse(valid_editorial_queue(queue))

    def test_facebook_has_a_real_minimum_without_mechanical_padding(self):
        shorter = dict(self.posts)
        shorter["facebook"] = " ".join(self.posts["facebook"].split()[:80])
        self.assertTrue(valid_posts(shorter))
        too_short = dict(self.posts)
        too_short["facebook"] = " ".join(self.posts["facebook"].split()[:59])
        self.assertFalse(valid_posts(too_short))

    def test_rejects_placeholder_repetition_and_identical_platform_copy(self):
        placeholder = dict(self.posts)
        placeholder["facebook"] = "RÉSUMÉ EN FRANÇAIS À PRODUIRE APRÈS TRADUCTION ET CONTRÔLE"
        self.assertTrue(any("consigne" in error for error in post_validation_errors(placeholder)))
        repeated = dict(self.posts)
        repeated["tiktok"] = "Cette annonce est importante. Cette annonce est importante. Le studio confirme un projet avec des informations utiles et une date à préciser pour les fans."
        self.assertTrue(any("répétée" in error for error in post_validation_errors(repeated)))
        identical = {"facebook": self.posts["facebook"], "tiktok": self.posts["facebook"]}
        self.assertTrue(any("identiques" in error for error in post_validation_errors(identical)))

    def test_rejects_placeholder_repetition_and_identical_platform_copy(self):
        placeholder = dict(self.posts)
        placeholder["facebook"] = "RÉSUMÉ EN FRANÇAIS À PRODUIRE APRÈS TRADUCTION ET CONTRÔLE"
        self.assertTrue(any("consigne" in error for error in post_validation_errors(placeholder)))
        repeated = dict(self.posts)
        repeated["tiktok"] = "Cette annonce est importante. Cette annonce est importante. Le studio confirme un projet avec des informations utiles et une date à préciser pour les fans."
        self.assertTrue(any("répétée" in error for error in post_validation_errors(repeated)))
        identical = {"facebook": self.posts["facebook"], "tiktok": self.posts["facebook"]}
        self.assertTrue(any("identiques" in error for error in post_validation_errors(identical)))

    def test_french_headline_and_summary_detection(self):
        self.assertEqual(detect_text_language("La saison 4 de cette série est confirmée"), "fr")
        self.assertEqual(detect_text_language("The fourth season of this series is confirmed"), "en")

    def test_worker_and_python_share_editorial_minimums(self):
        from scripts import generate_editorial
        worker_path = __import__("pathlib").Path(__file__).resolve().parents[1] / "functions" / "api" / "editorial.js"
        worker_prompt = worker_path.read_text(encoding="utf-8")
        self.assertEqual(generate_editorial.MIN_SUMMARY_WORDS, 35)
        self.assertIn("summary_fr : 40 à 70 mots", worker_prompt)
        self.assertIn("summary_fr doit contenir au moins ${MIN_SUMMARY_WORDS} mots", worker_prompt)
        self.assertNotIn("atteindre 60 mots", worker_prompt)
        self.assertIn('const PLATFORMS = ["facebook", "tiktok"]', worker_prompt)
        self.assertNotIn("Instagram :", worker_prompt)
        self.assertNotIn("Pinterest :", worker_prompt)

    def test_radar_workflow_uses_configured_ai_endpoint_secret(self):
        from pathlib import Path
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "radar-rss.yml").read_text(encoding="utf-8")
        self.assertIn("AUTOTREND_AI_URL: ${{ secrets.AUTOTREND_AI_URL }}", workflow)
        self.assertNotIn("autretrend-studios-ai-test.pages.dev", workflow)

    def test_generation_diagnostics_are_per_item_and_use_the_real_summary_threshold(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / "scripts" / "generate_editorial.py").read_text(encoding="utf-8")
        self.assertIn("ai_generation_diagnostics", source)
        self.assertIn("response_received", source)
        self.assertIn("response_valid", source)
        self.assertIn("draft_returned", source)
        self.assertIn("validation_errors", source)
        self.assertIn("MIN_SUMMARY_WORDS", source)
        self.assertNotIn("résumé de 60 mots non validé", source)

    def test_generation_response_diagnostics_distinguish_rejection_from_no_response(self):
        from scripts.generate_editorial import generation_response_diagnostic
        received = {"trend-a"}
        valid = {"trend-a"}
        rejected = generation_response_diagnostic("trend-a", received, valid, draft_returned=False)
        self.assertEqual(rejected, {
            "response_received": True,
            "response_valid": True,
            "draft_returned": False,
        })
        missing = generation_response_diagnostic("trend-b", received, valid, draft_returned=False)
        self.assertEqual(missing, {
            "response_received": False,
            "response_valid": False,
            "draft_returned": False,
        })
        accepted = generation_response_diagnostic("trend-a", received, valid, draft_returned=True)
        self.assertEqual(accepted, {
            "response_received": True,
            "response_valid": True,
            "draft_returned": True,
        })
    def test_worker_prompt_protects_proper_names_and_source_fidelity(self):
        worker_path = __import__("pathlib").Path(__file__).resolve().parents[1] / "functions" / "api" / "editorial.js"
        worker_prompt = worker_path.read_text(encoding="utf-8")
        self.assertIn("ne traduis jamais les noms propres", worker_prompt)
        self.assertIn("Forgeron", worker_prompt)
        self.assertIn("laisse le contrôle rejeter le sujet", worker_prompt)


if __name__ == "__main__":
    unittest.main()
