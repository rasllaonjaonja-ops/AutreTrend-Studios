#!/usr/bin/env python3
"""Contrôle de provenance : repère les liens de première partie, sans déclarer automatiquement un fait vrai."""
import json
import re
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

try:
    from radar_logic import detect_text_language, diversify_queue
except ModuleNotFoundError:  # Import également possible depuis les tests à la racine du dépôt.
    from scripts.radar_logic import detect_text_language, diversify_queue
from urllib.parse import urlparse, urljoin

ROOT = Path(__file__).resolve().parents[1]
RADAR = ROOT / "data" / "radar.json"
OUT = ROOT / "data" / "verification.json"
QUEUE = ROOT / "data" / "editorial_queue.json"
MAX_ARTICLES = 40
MAX_PREPUBLICATIONS = 3
SOCIAL_NETWORKS = ("facebook", "tiktok")
TIMEOUT = 4

# Liste volontairement conservatrice : les médias généralistes ne sont pas traités comme preuves officielles.
OFFICIAL_DOMAINS = {
    "shueisha.co.jp", "shonenjumpplus.com", "mangaplus.shueisha.co.jp",
    "kodansha.co.jp", "kc.kodansha.co.jp", "shogakukan.co.jp",
    "sunday-webry.com", "viz.com", "集英社.jp",
    "toei-animation.com", "toei-anim.co.jp", "aniplex.co.jp",
    "a1p.jp", "ufotable.com", "mappa.co.jp", "witstudio.co.jp",
    "science-saru.com", "bones.co.jp", "pierrot.jp", "pierrot.jp",
    "bandainamcoarts.co.jp", "bnarts.jp", "production-ig.co.jp",
    "netflix.com", "about.netflix.com", "media.netflix.com",
    "disneyplus.com", "primevideo.com",
    "toho.co.jp", "tohoanimation.com", "kadokawa.co.jp",
    "hakusensha.co.jp", "square-enix.com", "magazine.jp",
    "tv-tokyo.co.jp", "ntv.co.jp",
    "kadokawa-animation.jp", "kadokawa-anime.com"
}
NEWS_DOMAINS = {
    "animenewsnetwork.com", "crunchyroll.com", "myanimelist.net",
    "animenews.com", "animecorner.me", "comicbook.com", "variety.com",
    "deadline.com", "hollywoodreporter.com", "ign.com"
}

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.title_parts = []
        self.in_title = False
        self.current_href = None
        self.current_anchor_parts = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag.lower() == "a":
            self.current_href = attrs.get("href")
            self.current_anchor_parts = []
        if tag.lower() == "title":
            self.in_title = True
    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.current_href:
            label = re.sub(r"\s+", " ", " ".join(self.current_anchor_parts)).strip()[:180]
            self.links.append({"href": self.current_href, "label": label})
            self.current_href = None
            self.current_anchor_parts = []
        if tag.lower() == "title":
            self.in_title = False
    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data.strip())
        if self.current_href is not None:
            self.current_anchor_parts.append(data.strip())

def host_is(domain, base):
    return domain == base or domain.endswith("." + base)

def is_official(url, article_host):
    try:
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
        if not host or host == article_host:
            return False
        return any(host_is(host, d) for d in OFFICIAL_DOMAINS)
    except Exception:
        return False

