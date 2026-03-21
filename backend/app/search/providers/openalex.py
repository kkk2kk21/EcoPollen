from __future__ import annotations

import os
import httpx

BASE = "https://api.openalex.org/works"

def _within_year_range(year: int | None, year_from: int | None, year_to: int | None) -> bool:
    if year is None:
        return year_from is None and year_to is None
    if year_from is not None and year < year_from:
        return False
    if year_to is not None and year > year_to:
        return False
    return True


async def search_openalex(
    term: str,
    limit: int = 10,
    *,
    year_from: int | None = None,
    year_to: int | None = None,
    sort: str = "relevance",
) -> list[dict]:
    api_key = os.getenv("OPENALEX_API_KEY")  # ключ можно не задавать

    params = {
        "search": term,
        "per-page": limit,
    }
    if api_key:
        params["api_key"] = api_key

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(BASE, params=params)
        r.raise_for_status()
        data = r.json()

    results = []
    for w in data.get("results") or []:
        title = w.get("title")
        year = w.get("publication_year")
        url = w.get("primary_location", {}).get("landing_page_url") or w.get("id")
        authorships = w.get("authorships") or []
        authors = ", ".join([(a.get("author") or {}).get("display_name") for a in authorships[:5] if (a.get("author") or {}).get("display_name")]) or None
        if not _within_year_range(year, year_from, year_to):
            continue

        results.append({
            "source": "openalex",
            "title": title,
            "authors": authors,
            "year": year,
            "published_at": w.get("publication_date"),
            "language": w.get("language"),
            "snippet": None,
            "url": url,
        })

    return results
