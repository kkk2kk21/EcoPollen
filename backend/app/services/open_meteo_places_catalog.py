from __future__ import annotations

import io
import json
import urllib.request
import zipfile
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from ..geo.open_meteo_region import is_open_meteo_region_point

OPEN_METEO_REGION_CITY_CATALOG_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "open-meteo-region-city-catalog.json"
)
GEONAMES_CITIES500_URL = "https://download.geonames.org/export/dump/cities500.zip"
GEONAMES_ALT_NAMES_URL = "https://download.geonames.org/export/dump/alternateNamesV2.zip"
GEONAMES_ADMIN1_URL = "https://download.geonames.org/export/dump/admin1CodesASCII.txt"
OPEN_METEO_REGION_CITY_MIN_POPULATION = 5000
OPEN_METEO_REGION_COUNTRY_CODES = ("RU", "BY", "MD", "UA", "GE", "AM", "AZ")
OPEN_METEO_REGION_COUNTRY_NAMES_RU = {
    "RU": "Россия",
    "BY": "Беларусь",
    "MD": "Молдова",
    "UA": "Украина",
    "GE": "Грузия",
    "AM": "Армения",
    "AZ": "Азербайджан",
}


def _fetch_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=90) as response:
        return response.read()


def _fetch_text(url: str) -> str:
    return _fetch_bytes(url).decode("utf-8", errors="ignore")


def _clean(value: str | None) -> str:
    return " ".join(str(value or "").replace("\u200f", "").replace("\u200e", "").split()).strip(" ,;")


def _unique(values: list[str]) -> list[str]:
    seen = set()
    items: list[str] = []
    for value in values:
        cleaned = _clean(value)
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        items.append(cleaned)
    return items


def _load_admin1_catalog() -> tuple[dict[str, dict[str, str]], set[str]]:
    admin1_map: dict[str, dict[str, str]] = {}
    admin1_ids: set[str] = set()
    for line in _fetch_text(GEONAMES_ADMIN1_URL).splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        code = parts[0]
        geoname_id = parts[3]
        admin1_map[code] = {
            "name": _clean(parts[1]),
            "geoname_id": geoname_id,
        }
        admin1_ids.add(geoname_id)
    return admin1_map, admin1_ids


def _iter_cities500_rows():
    with zipfile.ZipFile(io.BytesIO(_fetch_bytes(GEONAMES_CITIES500_URL))) as archive:
        with archive.open("cities500.txt") as handle:
            for line in handle:
                yield line.decode("utf-8").rstrip("\n").split("\t")


def _iter_alternate_name_rows():
    with zipfile.ZipFile(io.BytesIO(_fetch_bytes(GEONAMES_ALT_NAMES_URL))) as archive:
        with archive.open("alternateNamesV2.txt") as handle:
            for line in handle:
                yield line.decode("utf-8", errors="ignore").rstrip("\n").split("\t")