def fetch_links(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "AutreTrendStudios/1.0 (editorial source checker; contact: repository owner)",
        "Accept": "text/html,application/xhtml+xml"
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type.lower():
            return [], ""
        raw = response.read(1_500_000).decode("utf-8", "replace")
    parser = Links()
    parser.feed(raw)
    base = url
    resolved = []
    for entry in parser.links:
        absolute = urljoin(base, entry["href"])
        if absolute.startswith("https://"):
            resolved.append({"url": absolute.split("#", 1)[0], "label": entry["label"]})
    unique = {}
    for entry in resolved:
        unique.setdefault(entry["url"], entry)
    return list(unique.values()), " ".join(parser.title_parts)[:300]

def enrich_source_reports(trend_articles, radar_items):
    """Associe chaque titre du groupe à son résumé RSS d'origine, sans inventer de contenu."""
    reports = []
    for article in trend_articles:
        url = article.get("url", "")
        original = radar_items.get(url, {})
        reports.append({
            **article,
            "summary": str(original.get("summary", "")).strip()[:1200],
            "publisher": original.get("publisher") or original.get("source") or article.get("source", ""),
            "published_at": original.get("published_at", ""),
            "language": original.get("language", article.get("title_language", "und")),
            "summary_status": original.get("summary_status", "missing"),
            "date_status": original.get("date_status", "unknown")
        })
    return reports

def age_hours_for_sampling(value, now=None):
    """Retourne l'âge en heures; les dates absentes, trop anciennes ou futures sont non classables."""
    from datetime import datetime, timedelta, timezone
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        if dt > current + timedelta(hours=24):
            return None
        hours = (current - dt).total_seconds() / 3600
        if hours > 24 * 30:
            return None
        return max(0, hours)
    except Exception:
        return None


def verification_rank(item, now=None):
    """Classe les dates valides de la plus récente à la plus ancienne, puis par score."""
    age = age_hours_for_sampling(item.get("published_at"), now=now)
    try:
        score = int(item.get("score", 0) or 0)
    except (TypeError, ValueError):
        score = 0
    return (age is None, age if age is not None else float("inf"), -score)


def main():
    radar = json.loads(RADAR.read_text(encoding="utf-8"))
    items = radar.get("items", [])
    checks = []
    errors = []
    # Échantillon de vérification : dates valides les plus récentes d'abord,
    # puis score décroissant. Les dates absentes/anciennes restent en fin d'échantillon.
    selected_items = sorted(items, key=verification_rank)[:MAX_ARTICLES]
    for item in selected_items:
        url = item.get("url", "")
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
        result = {
            "title": item.get("title", ""),
            "article_url": url,
            "publisher": item.get("publisher") or item.get("source", ""),
            "published_at": item.get("published_at", ""),
            "official_evidence": [],
            "status": "aucune preuve officielle repérée — vérification humaine requise"
        }
        try:
            links, page_title = fetch_links(url)
            for link in links:
                link_url = link["url"]
                if is_official(link_url, host):
                    domain = (urlparse(link_url).hostname or "").lower()
                    result["official_evidence"].append({
                        "url": link_url,
                        "domain": domain,
                        "link_text": link["label"],
                        "evidence_type": "lien externe vers un domaine de première partie répertorié"
                    })
            if result["official_evidence"]:
                result["status"] = "lien de première partie repéré — contenu à contrôler"
            result["page_title"] = page_title
        except Exception as exc:
            errors.append({"url": url, "error": str(exc)[:180]})
            result["status"] = "page source inaccessible — vérification humaine requise"
        checks.append(result)
        time.sleep(0.1)

    # Filtrage éditorial strict : priorité aux sujets frais, pertinents et recoupés.
    by_url = {c["article_url"]: c for c in checks}
    radar_items = {x.get("url"): x for x in items if x.get("url")}
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    excluded_terms = (
        "episode review", "review:", "recap", "spoiler review",
        "weekly review", "manga review", "anime review"
    )

    def age_hours(value):
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            # Une date anormalement future est considérée comme invalide,
            # pas comme une actualité fraîche.
            if dt > now + __import__("datetime").timedelta(hours=24):
                return None
            return max(0, (now - dt).total_seconds() / 3600)
        except Exception:
            return None

    def hashtags(title):
        words = re.findall(r"[A-Za-z0-9À-ÿ]+", title or "")
        ignored = {"anime", "manga", "the", "and", "gets", "new", "for", "with"}
        tags = []
        for word in words:
            clean = re.sub(r"[^A-Za-z0-9À-ÿ]", "", word)
            if len(clean) >= 3 and clean.lower() not in ignored:
                tag = "#" + clean[:28]
                if tag.lower() not in [x.lower() for x in tags]:
                    tags.append(tag)
            if len(tags) >= 4:
                break
        return " ".join(["#Anime", "#Manga"] + tags[:3])

    def make_social_posts(title, summary, language, sources, source_url, verified):
        # Les champs sociaux restent vides jusqu'à la rédaction et à la validation IA.
        # Aucun texte de remplacement ou consigne ne doit apparaître dans l'interface.
        return {
            "language_ready": False,
            "translation_required": True,
            "translation_note": "Rédaction française IA en attente : aucun texte provisoire ne doit être publié.",
            "facebook": "",
            "tiktok": ""
        }

    queue = []
    rejected = []
    for trend in radar.get("trends", []):
        title = str(trend.get("title", "")).strip()
        low_title = title.lower()
        trend_articles = trend.get("articles", [])
        evidence, summary_candidates, article_urls, checked_urls = [], [], [], []
        source_reports = enrich_source_reports(trend_articles, radar_items)
        for article in trend_articles:
            url = article.get("url", "")
            article_urls.append(url)
            check = by_url.get(url)
            if check:
                checked_urls.append(url)
                evidence.extend(check["official_evidence"])
            original = radar_items.get(url, {})
            snippet = original.get("summary", "").strip()
            if snippet and all(existing[0] != snippet for existing in summary_candidates):
                summary_candidates.append((
                    snippet,
                    detect_text_language(snippet),
                    url,
                    bool(check)
                ))
        evidence = list({x["url"]: x for x in evidence}.values())
        sources = trend.get("sources", [])
        publisher_count = int(trend.get("source_count", 0) or 0)
        primary_source_count = int(trend.get("primary_source_count", 0) or 0)
        primary_sources = trend.get("primary_sources", [])
        score_value = int(trend.get("score", 0) or 0)
        known_ages = [
            age_hours(radar_items.get(u, {}).get("published_at"))
            for u in article_urls
        ]
        known_ages = [age for age in known_ages if age is not None]
        latest_age = min(known_ages) if known_ages else None
        excluded_format = any(term in low_title for term in excluded_terms)
        has_official = bool(evidence)
        cross_checked = publisher_count >= 2
        verification_coverage = len(set(checked_urls))
        reasons = []
        if excluded_format:
            reasons.append("format critique/recap écarté du flux prioritaire")
        if publisher_count == 0:
            reasons.append("aucun éditeur indépendant : agrégateur seul, sujet non admissible")
        if score_value < 45:
            reasons.append("score éditorial inférieur à 45/100")
        if latest_age is None:
            reasons.append("date de publication absente, invalide ou anormalement future")
        elif latest_age > 168:
            reasons.append("actualité trop ancienne (plus de 7 jours)")
        if not cross_checked and not has_official and score_value < 65:
            reasons.append("source unique sans lien officiel repéré")
        if not summary_candidates and score_value < 60:
            reasons.append("aucun résumé exploitable dans le flux RSS")
        # Une absence de contrôle dans l'échantillon global n'est pas un échec
        # de vérification : elle signifie uniquement que la page reste à contrôler.
        # Le sujet peut entrer dans la file de brouillons s'il satisfait les autres
        # critères éditoriaux; la revue humaine et le blocage de publication restent actifs.
        if reasons:
            rejected.append({"title": title, "reasons": reasons})
            continue

        # Choisir l'extrait le plus exploitable : français d'abord, puis page
        # effectivement contrôlée, puis longueur utile. L'URL suit toujours
        # exactement l'article dont provient l'extrait retenu.
        summary_candidates.sort(
            key=lambda row: (row[1] == "fr", row[3], min(len(row[0]), 420)),
            reverse=True
        )
        summary, summary_language, primary_url, summary_page_checked = (
            summary_candidates[0] if summary_candidates else ("", "und", "", False)
        )
        if not primary_url and article_urls:
            primary_url = article_urls[0]
        primary_item = radar_items.get(primary_url, {})
        # La langue du résumé est détectée indépendamment de celle du titre.
        # En cas de doute, le texte reste bloqué comme traduction à contrôler.
        summary_language = detect_text_language(summary)
        title_language = detect_text_language(title)
        # Un brouillon n'est considéré prêt en français que si le titre ET
        # l'extrait le sont. Traduire uniquement le résumé laisserait le titre anglais.
        posts = make_social_posts(
            title, summary,
            "fr" if title_language == "fr" and summary_language == "fr" else "und",
            sources, primary_url, has_official
        )
        if verification_coverage == 0:
            editorial_status = "contrôle de provenance en attente — revue humaine obligatoire"
        elif has_official:
            editorial_status = "lien officiel repéré — détails à relire"
        elif primary_source_count > 0:
            editorial_status = "flux de première partie présent — contenu à vérifier"
        elif cross_checked:
            editorial_status = "plusieurs médias — confirmation officielle requise"
        else:
            editorial_status = "signal fort isolé — confirmation obligatoire"
        queue.append({
            "trend_id": trend.get("id"),
            "title": title,
            "score_indicatif": score_value,
            "media_count": publisher_count,
            "media": sources,
            "source_countries": trend.get("source_countries", []),
            "source_regions": trend.get("source_regions", []),
            "market_countries": trend.get("market_countries", []),
            "market_regions": trend.get("market_regions", []),
            "primary_sources": primary_sources,
            "primary_source_count": primary_source_count,
            "source_excerpt_url": primary_url,
            "source_excerpt_checked": summary_page_checked,
            "articles": source_reports,
            "official_evidence": evidence,
            "verification_coverage": {
                "checked_articles": verification_coverage,
                "total_articles": len(article_urls),
                "status": "checked" if verification_coverage else "pending"
            },
            "verification_pending": verification_coverage == 0,
            "editorial_status": editorial_status,
            "human_review_required": True,
            "publication_allowed": False,
            "title_language": title_language,
            "summary_language": summary_language,
            "source_excerpt": summary,
            "social_posts": posts,
            "draft_fr": "BRIEF ÉDITORIAL — BROUILLON À VALIDER\n\nSujet : " + title + "\nExtrait RSS : " + (summary or "Aucun résumé fourni par la source.") + "\n\nÉtat : " + editorial_status + "\nSources médias : " + ", ".join(sources) + "\n" + (posts["translation_note"] + "\n" if posts["translation_note"] else "") + "Ne pas publier avant contrôle des faits et de la traduction."
        })

    queue.sort(key=lambda x: (
        bool(x["official_evidence"]),
        x.get("primary_source_count", 0),
        x["media_count"],
        x["score_indicatif"]
    ), reverse=True)
    candidate_count = len(queue)
    queue = diversify_queue(queue, limit=MAX_PREPUBLICATIONS, max_per_franchise=1)
    diversity_excluded_count = candidate_count - len(queue)

    payload = {
        "checked_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "checked_articles": len(checks),
        "sample_strategy": "échantillon global des articles récents; les sujets admissibles non inclus dans cet échantillon restent en attente de contrôle humain et ne sont pas rejetés pour cette seule raison",
        "official_link_found": sum(bool(x["official_evidence"]) for x in checks),
        "errors": errors,
        "checks": checks,
        "policy": "Le détecteur examine les liens HTML visibles vers une liste conservatrice de domaines de première partie, dont les portails KADOKAWA Animation japonais et international. ORICON / Japan Anime News est traité comme média professionnel de veille, pas comme source primaire officielle d'une annonce. L'absence de résultat ne prouve pas l'absence d'annonce officielle. Un lien repéré n'est jamais une validation automatique du fait : comparer séparément chaque date, format, studio, casting, nombre d'épisodes et territoire. Vérification humaine obligatoire."
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    QUEUE.write_text(json.dumps({
        "generated_at": payload["checked_at"],
        "count": len(queue),
        "daily_goal": MAX_PREPUBLICATIONS,
        "selected_networks": list(SOCIAL_NETWORKS),
        "network_variant_count": len(queue) * len(SOCIAL_NETWORKS),
        "selection_note": "Trois sujets éditoriaux maximum, distincts par franchise, chacun décliné pour Facebook et TikTok. Si moins de trois sujets satisfont les critères, la file reste plus courte plutôt que d'inventer ou d'abaisser les exigences.",
        "rejected_count": len(rejected),
        "rejected_sample": rejected[:30],
        "filter_policy": "Score minimum 45/100, actualité de moins de 7 jours, priorité aux sujets recoupés ou reliés à une source officielle. Les recaps/critiques et signaux isolés faibles sont écartés. Maximum 15 sujets.",
        "diversity_policy": "Maximum 1 prépublication par franchise dans les trois sujets du jour, pour privilégier trois actualités réellement distinctes.",
        "diversity_excluded_count": diversity_excluded_count,
        "items": queue,
        "notice": "Trois sujets éditoriaux au maximum, chacun adapté uniquement à Facebook et TikTok. Les adaptations restent des brouillons à relire. Toute traduction non validée et toute information non confirmée bloquent la publication. Aucune publication automatique."
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Vérification : {len(checks)} pages contrôlées; {payload['official_link_found']} avec lien officiel repéré; {len(errors)} erreur(s).")
    print(f"File éditoriale : {len(queue)} briefs non publiables générés.")

if __name__ == "__main__":
    main()
