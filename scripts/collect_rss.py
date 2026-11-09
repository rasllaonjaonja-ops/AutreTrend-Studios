#!/usr/bin/env python3
"""Collecte RSS/Atom sans dépendance externe pour AutreTrend Studios."""
import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))["sources"]
OUT = ROOT / "data" / "radar.json"
KEYWORDS = {
    "anime": 8, "manga": 8, "adaptation": 7, "anime film": 6,
    "season": 4, "trailer": 5, "teaser": 5, "announcement": 5,
    "announced": 5, "premiere": 5, "release": 4, "volume": 3,
    "chapter": 3, "one piece": 4, "naruto": 4, "jujutsu": 4,
    "demon slayer": 4, "chainsaw man": 4, "my hero academia": 4
}

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
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
    except Exception:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
        except Exception:
            return ""

def score(title, summary):
    text = (title + " " + summary).lower()
    points = sum(weight for word, weight in KEYWORDS.items() if word in text)
    return min(points, 100)

items, errors = [], []
for source in SOURCES:
    if not source.get("enabled", True):
        continue
    try:
        request = urllib.request.Request(source["url"], headers={"User-Agent": "AutreTrendStudios/0.1 (RSS reader)"})
        with urllib.request.urlopen(request, timeout=20) as response:
            root = ET.fromstring(response.read())
        entries = [node for node in root.iter() if local_name(node.tag) in ("item", "entry")]
        for entry in entries[:40]:
            title = child_text(entry, {"title"})
            link = child_text(entry, {"link"})
            if not link:
                for node in list(entry):
                    if local_name(node.tag) == "link":
                        link = node.attrib.get("href", "")
                        if link:
                            break
            summary = child_text(entry, {"description", "summary", "encoded", "content"})
            date = child_text(entry, {"pubdate", "published", "updated", "date"})
            if title and link.startswith(("https://", "http://")):
                items.append({
                    "id": link, "title": re.sub(r"\\s+", " ", title).strip(),
                    "url": link, "summary": re.sub(r"<[^>]+>", " ", summary)[:500],
                    "published_at": parse_date(date), "source": source["name"],
                    "category": source.get("category", "anime-manga"),
                    "language": source.get("language", "und"),
                    "score": score(title, summary), "verification": "à vérifier"
                })
    except Exception as exc:
        errors.append({"source": source.get("name", "unknown"), "error": str(exc)[:240]})

unique = {}
for item in items:
    unique.setdefault(item["url"], item)
result = sorted(unique.values(), key=lambda x: (x["score"], x["published_at"]), reverse=True)
payload = {
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "source_count": sum(1 for s in SOURCES if s.get("enabled", True)),
    "item_count": len(result), "items": result[:100], "errors": errors,
    "notice": "Classement indicatif par mots-clés, pas une mesure de viralité. Chaque information doit être vérifiée."
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Radar: {len(result)} éléments; {len(errors)} erreur(s) de flux.")
