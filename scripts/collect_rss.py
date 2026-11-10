#!/usr/bin/env python3
"""Collecte RSS/Atom et classement éditorial indicatif pour AutreTrend Studios."""
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

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
    return parsed.astimezone(timezone.utc).isoformat()

def parse_timestamp(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0

def score(title, summary):
    text = (title + " " + summary).lower()
    return min(sum(weight for word, weight in KEYWORDS.items() if word in text), 100)

def publisher_name(source_name):
    # Deux flux d'un même éditeur ne valent qu'une seule source indépendante.
    name = source_name.lower()
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

def title_tokens(title):
    words = re.findall(r"[a-z0-9]{3,}", title.lower())
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
            if similarity(candidates[i]["title"], candidates[j]["title"]) >= 0.52:
                ri, rj = root(i), root(j)
                if ri != rj:
                    parent[rj] = ri
    groups = {}
    for i, item in enumerate(candidates):
        groups.setdefault(root(i), []).append(item)

    trends = []
    for group in groups.values():
        publishers = sorted({publisher_name(x["source"]) for x in group})
        newest = max((parse_timestamp(x["published_at"]) for x in group), default=0)
        age_hours = max(0, (now.timestamp() - newest) / 3600) if newest else 999
        freshness = max(0, 100 * (1 - min(age_hours, 72) / 72)) if newest else 0
        relevance = max((x["score"] for x in group), default=0)
        coverage = 100 if len(publishers) >= 3 else (70 if len(publishers) == 2 else 35)
        volume = 100 if len(group) >= 4 else (70 if len(group) >= 2 else 35)
        # Priorité éditoriale indicative : pertinence 35 %, fraîcheur 30 %,
        # diversité des éditeurs 25 %, volume d'articles 10 %.
        # Ce score ne mesure ni les vues, ni la viralité, ni la véracité.
        heat = round(min(100, relevance * 0.35 + freshness * 0.30 + coverage * 0.25 + volume * 0.10))
        if len(publishers) >= 2:
            status = "multi-source à confirmer"
        else:
            status = "signal à surveiller"
        priority = "priorité élevée" if heat >= 70 else ("à examiner" if heat >= 50 else "veille")
        ordered = sorted(group, key=lambda x: (x["published_at"], x["score"]), reverse=True)
        trends.append({
            "id": ordered[0]["id"],
            "title": ordered[0]["title"],
            "score": heat,
            "priority": priority,
            "score_breakdown": {
                "relevance": round(relevance),
                "freshness": round(freshness),
                "independent_sources": len(publishers),
                "article_volume": len(group)
            },
            "article_count": len(group),
            "source_count": len(publishers),
            "sources": publishers,
            "published_at": ordered[0]["published_at"],
            "status": status,
            "articles": [{"title": x["title"], "url": x["url"], "source": x["source"], "feed_sources": x.get("feed_sources", [x["source"]])} for x in ordered[:8]]
        })
    return sorted(trends, key=lambda x: (x["score"], x["source_count"], x["published_at"]), reverse=True)

items, errors = [], []
enabled_sources = [s for s in SOURCES if s.get("enabled", True)]
source_stats = {
    s["name"]: {"entries_found": 0, "accepted_items": 0, "unique_items": 0}
    for s in enabled_sources
}
for source in enabled_sources:
    try:
        request = urllib.request.Request(
            source["url"],
            headers={"User-Agent": "AutreTrendStudios/0.2 (+RSS editorial reader)"}
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            root = ET.fromstring(response.read())
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
            if title and link.startswith(("https://", "http://")):
                items.append({
                    "id": link, "title": title, "url": link,
                    "summary": summary[:500], "published_at": parse_date(date),
                    "source": source["name"],
                    "publisher": publisher_name(source["name"]),
                    "category": source.get("category", "anime-manga"),
                    "language": source.get("language", "und"),
                    "score": score(title, summary),
                    "verification": "à vérifier"
                })
                source_stats[source["name"]]["accepted_items"] += 1
    except Exception as exc:
        errors.append({"source": source.get("name", "unknown"), "error": str(exc)[:240]})

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
    "sources": [s["name"] for s in enabled_sources],
    "source_stats": source_stats,
    "item_count": len(result),
    "items": result[:100],
    "trend_count": len(trends),
    "trends": trends,
    "errors": errors,
    "notice": "Priorité éditoriale indicative : pertinence du sujet (35 %), fraîcheur sur 72 h (30 %), diversité des éditeurs indépendants (25 %) et volume d'articles (10 %). Ce score ne mesure ni les vues, ni la viralité, ni la véracité. Toute information reste à vérifier."
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Radar: {len(result)} articles; {len(trends)} groupes de sujets; {len(errors)} erreur(s) de flux.")
