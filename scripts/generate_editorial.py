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


def valid_posts(posts):
    if not isinstance(posts, dict) or not all(key in posts for key in PLATFORMS):
        return False
    for key in PLATFORMS:
        value = posts[key]
        if key in ("youtube", "pinterest"):
            if not isinstance(value, dict) or not value.get("title") or not value.get("description"):
                return False
        elif not isinstance(value, str) or not value.strip():
            return False
    return True


def main():
    endpoint = os.environ.get("AUTOTREND_AI_URL", "").strip()
    token = os.environ.get("AUTOTREND_AI_TOKEN", "").strip()
    if not endpoint or not token:
        print("IA éditoriale non configurée : les brouillons sûrs restent disponibles, traduction à relire.")
        return 0

    if not endpoint.startswith("https://"):
        print("IA éditoriale ignorée : l'endpoint doit utiliser HTTPS.")
        return 0

    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    items = queue.get("items", [])
    if not items:
        print("Aucun sujet éligible à rédiger.")
        return 0

    payload_items = []
    for item in items[:3]:
        payload_items.append({
            "trend_id": item.get("trend_id", ""),
            "title": item.get("title", ""),
            "source_excerpt": item.get("source_excerpt", "")[:1200],
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
        print(f"IA éditoriale indisponible : {str(exc)[:200]}. Brouillons de secours conservés.")
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
        if detect_text_language(title_fr) != "fr" or detect_text_language(summary_fr) != "fr":
            continue

        item["title_fr"] = title_fr
        item["summary_fr"] = summary_fr
        item["editorial_angle"] = str(draft.get("editorial_angle", "")).strip()
        item["discussion_question"] = str(draft.get("discussion_question", "")).strip()
        item["claims_to_verify"] = draft.get("claims_to_verify", [])[:12]
        item["social_posts"] = {
            **draft["posts"],
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
    queue["ai_model"] = result.get("model", "")
    queue["ai_notice"] = "Rédaction assistée par IA, traduction et adaptations à relire. Validation humaine obligatoire; aucune publication automatique."
    QUEUE.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"IA éditoriale : {accepted}/{len(items[:3])} prépublication(s) françaises validées structurellement; contrôle humain toujours requis.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
