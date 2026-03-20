import asyncio
import copy
import math
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Query

from ...domain.models import User
from ...search.semantic import expand_query as expand_semantic_query
from .auth import get_current_user
from ...search.providers.cyberleninka import search_cyberleninka
from ...search.providers.crossref import search_crossref
from ...search.providers.pubmed import search_pubmed
from ...search.providers.openalex import search_openalex

router = APIRouter(prefix="/library", tags=["library"])

DEFAULT_SOURCE_ORDER = ["cyberleninka", "crossref", "pubmed", "openalex"]
SOURCE_SEARCHERS = {
    "cyberleninka": search_cyberleninka,
    "crossref": search_crossref,
    "pubmed": search_pubmed,
    "openalex": search_openalex,
}
ALLOWED_SORTS = {"relevance", "date_desc", "date_asc"}
ALLOWED_LANGUAGES = {"any", "ru", "en", "other"}
SEARCH_CACHE_TTL_SECONDS = 15 * 60
SEARCH_CACHE_MAX_ENTRIES = 128
SEARCH_FETCH_LIMIT = 80
SEARCH_CACHE_SCHEMA_VERSION = 8
SEARCH_CACHE: dict[tuple, dict] = {}
SEARCH_CACHE_LOCK = asyncio.Lock()
INFLIGHT_SEARCHES: dict[tuple, asyncio.Task] = {}
INFLIGHT_SEARCHES_LOCK = asyncio.Lock()
GENERIC_ENGLISH_EXPANSIONS = {
    "allergy",
    "allergic disease",
    "hypersensitivity",
    "pollen",
    "airborne pollen",
}
EXPANDED_TERM_WEIGHTS = {
    "allergen": {"title": 34, "snippet": 14},
    "condition": {"title": 28, "snippet": 11},
    "specific": {"title": 14, "snippet": 6},
    "generic": {"title": 6, "snippet": 2},
}
TOPIC_RELEVANCE_WEIGHTS = {
    "title_anchor": 28,
    "snippet_anchor": 12,
    "author_anchor": 4,
    "coverage_bonus": 44,
    "all_specific_bonus": 34,
    "title_specific_bonus": 22,
    "generic_only_penalty": 52,
    "no_anchor_penalty": 18,
}
BROAD_TOPIC_TOKENS = {
    "пыльца",
    "пыльцу",
    "пыльцы",
    "пыльцой",
    "пыльце",
    "pollen",
    "pollens",
}
# Generic medical terms help broaden external queries, but are too weak to prove
# that a result is really about the user's specific topic.
GENERIC_TOPIC_TOKENS = {
    "аллергия",
    "аллергии",
    "аллергию",
    "аллергией",
    "аллергиям",
    "аллергических",
    "аллергический",
    "аллергическая",
    "аллергическое",
    "аллергические",
    "аллергического",
    "аллергической",
    "аллергическом",
    "аллергическим",
    "аллергическими",
    "аллергологический",
    "аллергологическая",
    "аллергологические",
    "гиперчувствительность",
    "гиперчувствительности",
    "гиперчувствительностью",
    "сенсибилизация",
    "сенсибилизации",
    "сенсибилизацией",
    "симптом",
    "симптомы",
    "симптомов",
    "симптоматика",
    "проявление",
    "проявления",
    "клиника",
    "клинический",
    "клинические",
    "лечение",
    "терапия",
    "диагностика",
    "профилактика",
    "заболевание",
    "заболевания",
    "болезнь",
    "болезни",
    "пациент",
    "пациенты",
    "дети",
    "ребенок",
    "ребёнок",
    "детей",
    "allergy",
    "allergic",
    "allergies",
    "allergen",
    "allergens",
    "disease",
    "diseases",
    "hypersensitivity",
    "sensitization",
    "symptom",
    "symptoms",
    "clinical",
    "manifestation",
    "manifestations",
    "treatment",
    "therapy",
    "diagnosis",
    "diagnostic",
    "prevention",
    "patient",
    "patients",
    "child",
    "children",
    "airborne",
}
# Service words should never become topic anchors.
TOPIC_STOPWORDS = {
    "в",
    "на",
    "к",
    "у",
    "с",
    "со",
    "по",
    "для",
    "при",
    "от",
    "до",
    "из",
    "под",
    "над",
    "без",
    "про",
    "и",
    "или",
    "а",
    "но",
    "не",
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "for",
    "with",
    "in",
    "to",
    "on",
    "by",
    "from",
    "at",
    "as",
    "is",
    "are",
}


