#!/usr/bin/env python3
"""Génère des déclinaisons sociales françaises via l'endpoint IA sécurisé, sans jamais publier."""
import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from pathlib import Path

try:
    from radar_logic import detect_text_language
except ModuleNotFoundError:
    from scripts.radar_logic import detect_text_language

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "data" / "editorial_queue.json"
PLATFORMS = ("facebook", "instagram", "tiktok", "x", "threads", "youtube", "telegram", "pinterest")


def word_count(value):
    return len(str(value or "").split())


def post_validation_errors(posts):
    """Retourne les contrôles précis qui empêchent l'acceptation des textes sociaux."""
    if not isinstance(posts, dict):
        return ["posts absent ou non structuré"]
    errors = [f"plateforme absente : {key}" for key in PLATFORMS if key not in posts]
    minimum_words = {
        "facebook": 70, "instagram": 45, "tiktok": 35,
        "x": 8, "threads": 40, "telegram": 40,
    }
    for key in PLATFORMS:
        if key not in posts:
            continue
        value = posts[key]
        if key in ("youtube", "pinterest"):
            if not isinstance(value, dict):
                errors.append(f"{key} : titre/description doivent être un objet")
                continue
            title = value.get("title")
            description = value.get("description")
            if not isinstance(title, str) or len(title.strip()) < 45:
                errors.append(f"{key} : titre inférieur à 45 caractères")
            minimum = 50 if key == "youtube" else 35
            if not isinstance(description, str) or word_count(description) < minimum:
                actual = word_count(description) if isinstance(description, str) else 0
                errors.append(f"{key} : description {actual}/{minimum} mots")
        else:
            if not isinstance(value, str):
                errors.append(f"{key} : texte absent ou invalide")
                continue
            actual = word_count(value)
            if actual < minimum_words[key]:
                errors.append(f"{key} : texte {actual}/{minimum_words[key]} mots")
            if key == "x" and len(value) > 260:
                errors.append(f"x : {len(value)}/260 caractères")
    return errors


def valid_posts(posts):
    """Compatibilité avec les tests et les autres modules du projet."""
    return not post_validation_errors(posts)


def valid_synthesis(synthesis):
    if not isinstance(synthesis, dict):
        return False
    key_facts = synthesis.get("key_facts")
    unconfirmed = synthesis.get("reported_but_unconfirmed")
    coverage = synthesis.get("coverage_summary")
    context = synthesis.get("editorial_context")
    return (
        isinstance(key_facts, list) and bool(key_facts)
        and all(isinstance(x, str) and word_count(x) >= 5 and detect_text_language(x) == "fr" for x in key_facts)
        and isinstance(unconfirmed, list)
        and all(isinstance(x, str) and word_count(x) >= 4 and detect_text_language(x) == "fr" for x in unconfirmed)
        and isinstance(coverage, str) and word_count(coverage) >= 8
        and detect_text_language(coverage) == "fr"
        and isinstance(context, str) and word_count(context) >= 8
        and detect_text_language(context) == "fr"
    )


