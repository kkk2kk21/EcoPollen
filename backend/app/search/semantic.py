from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path


def _resolve_ontology_path() -> Path:
    current = Path(__file__).resolve()
    candidates = [
        current.parents[2] / "data" / "ontologies" / "concept_overlay.json",
        current.parents[1] / "data" / "ontologies" / "concept_overlay.json",
        current.parent / "data" / "ontologies" / "concept_overlay.json",
        Path.cwd() / "data" / "ontologies" / "concept_overlay.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


ONTOLOGY_PATH = _resolve_ontology_path()
MAX_CHIPS = 6
MAX_QUERIES = 4
GENERIC_CONCEPT_IDS = {"allergy", "pollen", "child"}
TYPE_BOOST = {
    "allergen": 50,
    "condition": 32,
    "treatment": 24,
    "diagnostic": 22,
    "symptom": 18,
    "trigger": 16,
    "monitoring": 16,
    "management": 14,
    "mechanism": 12,
    "population": 12,
}


def expanded_term_priority(concept: dict) -> tuple[int, int]:
    concept_id = concept["id"]
    concept_type = concept["type"]

    if concept_type == "allergen" and concept_id not in GENERIC_CONCEPT_IDS:
        return (0, -TYPE_BOOST.get(concept_type, 0))
    if concept_type == "condition" and concept_id not in GENERIC_CONCEPT_IDS:
        return (1, -TYPE_BOOST.get(concept_type, 0))
    if concept_id not in GENERIC_CONCEPT_IDS:
        return (2, -TYPE_BOOST.get(concept_type, 0))
    return (3, -TYPE_BOOST.get(concept_type, 0))


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower().replace("ё", "е"))


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]+", normalize(text))


def dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = normalize(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value.strip())
    return result


@lru_cache(maxsize=1)
def load_semantic_index() -> dict:
    if not ONTOLOGY_PATH.exists():
        return {"concepts": [], "metadata": {"missing_ontology": True}}

    payload = json.loads(ONTOLOGY_PATH.read_text(encoding="utf-8"))
    concepts = []
    for concept in payload.get("concepts", []):
        aliases = dedupe(concept.get("aliases", []))
        concepts.append(
            {
                **concept,
                "normalized_aliases": [normalize(alias) for alias in aliases],
                "query_base_en": concept.get("query_base_en", "").strip(),
            }
        )
    return {"concepts": concepts, "metadata": payload}


def score_alias_match(query_norm: str, query_tokens: set[str], alias_norm: str) -> int:
    if not alias_norm:
        return 0

    alias_tokens = tokenize(alias_norm)
    if not alias_tokens:
        return 0

    if len(alias_tokens) > 1 and alias_norm in query_norm:
        return 120 + len(alias_tokens) * 8 + len(alias_norm)

    if all(token in query_tokens for token in alias_tokens):
        return 95 + len(alias_tokens) * 10

    if len(alias_tokens) == 1 and alias_tokens[0] in query_tokens:
        return 62 + len(alias_tokens[0])

    return 0


def match_concepts(query: str) -> list[dict]:
    index = load_semantic_index()
    query_norm = normalize(query)
    query_tokens = set(tokenize(query))
    matches = []

    for concept in index["concepts"]:
        best_score = 0
        best_alias = None
        for alias_norm in concept["normalized_aliases"]:
            alias_score = score_alias_match(query_norm, query_tokens, alias_norm)
            if alias_score > best_score:
                best_score = alias_score
                best_alias = alias_norm

        if best_score <= 0:
            continue

        matches.append(
            {
                **concept,
                "match_score": best_score + TYPE_BOOST.get(concept["type"], 0),
                "matched_alias": best_alias,
            }
        )

    matches.sort(key=lambda item: (-item["match_score"], item["label"]))
    return matches