def _normalize_sources(raw_sources: str | None) -> list[str]:
    if not raw_sources:
        return DEFAULT_SOURCE_ORDER.copy()

    requested = [item.strip().lower() for item in raw_sources.split(",") if item.strip()]
    selected = [key for key in DEFAULT_SOURCE_ORDER if key in requested]

    if not selected:
        raise HTTPException(
            status_code=400,
            detail="Нужно указать хотя бы один корректный источник: cyberleninka, crossref, pubmed, openalex.",
        )

    return selected


def _within_year_range(year: int | None, year_from: int | None, year_to: int | None) -> bool:
    if year is None:
        return year_from is None and year_to is None
    if year_from is not None and year < year_from:
        return False
    if year_to is not None and year > year_to:
        return False
    return True


def _parse_publication_date(value: str | None) -> tuple[int, int, int] | None:
    match = re.match(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$", (value or "").strip())
    if not match:
        return None

    year = int(match.group(1))
    month = int(match.group(2) or 0)
    day = int(match.group(3) or 0)
    return year, month, day


def _infer_language(*parts: str | None) -> str | None:
    text = " ".join(part for part in parts if part).strip()
    if not text:
        return None

    if re.search(r"[ІіЇїЄєҐґ]", text):
        return "other"

    cyrillic_count = len(re.findall(r"[А-Яа-яЁё]", text))
    latin_count = len(re.findall(r"[A-Za-z]", text))

    if cyrillic_count and not latin_count:
        return "ru"
    if latin_count and not cyrillic_count:
        return "en"
    if cyrillic_count and latin_count:
        return "ru" if cyrillic_count >= latin_count else "en"

    return "other"


def _normalize_source_language(value: str | None) -> str | None:
    normalized = _normalize_text(value)
    if not normalized:
        return None
    if normalized in {"ru", "rus", "russian"}:
        return "ru"
    if normalized in {"en", "eng", "english"}:
        return "en"
    if normalized in {"uk", "ukr", "ukrainian"}:
        return "other"
    return None


def _matches_author(item: dict, author: str | None) -> bool:
    if not author:
        return True
    authors = (item.get("authors") or "").lower()
    return author.lower() in authors


def _matches_language(item: dict, language: str) -> bool:
    if language == "any":
        return True
    return item.get("language") == language


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _sanitize_expanded_terms(base_query: str, expanded_terms: list[str] | None) -> list[str]:
    normalized_query = _normalize_text(base_query)
    cleaned = []
    seen = set()

    for term in expanded_terms or []:
        normalized_term = _normalize_text(term)
        if not normalized_term or normalized_term == normalized_query or normalized_term in seen:
            continue
        seen.add(normalized_term)
        cleaned.append(term.strip())

    return cleaned


def _sanitize_expanded_term_meta(
    expanded_terms: list[str],
    expanded_term_meta: dict[str, dict] | None,
) -> dict[str, dict]:
    cleaned = {}
    for term in expanded_terms:
        normalized_term = _normalize_text(term)
        if not normalized_term:
            continue
        meta = (expanded_term_meta or {}).get(normalized_term) or {}
        cleaned[normalized_term] = {
            "type": meta.get("type"),
            "is_generic": bool(meta.get("is_generic")),
        }
    return cleaned


def _tokenize_text(value: str | None) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]+", _normalize_text(value))
        if len(token) >= 2
    ]


