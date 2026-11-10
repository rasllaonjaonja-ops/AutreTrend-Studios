#!/usr/bin/env python3
"""Collecte RSS/Atom et classement éditorial indicatif pour AutreTrend Studios."""
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from radar_logic import coverage_score, evidence_level, same_event

ROOT = Path(__file__).resolve().parents[1]
SOURCES = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))["sources"]
OUT = ROOT / "data" / "radar.json"
KEYWORDS = {
    "anime": 8, "manga": 8, "adaptation": 7, "anime film": 6,
    "season": 4, "trailer": 5, "teaser": 5, "announcement": 5,
    "announced": 5, "premiere": 5, "release": 4, "volume": 3,
    "chapter": 3, "one piece": 4, "naruto": 4, "jujutsu": 4,
    "demon slayer": 4, "chainsaw man": 4, "my hero academia": 4,
    "spy family": 4, "dragon ball": 4, "studio": 2, "movie": 3,
    "film": 3, "episode": 2, "netflix": 2, "crunchyroll": 2
}
STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "new", "more",
    "anime", "manga", "gets", "get", "its", "are", "was", "has", "have",
    "des", "les", "une", "dans", "pour", "avec", "sur", "qui", "est",
    "the", "of", "to", "on", "in", "a", "an"
}

class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
    def handle_data(self, data):
        value = data.strip()
        if value:
            self.parts.append(value)

def clean_text(value):
    parser = TextOnly()
    try:
        parser.feed(value or "")
        value = " ".join(parser.parts)
    except Exception:
        value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", value).strip()

def local_name(tag):
    return tag.rsplit("}", 1)[-1].lower()

def child_text(node, names):
    for child in list(node):
        if local_name(child.tag) in names:
            return " ".join(child.itertext()).strip()
    return ""

def parse_date(value):
    if not value:
        return ""
    try:
        parsed = parsedate_to_datetime(value)
    except Exception:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    # Un flux peut contenir une date erronée ou une date de mise à jour future.
    # Ne jamais transformer cette valeur en signal de fraîcheur artificiel.
    if parsed > datetime.now(timezone.utc) + timedelta(hours=24):
        return ""
    return parsed.isoformat()

def parse_timestamp(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0

def score(title, summary):
    text = (title + " " + summary).lower()
    return min(sum(weight for word, weight in KEYWORDS.items() if word in text), 100)

def is_aggregator_source(source_name):
    """Les agrégateurs ne comptent jamais comme éditeurs indépendants."""
    name = str(source_name or "").lower()
    return "google actualités" in name or "google actualites" in name or "google news" in name


def publisher_name(source_name):
    # Deux flux d'un même éditeur ne valent qu'une seule source indépendante.
    name = source_name.lower()
    if is_aggregator_source(name):
        return "Google News (agrégateur)"
    if "anime news network" in name:
        return "Anime News Network"
    if "shonen jump" in name:
        return "Shueisha / Shonen Jump+"
    if "crunchyroll" in name:
        return "Crunchyroll"
    if "myanimelist" in name or "my anime list" in name:
        return "MyAnimeList"
    if "oricon" in name or "japan anime news" in name:
        return "ORICON / Japan Anime News"
    return source_name.strip()

def detect_title_language(title):
    """Détection légère de l'écriture du titre, sans prétendre le traduire."""
    if re.search(r"[ぁ-んァ-ン一-龯々ー]", title or ""):
        return "ja"
    low = (title or "").lower()
    if re.search(r"\b(le|la|les|des|une|un|pour|avec|dans|est|sur)\b", low) or re.search(r"[àâçéèêëîïôùûüÿœ]", low):
        return "fr"
    return "en"

def title_tokens(title):
    low = (title or "").lower()
    words = set(re.findall(r"[a-z0-9]{3,}", low))
    # Les titres japonais n'ont pas toujours d'espaces : les bigrammes
    # permettent de comparer les séquences communes sans translittération hasardeuse.
    for run in re.findall(r"[ぁ-んァ-ン一-龯々ー]{2,}", low):
        words.update(run[i:i+2] for i in range(len(run)-1))
    return {w for w in words if w not in STOPWORDS}

def similarity(a, b):
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)

