#!/usr/bin/env python3
"""Génère des déclinaisons sociales françaises via l'endpoint IA sécurisé, sans jamais publier."""
import json
import os
import sys
import urllib.error
import urllib.request
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


def valid_posts(posts):
    if not isinstance(posts, dict) or not all(key in posts for key in PLATFORMS):
        return False
    minimum_words = {
        "facebook": 45, "instagram": 30, "tiktok": 25,
        "x": 8, "threads": 25, "telegram": 25,
    }
    for key in PLATFORMS:
        value = posts[key]
        if key in ("youtube", "pinterest"):
            if (not isinstance(value, dict)
                    or not isinstance(value.get("title"), str)
                    or len(value["title"].strip()) < 12
                    or not isinstance(value.get("description"), str)
                    or word_count(value["description"]) < 25):
                return False
        elif (not isinstance(value, str)
                or word_count(value) < minimum_words[key]):
            return False
        elif key == "x" and len(value) > 280:
            return False
    return True


def save_generation_status(queue, status, notice, model=""):
    queue["ai_generated_count"] = 0
    queue["ai_generation_status"] = status
    queue["ai_model"] = model
    queue["ai_notice"] = notice
    QUEUE.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")


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

    payload_items = []
    for item in items[:3]:
        payload_items.append({
            "trend_id": item.get("trend_id", ""),
            "title": item.get("title", ""),
            "source_excerpt": item.get("source_excerpt", "")[:1200],
            "source_url": item.get("source_excerpt_url", ""),
            "sources": item.get("media", [])[:8],
            "source_countries": item.get("source_countries", []),
            "market_countries": item.get("market_countries", []),
            "editorial_status": item.get("editorial_status", ""),
            "official_evidence": item.get("official_evidence", [])[:5]
        })

    request = urllib.request.Request(
        endpoint,
        data=json.dumps({"items": payload_items}, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token,
            "User-Agent": "AutreTrendStudios/1.0"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=55) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        save_generation_status(
            queue, "unavailable",
            "Service IA indisponible : " + str(exc)[:180] + ". Les brouillons restent non publiables."
        )
        print(f"IA éditoriale indisponible : {str(exc)[:200]}. Brouillons de secours conservés.")
        return 0

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
    accepted = 0
    for item in items[:3]:
        draft = generated.get(item.get("trend_id"))
        if not draft or not valid_posts(draft.get("posts")):
            continue
        title_fr = str(draft.get("title_fr", "")).strip()
        summary_fr = str(draft.get("summary_fr", "")).strip()
        # Une simple réponse du modèle ne suffit pas : on exige aussi une détection française.
        if (detect_text_language(title_fr) != "fr"
                or detect_text_language(summary_fr) != "fr"
                or word_count(summary_fr) < 35):
            continue
        if (word_count(draft.get("editorial_angle", "")) < 8
                or word_count(draft.get("discussion_question", "")) < 6
                or not str(draft.get("discussion_question", "")).strip().endswith("?")):
            continue
        claims = draft.get("claims_to_verify", [])
        if not isinstance(claims, list) or not all(isinstance(x, str) for x in claims):
            continue
        french_platforms = ("facebook", "instagram", "tiktok", "threads", "telegram")
        if any(detect_text_language(draft["posts"][key]) != "fr" for key in french_platforms):
            continue
        if any(detect_text_language(draft["posts"][key]["description"]) != "fr" for key in ("youtube", "pinterest")):
            continue

        item["title_fr"] = title_fr
        item["summary_fr"] = summary_fr
        item["editorial_angle"] = str(draft.get("editorial_angle", "")).strip()
        item["discussion_question"] = str(draft.get("discussion_question", "")).strip()
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
            + "Question : " + item["discussion_question"] + "\n\n"
            + "Points à vérifier : " + "; ".join(item["claims_to_verify"]) + "\n\n"
            + "Sources : " + ", ".join(item.get("media", [])) + "\n"
            + "Ne pas publier sans relecture humaine."
        )
        accepted += 1

    queue["ai_generated_count"] = accepted
    queue["ai_generation_status"] = "generated" if accepted == len(items[:3]) else ("partial" if accepted else "rejected")
    queue["ai_model"] = result.get("model", "")
    queue["ai_notice"] = "Rédaction assistée par IA, adaptations spécifiques à chaque réseau. Validation humaine obligatoire; aucune publication automatique."
    QUEUE.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"IA éditoriale : {accepted}/{len(items[:3])} prépublication(s) françaises validées structurellement; contrôle humain toujours requis.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
