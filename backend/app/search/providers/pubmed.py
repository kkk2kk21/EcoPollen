from __future__ import annotations

import httpx
import re

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

def _within_year_range(year: int | None, year_from: int | None, year_to: int | None) -> bool:
    if year is None:
        return year_from is None and year_to is None
    if year_from is not None and year < year_from:
        return False
    if year_to is not None and year > year_to:
        return False
    return True


def _format_date(year: int, month: int | None = None, day: int | None = None) -> str:
    if month is None:
        return f"{year:04d}"
    if day is None:
        return f"{year:04d}-{month:02d}"
    return f"{year:04d}-{month:02d}-{day:02d}"


def _extract_publication_date(item: dict) -> tuple[int | None, str | None]:
    sortpubdate = (item.get("sortpubdate") or "").strip()
    match = re.search(r"(\d{4})/(\d{2})/(\d{2})", sortpubdate)
    if match:
        year, month, day = (int(value) for value in match.groups())
        return year, _format_date(year, month, day)

    raw_pubdate = (item.get("epubdate") or item.get("pubdate") or "").strip()
    match = re.search(r"(\d{4})\s+([A-Za-z]{3,9})\s+(\d{1,2})", raw_pubdate)
    if match:
        year = int(match.group(1))
        month = MONTHS.get(match.group(2)[:3].lower())
        day = int(match.group(3))
        if month:
            return year, _format_date(year, month, day)

    match = re.search(r"(\d{4})\s+([A-Za-z]{3,9})", raw_pubdate)
    if match:
        year = int(match.group(1))
        month = MONTHS.get(match.group(2)[:3].lower())
        if month:
            return year, _format_date(year, month)

    match = re.search(r"(\d{4})", raw_pubdate)
    if match:
        year = int(match.group(1))
        return year, _format_date(year)

    return None, None


async def search_pubmed(
    term: str,
    limit: int = 10,
    *,
    year_from: int | None = None,
    year_to: int | None = None,
    sort: str = "relevance",
) -> list[dict]:
    async with httpx.AsyncClient(timeout=20) as client:
        params = {
            "db": "pubmed",
            "retmode": "json",
            "retmax": limit,
            "term": term,
        }
        if year_from is not None:
            params["mindate"] = str(year_from)
        if year_to is not None:
            params["maxdate"] = str(year_to)
        if year_from is not None or year_to is not None:
            params["datetype"] = "pdat"
        if sort in ("date_desc", "date_asc"):
            params["sort"] = "pub date"

        # 1) esearch -> ids
        r = await client.get(
            f"{BASE}/esearch.fcgi",
            params=params,
        )
        r.raise_for_status()
        ids = (r.json().get("esearchresult") or {}).get("idlist") or []
        if not ids:
            return []

        # 2) esummary -> metadata
        r2 = await client.get(
            f"{BASE}/esummary.fcgi",
            params={"db": "pubmed", "retmode": "json", "id": ",".join(ids)},
        )
        r2.raise_for_status()
        data = r2.json().get("result") or {}

    results = []
    for pid in ids:
        item = data.get(pid) or {}
        title = item.get("title")
        year, published_at = _extract_publication_date(item)
        authors = ", ".join([a.get("name") for a in (item.get("authors") or []) if a.get("name")][:5]) or None
        if not _within_year_range(year, year_from, year_to):
            continue

        results.append({
            "source": "pubmed",
            "title": title,
            "authors": authors,
            "year": year,
            "published_at": published_at,
            "snippet": None,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
        })

    return results
