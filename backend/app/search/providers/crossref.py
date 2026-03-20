from __future__ import annotations

import os

import httpx
from bs4 import BeautifulSoup

BASE = "https://api.crossref.org/works"
CROSSREF_CONTACT_EMAIL = os.getenv("CROSSREF_CONTACT_EMAIL", "admin@example.local").strip()

DEFAULT_HEADERS = {
    "User-Agent": f"EcoPollen/1.0 (mailto:{CROSSREF_CONTACT_EMAIL})",
    "Accept": "application/json",
}


def _within_year_range(year: int | None, year_from: int | None, year_to: int | None) -> bool:
    if year is None:
        return year_from is None and year_to is None
    if year_from is not None and year < year_from:
        return False
    if year_to is not None and year > year_to:
        return False
    return True


def _clean_text(value: str | None) -> str | None:
    if not value:
        return None
    text = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    return text or None


def _extract_date_parts(item: dict) -> tuple[int, int | None, int | None] | None:
    for field in ("published-print", "published-online", "published", "issued", "created"):
        date_parts = ((item.get(field) or {}).get("date-parts") or [[]])[0]
        if date_parts and str(date_parts[0]).isdigit():
            year = int(date_parts[0])
            month = int(date_parts[1]) if len(date_parts) > 1 and str(date_parts[1]).isdigit() else None
            day = int(date_parts[2]) if len(date_parts) > 2 and str(date_parts[2]).isdigit() else None
            return year, month, day
    return None


def _format_date_parts(parts: tuple[int, int | None, int | None] | None) -> str | None:
    if not parts:
        return None

    year, month, day = parts
    if month is None:
        return f"{year:04d}"
    if day is None:
        return f"{year:04d}-{month:02d}"
    return f"{year:04d}-{month:02d}-{day:02d}"


async def search_crossref(
    term: str,
    limit: int = 10,
    *,
    year_from: int | None = None,
    year_to: int | None = None,
    sort: str = "relevance",
) -> list[dict]:
    params = {
        "query": term,
        "rows": limit,
    }

    filters = []
    if year_from is not None:
        filters.append(f"from-pub-date:{year_from}-01-01")
    if year_to is not None:
        filters.append(f"until-pub-date:{year_to}-12-31")
    if filters:
        params["filter"] = ",".join(filters)

    if sort == "date_desc":
        params["sort"] = "published"
        params["order"] = "desc"
    elif sort == "date_asc":
        params["sort"] = "published"
        params["order"] = "asc"

    async with httpx.AsyncClient(timeout=20, headers=DEFAULT_HEADERS) as client:
        response = await client.get(BASE, params=params)
        response.raise_for_status()
        data = response.json()

    results = []
    seen = set()

    for item in (data.get("message") or {}).get("items") or []:
        title = _clean_text(" ".join(item.get("title") or []))
        if not title:
            continue

        url = (
            ((item.get("resource") or {}).get("primary") or {}).get("URL")
            or item.get("URL")
        )
        if not url or url in seen:
            continue
        seen.add(url)

        date_parts = _extract_date_parts(item)
        year = date_parts[0] if date_parts else None
        if not _within_year_range(year, year_from, year_to):
            continue

        authors = ", ".join(
            " ".join(part for part in [author.get("given"), author.get("family")] if part).strip()
            for author in (item.get("author") or [])[:5]
            if " ".join(part for part in [author.get("given"), author.get("family")] if part).strip()
        ) or None

        snippet = _clean_text(item.get("abstract"))
        if not snippet:
            snippet = _clean_text(" ".join(item.get("container-title") or []))

        results.append(
            {
                "source": "crossref",
                "title": title,
                "authors": authors,
                "year": year,
                "published_at": _format_date_parts(date_parts),
                "language": item.get("language"),
                "snippet": snippet,
                "url": url,
            }
        )

        if len(results) >= limit:
            break

    return results
