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
PLATFORMS = ("facebook", "tiktok")
MIN_SUMMARY_WORDS = 45


def word_count(value):
    return len(str(value or "").split())


def fit_x_post(value, max_chars=260):
    """Conserve un message X complet; ne coupe jamais un mot en plein milieu."""
    text = " ".join(str(value or "").split())
    last_punctuation = max(text.rfind("."), text.rfind("!"), text.rfind("?"), text.rfind("…"))
    if last_punctuation >= 0:
        complete = text[:last_punctuation + 1].strip()
        if len(complete) <= max_chars and word_count(complete) >= 8:
            return complete
    if len(text) <= max_chars and text.endswith((".", "!", "?", "…")):
        return text
    prefix = text[:max_chars - 1]
    boundary = prefix.rfind(" ")
    if boundary < 1:
        raise ValueError("Message X impossible à raccourcir proprement")
    shortened = prefix[:boundary].rstrip() + "…"
    if word_count(shortened) < 8:
        raise ValueError("Message X trop court après ajustement")
    return shortened


def add_x_source_link(post, source_url, max_chars=260):
    """Ajoute l'URL uniquement si elle tient sans tronquer le texte éditorial."""
    text = fit_x_post(post, max_chars=max_chars)
    url = str(source_url or "").strip()
    if url.startswith("https://") and len(text) + 1 + len(url) <= max_chars:
        return text + " " + url
    return text


def _normalise_sentence(value):
    import re
    import unicodedata
    value = unicodedata.normalize("NFKD", str(value or "").lower())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _content_quality_errors(value, platform):
    import re
    errors = []
    text = str(value or "").strip()
    folded = text.casefold()
    forbidden = (
        "résumé en français à produire", "a produire apres traduction",
        "après traduction et contrôle", "apres traduction et controle",
        "texte à compléter", "texte a completer", "contenu à générer",
        "contenu a generer", "[résumé", "[resume"
    )
    if any(marker in folded for marker in forbidden):
        errors.append(f"{platform} : consigne ou texte de remplacement interdit")
    sentences = [
        _normalise_sentence(part)
        for part in re.split(r"(?<=[.!?…])\s+", text)
        if _normalise_sentence(part)
    ]
    if len(sentences) != len(set(sentences)):
        errors.append(f"{platform} : phrase répétée")
    if platform == "facebook" and not (75 <= word_count(text) <= 135):
        errors.append(f"facebook : longueur {word_count(text)} mots, cible 90 à 110")
    if platform == "tiktok" and not (35 <= word_count(text) <= 75):
        errors.append(f"tiktok : longueur {word_count(text)} mots, cible 40 à 60")
    if detect_text_language(text) != "fr":
        errors.append(f"{platform} : contenu non reconnu comme français")
    return errors


def post_validation_errors(posts):
    """Valide uniquement les deux formats réellement demandés."""
    if not isinstance(posts, dict):
        return ["posts absent ou non structuré"]
    errors = [f"plateforme absente : {key}" for key in PLATFORMS if key not in posts]
    errors.extend(f"plateforme non activée : {key}" for key in posts if key not in PLATFORMS)
    for key in PLATFORMS:
        if key in posts:
            if not isinstance(posts[key], str) or not posts[key].strip():
                errors.append(f"{key} : texte absent ou invalide")
            else:
                errors.extend(_content_quality_errors(posts[key], key))
    if isinstance(posts.get("facebook"), str) and isinstance(posts.get("tiktok"), str):
        facebook_tokens = set(__import__("re").findall(r"[a-zà-ÿ]{4,}", posts["facebook"].lower()))
        tiktok_tokens = set(__import__("re").findall(r"[a-zà-ÿ]{4,}", posts["tiktok"].lower()))
        smaller = min(len(facebook_tokens), len(tiktok_tokens))
        shared = len(facebook_tokens & tiktok_tokens)
        if _normalise_sentence(posts["facebook"]) == _normalise_sentence(posts["tiktok"]) or (smaller and shared / smaller > 0.9):
            errors.append("Facebook et TikTok : adaptations identiques ou trop similaires")
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


