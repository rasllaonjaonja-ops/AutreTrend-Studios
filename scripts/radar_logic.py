"""Logique pure et testable du Radar intelligent AutreTrend Studios."""
import re
import unicodedata

GENERIC = {
    "anime", "manga", "news", "new", "gets", "get", "the", "and", "for",
    "with", "from", "this", "that", "its", "are", "was", "has", "have",
    "des", "les", "une", "un", "dans", "pour", "avec", "sur", "qui", "est",
    "season", "saison", "movie", "film", "theatrical", "cinema", "announced",
    "announcement", "reveals", "revealed", "confirms", "confirmed", "2027",
}


def _plain(value):
    value = unicodedata.normalize("NFKD", str(value or "").lower())
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def event_parts(title):
    """Retourne les tokens distinctifs et les facettes d'événement normalisées."""
    text = _plain(title).replace("×", "x")
    text = re.sub(r"\b(\d+)(?:st|nd|rd|th)\b", r"\1", text)
    text = re.sub(r"\b(first|1st)\b", "1", text)
    text = re.sub(r"\b(second|2nd)\b", "2", text)
    text = re.sub(r"\b(third|3rd)\b", "3", text)
    tokens = set(re.findall(r"[a-z0-9]{2,}", text))
    core = {token for token in tokens if token not in GENERIC and not token.isdigit()}
    facets = set()
    for match in re.finditer(r"\b(?:season|saison)\s*(\d+)\b", text):
        facets.add("season:" + match.group(1))
    if re.search(r"\b(movie|film|theatrical|cinema|feature)\b", text):
        facets.add("film")
    for year in re.findall(r"\b20\d{2}\b", text):
        facets.add("year:" + year)
    return core, facets


def same_event(title_a, title_b):
    """Fusion conservatrice : franchise/sujet commun ET facette événementielle commune."""
    core_a, facets_a = event_parts(title_a)
    core_b, facets_b = event_parts(title_b)
    if len(core_a & core_b) < 2 or not (facets_a & facets_b):
        return False
    denominator = min(len(core_a), len(core_b))
    return bool(denominator and len(core_a & core_b) / denominator >= 0.5)


def evidence_level(publisher_count):
    """Niveau de couverture médiatique, jamais une validation de vérité."""
    return "multi_media_reported" if publisher_count >= 2 else "single_publisher_signal"