def build_trends(items, now):
    candidates = [x for x in items if x["score"] >= 4 and title_tokens(x["title"])]
    parent = list(range(len(candidates)))
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            # Seuil volontairement élevé pour éviter de fusionner deux événements proches.
            # La similarité lexicale seule confondait des articles parlant du même manga.
            # On exige un sujet distinctif commun et une facette d’événement commune.
            # La similarité lexicale seule ne fusionne jamais deux sujets :
            # seule une correspondance d'événement explicite autorise le regroupement.
            if same_event(candidates[i]["title"], candidates[j]["title"]):
                ri, rj = root(i), root(j)
                if ri != rj:
                    parent[rj] = ri
    groups = {}
    for i, item in enumerate(candidates):
        groups.setdefault(root(i), []).append(item)

    trends = []
    for group in groups.values():
        # Google News et Google Actualités sont des agrégateurs :
        # leurs reprises ne constituent ni un éditeur indépendant ni un article éditorial supplémentaire.
        editorial_group = [
            x for x in group
            if x.get("source_type") != "market_search"
            and not is_aggregator_source(x.get("source", ""))
        ]
        aggregator_group = [x for x in group if is_aggregator_source(x.get("source", ""))]
        market_group = [x for x in group if x.get("source_type") == "market_search"]
        publishers = sorted({publisher_name(x["source"]) for x in editorial_group})
        primary_sources = sorted({
            publisher_name(x["source"]) for x in group
            if x.get("source_role") == "first_party"
            and not is_aggregator_source(x.get("source", ""))
        })
        source_countries = sorted({x.get("source_country", "International") for x in editorial_group if x.get("source_country")})
        source_regions = sorted({x.get("source_region", "International") for x in editorial_group if x.get("source_region")})
        market_countries = sorted({x.get("market_country") for x in group if x.get("market_country")})
        market_regions = sorted({x.get("market_region") for x in group if x.get("market_region")})
        # La fraîcheur est calculée sur les éditeurs directs, pas sur l'heure
        # à laquelle Google News a simplement repris leur article.
        freshness_group = editorial_group or group
        newest = max((parse_timestamp(x["published_at"]) for x in freshness_group), default=0)
        age_hours = max(0, (now.timestamp() - newest) / 3600) if newest else 999
        freshness = max(0, 100 * (1 - min(age_hours, 72) / 72)) if newest else 0
        relevance = max((x["score"] for x in group), default=0)
        coverage = coverage_score(len(publishers), len(primary_sources))
        volume = 100 if len(editorial_group) >= 4 else (70 if len(editorial_group) >= 2 else 35)
        # Priorité éditoriale indicative : pertinence 35 %, fraîcheur 30 %,
        # diversité des éditeurs 25 %, volume d'articles 10 %.
        # Ce score ne mesure ni les vues, ni la viralité, ni la véracité.
        heat = round(min(100, relevance * 0.35 + freshness * 0.30 + coverage * 0.25 + volume * 0.10))
        if len(publishers) >= 2:
            status = "multi-source à confirmer"
        else:
            status = "signal à surveiller"
        priority = "priorité élevée" if heat >= 70 else ("à examiner" if heat >= 50 else "veille")
        # Si des articles de médias directs existent, les copies Google News
        # sont écartées de la liste de preuves et des rapports transmis à l'IA.
        source_group = editorial_group or aggregator_group or market_group
        ordered = sorted(source_group, key=lambda x: (x["published_at"], x["score"]), reverse=True)
        trends.append({
            "id": ordered[0]["id"],
            "title": ordered[0]["title"],
            "title_language": detect_title_language(ordered[0]["title"]),
            "score": heat,
            "priority": priority,
            "score_breakdown": {
                "relevance": round(relevance),
                "freshness": round(freshness),
                "independent_sources": len(publishers),
                "article_volume": len(editorial_group)
            },
            "article_count": len(editorial_group),
            "market_signal_count": len(market_group),
            "source_count": len(publishers),
            "primary_source_count": len(primary_sources),
            "primary_sources": primary_sources,
            "source_countries": source_countries,
            "source_regions": source_regions,
            "market_countries": market_countries,
            "market_regions": market_regions,
            "evidence_level": evidence_level(len(publishers), len(primary_sources)),
            "evidence_note": "Couverture médiatique indicative ; ne constitue pas une confirmation officielle ni une validation des faits.",
            "sources": publishers,
            "published_at": ordered[0]["published_at"],
            "status": status,
            "articles": [{"title": x["title"], "title_language": x.get("title_language", detect_title_language(x["title"])), "url": x["url"], "source": x["source"], "source_type": x.get("source_type", "editorial_site"), "source_country": x.get("source_country"), "market_country": x.get("market_country"), "feed_sources": x.get("feed_sources", [x["source"]])} for x in ordered[:8]]
        })
    return sorted(trends, key=lambda x: (x["score"], x["source_count"], x["published_at"]), reverse=True)

