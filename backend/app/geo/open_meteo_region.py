from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

OPEN_METEO_REGION_MASK_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "open-meteo-region-mask.json"
)
OPEN_METEO_GRID_KIND = "open_meteo_grid"
OPEN_METEO_GRID_TARGET = 1682
OPEN_METEO_REGION_COUNTRIES = (
    "Россия",
    "Беларусь",
    "Молдова",
    "Украина",
    "Грузия",
    "Армения",
    "Азербайджан",
)
OPEN_METEO_REGION_COUNTRY_CODES = (
    "RU",
    "BY",
    "MD",
    "UA",
    "GE",
    "AM",
    "AZ",
)
OPEN_METEO_REGION_GRID = {
    "min_lat": 38.0,
    "max_lat": 72.0,
    "min_lon": 19.0,
    "max_lon": 45.0,
    "rows": 60,
    "cols": 60,
}
OPEN_METEO_REGION_BBOX = {
    "min_lat": 38.0,
    "max_lat": 72.0,
    "min_lon": 19.0,
    "max_lon": 45.0,
}


@lru_cache(maxsize=1)
def load_open_meteo_region_geometry():
    with OPEN_METEO_REGION_MASK_PATH.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def normalize_geo_longitude(lon: float) -> float:
    return lon + 360 if lon < 0 else lon


def point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    for index, point in enumerate(ring):
        prev_point = ring[index - 1]
        xi = normalize_geo_longitude(float(point[0]))
        yi = float(point[1])
        xj = normalize_geo_longitude(float(prev_point[0]))
        yj = float(prev_point[1])

        intersects = (yi > lat) != (yj > lat) and lon < (
            ((xj - xi) * (lat - yi)) / ((yj - yi) or 1e-12) + xi
        )
        if intersects:
            inside = not inside
    return inside


def point_in_polygon(lon: float, lat: float, polygon: list[list[list[float]]]) -> bool:
    if not polygon:
        return False
    if not point_in_ring(lon, lat, polygon[0]):
        return False

    for ring in polygon[1:]:
        if point_in_ring(lon, lat, ring):
            return False
    return True


def point_in_open_meteo_region_mask(lat: float, lon: float) -> bool:
    geometry = load_open_meteo_region_geometry()
    normalized_lon = normalize_geo_longitude(float(lon))
    latitude = float(lat)

    if geometry["type"] == "Polygon":
        return point_in_polygon(normalized_lon, latitude, geometry["coordinates"])

    if geometry["type"] == "MultiPolygon":
        return any(
            point_in_polygon(normalized_lon, latitude, polygon)
            for polygon in geometry["coordinates"]
        )

    return False


def is_open_meteo_region_point(lat: float, lon: float) -> bool:
    return (
        OPEN_METEO_REGION_BBOX["min_lat"] <= lat <= OPEN_METEO_REGION_BBOX["max_lat"]
        and OPEN_METEO_REGION_BBOX["min_lon"] <= lon <= OPEN_METEO_REGION_BBOX["max_lon"]
        and point_in_open_meteo_region_mask(lat, lon)
    )


def build_grid_points(
    *,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    rows: int,
    cols: int,
    filter_fn=None,
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for row_index in range(rows):
        lat = min_lat + (max_lat - min_lat) * (row_index / (rows - 1))
        for col_index in range(cols):
            lon = min_lon + (max_lon - min_lon) * (col_index / (cols - 1))
            if filter_fn and not filter_fn(lat, lon):
                continue
            points.append((lat, lon))
    return points


def generate_open_meteo_grid_points() -> list[dict[str, float | str]]:
    points = build_grid_points(
        min_lat=OPEN_METEO_REGION_GRID["min_lat"],
        max_lat=OPEN_METEO_REGION_GRID["max_lat"],
        min_lon=OPEN_METEO_REGION_GRID["min_lon"],
        max_lon=OPEN_METEO_REGION_GRID["max_lon"],
        rows=OPEN_METEO_REGION_GRID["rows"],
        cols=OPEN_METEO_REGION_GRID["cols"],
        filter_fn=point_in_open_meteo_region_mask,
    )

    if len(points) != OPEN_METEO_GRID_TARGET:
        raise RuntimeError(
            f"Open-Meteo region grid expected {OPEN_METEO_GRID_TARGET} points, got {len(points)}"
        )

    return [
        {
            "native_key": f"open-meteo-grid-{index + 1:04d}",
            "name": f"Open-Meteo CAMS #{index + 1:04d}",
            "lat": float(lat),
            "lon": float(lon),
            "kind": OPEN_METEO_GRID_KIND,
        }
        for index, (lat, lon) in enumerate(points)
    ]