def generation_response_diagnostic(trend_id, response_received_ids, response_valid_ids, draft_returned):
    """Sépare la réception HTTP, la validité du payload et le retour d'un brouillon."""
    return {
        "response_received": trend_id in response_received_ids,
        "response_valid": trend_id in response_valid_ids,
        "draft_returned": bool(draft_returned),
    }


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
    response_received_ids = set()
    response_valid_ids = set()

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
                response_body = response.read()
                response_received_ids.add(item.get("trend_id", ""))
                item_result = json.loads(response_body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Une réponse HTTP a bien été reçue, même si le serveur refuse la requête.
            response_received_ids.add(item.get("trend_id", ""))
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
        response_valid_ids.add(item.get("trend_id", ""))
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
    generation_diagnostics = []
    for item in items[:3]:
        draft = generated.get(item.get("trend_id"))
        if not draft:
            detail = next((str(error.get("detail", "")) for error in generation_errors
                           if isinstance(error, dict) and error.get("trend_id") == item.get("trend_id")), "")
            reason = detail or "aucune réponse IA reçue"
            validation_errors.append({"trend_id": item.get("trend_id", ""), "detail": reason})
            generation_diagnostics.append({
                "trend_id": item.get("trend_id", ""),
                "title": str(item.get("title", ""))[:180],
                **generation_response_diagnostic(
                    item.get("trend_id", ""), response_received_ids,
                    response_valid_ids, draft_returned=False
                ),
                "accepted": False,
                "validation_errors": [reason]
            })
            continue
        draft_posts = draft.get("posts")
        item_errors = []
        title_fr = str(draft.get("title_fr", "")).strip()
        summary_fr = str(draft.get("summary_fr", "")).strip()

        # Vérifier le brief avant les déclinaisons : les diagnostics doivent
        # expliquer le vrai défaut éditorial, pas seulement le premier réseau court.
        if detect_text_language(title_fr) != "fr":
            item_errors.append("title_fr : langue française non détectée")
        if detect_text_language(summary_fr) != "fr":
            item_errors.append("summary_fr : langue française non détectée")
        item_errors.extend(_content_quality_errors(summary_fr, "summary_fr"))
        summary_words = word_count(summary_fr)
        if summary_words < MIN_SUMMARY_WORDS:
            item_errors.append(
                f"summary_fr : {summary_words}/{MIN_SUMMARY_WORDS} mots"
            )

        post_errors = post_validation_errors(draft_posts)
        item_errors.extend(post_errors)

        editorial_angle = str(draft.get("editorial_angle", "")).strip()
        discussion_question = str(draft.get("discussion_question", "")).strip()
        if (word_count(editorial_angle) < 8
                or detect_text_language(editorial_angle) != "fr"):
            item_errors.append("editorial_angle : minimum 8 mots français")
        if (word_count(discussion_question) < 6
                or detect_text_language(discussion_question) != "fr"
                or not discussion_question.endswith("?")):
            item_errors.append("discussion_question : minimum 6 mots français et point d'interrogation")

        claims = draft.get("claims_to_verify", [])
        if (not isinstance(claims, list)
                or not all(isinstance(x, str) and word_count(x) >= 4
                           and detect_text_language(x) == "fr" for x in claims)):
            item_errors.append("claims_to_verify : élément trop court ou non français")

        if isinstance(draft_posts, dict):
            french_platforms = ("facebook", "tiktok")
            for key in french_platforms:
                value = draft_posts.get(key)
                if isinstance(value, str) and detect_text_language(value) != "fr":
                    item_errors.append(f"{key} : langue française non détectée")
            for key in ("youtube", "pinterest"):
                value = draft_posts.get(key)
                if isinstance(value, dict):
                    for field in ("title", "description"):
                        if isinstance(value.get(field), str) and detect_text_language(value[field]) != "fr":
                            item_errors.append(f"{key}.{field} : langue française non détectée")

        synthesis = draft.get("trend_synthesis", {})
        if not valid_synthesis(synthesis):
            item_errors.append("trend_synthesis : synthèse croisée absente, trop courte ou non française")

        if item_errors:
            validation_errors.append({
                "trend_id": item.get("trend_id", ""),
                "detail": " | ".join(item_errors[:20])
            })
            generation_diagnostics.append({
                "trend_id": item.get("trend_id", ""),
                "title": str(item.get("title", ""))[:180],
                "response_received": True,
                "accepted": False,
                "validation_errors": item_errors[:20]
            })
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
        # Les liens et noms des médias restent dans la fiche de sources, pas dans le corps rédactionnel.
        item["social_posts"] = {
            **posts,
            "language_ready": True,
            "translation_required": False,
            "translation_note": "Rédaction française IA contrôlée : relecture humaine obligatoire avant toute publication."
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
        generation_diagnostics.append({
            "trend_id": item.get("trend_id", ""),
            "title": str(item.get("title", ""))[:180],
            **generation_response_diagnostic(
                item.get("trend_id", ""), response_received_ids,
                response_valid_ids, draft_returned=True
            ),
            "accepted": True,
            "validation_errors": []
        })

    queue["ai_generation_diagnostics"] = generation_diagnostics[:12]
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
