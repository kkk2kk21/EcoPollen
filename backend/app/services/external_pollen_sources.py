from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timedelta

import httpx

NORKKO_BULLETIN_URL = "https://siirto.siitepoly.fi/media/sptied.txt"
NORKKO_STATION_COORDS = {
    "Turku": (60.4518, 22.2666),
    "Helsinki": (60.1699, 24.9384),
    "Imatra": (61.1719, 28.7524),
    "Kuopio": (62.8924, 27.6770),
    "Vaasa": (63.0951, 21.6165),
    "Oulu": (65.0121, 25.4651),
    "Rovaniemi": (66.5039, 25.7294),
    "Utsjoki": (69.9086, 27.0284),
}
NORKKO_TAXON_BY_CODE = {
    "L": "alder",
    "C": "hazel",
    "K": "birch",
    "H": "grass",
    "P": "mugwort",
    "T": "ragweed",
}

METEOSWISS_STATIONS_URL = "https://data.geo.admin.ch/ch.meteoschweiz.ogd-pollen/ogd-pollen_meta_stations.csv"
METEOSWISS_DAILY_RECENT_TEMPLATE = (
    "https://data.geo.admin.ch/ch.meteoschweiz.ogd-pollen/{station}/"
    "ogd-pollen_{station}_d_recent.csv"
)
METEOSWISS_DAILY_COLUMNS = {
    "alder": "kaalnud1",
    "ash": "kafraxd1",
    "birch": "kabetud1",
    "beech": "kafagud1",
    "hazel": "kacoryd1",
    "oak": "kaquerd1",
    "grass": "khpoacd1",
}

DWD_POLLEN_URL = "https://opendata.dwd.de/climate_environment/health/alerts/s31fg.json"
DWD_TAXON_BY_NAME = {
    "Erle": "alder",
    "Hasel": "hazel",
    "Esche": "ash",
    "Birke": "birch",
    "Graeser": "grass",
    "Roggen": "rye",
    "Beifuss": "mugwort",
    "Ambrosia": "ragweed",
}
DWD_REGION_CENTROIDS = {
    "10:11": (54.7500, 8.7000),
    "10:12": (53.7000, 9.9000),
    "20:-1": (53.7000, 12.5000),
    "30:31": (53.1000, 8.5000),
    "30:32": (52.6000, 10.7000),
    "40:41": (51.4500, 6.9000),
    "40:42": (51.9000, 8.6000),
    "40:43": (51.2000, 8.2000),
    "50:-1": (52.5000, 13.4000),
    "60:61": (52.1000, 11.7000),
    "60:62": (51.8000, 10.7000),
    "70:71": (50.9500, 11.1000),
    "70:72": (50.6500, 10.7000),
    "80:81": (51.0500, 13.7000),
    "80:82": (50.6500, 13.0000),
    "90:91": (51.1500, 9.4000),
    "90:92": (50.1000, 8.7000),
    "100:101": (49.9000, 7.9000),
    "100:102": (50.1000, 7.3000),
    "100:103": (49.3500, 6.9000),
    "110:111": (49.1000, 8.5000),
    "110:112": (48.7000, 9.5000),
    "110:113": (48.1000, 8.2000),
    "120:121": (48.2500, 11.6000),
    "120:122": (48.8000, 12.9000),
    "120:123": (49.6000, 11.8000),
    "120:124": (49.8000, 9.9000),
}


def _clean_text(value: str) -> str:
    return value.replace("\ufeff", "").replace("\r", "").strip()


def _parse_fi_date(value: str) -> date:
    return datetime.strptime(value.strip(), "%d.%m.%Y").date()


def _parse_dwd_last_update(value: str) -> date:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", value or "")
    if not match:
        raise ValueError("Не удалось распознать дату DWD")
    return date.fromisoformat(match.group(1))


def _index_0_3_from_range(value: str | int | float | None) -> float | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None
    if "-" in text:
        left, right = text.split("-", 1)
        return (float(left) + float(right)) / 2
    return float(text)


async def fetch_norkko_records(day: date | None = None) -> tuple[date, list[dict], str]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(NORKKO_BULLETIN_URL)
        response.raise_for_status()
        text = response.text

    text = text.replace("ä", "a").replace("ö", "o")
    lines = [_clean_text(line) for line in text.splitlines()]
    lines = [line for line in lines if line]

    if "TILANNE" not in lines or "ENNUSTE" not in lines:
        raise ValueError("Norkko: неожиданная структура бюллетеня")

    current_idx = lines.index("TILANNE")
    forecast_idx = lines.index("ENNUSTE")
    current_day = _parse_fi_date(lines[current_idx + 1])

    forecast_range = lines[forecast_idx + 1]
    forecast_match = re.match(r"(\d{2}\.\d{2}\.\d{4})\s*-\s*(\d{2}\.\d{2}\.\d{4})", forecast_range)
    if not forecast_match:
        raise ValueError("Norkko: не удалось распознать диапазон прогноза")

    forecast_start = _parse_fi_date(forecast_match.group(1))
    forecast_end = _parse_fi_date(forecast_match.group(2))

    current_station_lines = lines[current_idx + 2 : forecast_idx]
    forecast_station_lines = []
    for line in lines[forecast_idx + 2 :]:
        if line.startswith("Tunnukset:"):
            break
        forecast_station_lines.append(line)

    target_day = day or current_day
    if target_day == current_day:
        source_lines = current_station_lines
        mode = "current"
    elif forecast_start <= target_day <= forecast_end:
        source_lines = forecast_station_lines
        mode = "forecast"
    else:
        return current_day, [], "Norkko: для выбранной даты нет бюллетеня"

    records: list[dict] = []
    for line in source_lines:
        station_name = next(
            (name for name in NORKKO_STATION_COORDS if line.startswith(name)),
            None,
        )
        if not station_name:
            continue

        rest = line[len(station_name) :].strip()
        tokens = re.findall(r"\b([LCKHPT])\1{0,2}\b", rest)
        full_tokens = re.findall(r"\b(?:L{1,3}|C{1,3}|K{1,3}|H{1,3}|P{1,3}|T{1,3})\b", rest)
        if not full_tokens:
            continue

        lat, lon = NORKKO_STATION_COORDS[station_name]
        for token in full_tokens:
            code = token[0]
            taxon_key = NORKKO_TAXON_BY_CODE.get(code)
            if not taxon_key:
                continue
            records.append(
                {
                    "native_key": f"norkko:{station_name.lower()}",
                    "location_name": f"{station_name}, Finland",
                    "lat": lat,
                    "lon": lon,
                    "kind": "station",
                    "day": target_day,
                    "taxon_key": taxon_key,
                    "value": float(len(token)),
                    "unit": "index_0_3",
                }
            )

    return current_day, records, f"Norkko mode={mode}"


