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

    queue_items = queue.get("items", [])
    if queue.get("count") != len(queue_items):
        raise SystemExit("Le compteur de la file éditoriale ne correspond pas aux éléments.")
    if not isinstance(queue.get("rejected_count", 0), int):
        raise SystemExit("Le compteur des sujets écartés doit être un entier.")

    platforms = {"facebook", "instagram", "tiktok", "x", "threads", "youtube", "telegram", "pinterest"}
    for item in queue_items:
        if item.get("human_review_required") is not True or item.get("publication_allowed") is not False:
            raise SystemExit("Un brouillon ne respecte pas la règle de validation humaine.")
        if not platforms.issubset(set((item.get("social_posts") or {}).keys())):
            raise SystemExit(f"Formats sociaux incomplets pour : {item.get('title', 'sujet sans titre')}")

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

    for name in ("collect_rss.py", "verify_sources.py", "radar_logic.py"):
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
