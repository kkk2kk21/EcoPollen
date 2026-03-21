from __future__ import annotations

import asyncio

import httpx

from ..domain.pollen_taxa_catalog import OPEN_METEO_SUPPORTED_TAXA

BASE_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
CAMS_EUROPE_BOUNDS = {
    "min_lat": 30.0,
    "max_lat": 72.0,
    "min_lon": -25.0,
    "max_lon": 45.0,
}

# Так наши аллергены называются в Open-Meteo
POLLEN_VAR = {
    "alder": "alder_pollen",
    "birch": "birch_pollen",
    "grass": "grass_pollen",
    "mugwort": "mugwort_pollen",
    "olive": "olive_pollen",
    "ragweed": "ragweed_pollen",
}

# В Open-Meteo пыльца идёт только в сезон и максимум на 4 дня вперёд
POLLEN_FORECAST_DAYS = 4

# Чтобы URL не раздувался и API не отдавало 400, режем точки на пачки
MAX_POINTS_PER_REQUEST = 40
MAX_RETRY_ATTEMPTS = 4
DEFAULT_RETRY_DELAY_SECONDS = 30


class PollenUnavailableError(Exception):
    """Open-Meteo вернул 400, такое часто бывает вне сезона пыльцы"""


def _as_csv(values: list[float]) -> str:
    return ",".join(str(v) for v in values)


def _retry_delay_seconds(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return max(float(retry_after), 1.0)
        except ValueError:
            pass
    return float(DEFAULT_RETRY_DELAY_SECONDS * attempt)


def is_cams_europe_point(lat: float, lon: float) -> bool:
    return (
        CAMS_EUROPE_BOUNDS["min_lat"] <= lat <= CAMS_EUROPE_BOUNDS["max_lat"]
        and CAMS_EUROPE_BOUNDS["min_lon"] <= lon <= CAMS_EUROPE_BOUNDS["max_lon"]
    )


async def fetch_current_pollen(lat: float, lon: float, taxa_keys: list[str]) -> dict:
    vars_ = [POLLEN_VAR[k] for k in taxa_keys if k in OPEN_METEO_SUPPORTED_TAXA]
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": ",".join(vars_),
        "timezone": "auto",
        "domains": "cams_europe",
        "forecast_days": POLLEN_FORECAST_DAYS,
    }

    async with httpx.AsyncClient(timeout=20) as client:
        for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
            try:
                r = await client.get(BASE_URL, params=params)
                r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 400:
                    raise PollenUnavailableError(e.response.text) from e
                if e.response.status_code == 429 and attempt < MAX_RETRY_ATTEMPTS:
                    await asyncio.sleep(_retry_delay_seconds(e.response, attempt))
                    continue
                raise


async def fetch_current_pollen_multi(
    lats: list[float],
    lons: list[float],
    taxa_keys: list[str],
    chunk_delay_seconds: float = 0,
) -> list[dict]:
    """
    Open-Meteo поддерживает несколько координат списком (latitude=...,longitude=...).
    Но если точек много — URL становится огромным -> делаем запросы кусками.
    """
    if len(lats) != len(lons):
        raise ValueError("lats и lons должны быть одинаковой длины")

    vars_ = [POLLEN_VAR[k] for k in taxa_keys if k in OPEN_METEO_SUPPORTED_TAXA]
    if not vars_:
        return []

    out: list[dict] = []

    async with httpx.AsyncClient(timeout=30) as client:
        total_points = len(lats)
        for start in range(0, total_points, MAX_POINTS_PER_REQUEST):
            chunk_lats = lats[start : start + MAX_POINTS_PER_REQUEST]
            chunk_lons = lons[start : start + MAX_POINTS_PER_REQUEST]

            params = {
                "latitude": _as_csv(chunk_lats),
                "longitude": _as_csv(chunk_lons),
                "current": ",".join(vars_),
                "timezone": "auto",
                "domains": "cams_europe",
                "forecast_days": POLLEN_FORECAST_DAYS,
            }

            data = None
            for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
                try:
                    r = await client.get(BASE_URL, params=params)
                    r.raise_for_status()
                    data = r.json()
                    break
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 400:
                        raise PollenUnavailableError(e.response.text) from e
                    if e.response.status_code == 429 and attempt < MAX_RETRY_ATTEMPTS:
                        await asyncio.sleep(_retry_delay_seconds(e.response, attempt))
                        continue
                    raise

            if isinstance(data, dict):
                out.append(data)
            else:
                out.extend(data)

            has_more_chunks = start + MAX_POINTS_PER_REQUEST < total_points
            if has_more_chunks and chunk_delay_seconds > 0:
                await asyncio.sleep(chunk_delay_seconds)

    return out