def save_generation_status(queue, status, notice, model=""):
    queue["ai_generated_count"] = 0
    queue["ai_generation_status"] = status
    queue["ai_model"] = model
    queue["ai_notice"] = notice
    QUEUE.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    endpoint = os.environ.get("AUTOTREND_AI_URL", "").strip()
    token = os.environ.get("AUTOTREND_AI_TOKEN", "").strip()
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    items = queue.get("items", [])
    if not endpoint or not token:
        save_generation_status(
            queue, "blocked_configuration",
            "Rédaction IA non activée : configurer AUTOTREND_AI_URL et AUTOTREND_AI_TOKEN dans les secrets GitHub Actions. Les brouillons restent non publiables."
        )
        print("IA éditoriale bloquée : secrets GitHub Actions manquants.")
        return 0

    endpoint_host = urlsplit(endpoint).hostname or "hôte invalide"
    print(f"Endpoint IA (hôte) : {endpoint_host}")

    if not endpoint.startswith("https://"):
        save_generation_status(
            queue, "blocked_insecure_endpoint",
            "Rédaction IA bloquée : l'endpoint doit utiliser HTTPS. Aucune publication n'est autorisée."
        )
        print("IA éditoriale ignorée : l'endpoint doit utiliser HTTPS.")
        return 0
    if not items:
        print("Aucun sujet éligible à rédiger.")
        return 0

    # Envoyer un sujet par requête : une génération lente ne doit pas faire
    # expirer tout le lot ni empêcher les sujets suivants d'être traités.
    generated_items = []
    generation_errors = []
    model = ""
    generated_at = ""

    for item in items[:3]:
        payload_item = {
            "trend_id": item.get("trend_id", ""),
            "title": item.get("title", ""),
            "source_excerpt": item.get("source_excerpt", "")[:1200],
            "source_url": item.get("source_excerpt_url", ""),
            "sources": item.get("media", [])[:8],
            "source_countries": item.get("source_countries", []),
            "market_countries": item.get("market_countries", []),
            "editorial_status": item.get("editorial_status", ""),
            "official_evidence": item.get("official_evidence", [])[:5],
            "source_reports": [
                {
                    "title": article.get("title", "")[:300],
                    "summary": article.get("summary", "")[:500],
                    "publisher": article.get("publisher") or article.get("source", ""),
                    "source_type": article.get("source_type", ""),
                    "source_country": article.get("source_country", ""),
                    "market_country": article.get("market_country", ""),
                    "published_at": article.get("published_at", ""),
                    "url": article.get("url", "")[:500]
                }
                for article in item.get("articles", [])[:6]
            ],
            "coverage": {
                "media_count": item.get("media_count", len(item.get("media", []))),
                "primary_source_count": item.get("primary_source_count", 0),
                "verification_coverage": item.get("verification_coverage", {}),
                "source_regions": item.get("source_regions", []),
                "market_regions": item.get("market_regions", [])
            }
        }
        request = urllib.request.Request(
            endpoint,
            data=json.dumps({"items": [payload_item]}, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token,
                "User-Agent": "AutreTrendStudios/1.0"
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=150) as response:
                item_result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                response_detail = exc.read().decode("utf-8", errors="replace").strip()[:240]
            except Exception:
                response_detail = ""
            detail = f"HTTP {exc.code}" + ((" — " + response_detail) if response_detail else "")
            generation_errors.append({"trend_id": item.get("trend_id", ""), "detail": detail[:240]})
            print(f"Génération IA ignorée pour un sujet : {detail[:220]}")
            continue
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            detail = str(exc)[:220]
            generation_errors.append({"trend_id": item.get("trend_id", ""), "detail": detail})
            print(f"Génération IA ignorée pour un sujet : {detail}")
            continue

        if not isinstance(item_result, dict) or not isinstance(item_result.get("items"), list):
            generation_errors.append({
                "trend_id": item.get("trend_id", ""),
                "detail": "Réponse IA invalide ou sans liste items"
            })
            continue
        generated_items.extend(
            value for value in item_result.get("items", []) if isinstance(value, dict)
        )
        response_errors = item_result.get("errors", [])
        if isinstance(response_errors, list):
            generation_errors.extend(
                value for value in response_errors if isinstance(value, dict)
            )
        model = item_result.get("model") or model
        generated_at = item_result.get("generated_at") or generated_at

    result = {
        "items": generated_items,
        "errors": generation_errors,
        "model": model,
        "generated_at": generated_at
    }

    if not isinstance(result, dict) or not isinstance(result.get("items"), list):
        save_generation_status(
            queue, "invalid_response",
            "Le service IA a renvoyé une réponse invalide. Les brouillons restent non publiables."
        )
        print("IA éditoriale : réponse inattendue; brouillons de secours conservés.")
        return 0

    generated = {
        item.get("trend_id"): item
        for item in result.get("items", [])
        if isinstance(item, dict) and item.get("trend_id")
    }
    generation_errors = result.get("errors", [])
    if not isinstance(generation_errors, list):
        generation_errors = []
    accepted = 0
    validation_errors = []
    for item in items[:3]:
        draft = generated.get(item.get("trend_id"))
        if not draft:
            detail = next((str(error.get("detail", "")) for error in generation_errors
                           if isinstance(error, dict) and error.get("trend_id") == item.get("trend_id")), "")
            validation_errors.append({"trend_id": item.get("trend_id", ""),
                                      "detail": detail or "aucune réponse IA reçue"})
            continue
        post_errors = post_validation_errors(draft.get("posts"))
        if post_errors:
            validation_errors.append({"trend_id": item.get("trend_id", ""),
                                      "detail": " | ".join(post_errors[:8])})
            continue
        title_fr = str(draft.get("title_fr", "")).strip()
        summary_fr = str(draft.get("summary_fr", "")).strip()
        # Une simple réponse du modèle ne suffit pas : on exige aussi une détection française.
        if (detect_text_language(title_fr) != "fr"
                or detect_text_language(summary_fr) != "fr"
                or word_count(summary_fr) < 60):
            validation_errors.append({"trend_id": item.get("trend_id", ""),
                                      "detail": "titre/résumé : langue française ou résumé de 60 mots non validé"})
            continue
        editorial_angle = str(draft.get("editorial_angle", "")).strip()
        discussion_question = str(draft.get("discussion_question", "")).strip()
        if (word_count(editorial_angle) < 8
                or detect_text_language(editorial_angle) != "fr"
                or word_count(discussion_question) < 6
                or detect_text_language(discussion_question) != "fr"
                or not discussion_question.endswith("?")):
            validation_errors.append({"trend_id": item.get("trend_id", ""),
                                      "detail": "angle/question : langue française, longueur ou ponctuation invalide"})
            continue
        claims = draft.get("claims_to_verify", [])
        if (not isinstance(claims, list)
                or not all(isinstance(x, str) and word_count(x) >= 4
                           and detect_text_language(x) == "fr" for x in claims)):
            validation_errors.append({"trend_id": item.get("trend_id", ""),
                                      "detail": "claims_to_verify : au moins un élément est trop court ou non français"})
            continue
        french_platforms = ("facebook", "instagram", "tiktok", "x", "threads", "telegram")
        if any(detect_text_language(draft["posts"][key]) != "fr" for key in french_platforms):
            validation_errors.append({"trend_id": item.get("trend_id", ""),
                                      "detail": "au moins un texte social n'est pas détecté en français"})
            continue
        if any(
            detect_text_language(draft["posts"][key]["title"]) != "fr"
            or detect_text_language(draft["posts"][key]["description"]) != "fr"
            for key in ("youtube", "pinterest")
        ):
            validation_errors.append({"trend_id": item.get("trend_id", ""),
                                      "detail": "YouTube/Pinterest : titre ou description non détecté en français"})
            continue

        synthesis = draft.get("trend_synthesis", {})
        if not valid_synthesis(synthesis):
            validation_errors.append({"trend_id": item.get("trend_id", ""),
                                      "detail": "synthèse croisée absente, trop courte ou non française"})
            continue
        item["trend_synthesis"] = {
            "key_facts": [str(x)[:400] for x in synthesis.get("key_facts", [])[:8]],
            "reported_but_unconfirmed": [str(x)[:400] for x in synthesis.get("reported_but_unconfirmed", [])[:8]],
            "coverage_summary": synthesis.get("coverage_summary", "").strip(),
            "editorial_context": synthesis.get("editorial_context", "").strip()
        }
        item["title_fr"] = title_fr
        item["summary_fr"] = summary_fr
        item["editorial_angle"] = editorial_angle
        item["discussion_question"] = discussion_question
        item["claims_to_verify"] = claims[:12]
        posts = dict(draft["posts"])
        source_url = str(item.get("source_excerpt_url", "")).strip()
        if source_url.startswith("https://"):
            publishers = ", ".join(item.get("media", [])[:3])
            source_note = "\nSource à consulter : " + publishers + "\n" + source_url
            for key in ("facebook", "instagram", "threads", "telegram"):
                posts[key] = str(posts[key]).rstrip() + source_note
            posts["youtube"] = {
                **posts["youtube"],
                "description": str(posts["youtube"]["description"]).rstrip() + source_note
            }
            posts["pinterest"] = {
                **posts["pinterest"],
                "description": str(posts["pinterest"]["description"]).rstrip() + source_note
            }
            posts["tiktok"] = str(posts["tiktok"]).rstrip() + "\nSource à consulter : " + publishers
            x_post = str(posts["x"]).rstrip()
            x_with_link = x_post + " " + source_url
            posts["x"] = x_with_link if len(x_with_link) <= 280 else x_post[:250].rstrip()
        item["social_posts"] = {
            **posts,
            "language_ready": True,
            "translation_required": False,
            "translation_note": "Traduction IA proposée : relecture humaine obligatoire avant toute publication."
        }
        item["ai_generation"] = {
            "provider": "Cloudflare Workers AI",
            "model": result.get("model", "unknown"),
            "generated_at": result.get("generated_at", ""),
            "human_review_required": True
        }
        item["human_review_required"] = True
        item["publication_allowed"] = False
        item["editorial_status"] = str(item.get("editorial_status", "")) + " · rédaction IA à relire"
        item["draft_fr"] = (
            "PRÉPUBLICATION FRANÇAISE — GÉNÉRÉE PAR IA, À VALIDER\n\n"
            + "Titre : " + title_fr + "\n\n"
            + summary_fr + "\n\n"
            + "Angle éditorial : " + item["editorial_angle"] + "\n"
            + "Synthèse des tendances : " + item["trend_synthesis"]["coverage_summary"] + "\n"
            + "Faits clés : " + "; ".join(item["trend_synthesis"]["key_facts"]) + "\n"
            + "Éléments rapportés à confirmer : " + "; ".join(item["trend_synthesis"]["reported_but_unconfirmed"]) + "\n"
            + "Question : " + item["discussion_question"] + "\n\n"
            + "Points à vérifier : " + "; ".join(item["claims_to_verify"]) + "\n\n"
            + "Sources : " + ", ".join(item.get("media", [])) + "\n"
            + "Ne pas publier sans relecture humaine."
        )
        accepted += 1

    queue["ai_validation_errors"] = validation_errors[:12]
    queue["ai_generated_count"] = accepted
    queue["ai_generation_status"] = "generated" if accepted == len(items[:3]) else ("partial" if accepted else "rejected")
    queue["ai_model"] = result.get("model", "")
    if accepted == len(items[:3]):
        queue["ai_notice"] = "Rédaction assistée par IA, adaptations spécifiques à chaque réseau. Validation humaine obligatoire; aucune publication automatique."
    elif accepted:
        queue["ai_notice"] = (
            f"Rédaction IA partielle : {accepted}/{len(items[:3])} sujet(s) validé(s). "
            "Les sujets en échec restent non publiables. Validation humaine obligatoire."
        )
    else:
        all_errors = generation_errors + validation_errors
        details = "; ".join(
            str(error.get("detail", "échec de génération"))[:180]
            for error in all_errors if isinstance(error, dict)
        )
        queue["ai_notice"] = (
            "Aucune prépublication IA validée. Les brouillons restent non publiables."
            + ((" Détails : " + details) if details else "")
        )
    QUEUE.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"IA éditoriale : {accepted}/{len(items[:3])} prépublication(s) françaises validées structurellement; contrôle humain toujours requis.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