items, errors = [], []
enabled_sources = [s for s in SOURCES if s.get("enabled", True)]
source_stats = {
    s["name"]: {
        "country": s.get("country", "International"),
        "region": s.get("region", "International"),
        "market_country": s.get("market_country"),
        "market_region": s.get("market_region"),
        "source_type": s.get("source_type", "editorial_site"),
        "language": s.get("language", "und"),
        "entries_found": 0, "accepted_items": 0, "unique_items": 0,
        "status": "pending", "last_success_at": None, "error": None
    }
    for s in enabled_sources
}
for source in enabled_sources:
    try:
        request = urllib.request.Request(
            source["url"],
            headers={"User-Agent": "AutreTrendStudios/0.2 (+RSS editorial reader)"}
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            root = ET.fromstring(response.read())
        source_stats[source["name"]]["status"] = "ok"
        source_stats[source["name"]]["last_success_at"] = datetime.now(timezone.utc).isoformat()
        entries = [node for node in root.iter() if local_name(node.tag) in ("item", "entry")]
        source_stats[source["name"]]["entries_found"] = min(len(entries), 40)
        for entry in entries[:40]:
            title = clean_text(child_text(entry, {"title"}))
            link = child_text(entry, {"link"})
            if not link:
                for node in list(entry):
                    if local_name(node.tag) == "link":
                        link = node.attrib.get("href", "")
                        if link:
                            break
            summary = clean_text(child_text(entry, {"description", "summary", "encoded", "content"}))
            date = child_text(entry, {"pubdate", "published", "updated", "date"})
            published_at = parse_date(date)
            if title and link.startswith(("https://", "http://")):
                items.append({
                    "id": link, "title": title, "title_language": detect_title_language(title), "translation_status": "à traduire si japonais",
                    "url": link, "summary": summary[:500], "published_at": published_at,
                    "date_status": "known" if published_at else "unknown",
                    "summary_status": "available" if summary else "missing",
                    "source": source["name"],
                    "publisher": publisher_name(source["name"]),
                    "category": source.get("category", "anime-manga"),
                    "source_type": source.get("source_type", "editorial_site"),
                    "source_country": None if source.get("source_type") == "market_search" else source.get("country", "International"),
                    "source_region": None if source.get("source_type") == "market_search" else source.get("region", "International"),
                    "market_country": source.get("market_country"),
                    "market_region": source.get("market_region"),
                    "source_role": "first_party" if "official" in source.get("category", "") else "professional_media",
                    "language": source.get("language", "und"),
                    "score": score(title, summary),
                    "verification": "à vérifier"
                })
                source_stats[source["name"]]["accepted_items"] += 1
    except Exception as exc:
        message = str(exc)[:240]
        source_stats[source.get("name", "")]["status"] = "error"
        source_stats[source.get("name", "")]["error"] = message
        errors.append({"source": source.get("name", "unknown"), "error": message})

def canonical_article_url(value):
    """Normalise les URL d'un même article sans supprimer ses identifiants utiles."""
    from urllib.parse import parse_qsl, urlencode, urlunparse
    try:
        parsed = urlparse(value.strip())
        if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
            return value.strip()
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        tracking = {
            "fbclid", "gclid", "mc_cid", "mc_eid", "_location",
            "ref", "ref_src", "source"
        }
        query = [
            (key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in tracking and not key.lower().startswith("utm_")
        ]
        path = re.sub(r"/+$", "", parsed.path) or "/"
        return urlunparse((
            parsed.scheme.lower(), host, path, "", urlencode(sorted(query)), ""
        ))
    except Exception:
        return value.strip()


unique = {}
for item in items:
    canonical = canonical_article_url(item["url"])
    item["canonical_url"] = canonical
    existing = unique.get(canonical)
    if existing is None:
        item["feed_sources"] = [item["source"]]
        unique[canonical] = item
    else:
        # Une même URL reçue par plusieurs flux ne doit compter qu'une fois.
        feeds = set(existing.get("feed_sources", [existing.get("source", "")]))
        feeds.add(item["source"])
        existing["feed_sources"] = sorted(x for x in feeds if x)
        if item["score"] > existing["score"]:
            item["feed_sources"] = existing["feed_sources"]
            unique[canonical] = item
result = sorted(unique.values(), key=lambda x: (x["score"], x["published_at"]), reverse=True)
for article in result:
    for feed_name in article.get("feed_sources", [article.get("source", "")]):
        if feed_name in source_stats:
            source_stats[feed_name]["unique_items"] += 1
now = datetime.now(timezone.utc)
trends = build_trends(result, now)
payload = {
    "updated_at": now.isoformat(),
    "source_count": len(enabled_sources),
    "site_count": sum(1 for s in enabled_sources if s.get("source_type") != "market_search"),
    "market_feed_count": sum(1 for s in enabled_sources if s.get("source_type") == "market_search"),
    "source_country_count": len({s.get("country", "International") for s in enabled_sources if s.get("source_type") != "market_search"}),
    "source_region_count": len({s.get("region", "International") for s in enabled_sources if s.get("source_type") != "market_search"}),
    "market_country_count": len({s.get("market_country") for s in enabled_sources if s.get("market_country")}),
    "sources": [s["name"] for s in enabled_sources],
    "source_stats": source_stats,
    "health": {
        "sources_ok": sum(1 for stat in source_stats.values() if stat["status"] == "ok"),
        "source_countries_ok": sorted({stat["country"] for stat in source_stats.values() if stat["status"] == "ok" and stat.get("source_type") != "market_search"}),
        "market_countries_ok": sorted({stat["market_country"] for stat in source_stats.values() if stat["status"] == "ok" and stat.get("market_country")}),
        "sources_error": sum(1 for stat in source_stats.values() if stat["status"] == "error"),
        "items_without_date": sum(1 for item in result if item.get("date_status") == "unknown"),
        "items_without_summary": sum(1 for item in result if item.get("summary_status") == "missing")
    },
    "item_count": len(result),
    "items": result[:200],
    "trend_count": len(trends),
    "trends": trends,
    "errors": errors,
    "notice": "Radar international manga/anime : 20 sites éditoriaux et des flux Google Actualités localisés. Les pays des sites indiquent leur implantation; les marchés Google indiquent la zone ciblée, sans mesurer la popularité native sur les réseaux sociaux. Priorité indicative : pertinence (35 %), fraîcheur (30 %), diversité des éditeurs (25 %) et volume (10 %). Toute information reste à vérifier."
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Radar: {len(result)} articles; {len(trends)} groupes de sujets; {len(errors)} erreur(s) de flux.")