async def fetch_meteoswiss_records(day: date | None = None) -> tuple[date | None, list[dict], str]:
    async with httpx.AsyncClient(timeout=30) as client:
        stations_response = await client.get(METEOSWISS_STATIONS_URL)
        stations_response.raise_for_status()
        stations_rows = csv.DictReader(
            io.StringIO(stations_response.text),
            delimiter=";",
        )

        records: list[dict] = []
        imported_day: date | None = None

        for station in stations_rows:
            station_abbr = (station.get("station_abbr") or "").strip()
            if not station_abbr:
                continue

            station_key = station_abbr.lower()
            station_name = (station.get("station_name") or station_abbr).strip()
            lat = float(station["station_coordinates_wgs84_lat"])
            lon = float(station["station_coordinates_wgs84_lon"])

            data_url = METEOSWISS_DAILY_RECENT_TEMPLATE.format(station=station_key)
            data_response = await client.get(data_url)
            data_response.raise_for_status()
            station_rows = list(
                csv.DictReader(io.StringIO(data_response.text), delimiter=";")
            )
            if not station_rows:
                continue

            selected_row = None
            if day is not None:
                for row in station_rows:
                    row_day = datetime.strptime(
                        row["reference_timestamp"], "%d.%m.%Y %H:%M"
                    ).date()
                    if row_day == day:
                        selected_row = row
                        break
            else:
                selected_row = station_rows[-1]

            if not selected_row:
                continue

            row_day = datetime.strptime(
                selected_row["reference_timestamp"], "%d.%m.%Y %H:%M"
            ).date()
            if imported_day is None:
                imported_day = row_day

            for taxon_key, column in METEOSWISS_DAILY_COLUMNS.items():
                raw = selected_row.get(column)
                if raw in (None, ""):
                    continue
                records.append(
                    {
                        "native_key": f"meteoswiss:{station_key}",
                        "location_name": f"{station_name}, Switzerland",
                        "lat": lat,
                        "lon": lon,
                        "kind": "station",
                        "day": row_day,
                        "taxon_key": taxon_key,
                        "value": float(raw),
                        "unit": "pollen/m3",
                    }
                )

    return imported_day, records, "MeteoSwiss daily station import"


async def fetch_dwd_records(day: date | None = None) -> tuple[date, list[dict], str]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(DWD_POLLEN_URL)
        response.raise_for_status()
        payload = response.json()

    base_day = _parse_dwd_last_update(payload.get("last_update", ""))
    target_day = day or base_day
    delta = (target_day - base_day).days
    if delta == 0:
        day_key = "today"
    elif delta == 1:
        day_key = "tomorrow"
    elif delta == 2:
        day_key = "dayafter_to"
    else:
        return base_day, [], "DWD: доступны только today/tomorrow/dayafter_to"

    records: list[dict] = []
    for region in payload.get("content", []):
        region_id = region.get("region_id")
        partregion_id = region.get("partregion_id")
        centroid = DWD_REGION_CENTROIDS.get(f"{region_id}:{partregion_id}")
        if not centroid:
            continue

        region_name = (region.get("region_name") or "").strip()
        partregion_name = (region.get("partregion_name") or "").strip()
        location_name = (
            f"{partregion_name}, Germany"
            if partregion_name
            else f"{region_name}, Germany"
        )

        lat, lon = centroid
        pollen_map = region.get("Pollen") or {}
        for pollen_name, taxon_key in DWD_TAXON_BY_NAME.items():
            pollen_data = pollen_map.get(pollen_name) or {}
            raw = _index_0_3_from_range(pollen_data.get(day_key))
            if raw is None:
                continue

            records.append(
                {
                    "native_key": f"dwd:{region_id}:{partregion_id}",
                    "location_name": location_name,
                    "lat": lat,
                    "lon": lon,
                    "kind": "region",
                    "day": target_day,
                    "taxon_key": taxon_key,
                    "value": raw,
                    "unit": "index_0_3",
                }
            )

    return base_day, records, f"DWD {day_key}"
