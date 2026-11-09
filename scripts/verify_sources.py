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
MAX_ARTICLES = 45
TIMEOUT = 12

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
    "tv-tokyo.co.jp", "ntv.co.jp"
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
        self.title = False
        self.title_parts = []
        self.in_title = False
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag.lower() == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag.lower() == "title":
            self.in_title = True
    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self.in_title = False
    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data.strip())

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
    for href in parser.links:
        absolute = urljoin(base, href)
        if absolute.startswith("https://"):
            resolved.append(absolute.split("#", 1)[0])
    return list(dict.fromkeys(resolved)), " ".join(parser.title_parts)[:300]

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
                if is_official(link, host):
                    domain = (urlparse(link).hostname or "").lower()
                    result["official_evidence"].append({"url": link, "domain": domain})
            if result["official_evidence"]:
                result["status"] = "lien de première partie repéré — contenu à contrôler"
            result["page_title"] = page_title
        except Exception as exc:
            errors.append({"url": url, "error": str(exc)[:180]})
            result["status"] = "page source inaccessible — vérification humaine requise"
        checks.append(result)
        time.sleep(0.15)

    # Les sujets sont reliés à leurs articles via leurs URLs. Aucune validation automatique du fond.
    by_url = {c["article_url"]: c for c in checks}
    queue = []
    for trend in radar.get("trends", [])[:30]:
        evidence = []
        for article in trend.get("articles", []):
            check = by_url.get(article.get("url"))
            if check:
                evidence.extend(check["official_evidence"])
        unique = {x["url"]: x for x in evidence}
        evidence = list(unique.values())
        queue.append({
            "trend_id": trend.get("id"),
            "title": trend.get("title"),
            "score_indicatif": trend.get("score"),
            "media_count": trend.get("source_count", 0),
            "media": trend.get("sources", []),
            "articles": trend.get("articles", []),
            "official_evidence": evidence,
            "editorial_status": "preuve officielle à relire" if evidence else "en attente de source officielle",
            "human_review_required": True,
            "publication_allowed": False,
            "draft_fr": (
                "BRIEF ÉDITORIAL — À COMPLÉTER APRÈS LECTURE DE LA SOURCE OFFICIELLE\n\n"
                "Sujet : " + str(trend.get("title", "")) + "\n"
                "État : " + ("Une page de première partie a été repérée, mais chaque détail doit être comparé à son texte." if evidence else "Aucune preuve officielle n'a été repérée automatiquement. Ne pas présenter ce sujet comme confirmé.") +
                "\n\nSources médias : " + ", ".join(trend.get("sources", [])) +
                "\nPublication interdite avant validation humaine."
            )
        })

    payload = {
        "checked_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "checked_articles": len(checks),
        "official_link_found": sum(bool(x["official_evidence"]) for x in checks),
        "errors": errors,
        "checks": checks,
        "policy": "Un lien officiel repéré n'est pas une validation automatique du fait. Vérifier séparément chaque date, format, studio, casting, nombre d'épisodes et territoire."
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
