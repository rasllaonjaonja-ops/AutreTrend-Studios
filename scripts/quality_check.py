#!/usr/bin/env python3
"""Contrôles statiques du site AutreTrend avant déploiement."""
import json
import re
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class IdCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.assets = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.append(attrs["id"])
        for key in ("src", "href"):
            value = attrs.get(key, "")
            if value.startswith("assets/"):
                self.assets.append(value)


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"JSON invalide : {path.relative_to(ROOT)} — {exc}")



def valid_editorial_queue(queue):
    """Valide les brouillons IA et le mode de secours sans configuration IA."""
    if not isinstance(queue, dict):
        return False
    items = queue.get("items", [])
    if not isinstance(items, list):
        return False

    status = queue.get("ai_generation_status", "")
    generated_count = queue.get("ai_generated_count", 0)
    fallback_statuses = {
        "blocked_configuration", "blocked_insecure_endpoint",
        "unavailable", "invalid_response", "rejected",
    }
    if not isinstance(generated_count, int) or generated_count < 0:
        return False

    platforms = {"facebook", "tiktok"}
    ai_complete_count = 0
    for item in items:
        if not isinstance(item, dict):
            return False
        if item.get("human_review_required") is not True or item.get("publication_allowed") is not False:
            return False
        posts = item.get("social_posts") or {}
        if not isinstance(posts, dict):
            return False
        if posts and not platforms.issubset(set(posts.keys())):
            return False
        # Les brouillons de secours peuvent contenir huit variantes : seul le
        # marqueur ai_generation distingue un contenu réellement généré par l'IA.
        ai_generation = item.get("ai_generation")
        if ai_generation is not None:
            if not isinstance(ai_generation, dict) or not posts:
                return False
            ai_complete_count += 1

    if status in fallback_statuses:
        return generated_count == 0 and ai_complete_count == 0
    if status == "generated":
        return generated_count == len(items) and ai_complete_count == generated_count
    if status == "partial":
        return 0 < generated_count < len(items) and ai_complete_count == generated_count
    if not items and status in ("", "not_requested"):
        return generated_count == 0
    return False

def main():
    html_path = ROOT / "index.html"
    html = html_path.read_text(encoding="utf-8")
    parser = IdCollector()
    parser.feed(html)

    duplicates = sorted({value for value in parser.ids if parser.ids.count(value) > 1})
    if duplicates:
        raise SystemExit("Identifiants HTML dupliqués : " + ", ".join(duplicates))

    required_ids = {
        "radar-search", "radar-source", "radar-filter", "radar-score",
        "radar-age", "radar-language", "radar-sort", "radar-reset",
        "radar-result", "scan"
    }
    missing = sorted(required_ids - set(parser.ids))
    if missing:
        raise SystemExit("Contrôles HTML manquants : " + ", ".join(missing))

    for asset in sorted(set(parser.assets)):
        if not (ROOT / asset).is_file():
            raise SystemExit(f"Ressource locale absente : {asset}")

    radar = load_json(ROOT / "data" / "radar.json")
    verification = load_json(ROOT / "data" / "verification.json")
    queue = load_json(ROOT / "data" / "editorial_queue.json")
    sources = load_json(ROOT / "sources.json")

    if not isinstance(radar.get("items"), list) or not isinstance(radar.get("trends"), list):
        raise SystemExit("Structure radar.json invalide.")
    if not isinstance(verification.get("checks"), list):
        raise SystemExit("Structure verification.json invalide.")
    if not isinstance(sources.get("sources"), list) or not any(s.get("enabled", True) for s in sources["sources"]):
        raise SystemExit("Aucun flux RSS actif dans sources.json.")
    enabled_sources = [s for s in sources["sources"] if s.get("enabled", True)]
    site_sources = [s for s in enabled_sources if s.get("source_type") != "market_search"]
    market_sources = [s for s in enabled_sources if s.get("source_type") == "market_search"]
    if len(site_sources) != 20 or len(market_sources) != 7:
        raise SystemExit("Le Radar doit conserver 20 sites éditoriaux et 7 flux de veille par pays.")
    if not all(s.get("country") and s.get("region") and s.get("language") for s in enabled_sources):
        raise SystemExit("Chaque flux doit préciser son pays, sa région et sa langue.")

    queue_items = queue.get("items", [])
    if queue.get("count") != len(queue_items):
        raise SystemExit("Le compteur de la file éditoriale ne correspond pas aux éléments.")
    if len(queue_items) > 3:
        raise SystemExit("La file éditoriale dépasse les trois prépublications quotidiennes.")
    if queue.get("daily_goal") != 3 or queue.get("network_variant_count") != len(queue_items) * 2:
        raise SystemExit("Les trois emplacements éditoriaux et leurs deux déclinaisons sociales sont incohérents.")
    if queue.get("selected_networks") != ["facebook", "tiktok"]:
        raise SystemExit("Seuls Facebook et TikTok doivent être activés.")
    if not isinstance(queue.get("rejected_count", 0), int):
        raise SystemExit("Le compteur des sujets écartés doit être un entier.")

    if not valid_editorial_queue(queue):
        raise SystemExit(
            "File éditoriale incohérente : vérifier le statut IA, les déclinaisons sociales "
            "et la validation humaine."
        )

    scripts = re.findall(r"<script\b[^>]*>(.*?)</script\s*>", html, flags=re.I | re.S)
    if not scripts:
        raise SystemExit("Aucun script intégré trouvé dans index.html.")
    node = shutil.which("node")
    if not node:
        raise SystemExit("Node.js est requis pour vérifier le JavaScript intégré.")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write("\n;\n".join(scripts))
        js_path = Path(handle.name)
    try:
        subprocess.run([node, "--check", str(js_path)], check=True)
    finally:
        js_path.unlink(missing_ok=True)

    function_path = ROOT / "functions" / "api" / "editorial.js"
    if not function_path.is_file():
        raise SystemExit("Endpoint éditorial Cloudflare absent.")
    subprocess.run([node, "--check", str(function_path)], check=True)

    for name in ("collect_rss.py", "verify_sources.py", "radar_logic.py", "generate_editorial.py"):
        source = ROOT / "scripts" / name
        compile(source.read_text(encoding="utf-8"), str(source), "exec")

    print(
        "Qualité OK — "
        f"{len(radar['items'])} articles, {len(radar['trends'])} tendances, "
        f"{len(queue_items)} brouillons, {queue.get('rejected_count', 0)} sujets écartés, "
        f"{len(parser.ids)} identifiants HTML."
    )


if __name__ == "__main__":
    main()