def build_query_combinations(matches: list[dict], query: str) -> list[str]:
    by_type = {}
    query_norm = normalize(query)

    for match in matches:
        by_type.setdefault(match["type"], []).append(match)

    allergen = by_type.get("allergen", [None])[0]
    condition = by_type.get("condition", [None])[0]
    treatment = by_type.get("treatment", [None])[0]
    diagnostic = by_type.get("diagnostic", [None])[0]
    symptom = by_type.get("symptom", [None])[0]
    monitoring = by_type.get("monitoring", [None])[0]
    management = by_type.get("management", [None])[0]
    population = by_type.get("population", [None])[0]
    trigger = by_type.get("trigger", [None])[0]

    queries = []
    specific_condition = condition if condition and condition["id"] not in GENERIC_CONCEPT_IDS else None

    if allergen and specific_condition:
        queries.append(f"{allergen['query_base_en']} {specific_condition['query_base_en']}")
    elif allergen and ("аллерг" in query_norm or "allerg" in query_norm):
        queries.append(f"{allergen['query_base_en']} allergy")

    if treatment and allergen:
        queries.append(f"{treatment['query_base_en']} {allergen['query_base_en']}")
    if treatment and specific_condition:
        queries.append(f"{treatment['query_base_en']} {specific_condition['query_base_en']}")
    if diagnostic and allergen:
        queries.append(f"{diagnostic['query_base_en']} {allergen['query_base_en']}")
    if diagnostic and specific_condition:
        queries.append(f"{diagnostic['query_base_en']} {specific_condition['query_base_en']}")
    if symptom and specific_condition:
        queries.append(f"{symptom['query_base_en']} {specific_condition['query_base_en']}")
    elif symptom and condition and condition["id"] in GENERIC_CONCEPT_IDS:
        queries.append(f"{condition['query_base_en']} symptoms")
    if symptom and allergen:
        queries.append(f"{symptom['query_base_en']} {allergen['query_base_en']}")
    if symptom and trigger and condition and condition["id"] in GENERIC_CONCEPT_IDS:
        queries.append(f"{trigger['query_base_en']} allergy symptoms")
        queries.append(f"{symptom['query_base_en']} {trigger['query_base_en']}")
    if monitoring and (trigger or allergen):
        base = allergen["query_base_en"] if allergen else trigger["query_base_en"]
        queries.append(f"{monitoring['query_base_en']} {base}")
    if management and (trigger or allergen):
        base = allergen["query_base_en"] if allergen else trigger["query_base_en"]
        queries.append(f"{management['query_base_en']} {base}")
    if population and specific_condition:
        queries.append(f"{specific_condition['query_base_en']} {population['query_base_en']}")
    if population and allergen:
        queries.append(f"{allergen['query_base_en']} {population['query_base_en']}")
    if trigger and condition and not allergen:
        queries.append(f"{trigger['query_base_en']} {condition['query_base_en']}")

    return dedupe([query for query in queries if query.strip()])[:MAX_QUERIES]


def concept_output_priority(concept: dict) -> tuple[int, int]:
    concept_id = concept["id"]
    concept_type = concept["type"]

    if concept_type in {"allergen", "condition", "treatment"} and concept_id not in GENERIC_CONCEPT_IDS:
        return (0, -concept["match_score"])
    if concept_type == "population":
        return (1, -concept["match_score"])
    if concept_id in GENERIC_CONCEPT_IDS:
        return (2, -concept["match_score"])
    return (3, -concept["match_score"])


async def expand_query(q: str) -> dict:
    matches = match_concepts(q)
    if not matches:
        return {"search_terms": [q], "expanded_terms": [], "expanded_term_meta": {}}

    standalone_matches = [match for match in matches if match.get("standalone", True)]
    if not standalone_matches:
        return {"search_terms": [q], "expanded_terms": [], "expanded_term_meta": {}}

    if len(standalone_matches) == 1 and standalone_matches[0]["id"] in GENERIC_CONCEPT_IDS:
        return {"search_terms": [q], "expanded_terms": [], "expanded_term_meta": {}}

    top_matches = matches[:4]
    ordered_matches = sorted(top_matches, key=concept_output_priority)

    expanded_terms = []
    expanded_term_meta = {}
    expanded_term_ranks = {}
    queries = build_query_combinations(ordered_matches, q)
    for match in ordered_matches:
        match_expanded_terms = match.get("expanded_terms", match.get("chips", []))
        expanded_terms.extend(match_expanded_terms)
        queries.extend(match.get("query_terms", []))
        term_rank = expanded_term_priority(match)
        term_meta = {
            "type": match.get("type"),
            "is_generic": match.get("id") in GENERIC_CONCEPT_IDS,
        }
        for term in match_expanded_terms:
            normalized_term = normalize(term)
            if not normalized_term or normalized_term == normalize(q):
                continue
            if normalized_term not in expanded_term_ranks or term_rank < expanded_term_ranks[normalized_term]:
                expanded_term_ranks[normalized_term] = term_rank
                expanded_term_meta[normalized_term] = term_meta

    clean_expanded_terms = [
        term for term in dedupe(expanded_terms) if normalize(term) != normalize(q)
    ][:MAX_CHIPS]
    clean_queries = [
        item
        for item in dedupe(queries)
        if normalize(item) != normalize(q)
    ][:MAX_QUERIES]

    if not clean_expanded_terms and not clean_queries:
        return {"search_terms": [q], "expanded_terms": [], "expanded_term_meta": {}}

    return {
        "search_terms": dedupe([q] + clean_expanded_terms + clean_queries),
        "expanded_terms": clean_expanded_terms,
        "expanded_term_meta": {
            normalize(term): expanded_term_meta.get(normalize(term), {})
            for term in clean_expanded_terms
        },
    }
