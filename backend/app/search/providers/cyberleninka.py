from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

BASE = "https://cyberleninka.ru"
API_URL = f"{BASE}/api/search"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/133.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Referer": f"{BASE}/search",
    "Origin": BASE,
}


def _clean_text(value: str | None) -> str | None:
    if not value:
        return None
    text = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    return text or None


def _within_year_range(year: int | None, year_from: int | None, year_to: int | None) -> bool:
    if year is None:
        return year_from is None and year_to is None
    if year_from is not None and year < year_from:
        return False
    if year_to is not None and year > year_to:
        return False
    return True


async def search_cyberleninka(
    term: str,
    limit: int = 10,
    *,
    year_from: int | None = None,
    year_to: int | None = None,
    sort: str = "relevance",
) -> list[dict]:
    payload: dict[str, str | int] = {
        "mode": "articles",
        "q": term,
        "size": limit,
        "from": 0,
    }
    if year_from is not None:
        payload["year_from"] = year_from
    if year_to is not None:
        payload["year_to"] = year_to

    async with httpx.AsyncClient(timeout=20, headers=DEFAULT_HEADERS) as client:
        response = await client.post(API_URL, json=payload)
        response.raise_for_status()
        data = response.json()

    results = []
    seen = set()

    for item in data.get("articles") or []:
        href = item.get("link")
        if not href:
            continue

        full_url = href if href.startswith("http") else f"{BASE}{href}"
        if full_url in seen:
            continue
        seen.add(full_url)

        title = _clean_text(item.get("name"))
        if not title:
            continue

        year = item.get("year")
        if not _within_year_range(year, year_from, year_to):
            continue

        authors = ", ".join(item.get("authors") or []) or None
        snippet = _clean_text(item.get("annotation"))

        results.append(
            {
                "source": "cyberleninka",
                "title": title,
                "authors": authors,
                "year": year,
                "published_at": str(year) if year else None,
                "snippet": snippet,
                "url": full_url,
            }
        )

        if len(results) >= limit:
            break

    return results
