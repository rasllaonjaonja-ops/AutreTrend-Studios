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
from urllib.parse import urlparse, urljoin

ROOT = Path(__file__).resolve().parents[1]
RADAR = ROOT / "data" / "radar.json"
OUT = ROOT / "data" / "verification.json"
QUEUE = ROOT / "data" / "editorial_queue.json"
MAX_ARTICLES = 25
TIMEOUT = 8

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
            label = re.sub(r"\\s+", " ", " ".join(self.current_anchor_parts)).strip()[:180]
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

def main():
    radar = json.loads(RADAR.read_text(encoding="utf-8"))
    items = radar.get("items", [])
    checks = []
    errors = []
    for item in items[:MAX_ARTICLES]:
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
            return max(0, (now - dt).total_seconds() / 3600)
        except Exception:
            return 9999

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
        excerpt = re.sub(r"\s+", " ", summary or "").strip()[:420].rstrip()
        french_ready = language == "fr" and bool(excerpt)
        tags = hashtags(title)
        core = excerpt if french_ready else "[RÉSUMÉ EN FRANÇAIS À PRODUIRE APRÈS TRADUCTION ET CONTRÔLE]"
        hook = title
        source_line = "Sources à consulter : " + ", ".join(sources[:3])
        source_line += " · lien officiel repéré, détails à comparer" if verified else " · recoupement officiel non établi"
        url_line = source_url or ""
        return {
            "language_ready": french_ready,
            "translation_required": not french_ready,
            "translation_note": "" if french_ready else "Titre ou résumé non francophone : traduction humaine/IA requise avant publication.",
            "facebook": hook + "\n\n" + core + "\n\nQu'en pensez-vous ? Donnez votre avis en commentaire !\n\n" + tags + "\n" + source_line + ("\n" + url_line if url_line else ""),
            "instagram": hook + "\n\n" + core + "\n\nEnregistrez ce post et partagez votre avis !\n\n" + tags + ("\n" + url_line if url_line else ""),
            "tiktok": "ACCROCHE : " + hook + "\n\nSCRIPT À LIRE : " + core + "\n\nQUESTION : Vous en pensez quoi ?\n" + tags,
            "x": (hook + " — " + core + " " + tags)[:275],
            "threads": "On vient de repérer cette actualité : " + hook + "\n\n" + core + "\n\nVous suivez cette série ?",
            "youtube": {"title": hook[:95], "description": core + "\n\n" + source_line + ("\n" + url_line if url_line else "") + "\n\n" + tags},
            "telegram": "📰 " + hook + "\n\n" + core + "\n\n" + source_line + ("\n" + url_line if url_line else ""),
            "pinterest": {"title": hook[:100], "description": core + "\n" + tags + ("\n" + url_line if url_line else "")}
        }

    queue = []
    rejected = []
    for trend in radar.get("trends", []):
        title = str(trend.get("title", "")).strip()
        low_title = title.lower()
        trend_articles = trend.get("articles", [])
        evidence, summaries, article_urls = [], [], []
        for article in trend_articles:
            url = article.get("url", "")
            article_urls.append(url)
            check = by_url.get(url)
            if check:
                evidence.extend(check["official_evidence"])
            original = radar_items.get(url, {})
            snippet = original.get("summary", "").strip()
            if snippet and snippet not in summaries:
                summaries.append(snippet)
        evidence = list({x["url"]: x for x in evidence}.values())
        sources = trend.get("sources", [])
        publisher_count = int(trend.get("source_count", 0) or 0)
        score_value = int(trend.get("score", 0) or 0)
        latest_age = min((age_hours(radar_items.get(u, {}).get("published_at")) for u in article_urls), default=9999)
        excluded_format = any(term in low_title for term in excluded_terms)
        has_official = bool(evidence)
        cross_checked = publisher_count >= 2
        reasons = []
        if excluded_format:
            reasons.append("format critique/recap écarté du flux prioritaire")
        if score_value < 45:
            reasons.append("score éditorial inférieur à 45/100")
        if latest_age > 168:
            reasons.append("actualité trop ancienne (plus de 7 jours)")
        if not cross_checked and not has_official and score_value < 65:
            reasons.append("source unique sans lien officiel repéré")
        if not summaries and score_value < 60:
            reasons.append("aucun résumé exploitable dans le flux RSS")
        if reasons:
            rejected.append({"title": title, "reasons": reasons})
            continue

        primary_url = article_urls[0] if article_urls else ""
        primary_item = radar_items.get(primary_url, {})
        language = primary_item.get("title_language", trend.get("title_language", "en"))
        summary = summaries[0] if summaries else ""
        posts = make_social_posts(title, summary, language, sources, primary_url, has_official)
        if has_official:
            editorial_status = "lien officiel repéré — détails à relire"
        elif cross_checked:
            editorial_status = "plusieurs médias — confirmation officielle requise"
        else:
            editorial_status = "signal fort isolé — confirmation obligatoire"
        queue.append({
            "trend_id": trend.get("id),
            "title": title,
            "score_indicatif": score_value,
            "media_count": publisher_count,
            "media": sources,
            "articles": trend_articles,
            "official_evidence": evidence,
            "editorial_status": editorial_status,
            "human_review_required": True,
            "publication_allowed": False,
            "title_language": language,
            "source_excerpt": summary,
            "social_posts": posts,
            "draft_fr": "BRIEF ÉDITORIAL — BROUILLON À VALIDER\n\nSujet : " + title + "\nExtrait RSS : " + (summary or "Aucun résumé fourni par la source.") + "\n\nÉtat : " + editorial_status + "\nSources médias : " + ", ".join(sources) + "\n" + (posts["translation_note"] + "\n" if posts["translation_note"] else "") + "Ne pas publier avant contrôle des faits et de la traduction."
        })

    queue.sort(key=lambda x: (bool(x["official_evidence"]), x["media_count"], x["score_indicatif"]), reverse=True)
    queue = queue[:15]

    payload = {
        "checked_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "checked_articles": len(checks),
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
        "items": queue,
        "notice": "Briefs de travail uniquement. Aucun contenu n'est prêt à publier sans validation humaine."
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Vérification : {len(checks)} pages contrôlées; {payload['official_link_found']} avec lien officiel repéré; {len(errors)} erreur(s).")
    print(f"File éditoriale : {len(queue)} briefs non publiables générés.")

if __name__ == "__main__":
    main()