def _contains_cyrillic(value: str | None) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", value or ""))


def _normalize_source_term(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _token_anchor(token: str) -> str:
    normalized = _normalize_text(token)
    if len(normalized) >= 5:
        return normalized[:5]
    return normalized


def _build_query_variants(
    query: str,
    search_terms: list[str],
    expanded_terms: list[str],
) -> dict[str, str]:
    candidate_terms = [query, *search_terms, *expanded_terms]
    all_parts = []
    english_parts = []
    cyrillic_parts = []

    for value in candidate_terms:
        for piece in re.split(r"[,;]", value or ""):
            normalized = _normalize_source_term(piece)
            if not normalized:
                continue
            all_parts.append(normalized)
            if _contains_cyrillic(normalized):
                cyrillic_parts.append(normalized)
            else:
                english_parts.append(normalized)

    unique_all_parts = list(dict.fromkeys(all_parts))
    unique_english_parts = list(dict.fromkeys(english_parts))
    unique_cyrillic_parts = list(dict.fromkeys(cyrillic_parts))
    normalized_english_parts = {_normalize_text(part) for part in unique_english_parts}
    has_specific_english_parts = any(
        part not in GENERIC_ENGLISH_EXPANSIONS
        for part in normalized_english_parts
    )

    if (
        not has_specific_english_parts
        and bool(unique_english_parts)
        and any("pollen" in part for part in normalized_english_parts)
        and any(part in {"allergy", "allergic disease", "hypersensitivity"} for part in normalized_english_parts)
    ):
        unique_english_parts = [
            *[part for part in ["pollen allergy", "pollinosis"] if part not in unique_english_parts],
            *unique_english_parts,
        ]

    all_query = " ".join(unique_all_parts)
    english_query = " ".join(unique_english_parts)
    cyrillic_query = " ".join(unique_cyrillic_parts)
    original_query = _normalize_source_term(query)

    return {
        "original": original_query,
        "all": all_query,
        "english": english_query,
        "cyrillic": cyrillic_query,
    }


def _build_topic_anchors(base_query: str, expanded_terms: list[str]) -> tuple[list[str], list[str]]:
    anchors = []
    specific_anchors = []
    for value in [base_query, *expanded_terms]:
        for token in _tokenize_text(value):
            normalized = _normalize_text(token)
            if (
                not normalized
                or normalized in TOPIC_STOPWORDS
                or normalized in GENERIC_TOPIC_TOKENS
                or len(normalized) < 3
            ):
                continue
            anchor = _token_anchor(normalized)
            anchors.append(anchor)
            if normalized not in BROAD_TOPIC_TOKENS:
                specific_anchors.append(anchor)

    return list(dict.fromkeys(anchors)), list(dict.fromkeys(specific_anchors))


def _collect_item_anchor_sets(item: dict) -> dict[str, set[str]]:
    anchor_sets = {}
    for field in ("title", "snippet", "authors"):
        anchor_sets[field] = {
            _token_anchor(token)
            for token in _tokenize_text(item.get(field))
        }
    anchor_sets["all"] = anchor_sets["title"] | anchor_sets["snippet"] | anchor_sets["authors"]
    return anchor_sets


def _score_topic_alignment(item: dict, base_query: str, expanded_terms: list[str]) -> int:
    anchors, specific_anchors = _build_topic_anchors(base_query, expanded_terms)
    if not anchors:
        return 0

    active_anchors = specific_anchors or anchors
    anchor_sets = _collect_item_anchor_sets(item)

    title_hits = [anchor for anchor in active_anchors if anchor in anchor_sets["title"]]
    snippet_hits = [anchor for anchor in active_anchors if anchor in anchor_sets["snippet"]]
    author_hits = [anchor for anchor in active_anchors if anchor in anchor_sets["authors"]]
    all_hits = [anchor for anchor in active_anchors if anchor in anchor_sets["all"]]

    if not all_hits:
        return -TOPIC_RELEVANCE_WEIGHTS["no_anchor_penalty"]

    score = 0
    score += len(title_hits) * TOPIC_RELEVANCE_WEIGHTS["title_anchor"]
    score += len(snippet_hits) * TOPIC_RELEVANCE_WEIGHTS["snippet_anchor"]
    score += len(author_hits) * TOPIC_RELEVANCE_WEIGHTS["author_anchor"]
    score += round(
        TOPIC_RELEVANCE_WEIGHTS["coverage_bonus"] * (len(set(all_hits)) / max(1, len(active_anchors)))
    )

    if specific_anchors:
        specific_title_hits = [anchor for anchor in specific_anchors if anchor in anchor_sets["title"]]
        specific_all_hits = [anchor for anchor in specific_anchors if anchor in anchor_sets["all"]]

        if not specific_all_hits:
            return -TOPIC_RELEVANCE_WEIGHTS["generic_only_penalty"]
        if len(set(specific_all_hits)) == len(specific_anchors):
            score += TOPIC_RELEVANCE_WEIGHTS["all_specific_bonus"]
        if specific_title_hits:
            score += TOPIC_RELEVANCE_WEIGHTS["title_specific_bonus"]

    return score


def _prepare_source_terms(
    *,
    source_key: str,
    query: str,
    search_terms: list[str],
    expanded_terms: list[str],
) -> list[str]:
    variants = _build_query_variants(query, search_terms, expanded_terms)
    english_query = variants["english"]
    cyrillic_query = variants["cyrillic"]

    if source_key == "pubmed":
        if english_query:
            return [english_query]
        return []

    prepared = []
    if cyrillic_query:
        prepared.append(cyrillic_query)
    if english_query and english_query not in prepared:
        prepared.append(english_query)
    if prepared:
        return prepared
    return [query]


def _expanded_term_weight(meta: dict | None) -> dict[str, int]:
    if not meta or meta.get("is_generic"):
        return EXPANDED_TERM_WEIGHTS["generic"]
    if meta.get("type") == "allergen":
        return EXPANDED_TERM_WEIGHTS["allergen"]
    if meta.get("type") == "condition":
        return EXPANDED_TERM_WEIGHTS["condition"]
    return EXPANDED_TERM_WEIGHTS["specific"]


def _score_direct_text_match(item: dict, base_query: str) -> int:
    title = _normalize_text(item.get("title"))
    snippet = _normalize_text(item.get("snippet"))
    authors = _normalize_text(item.get("authors"))
    base_query_norm = _normalize_text(base_query)
    query_tokens = list(dict.fromkeys(_tokenize_text(base_query)))

    score = 0

    if base_query_norm:
        if base_query_norm in title:
            score += 120
        if title.startswith(base_query_norm):
            score += 20
        if base_query_norm in snippet:
            score += 45
        if base_query_norm in authors:
            score += 18

    if query_tokens:
        title_hits = {token for token in query_tokens if token in title}
        snippet_hits = {token for token in query_tokens if token in snippet}
        author_hits = {token for token in query_tokens if token in authors}
        all_hits = title_hits | snippet_hits | author_hits

        score += round(48 * (len(title_hits) / len(query_tokens)))
        score += round(20 * (len(snippet_hits) / len(query_tokens)))
        score += round(10 * (len(author_hits) / len(query_tokens)))

        if len(all_hits) == len(query_tokens):
            score += 18

    return score


def _score_semantic_expansion(
    item: dict,
    expanded_terms: list[str],
    expanded_term_meta: dict[str, dict] | None = None,
) -> int:
    title = _normalize_text(item.get("title"))
    snippet = _normalize_text(item.get("snippet"))
    expanded_norm = [
        term
        for term in dict.fromkeys(_normalize_text(term) for term in expanded_terms)
        if term
    ]

    score = 0
    for term in expanded_norm:
        weights = _expanded_term_weight((expanded_term_meta or {}).get(term))
        if term in title:
            score += weights["title"]
        if term in snippet:
            score += weights["snippet"]

    return score


def _score_relevance(
    item: dict,
    base_query: str,
    expanded_terms: list[str],
    expanded_term_meta: dict[str, dict] | None = None,
) -> int:
    direct_score = _score_direct_text_match(item, base_query)
    semantic_score = _score_semantic_expansion(item, expanded_terms, expanded_term_meta)
    topic_score = _score_topic_alignment(item, base_query, expanded_terms)
    return direct_score + semantic_score + topic_score


def _get_publication_parts(item: dict) -> tuple[int, int, int] | None:
    published_at = (item.get("published_at") or "").strip()
    match = re.match(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$", published_at)
    if match:
        year = int(match.group(1))
        month = int(match.group(2) or 0)
        day = int(match.group(3) or 0)
        return year, month, day

    year = item.get("year")
    if isinstance(year, int):
        return year, 0, 0

    return None


def _filter_results(
    results: list[dict],
    *,
    selected_sources: list[str],
    year_from: int | None,
    year_to: int | None,
    date_from: str | None,
    date_to: str | None,
    author: str | None,
    language: str,
    only_with_year: bool,
) -> list[dict]:
    parsed_date_from = _parse_publication_date(date_from)
    parsed_date_to = _parse_publication_date(date_to)
    filtered = []

    for item in results:
        if item.get("source") not in selected_sources:
            continue
        if not _within_year_range(item.get("year"), year_from, year_to):
            continue
        publication_parts = _get_publication_parts(item)
        if parsed_date_from is not None:
            if publication_parts is None or publication_parts < parsed_date_from:
                continue
        if parsed_date_to is not None:
            if publication_parts is None or publication_parts > parsed_date_to:
                continue
        if only_with_year and item.get("year") is None:
            continue
        if not _matches_author(item, author):
            continue
        if not _matches_language(item, language):
            continue
        filtered.append(item)

    return filtered


def _sort_results(
    results: list[dict],
    sort: str,
    *,
    base_query: str,
    expanded_terms: list[str],
    expanded_term_meta: dict[str, dict] | None = None,
) -> list[dict]:
    def date_desc_key(item: dict) -> tuple:
        parts = _get_publication_parts(item)
        if parts is None:
            return (1, 0, 0, 0, item.get("title") or "")

        year, month, day = parts
        return (0, -year, -month, -day, item.get("title") or "")

    def date_asc_key(item: dict) -> tuple:
        parts = _get_publication_parts(item)
        if parts is None:
            return (1, 9999, 99, 99, item.get("title") or "")

        year, month, day = parts
        return (0, year, month, day, item.get("title") or "")

    if sort == "date_desc":
        return sorted(results, key=date_desc_key)

    if sort == "date_asc":
        return sorted(results, key=date_asc_key)

    return sorted(
        results,
        key=lambda item: (
            -_score_relevance(item, base_query, expanded_terms, expanded_term_meta),
            *date_desc_key(item)[:-1],
            item.get("title") or "",
        ),
    )


def _build_cache_lookup_key(
    *,
    q: str,
    expand_query: bool,
) -> tuple:
    return (
        SEARCH_CACHE_SCHEMA_VERSION,
        q.strip().lower(),
        expand_query,
    )


def _build_inflight_search_key(
    *,
    q: str,
    expand_query: bool,
    selected_sources: list[str],
    year_from: int | None,
    year_to: int | None,
    sort: str,
) -> tuple:
    normalized_sources = tuple(selected for selected in DEFAULT_SOURCE_ORDER if selected in selected_sources)
    return (
        q.strip().lower(),
        expand_query,
        normalized_sources,
        year_from,
        year_to,
        sort,
    )


def _covers_sources(
    *,
    cached_sources: tuple[str, ...],
    requested_sources: list[str],
) -> bool:
    return set(requested_sources).issubset(set(cached_sources))


def _covers_year_window(
    *,
    cached_from: int | None,
    cached_to: int | None,
    requested_from: int | None,
    requested_to: int | None,
) -> bool:
    lower_ok = cached_from is None or (requested_from is not None and cached_from <= requested_from)
    upper_ok = cached_to is None or (requested_to is not None and cached_to >= requested_to)
    return lower_ok and upper_ok


def _cache_entry_specificity(entry: dict) -> tuple[int, int, float]:
    source_count = len(entry["fetched_sources"])
    cached_from = entry["fetch_year_from"]
    cached_to = entry["fetch_year_to"]
    open_bounds = int(cached_from is None) + int(cached_to is None)
    lower = cached_from if cached_from is not None else -9999
    upper = cached_to if cached_to is not None else 9999
    return (source_count, open_bounds, upper - lower, -entry["expires_at"])


async def _get_cached_search(
    lookup_key: tuple,
    *,
    requested_sources: list[str],
    requested_year_from: int | None,
    requested_year_to: int | None,
    required_window: int,
) -> tuple[dict | None, bool]:
    now = time.time()

    async with SEARCH_CACHE_LOCK:
        expired_keys = [
            key
            for key, entry in SEARCH_CACHE.items()
            if entry["expires_at"] <= now
        ]
        for key in expired_keys:
            SEARCH_CACHE.pop(key, None)

        candidates = [
            entry
            for entry in SEARCH_CACHE.values()
            if entry["lookup_key"] == lookup_key
            # The cache stores the full fetched payload, not individual pages.
            # Requiring page * limit here only causes unnecessary misses for the
            # last page (and any later page revisits), because pagination is
            # always sliced from the same cached result set.
            and _covers_sources(
                cached_sources=entry["fetched_sources"],
                requested_sources=requested_sources,
            )
            and _covers_year_window(
                cached_from=entry["fetch_year_from"],
                cached_to=entry["fetch_year_to"],
                requested_from=requested_year_from,
                requested_to=requested_year_to,
            )
        ]
        if not candidates:
            return None, False

        cached = sorted(candidates, key=_cache_entry_specificity)[0]
        cached["expires_at"] = now + SEARCH_CACHE_TTL_SECONDS
        return copy.deepcopy(cached["payload"]), True


async def _store_cached_search(
    lookup_key: tuple,
    *,
    fetched_sources: list[str],
    fetch_year_from: int | None,
    fetch_year_to: int | None,
    required_window: int,
    payload: dict,
) -> None:
    now = time.time()
    stored_window = max(required_window, len(payload.get("results") or []))
    normalized_sources = tuple(selected for selected in DEFAULT_SOURCE_ORDER if selected in fetched_sources)
    entry_key = (*lookup_key, normalized_sources, fetch_year_from, fetch_year_to)

    async with SEARCH_CACHE_LOCK:
        SEARCH_CACHE[entry_key] = {
            "lookup_key": lookup_key,
            "fetched_sources": normalized_sources,
            "fetch_year_from": fetch_year_from,
            "fetch_year_to": fetch_year_to,
            "window_size": stored_window,
            "expires_at": now + SEARCH_CACHE_TTL_SECONDS,
            "payload": copy.deepcopy(payload),
        }

        if len(SEARCH_CACHE) <= SEARCH_CACHE_MAX_ENTRIES:
            return

        oldest_keys = sorted(
            SEARCH_CACHE,
            key=lambda key: SEARCH_CACHE[key]["expires_at"],
        )[: len(SEARCH_CACHE) - SEARCH_CACHE_MAX_ENTRIES]

        for key in oldest_keys:
            SEARCH_CACHE.pop(key, None)


async def _get_or_execute_inflight_search(
    inflight_key: tuple,
    execute_coro_factory,
) -> dict:
    async with INFLIGHT_SEARCHES_LOCK:
        task = INFLIGHT_SEARCHES.get(inflight_key)
        owner = False
        if task is None:
            task = asyncio.create_task(execute_coro_factory())
            INFLIGHT_SEARCHES[inflight_key] = task
            owner = True

    try:
        return await task
    finally:
        if owner:
            async with INFLIGHT_SEARCHES_LOCK:
                current = INFLIGHT_SEARCHES.get(inflight_key)
                if current is task:
                    INFLIGHT_SEARCHES.pop(inflight_key, None)


async def _execute_search(
    *,
    q: str,
    selected_sources: list[str],
    expand_query: bool,
    year_from: int | None,
    year_to: int | None,
    date_from: str | None,
    date_to: str | None,
    author: str | None,
    language: str,
    only_with_year: bool,
    sort: str,
    fetch_limit: int,
) -> dict:
    if expand_query:
        sem = await expand_semantic_query(q)
        search_terms = sem["search_terms"]
        expanded_terms = sem["expanded_terms"]
        expanded_term_meta = sem.get("expanded_term_meta", {})
    else:
        search_terms = [q]
        expanded_terms = []
        expanded_term_meta = {}

    tasks = []
    task_meta = []
    for source_key in selected_sources:
        search_fn = SOURCE_SEARCHERS[source_key]
        source_terms = _prepare_source_terms(
            source_key=source_key,
            query=q,
            search_terms=search_terms,
            expanded_terms=expanded_terms,
        )
        for term in source_terms:
            tasks.append(
                search_fn(
                    term,
                    limit=fetch_limit,
                    year_from=year_from,
                    year_to=year_to,
                    sort=sort,
                )
            )
            task_meta.append({"source": source_key, "term": term})

    raw_lists = await asyncio.gather(*tasks, return_exceptions=True)

    source_status = {
        source_key: {
            "source": source_key,
            "status": "ok",
            "success_terms": 0,
            "failed_terms": 0,
            "warning": None,
        }
        for source_key in selected_sources
    }

    results = []
    seen = set()

    for meta, item in zip(task_meta, raw_lists):
        state = source_status[meta["source"]]

        if isinstance(item, Exception):
            state["failed_terms"] += 1
            if state["warning"] is None:
                state["warning"] = str(item)
            continue

        state["success_terms"] += 1
        for result in item:
            enriched_result = {
                **result,
                "language": _normalize_source_language(result.get("language"))
                or _infer_language(result.get("title"), result.get("authors")),
            }
            key = result.get("url") or result.get("title")
            if not key or key in seen:
                continue
            seen.add(key)
            results.append(enriched_result)

    for state in source_status.values():
        if state["failed_terms"] and not state["success_terms"]:
            state["status"] = "error"
        elif state["failed_terms"]:
            state["status"] = "partial_error"

    warnings = [
        {"source": state["source"], "message": state["warning"]}
        for state in source_status.values()
        if state["warning"]
    ]

    return {
        "search_terms": search_terms,
        "expanded_terms": expanded_terms,
        "expanded_term_meta": expanded_term_meta,
        "source_statuses": list(source_status.values()),
        "warnings": warnings,
        "results": results,
    }


@router.get(
    "/search",
    summary="Поиск публикаций",
    description="Ищет публикации по подключённым научным источникам с фильтрами и необязательным расширением запроса.",
)
async def search(
    q: str = Query(..., min_length=2),
    page: int = Query(1, ge=1, le=100),
    limit: int = Query(10, ge=1, le=20),
    expand_query: bool = Query(False),
    year_from: int | None = Query(None, ge=1900, le=2100),
    year_to: int | None = Query(None, ge=1900, le=2100),
    date_from: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    author: str | None = Query(None, min_length=2),
    language: str = Query("any"),
    only_with_year: bool = Query(False),
    sort: str = Query("relevance"),
    sources: str | None = Query(
        None,
        description="Список источников через запятую: cyberleninka,crossref,pubmed,openalex",
    ),
    user: User = Depends(get_current_user),
):
    if year_from is not None and year_to is not None and year_from > year_to:
        raise HTTPException(status_code=400, detail="year_from не может быть больше year_to.")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from не может быть больше date_to.")

    if sort not in ALLOWED_SORTS:
        raise HTTPException(status_code=400, detail="sort должен быть: relevance, date_desc, date_asc.")

    if language not in ALLOWED_LANGUAGES:
        raise HTTPException(status_code=400, detail="language должен быть: any, ru, en, other.")

    selected_sources = _normalize_sources(sources)
    effective_year_from = year_from if year_from is not None else (int(date_from[:4]) if date_from else None)
    effective_year_to = year_to if year_to is not None else (int(date_to[:4]) if date_to else None)

    required_window = page * limit
    fetch_limit = SEARCH_FETCH_LIMIT

    cache_lookup_key = _build_cache_lookup_key(
        q=q,
        expand_query=expand_query,
    )

    cached_payload, cache_hit = await _get_cached_search(
        cache_lookup_key,
        requested_sources=selected_sources,
        requested_year_from=effective_year_from,
        requested_year_to=effective_year_to,
        required_window=required_window,
    )
    payload = cached_payload
    if payload is None:
        inflight_key = _build_inflight_search_key(
            q=q,
            expand_query=expand_query,
            selected_sources=selected_sources,
            year_from=effective_year_from,
            year_to=effective_year_to,
            sort=sort,
        )
        payload = await _get_or_execute_inflight_search(
            inflight_key,
            lambda: _execute_search(
                q=q,
                selected_sources=selected_sources,
                expand_query=expand_query,
                year_from=effective_year_from,
                year_to=effective_year_to,
                date_from=date_from,
                date_to=date_to,
                author=author,
                language=language,
                only_with_year=only_with_year,
                sort=sort,
                fetch_limit=fetch_limit,
            ),
        )
        await _store_cached_search(
            cache_lookup_key,
            fetched_sources=selected_sources,
            fetch_year_from=effective_year_from,
            fetch_year_to=effective_year_to,
            required_window=required_window,
            payload=payload,
        )

    visible_expanded_terms = _sanitize_expanded_terms(
        q,
        payload.get("expanded_terms") or payload.get("chips") or [],
    )
    visible_expanded_term_meta = _sanitize_expanded_term_meta(
        visible_expanded_terms,
        payload.get("expanded_term_meta"),
    )

    filtered_results = _filter_results(
        payload["results"],
        selected_sources=selected_sources,
        year_from=effective_year_from,
        year_to=effective_year_to,
        date_from=date_from,
        date_to=date_to,
        author=author,
        language=language,
        only_with_year=only_with_year,
    )

    sorted_results = _sort_results(
        filtered_results,
        sort,
        base_query=q,
        expanded_terms=visible_expanded_terms,
        expanded_term_meta=visible_expanded_term_meta,
    )

    total_results = len(sorted_results)
    total_pages = math.ceil(total_results / limit) if total_results else 0
    offset = (page - 1) * limit
    paginated_results = sorted_results[offset : offset + limit]

    return {
        "query": q,
        "expanded_terms": visible_expanded_terms,
        "filters": {
            "page": page,
            "sources": selected_sources,
            "expand_query": expand_query,
            "year_from": effective_year_from,
            "year_to": effective_year_to,
            "date_from": date_from,
            "date_to": date_to,
            "author": author,
            "language": language,
            "only_with_year": only_with_year,
            "sort": sort,
            "limit": limit,
        },
        "pagination": {
            "page": page,
            "limit": limit,
            "total_results": total_results,
            "total_pages": total_pages,
            "has_prev": page > 1,
            "has_next": offset + limit < total_results,
        },
        "cache": {
            "hit": cache_hit,
            "ttl_seconds": SEARCH_CACHE_TTL_SECONDS,
        },
        "source_statuses": [
            state for state in payload["source_statuses"] if state["source"] in selected_sources
        ],
        "warnings": [
            warning for warning in payload["warnings"] if warning["source"] in selected_sources
        ],
        "results": paginated_results,
        "user": {"email": user.email, "role": user.role},
    }