def build_open_meteo_region_city_catalog() -> list[dict]:
    admin1_map, admin1_ids = _load_admin1_catalog()

    city_entries: list[dict] = []
    city_ids: set[str] = set()
    for parts in _iter_cities500_rows():
        geoname_id = parts[0]
        name = _clean(parts[1])
        asciiname = _clean(parts[2])
        alternates = _unique(parts[3].split(","))
        lat = float(parts[4])
        lon = float(parts[5])
        feature_code = parts[7]
        country_code = parts[8]
        admin1_code = parts[10]
        population = int(parts[14] or 0)

        if country_code not in OPEN_METEO_REGION_COUNTRY_CODES:
            continue
        if not is_open_meteo_region_point(lat, lon):
            continue
        if not (feature_code.startswith("PPLA") or feature_code == "PPLC" or population >= OPEN_METEO_REGION_CITY_MIN_POPULATION):
            continue

        city_ids.add(geoname_id)
        city_entries.append(
            {
                "geoname_id": geoname_id,
                "name": name,
                "asciiname": asciiname,
                "alternates": alternates,
                "lat": lat,
                "lon": lon,
                "country_code": country_code,
                "country_name": OPEN_METEO_REGION_COUNTRY_NAMES_RU[country_code],
                "admin1_code": admin1_code,
                "population": population,
            }
        )

    ru_names: dict[str, list[str]] = defaultdict(list)
    preferred_ru_names: dict[str, str] = {}
    for parts in _iter_alternate_name_rows():
        if len(parts) < 5:
            continue
        geoname_id = parts[1]
        if geoname_id not in city_ids and geoname_id not in admin1_ids:
            continue
        if parts[2] != "ru":
            continue

        alt_name = _clean(parts[3])
        if not alt_name:
            continue

        ru_names[geoname_id].append(alt_name)
        if parts[4] == "1" and geoname_id not in preferred_ru_names:
            preferred_ru_names[geoname_id] = alt_name

    admin1_name_ru: dict[str, str] = {}
    for code, data in admin1_map.items():
        geoname_id = data["geoname_id"]
        variants = _unique(ru_names.get(geoname_id, []))
        admin1_name_ru[code] = preferred_ru_names.get(geoname_id) or (variants[0] if variants else data["name"])

    for item in city_entries:
        geoname_id = item["geoname_id"]
        variants = _unique(ru_names.get(geoname_id, []))
        display_name = preferred_ru_names.get(geoname_id) or (variants[0] if variants else item["name"] or item["asciiname"])

        aliases = _unique(
            [
                display_name,
                *variants,
                item["name"],
                item["asciiname"],
                *item["alternates"],
            ]
        )
        admin1_key = f"{item['country_code']}.{item['admin1_code']}"
        admin1_name_display = admin1_name_ru.get(admin1_key) or admin1_map.get(admin1_key, {}).get("name", "")
        search_text = " ".join(
            _unique(
                [
                    *aliases,
                    admin1_name_display,
                    admin1_map.get(admin1_key, {}).get("name", ""),
                    item["country_name"],
                    item["country_code"],
                ]
            )
        )

        item["display_name"] = display_name
        item["admin1_name_display"] = admin1_name_display
        item["search_text"] = search_text

    name_counts = Counter((item["display_name"].casefold(), item["country_code"]) for item in city_entries)

    output: list[dict] = []
    for item in city_entries:
        label = f"{item['display_name']}, {item['country_name']}"
        admin1_name = _clean(item["admin1_name_display"])
        if name_counts[(item["display_name"].casefold(), item["country_code"])] > 1:
            if admin1_name and admin1_name.casefold() != item["display_name"].casefold():
                label = f"{item['display_name']}, {admin1_name}, {item['country_name']}"

        output.append(
            {
                "id": f"catalog:city:{item['geoname_id']}",
                "name": item["display_name"],
                "lat": item["lat"],
                "lon": item["lon"],
                "country_code": item["country_code"],
                "country_name": item["country_name"],
                "admin1_name": item["admin1_name_display"],
                "population": item["population"],
                "search_text": item["search_text"],
                "label": label,
            }
        )

    output.sort(key=lambda row: (row["country_name"].casefold(), row["label"].casefold(), -row["population"]))
    return output


def save_open_meteo_region_city_catalog(path: Path = OPEN_METEO_REGION_CITY_CATALOG_PATH) -> list[dict]:
    catalog = build_open_meteo_region_city_catalog()
    path.write_text(
        json.dumps(catalog, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    load_open_meteo_region_city_catalog.cache_clear()
    return catalog


@lru_cache(maxsize=1)
def load_open_meteo_region_city_catalog() -> list[dict]:
    if not OPEN_METEO_REGION_CITY_CATALOG_PATH.exists():
        return []

    with OPEN_METEO_REGION_CITY_CATALOG_PATH.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)

    return payload if isinstance(payload, list) else []


if __name__ == "__main__":
    catalog = save_open_meteo_region_city_catalog()
    print(f"Saved {len(catalog)} city entries to {OPEN_METEO_REGION_CITY_CATALOG_PATH}")
