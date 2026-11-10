"""Logique pure et testable du Radar intelligent AutreTrend Studios."""
import re
import unicodedata

GENERIC = {
    "anime", "manga", "news", "new", "gets", "get", "the", "and", "for",
    "with", "from", "this", "that", "its", "are", "was", "has", "have", "in",
    "des", "les", "une", "un", "dans", "pour", "avec", "sur", "qui", "est",
    "season", "saison", "movie", "film", "theatrical", "cinema", "announced",
    "announcement", "reveals", "revealed", "confirms", "confirmed", "2027",
}

FRENCH_MARKERS = {
    "le", "la", "les", "des", "une", "un", "pour", "avec", "dans", "est",
    "sont", "cette", "ces", "sur", "par", "du", "de", "et", "mais", "apres",
    "selon", "annonce", "annoncee", "nouveau", "nouvelle", "episode", "saison",
    "de", "du", "au", "aux", "ce", "cet", "sa", "son", "ses", "notre", "leurs",
}
ENGLISH_MARKERS = {
    "the", "and", "for", "with", "from", "this", "that", "gets", "get", "has",
    "have", "new", "announced", "reveals", "will", "its", "their", "about",
    "after", "series",
}


def _plain(value):
    value = unicodedata.normalize("NFKD", str(value or "").lower())
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def detect_text_language(value):
    """Détection prudente d'un extrait ; 'und' si les indices sont insuffisants."""
    text = str(value or "")
    if re.search(r"[ぁ-んァ-ン一-龯々ー]", text):
        return "ja"
    plain = _plain(text)
    words = set(re.findall(r"[a-z]{2,}", plain))
    if not words:
        return "und"
    french = len(words & FRENCH_MARKERS)
    english = len(words & ENGLISH_MARKERS)
    has_french_accent = bool(re.search(r"[àâçéèêëîïôùûüÿœ]", text.lower()))
    if has_french_accent and french >= english:
        return "fr"
    if french >= 2 and french > english:
        return "fr"
    if english >= 2 and english > french:
        return "en"
    return "und"


def event_parts(title):
    """Retourne les tokens distinctifs et les facettes d'événement normalisées."""
    text = _plain(title).replace("×", " ")
    text = re.sub(r"\b(\d+)(?:st|nd|rd|th)\b", r"\1", text)
    text = re.sub(r"\b(first|1st)\b", "1", text)
    text = re.sub(r"\b(second|2nd)\b", "2", text)
    text = re.sub(r"\b(third|3rd)\b", "3", text)
    tokens = set(re.findall(r"[a-z0-9]{2,}", text))
    core = {token for token in tokens if token not in GENERIC and not token.isdigit()}
    facets = set()
    season_numbers = re.findall(r"\b(?:season|saison)\s*(\d+)\b", text)
    season_numbers += re.findall(r"\b(\d+)\s*(?:season|saison)\b", text)
    for number in season_numbers:
        facets.add("season:" + number)
    if re.search(r"\b(movie|film|theatrical|cinema|feature)\b", text):
        facets.add("film")
    for year in re.findall(r"\b20\d{2}\b", text):
        facets.add("year:" + year)
    return core, facets


def same_event(title_a, title_b):
    """Fusion conservatrice : sujet distinctif commun et même type d'annonce."""
    core_a, facets_a = event_parts(title_a)
    core_b, facets_b = event_parts(title_b)
    if len(core_a & core_b) < 2:
        return False
    seasons_a = {x for x in facets_a if x.startswith("season:")}
    seasons_b = {x for x in facets_b if x.startswith("season:")}
    same_season = bool(seasons_a & seasons_b)
    same_film_announcement = "film" in facets_a and "film" in facets_b
    # Une année commune ne suffit jamais : une saison et un film peuvent
    # être annoncés la même année tout en restant deux événements distincts.
    if not (same_season or same_film_announcement):
        return False
    years_a = {x for x in facets_a if x.startswith("year:")}
    years_b = {x for x in facets_b if x.startswith("year:")}
    if years_a and years_b and not (years_a & years_b):
        return False
    denominator = min(len(core_a), len(core_b))
    return bool(denominator and len(core_a & core_b) / denominator >= 0.5)


def coverage_score(publisher_count, primary_source_count=0):
    """Mesure la diversité des sources, avec bonus limité aux flux de première partie."""
    media_score = min(90, max(0, publisher_count) * 30)
    primary_bonus = min(20, max(0, primary_source_count) * 20)
    return min(100, media_score + primary_bonus)


def evidence_level(publisher_count, primary_source_count=0):
    """Niveau de provenance, jamais une validation automatique des faits."""
    if primary_source_count > 0:
        return "first_party_feed_present_needs_review"
    return "multi_media_reported" if publisher_count >= 2 else "single_publisher_signal"


# Termes éditoriaux à ignorer pour reconnaître une franchise dans un titre.
EDITORIAL_GENERIC = {
    "new", "latest", "announced", "announcement", "reveals", "revealed",
    "confirms", "confirmed", "adaptation", "anime", "manga", "release",
    "trailer", "teaser", "premiere", "episode", "chapter", "volume",
    "returns", "return", "live", "action", "gets", "get", "season",
    "saison", "movie", "film", "theatrical", "cinema", "feature",
    "my", "its", "the", "and", "for", "with", "from", "in", "on",
}


def same_franchise(title_a, title_b):
    """Repère prudemment deux titres d'une même franchise, sans confondre un mot générique."""
    core_a, _ = event_parts(title_a)
    core_b, _ = event_parts(title_b)
    core_a -= EDITORIAL_GENERIC
    core_b -= EDITORIAL_GENERIC
    if not core_a or not core_b:
        return False
    shared = core_a & core_b
    ratio = len(shared) / min(len(core_a), len(core_b))
    # Deux mots distinctifs suffisent ; un seul n'est accepté que s'il est long et rare.
    if len(shared) >= 2 and ratio >= 0.5:
        return True
    return len(shared) == 1 and len(next(iter(shared))) >= 7 and ratio >= 0.66


def diversify_queue(items, limit=15, max_per_franchise=2):
    """Conserve l'ordre de priorité tout en limitant la répétition d'une franchise."""
    selected = []
    groups = []
    for item in items:
        title = str(item.get("title", ""))
        group_index = next(
            (index for index, group in enumerate(groups)
             if same_franchise(title, group["representative"])),
            None
        )
        if group_index is not None:
            if groups[group_index]["count"] >= max_per_franchise:
                continue
            groups[group_index]["count"] += 1
        else:
            groups.append({"representative": title, "count": 1})
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected
