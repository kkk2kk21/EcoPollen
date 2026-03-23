from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select
from datetime import timedelta, date, time
from sqlalchemy import func

from ...core.db import get_db
from ...services.map_circle_styles import list_map_circle_styles
from ...services.external_timeseries_distance_settings import get_external_timeseries_distance_map
from ...domain.models import Observation, ExternalObservation, PollenTaxon, DataSource, Location, ExternalLocation
from ...domain.danger_levels import (
    to_danger_level,
    overall_label,
    recommendations,
    describe_measurement,
    measurement_label_rank,
    concentration_thresholds_for_taxon,
    MEASUREMENT_LEVEL_LABELS,
)
from ...services.open_meteo_client import (
    POLLEN_VAR,
    PollenUnavailableError,
    fetch_current_pollen,
)
from ...domain.pollen_taxa_catalog import OPEN_METEO_SUPPORTED_TAXA
from ...domain.pollen_sources import ACTIVE_PUBLIC_SOURCE_KEYS
from ...services.open_meteo_places_catalog import load_open_meteo_region_city_catalog
from ...geo.open_meteo_region import is_open_meteo_region_point

router = APIRouter(tags=["public"])
HEATMAP_ACTIVE_LOCATION_RECENT_DAYS = 2
PGNIU_MANUAL_CITY_PLACES = (
    {
        "id": "manual-city:perm",
        "name": "Пермь",
        "label": "Пермь",
        "lat": 58.0105,
        "lon": 56.2502,
    },
)


def _bbox_predicates(model, *, min_lat=None, max_lat=None, min_lon=None, max_lon=None):
    predicates = []
    if min_lat is not None:
        predicates.append(model.lat >= min_lat)
    if max_lat is not None:
        predicates.append(model.lat <= max_lat)
    if min_lon is not None:
        predicates.append(model.lon >= min_lon)
    if max_lon is not None:
        predicates.append(model.lon <= max_lon)
    return predicates


def _heatmap_rows_for_day(
    db: Session,
    *,
    source_id: int,
    taxon_id: int,
    day: date,
    min_lat: float | None = None,
    max_lat: float | None = None,
    min_lon: float | None = None,
    max_lon: float | None = None,
):
    bbox_predicates = _bbox_predicates(
        Location,
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
    )
    day_end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=timezone.utc)
    latest_ts = db.scalar(
        select(func.max(Observation.ts))
        .join(Location, Observation.location_id == Location.id)
        .where(
            Observation.source_id == source_id,
            Observation.taxon_id == taxon_id,
            Observation.ts < day_end,
            *bbox_predicates,
        )
    )
    if latest_ts is None:
        return []

    ranked = (
        select(
            Location.id.label("location_id"),
            Location.name.label("location_name"),
            Location.kind.label("location_kind"),
            Location.lat.label("lat"),
            Location.lon.label("lon"),
            Observation.ts.label("observed_at"),
            Observation.value.label("value"),
            Observation.unit.label("unit"),
            func.row_number()
            .over(
                partition_by=Location.id,
                order_by=(Observation.ts.desc(), Observation.created_at.desc()),
            )
            .label("rownum"),
        )
        .join(Location, Observation.location_id == Location.id)
        .where(
            Observation.source_id == source_id,
            Observation.taxon_id == taxon_id,
            Observation.ts < day_end,
            *bbox_predicates,
        )
        .subquery()
    )

    return db.execute(
        select(
            ranked.c.location_id,
            ranked.c.location_name,
            ranked.c.location_kind,
            ranked.c.lat,
            ranked.c.lon,
            ranked.c.observed_at,
            ranked.c.value,
            ranked.c.unit,
        )
        .where(ranked.c.rownum == 1)
        .order_by(ranked.c.location_name.asc())
    ).all()


def _external_heatmap_rows_for_day(
    db: Session,
    *,
    source_id: int,
    taxon_id: int,
    day: date,
    min_lat: float | None = None,
    max_lat: float | None = None,
    min_lon: float | None = None,
    max_lon: float | None = None,
):
    bbox_predicates = _bbox_predicates(
        ExternalLocation,
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
    )
    day_end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=timezone.utc)
    latest_ts = db.scalar(
        select(func.max(ExternalObservation.ts))
        .join(ExternalLocation, ExternalObservation.external_location_id == ExternalLocation.id)
        .where(
            ExternalLocation.source_id == source_id,
            ExternalObservation.taxon_id == taxon_id,
            ExternalObservation.ts < day_end,
            *bbox_predicates,
        )
    )
    if latest_ts is None:
        return []

    latest_day = latest_ts.date()
    active_window_start = datetime.combine(
        latest_day - timedelta(days=HEATMAP_ACTIVE_LOCATION_RECENT_DAYS - 1),
        time.min,
        tzinfo=timezone.utc,
    )
    active_window_end = datetime.combine(
        latest_day + timedelta(days=1),
        time.min,
        tzinfo=timezone.utc,
    )
    active_location_ids = (
        select(ExternalObservation.external_location_id)
        .join(ExternalLocation, ExternalObservation.external_location_id == ExternalLocation.id)
        .where(
            ExternalLocation.source_id == source_id,
            ExternalObservation.taxon_id == taxon_id,
            ExternalObservation.ts >= active_window_start,
            ExternalObservation.ts < active_window_end,
            *bbox_predicates,
        )
        .distinct()
    )

    ranked = (
        select(
            ExternalLocation.id.label("location_id"),
            ExternalLocation.name.label("location_name"),
            ExternalLocation.kind.label("location_kind"),
            ExternalLocation.lat.label("lat"),
            ExternalLocation.lon.label("lon"),
            ExternalObservation.ts.label("observed_at"),
            ExternalObservation.value.label("value"),
            ExternalObservation.unit.label("unit"),
            func.row_number()
            .over(
                partition_by=ExternalLocation.id,
                order_by=(ExternalObservation.ts.desc(), ExternalObservation.created_at.desc()),
            )
            .label("rownum"),
        )
        .join(ExternalLocation, ExternalObservation.external_location_id == ExternalLocation.id)
        .where(
            ExternalLocation.source_id == source_id,
            ExternalObservation.taxon_id == taxon_id,
            ExternalObservation.ts < day_end,
            ExternalObservation.external_location_id.in_(active_location_ids),
            *bbox_predicates,
        )
        .subquery()
    )

    return db.execute(
        select(
            ranked.c.location_id,
            ranked.c.location_name,
            ranked.c.location_kind,
            ranked.c.lat,
            ranked.c.lon,
            ranked.c.observed_at,
            ranked.c.value,
            ranked.c.unit,
        )
        .where(ranked.c.rownum == 1)
        .order_by(ranked.c.location_name.asc())
    ).all()

@router.get("/taxa", summary="Справочник аллергенов")
def list_taxa(db: Session = Depends(get_db)):
    taxa = db.scalars(select(PollenTaxon).order_by(PollenTaxon.name_ru)).all()
    return [
        {
            "id": t.id,
            "key": t.key,
            "name_ru": t.name_ru,
            "emoji": t.emoji,
            "group": t.group,
            "legend": {
                "unit": "grains/m3",
                "labels": list(MEASUREMENT_LEVEL_LABELS),
                "concentration_thresholds": list(concentration_thresholds_for_taxon(t.key)),
            },
        }
        for t in taxa
    ]

@router.get("/sources", summary="Справочник источников")
def list_sources(db: Session = Depends(get_db)):
    sources = db.scalars(
        select(DataSource)
        .where(DataSource.key.in_(ACTIVE_PUBLIC_SOURCE_KEYS))
        .order_by(DataSource.priority.desc())
    ).all()
    return [
        {"id": s.id, "key": s.key, "name": s.name, "type": s.source_type, "priority": s.priority, "url": s.url}
        for s in sources
    ]

@router.get("/locations", summary="Внутренние локации")
def list_locations(db: Session = Depends(get_db)):
    locs = db.scalars(
        select(Location)
        .where(Location.kind == "trap")
        .order_by(Location.kind, Location.name)
    ).all()
    return [
        {"id": l.id, "name": l.name, "lat": l.lat, "lon": l.lon, "kind": l.kind}
        for l in locs
    ]


def _map_place_payload(
    *,
    place_id: str,
    name: str,
    label: str | None = None,
    lat: float,
    lon: float,
    kind: str,
    scope: str,
    location_id: int | None = None,
    source_key: str | None = None,
    source_name: str | None = None,
    search_text: str | None = None,
    population: int | None = None,
    country_name: str | None = None,
    source_priority: int | None = None,
    external_location_id: int | None = None,
):
    return {
        "id": place_id,
        "name": name,
        "label": label or name,
        "lat": float(lat),
        "lon": float(lon),
        "kind": kind,
        "scope": scope,
        "location_id": location_id,
        "source_key": source_key,
        "source_name": source_name,
        "search_text": search_text,
        "population": population,
        "country_name": country_name,
        "source_priority": source_priority,
        "external_location_id": external_location_id,
    }


def _find_nearest_internal_location(
    db: Session,
    *,
    lat: float,
    lon: float,
) -> Location | None:
    distance_by_kind = get_external_timeseries_distance_map(db)
    trap_distance_m = float(distance_by_kind.get("trap", 44_400.0))
    max_delta = _distance_window_degrees(trap_distance_m)

    candidates = db.scalars(
        select(Location).where(
            Location.kind == "trap",
            func.abs(Location.lat - lat) <= max_delta,
            func.abs(Location.lon - lon) <= max_delta,
        )
    ).all()

    return _pick_nearest_internal_candidate(
        candidates,
        lat=lat,
        lon=lon,
        distance_by_kind=distance_by_kind,
    )


def _latest_internal_observation_ts(
    db: Session,
    *,
    location_id: int,
    before_dt: datetime,
) -> datetime | None:
    return db.scalar(
        select(func.max(Observation.ts))
        .join(DataSource, Observation.source_id == DataSource.id)
        .where(
            Observation.location_id == location_id,
            Observation.ts < before_dt,
            DataSource.key.in_(ACTIVE_PUBLIC_SOURCE_KEYS),
        )
    )


def _find_nearest_internal_location_with_data(
    db: Session,
    *,
    lat: float,
    lon: float,
    before_dt: datetime,
) -> Location | None:
    distance_by_kind = get_external_timeseries_distance_map(db)
    trap_distance_m = float(distance_by_kind.get("trap", 44_400.0))
    max_delta = _distance_window_degrees(trap_distance_m)

    candidates = db.scalars(
        select(Location)
        .join(Observation, Observation.location_id == Location.id)
        .join(DataSource, Observation.source_id == DataSource.id)
        .where(
            Location.kind == "trap",
            Observation.ts < before_dt,
            DataSource.key.in_(ACTIVE_PUBLIC_SOURCE_KEYS),
            func.abs(Location.lat - lat) <= max_delta,
            func.abs(Location.lon - lon) <= max_delta,
        )
        .group_by(Location.id)
    ).all()

    return _pick_nearest_internal_candidate(
        candidates,
        lat=lat,
        lon=lon,
        distance_by_kind=distance_by_kind,
    )


def _find_best_internal_location_with_data(
    db: Session,
    *,
    lat: float,
    lon: float,
    before_dt: datetime,
) -> Location | None:
    distance_by_kind = get_external_timeseries_distance_map(db)
    trap_distance_m = float(distance_by_kind.get("trap", 44_400.0))
    max_delta = _distance_window_degrees(trap_distance_m)

    rows = db.execute(
        select(
            Location,
            func.max(Observation.ts).label("latest_ts"),
        )
        .join(Observation, Observation.location_id == Location.id)
        .join(DataSource, Observation.source_id == DataSource.id)
        .where(
            Location.kind == "trap",
            Observation.ts < before_dt,
            DataSource.key.in_(ACTIVE_PUBLIC_SOURCE_KEYS),
            func.abs(Location.lat - lat) <= max_delta,
            func.abs(Location.lon - lon) <= max_delta,
        )
        .group_by(Location.id)
    ).all()

    ranked: list[tuple[datetime, float, Location]] = []
    for candidate, latest_ts in rows:
        distance_m = _distance_meters(lat, lon, candidate.lat, candidate.lon)
        if distance_m > trap_distance_m:
            continue
        ranked.append((latest_ts, distance_m, candidate))

    if not ranked:
        return None

    ranked.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    return ranked[0][2]


def _distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6_371_000.0
    lat1_rad = radians(float(lat1))
    lon1_rad = radians(float(lon1))
    lat2_rad = radians(float(lat2))
    lon2_rad = radians(float(lon2))

    delta_lat = lat2_rad - lat1_rad
    delta_lon = lon2_rad - lon1_rad
    hav = sin(delta_lat / 2.0) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(delta_lon / 2.0) ** 2
    return 2.0 * earth_radius_m * asin(sqrt(hav))


def _distance_window_degrees(max_distance_m: float) -> float:
    return max(float(max_distance_m), 0.0) / 111_000.0


def _pick_nearest_internal_candidate(
    candidates: list[Location],
    *,
    lat: float,
    lon: float,
    distance_by_kind: dict[str, float],
) -> Location | None:
    trap_distance_m = float(distance_by_kind.get("trap", 44_400.0))
    ranked: list[tuple[int, float, Location]] = []

    for candidate in candidates:
        max_distance_m = float(distance_by_kind.get(candidate.kind, trap_distance_m))
        distance_m = _distance_meters(lat, lon, candidate.lat, candidate.lon)
        if distance_m > max_distance_m:
            continue
        kind_rank = 0 if candidate.kind == "trap" else 1
        ranked.append((kind_rank, distance_m, candidate))

    if not ranked:
        return None

    ranked.sort(key=lambda item: (item[0], item[1]))
    return ranked[0][2]


def _find_nearest_trap(
    db: Session,
    *,
    lat: float,
    lon: float,
) -> Location | None:
    distance_by_kind = get_external_timeseries_distance_map(db)
    trap_distance_m = float(distance_by_kind.get("trap", 44_400.0))
    max_delta = _distance_window_degrees(trap_distance_m)

    candidates = db.scalars(
        select(Location).where(
            Location.kind == "trap",
            func.abs(Location.lat - lat) <= max_delta,
            func.abs(Location.lon - lon) <= max_delta,
        )
    ).all()

    return _pick_nearest_internal_candidate(
        candidates,
        lat=lat,
        lon=lon,
        distance_by_kind=distance_by_kind,
    )


def _pick_external_timeseries_locations(
    db: Session,
    *,
    lat: float,
    lon: float,
    external_location_id: int | None = None,
    include_nearby_sources_for_selected: bool = False,
) -> dict[str, dict]:
    distance_by_kind = get_external_timeseries_distance_map(db)

    if external_location_id is not None:
        row = db.execute(
            select(
                ExternalLocation.id,
                ExternalLocation.name.label("location_name"),
                ExternalLocation.kind,
                ExternalLocation.lat,
                ExternalLocation.lon,
                DataSource.key,
                DataSource.name.label("source_name"),
                DataSource.priority,
            )
            .join(DataSource, ExternalLocation.source_id == DataSource.id)
            .where(
                ExternalLocation.id == external_location_id,
                DataSource.key.in_(ACTIVE_PUBLIC_SOURCE_KEYS),
            )
            .limit(1)
        ).first()
        if not row:
            return {}
        selected_entry = {
            row.key: {
                "external_location_id": row.id,
                "source_key": row.key,
                "source_name": row.source_name,
                "location_name": row.location_name,
                "kind": row.kind,
                "distance_m": 0.0,
            }
        }
        if not include_nearby_sources_for_selected:
            return selected_entry
        lat = float(row.lat)
        lon = float(row.lon)
        nearest_by_source: dict[str, dict] = dict(selected_entry)
    else:
        nearest_by_source = {}

    candidates = db.execute(
        select(
            ExternalLocation.id,
            ExternalLocation.name.label("location_name"),
            ExternalLocation.kind,
            ExternalLocation.lat,
            ExternalLocation.lon,
            DataSource.key,
            DataSource.name.label("source_name"),
            DataSource.priority,
        )
        .join(DataSource, ExternalLocation.source_id == DataSource.id)
        .where(DataSource.key.in_(ACTIVE_PUBLIC_SOURCE_KEYS))
    ).all()

    for row in candidates:
        max_distance = distance_by_kind.get(row.kind)
        if max_distance is None:
            continue

        distance_m = _distance_meters(lat, lon, row.lat, row.lon)
        if distance_m > max_distance:
            continue

        current = nearest_by_source.get(row.key)
        if current is None or distance_m < current["distance_m"]:
            nearest_by_source[row.key] = {
                "external_location_id": row.id,
                "source_key": row.key,
                "source_name": row.source_name,
                "location_name": row.location_name,
                "kind": row.kind,
                "distance_m": distance_m,
            }

    return nearest_by_source


@router.get("/map-circle-styles", summary="Настройки радиусов слоёв")
def map_circle_styles(db: Session = Depends(get_db)):
    return list_map_circle_styles(db)


@router.get("/map-locations", summary="Места для выбора на карте")
def map_locations(db: Session = Depends(get_db)):
    items = []
    city_catalog = load_open_meteo_region_city_catalog()
    seen_city_keys: set[tuple[str, float, float]] = set()

    for place in PGNIU_MANUAL_CITY_PLACES:
        nearest_trap = _find_nearest_trap(
            db,
            lat=float(place["lat"]),
            lon=float(place["lon"]),
        )
        city_key = (
            str(place["name"]).strip().lower(),
            round(float(place["lat"]), 4),
            round(float(place["lon"]), 4),
        )
        seen_city_keys.add(city_key)
        items.append(
            _map_place_payload(
                place_id=str(place["id"]),
                name=place["name"],
                label=place["label"],
                lat=place["lat"],
                lon=place["lon"],
                kind="city",
                scope="internal",
                location_id=nearest_trap.id if nearest_trap is not None else None,
                source_key="pgniu_manual",
                source_name="Замеры ПГНИУ",
                search_text=place["name"],
                country_name="Россия",
            )
        )

    for city in city_catalog:
        city_key = (
            str(city["name"]).strip().lower(),
            round(float(city["lat"]), 4),
            round(float(city["lon"]), 4),
        )
        if city_key in seen_city_keys:
            continue
        items.append(
            _map_place_payload(
                place_id=str(city["id"]),
                name=city["name"],
                label=city["name"],
                lat=city["lat"],
                lon=city["lon"],
                kind="city",
                scope="catalog",
                source_key="open_meteo",
                source_name="Open-Meteo / CAMS Europe",
                search_text=city.get("search_text"),
                population=city.get("population"),
                country_name=city.get("country_name"),
            )
        )

    external_rows = db.execute(
        select(
            ExternalLocation.id,
            ExternalLocation.native_key,
            ExternalLocation.name,
            ExternalLocation.lat,
            ExternalLocation.lon,
            ExternalLocation.kind,
            DataSource.key,
            DataSource.name,
            DataSource.priority,
        )
        .join(DataSource, ExternalLocation.source_id == DataSource.id)
        .where(
            DataSource.key.in_(ACTIVE_PUBLIC_SOURCE_KEYS),
            ExternalLocation.kind.in_(("station", "region")),
        )
        .order_by(DataSource.priority.desc(), ExternalLocation.name.asc())
    ).all()

    for loc_id, native_key, name, lat, lon, kind, source_key, source_name, _priority in external_rows:
        items.append(
            _map_place_payload(
                place_id=f"external:{source_key}:{native_key}",
                name=name,
                label=name,
                lat=lat,
                lon=lon,
                kind=kind,
                scope="external",
                location_id=None,
                source_key=source_key,
                source_name=source_name,
                search_text=f"{name} {source_name}",
                source_priority=_priority,
                external_location_id=loc_id,
            )
        )

    return items

@router.get(
    "/summary",
    summary="Сводка по текущей пыльцевой ситуации",
    description=(
        "Возвращает текущую сводку по выбранному месту. Сначала используются данные из БД, "
        "а при нехватке значений внутри зоны CAMS может быть подставлен Open-Meteo."
    ),
)
async def summary(
    location_id: int | None = Query(None, description="ID локации из /api/v1/locations (если указан — используется он)"),
    external_location_id: int | None = Query(None, description="ID внешней локации из /api/v1/map-locations"),
    preferred_source_key: str | None = Query(None, description="Предпочтительный источник для выбранной локации"),
    day: date | None = Query(None, description="Дата сводки в локальном представлении клиента"),
    lat: float | None = Query(None, description="Широта (если location_id не указан)"),
    lon: float | None = Query(None, description="Долгота (если location_id не указан)"),
    db: Session = Depends(get_db),
):
    selected_external_location = None

    if location_id is not None:
        loc = db.get(Location, location_id)
        if not loc:
            raise HTTPException(status_code=404, detail="Локация не найдена")
        lat = loc.lat
        lon = loc.lon
    elif external_location_id is not None:
        selected_external_location = db.execute(
            select(
                ExternalLocation.id,
                ExternalLocation.name,
                ExternalLocation.kind,
                ExternalLocation.lat,
                ExternalLocation.lon,
                DataSource.key.label("source_key"),
            )
            .join(DataSource, ExternalLocation.source_id == DataSource.id)
            .where(
                ExternalLocation.id == external_location_id,
                DataSource.key.in_(ACTIVE_PUBLIC_SOURCE_KEYS),
            )
            .limit(1)
        ).first()
        if not selected_external_location:
            raise HTTPException(status_code=404, detail="Внешняя локация не найдена")
        lat = float(selected_external_location.lat)
        lon = float(selected_external_location.lon)
        loc = SimpleNamespace(
            id=None,
            name=selected_external_location.name,
            lat=lat,
            lon=lon,
            kind=selected_external_location.kind,
        )
    else:
        if lat is None or lon is None:
            raise HTTPException(status_code=400, detail="Нужно указать либо location_id, либо external_location_id, либо lat+lon")
        nearest = None
        if preferred_source_key in {None, "pgniu_manual"}:
            nearest = _find_best_internal_location_with_data(
                db,
                lat=float(lat),
                lon=float(lon),
                before_dt=datetime.combine(datetime.now(timezone.utc).date() + timedelta(days=1), time.min, tzinfo=timezone.utc),
            )
            if nearest is None:
                nearest = _find_nearest_internal_location(db, lat=float(lat), lon=float(lon))
        if nearest is not None:
            loc = nearest
            lat = loc.lat
            lon = loc.lon
        else:
            lat = float(lat)
            lon = float(lon)
            loc = SimpleNamespace(
                id=None,
                name="Выбранный город",
                lat=lat,
                lon=lon,
                kind="city",
            )

    if isinstance(day, datetime):
        requested_day = day.date()
    elif isinstance(day, date):
        requested_day = day
    else:
        requested_day = None

    today = requested_day or datetime.now(timezone.utc).date()
    effective_day = today
    day_start = datetime.combine(effective_day, time.min, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    measurement_loc = loc
    latest_internal_ts = None
    if loc.id is not None:
        latest_internal_ts = _latest_internal_observation_ts(
            db,
            location_id=loc.id,
            before_dt=day_end,
        )

    if (
        latest_internal_ts is None
        and selected_external_location is None
        and preferred_source_key in {None, "pgniu_manual"}
    ):
        fallback_loc = _find_nearest_internal_location_with_data(
            db,
            lat=float(lat),
            lon=float(lon),
            before_dt=day_end,
        )
        if fallback_loc is not None:
            measurement_loc = fallback_loc
            latest_internal_ts = _latest_internal_observation_ts(
                db,
                location_id=fallback_loc.id,
                before_dt=day_end,
            )

    if latest_internal_ts is not None and latest_internal_ts.date() < effective_day:
        effective_day = latest_internal_ts.date()
        day_start = datetime.combine(effective_day, time.min, tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)

    external_rows_by_taxon: dict[int, tuple[float, str, str]] = {}
    external_targets = _pick_external_timeseries_locations(
        db,
        lat=float(lat),
        lon=float(lon),
        external_location_id=external_location_id,
        include_nearby_sources_for_selected=external_location_id is not None,
    )
    if preferred_source_key:
        external_targets = {
            key: value
            for key, value in external_targets.items()
            if key == preferred_source_key
        }

    if external_location_id is not None:
        latest_external_ts = db.scalar(
            select(func.max(ExternalObservation.ts))
            .where(
                ExternalObservation.external_location_id == external_location_id,
                ExternalObservation.ts < day_end,
            )
        )
        if latest_external_ts is not None and latest_external_ts.date() < effective_day:
            effective_day = latest_external_ts.date()
            day_start = datetime.combine(effective_day, time.min, tzinfo=timezone.utc)
            day_end = day_start + timedelta(days=1)

    if external_targets:
        external_location_ids = [
            item["external_location_id"] for item in external_targets.values()
        ]
        external_rows = db.execute(
            select(
                ExternalObservation.taxon_id,
                ExternalObservation.value,
                ExternalObservation.unit,
                DataSource.key,
                DataSource.priority,
            )
            .join(
                ExternalLocation,
                ExternalObservation.external_location_id == ExternalLocation.id,
            )
            .join(DataSource, ExternalLocation.source_id == DataSource.id)
            .where(
                ExternalObservation.external_location_id.in_(external_location_ids),
                ExternalObservation.ts >= day_start,
                ExternalObservation.ts < day_end,
                DataSource.key.in_(ACTIVE_PUBLIC_SOURCE_KEYS),
            )
            .order_by(
                ExternalObservation.taxon_id.asc(),
                DataSource.priority.desc(),
                ExternalObservation.created_at.desc(),
            )
        ).all()

        for taxon_id, value, unit, source_key, _priority in external_rows:
            if taxon_id not in external_rows_by_taxon:
                external_rows_by_taxon[taxon_id] = (value, unit, source_key)

    taxa = db.scalars(select(PollenTaxon).order_by(PollenTaxon.name_ru)).all()
    items = []
    max_level = 0
    max_measurement_rank = -1
    missing_taxa = []

    for t in taxa:
        row = None
        if measurement_loc.id is not None:
            row = db.execute(
                select(Observation.value, Observation.unit, DataSource.key)
                .join(DataSource, Observation.source_id == DataSource.id)
                .where(
                    Observation.location_id == measurement_loc.id,
                    Observation.taxon_id == t.id,
                    Observation.ts >= day_start,
                    Observation.ts < day_end,
                    DataSource.key.in_(ACTIVE_PUBLIC_SOURCE_KEYS),
                )
                .order_by(DataSource.priority.desc(), Observation.created_at.desc())
                .limit(1)
            ).first()

        if row:
            raw, unit, source_key = row
            danger_level = to_danger_level(raw, unit, taxon_key=t.key)
            value_label = describe_measurement(raw, unit, taxon_key=t.key)
            max_level = max(max_level, danger_level)
            max_measurement_rank = max(max_measurement_rank, measurement_label_rank(value_label))
            items.append({
                "key": t.key,
                "name_ru": t.name_ru,
                "emoji": t.emoji,
                "raw_value": raw,
                "unit": unit,
                "value_label": value_label,
                "danger_level": danger_level,
                "danger_label": overall_label(danger_level)["label"],
                "source": source_key,
            })
        elif t.id in external_rows_by_taxon:
            raw, unit, source_key = external_rows_by_taxon[t.id]
            danger_level = to_danger_level(raw, unit, taxon_key=t.key)
            value_label = describe_measurement(raw, unit, taxon_key=t.key)
            max_level = max(max_level, danger_level)
            max_measurement_rank = max(max_measurement_rank, measurement_label_rank(value_label))
            items.append({
                "key": t.key,
                "name_ru": t.name_ru,
                "emoji": t.emoji,
                "raw_value": raw,
                "unit": unit,
                "value_label": value_label,
                "danger_level": danger_level,
                "danger_label": overall_label(danger_level)["label"],
                "source": source_key,
            })
        else:
            missing_taxa.append(t.key)
            items.append({
                "key": t.key,
                "name_ru": t.name_ru,
                "emoji": t.emoji,
                "raw_value": None,
                "unit": "grains/m3",
                "value_label": None,
                "danger_level": 0,
                "danger_label": overall_label(0)["label"],
                "source": None,
            })

    can_use_open_meteo = is_open_meteo_region_point(float(lat), float(lon))

    # Open-Meteo добирает только те аллергены, которых пока не хватило
    # и только там, где эта зона вообще поддерживается
    open_meteo_missing_taxa = [
        taxon_key for taxon_key in missing_taxa if taxon_key in OPEN_METEO_SUPPORTED_TAXA
    ]

    if open_meteo_missing_taxa and can_use_open_meteo:
        try:
            data = await fetch_current_pollen(lat, lon, open_meteo_missing_taxa)
            current = data.get("current") or {}
            current_units = data.get("current_units") or {}
            ts = current.get("time")
        except PollenUnavailableError:
            current = {}
            current_units = {}
            ts = datetime.now(timezone.utc).isoformat()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Open-Meteo недоступен: {e}")

        for it in items:
            if it["source"] is not None:
                continue  # это значение уже пришло из БД
            k = it["key"]
            vname = POLLEN_VAR.get(k)
            if not vname:
                continue
            raw = current.get(vname)
            unit = current_units.get(vname) or "grains/m3"
            danger_level = to_danger_level(raw, unit, taxon_key=k)
            value_label = describe_measurement(raw, unit, taxon_key=k)
            it["raw_value"] = raw
            it["unit"] = unit
            it["value_label"] = value_label
            it["danger_level"] = danger_level
            it["danger_label"] = overall_label(danger_level)["label"]
            it["source"] = "open_meteo"
            max_level = max(max_level, danger_level)
            max_measurement_rank = max(max_measurement_rank, measurement_label_rank(value_label))

    used_sources = sorted({it["source"] for it in items if it["source"]})
    has_pgniu_today = any(it["source"] == "pgniu_manual" for it in items)

    note = None
    if not has_pgniu_today:
        if can_use_open_meteo:
            note = "На сегодня нет замеров ПГНИУ для выбранной локации. Показан прогноз/модель (Open-Meteo/CAMS) или другие источники."
        else:
            note = "На сегодня нет замеров ПГНИУ для выбранной локации. Вне зоны Open-Meteo/CAMS показаны только локальные внешние источники."

    return {
        "location": {"id": loc.id, "name": loc.name, "lat": lat, "lon": lon, "kind": loc.kind},
        "time": day_start.isoformat(),
        "overall": {
            "danger_level": max_level,
            "display_label": (
                MEASUREMENT_LEVEL_LABELS[max_measurement_rank]
                if max_measurement_rank >= 0
                else "—"
            ),
            **overall_label(max_level),
        },
        "taxa": items,
        "recommendations": recommendations(max_level),
        "used_sources": used_sources,
        "note": note,
        "danger_rules": {
            "unit": "source-specific",
            "meaning": "0..3 — внутренняя сводная шкала опасности. Для концентрационных источников пороги зависят от аллергена, для индексных используются уровни источника.",
        },

    }

@router.get(
    "/timeseries",
    summary="История значений по аллергену",
    description=(
        "Возвращает историю по выбранному аллергену из БД для внутренней или внешней точки. "
        "Для произвольного города подбираются ближайшие подходящие источники."
    ),
)
def timeseries(
    location_id: int | None = Query(None, description="ID внутренней локации"),
    external_location_id: int | None = Query(None, description="ID внешней локации"),
    lat: float | None = Query(None, description="Широта для произвольной точки карты"),
    lon: float | None = Query(None, description="Долгота для произвольной точки карты"),
    place_name: str | None = Query(None, description="Подпись выбранной точки"),
    taxon_key: str = Query(..., description="Напр.: birch, grass, alder, mugwort, ragweed"),
    days: int = Query(7, ge=1, le=30, description="Сколько дней показать (1..30)"),
    end_day: date | None = Query(None, description="Последний день интервала в локальном представлении клиента"),
    db: Session = Depends(get_db),
):
    loc = None
    requested_location = None
    note = None
    anchor_day = end_day or date.today()
    internal_before_dt = datetime.combine(
        anchor_day + timedelta(days=1),
        time.min,
        tzinfo=timezone.utc,
    )
    if location_id is not None:
        loc = db.get(Location, location_id)
        if not loc:
            raise HTTPException(status_code=404, detail="Локация не найдена")
        requested_location = {
            "id": loc.id,
            "name": loc.name,
            "lat": loc.lat,
            "lon": loc.lon,
            "kind": loc.kind,
        }
        lat = float(loc.lat)
        lon = float(loc.lon)
    else:
        if external_location_id is not None and (lat is None or lon is None):
            exact_external = db.execute(
                select(
                    ExternalLocation.id,
                    ExternalLocation.name,
                    ExternalLocation.kind,
                    ExternalLocation.lat,
                    ExternalLocation.lon,
                )
                .where(ExternalLocation.id == external_location_id)
                .limit(1)
            ).first()
            if not exact_external:
                raise HTTPException(status_code=404, detail="Внешняя локация не найдена")
            lat = float(exact_external.lat)
            lon = float(exact_external.lon)
            if not place_name:
                place_name = exact_external.name
        if lat is None or lon is None:
            raise HTTPException(
                status_code=400,
                detail="Нужно указать location_id, external_location_id или lat+lon",
            )

        nearest = _find_best_internal_location_with_data(
            db,
            lat=float(lat),
            lon=float(lon),
            before_dt=internal_before_dt,
        )
        if nearest is None:
            nearest = _find_nearest_internal_location(db, lat=float(lat), lon=float(lon))
        requested_location = {
            "id": nearest.id if nearest else None,
            "name": (place_name or (nearest.name if nearest else None) or "Выбранная точка"),
            "lat": float(lat),
            "lon": float(lon),
            "kind": nearest.kind if nearest else "point",
        }
        loc = nearest
        if nearest is not None and place_name and place_name.strip() and place_name.strip() != nearest.name:
            note = f"График построен по внутренней локации: {nearest.name}."
        else:
            note = None

    taxon = db.scalar(select(PollenTaxon).where(PollenTaxon.key == taxon_key))
    if not taxon:
        raise HTTPException(status_code=400, detail="Неизвестный taxon_key")

    today = anchor_day
    start_day = today - timedelta(days=days - 1)
    start_dt = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(today + timedelta(days=1), time.min, tzinfo=timezone.utc)

    # Сначала собираем все наблюдения за нужный период
    rows = []
    if loc is not None:
        rows = db.execute(
            select(
                Observation.ts,
                Observation.value,
                Observation.unit,
                DataSource.key,
                DataSource.priority,
            )
            .join(DataSource, Observation.source_id == DataSource.id)
            .where(
                Observation.location_id == loc.id,
                Observation.taxon_id == taxon.id,
                Observation.ts >= start_dt,
                Observation.ts < end_dt,
                DataSource.key.in_(ACTIVE_PUBLIC_SOURCE_KEYS),
            )
            .order_by(Observation.ts.asc())
        ).all()

    external_targets = _pick_external_timeseries_locations(
        db,
        lat=float(lat),
        lon=float(lon),
        external_location_id=external_location_id,
        include_nearby_sources_for_selected=external_location_id is not None,
    )
    external_rows = []
    if external_targets:
        external_location_ids = [
            item["external_location_id"] for item in external_targets.values()
        ]
        external_rows = db.execute(
            select(
                ExternalObservation.ts,
                ExternalObservation.value,
                ExternalObservation.unit,
                DataSource.key,
                DataSource.priority,
            )
            .join(
                ExternalLocation,
                ExternalObservation.external_location_id == ExternalLocation.id,
            )
            .join(DataSource, ExternalLocation.source_id == DataSource.id)
            .where(
                ExternalObservation.external_location_id.in_(external_location_ids),
                ExternalObservation.taxon_id == taxon.id,
                ExternalObservation.ts >= start_dt,
                ExternalObservation.ts < end_dt,
                DataSource.key.in_(ACTIVE_PUBLIC_SOURCE_KEYS),
            )
            .order_by(ExternalObservation.ts.asc())
        ).all()

    rows = [*rows, *external_rows]

    if loc is None and not external_targets:
        note = "Для выбранного места нет ближайшей внутренней или внешней точки, поэтому история пока недоступна."
    elif loc is None and external_targets:
        external_names = ", ".join(
            sorted({item["location_name"] for item in external_targets.values()})
        )
        if external_location_id is not None:
            note = (
                f"История построена по выбранной внешней точке и ближайшим источникам: {external_names}."
                if external_names
                else "История построена по выбранной внешней точке и ближайшим источникам."
            )
        else:
            note = (
                f"История построена по ближайшим внешним точкам: {external_names}."
                if external_names
                else "История построена по ближайшим внешним точкам."
            )

    # Календарь делаем заранее, чтобы пустые дни тоже попали в график
    days_list = [(start_day + timedelta(days=i)).isoformat() for i in range(days)]

    # Тут копим точки по каждому источнику
    series_by_source: dict[str, dict[str, dict]] = {}

    # А тут держим лучший источник на каждый день
    best_by_day: dict[str, tuple[int, str, dict]] = {}

    for ts, value, unit, source_key, priority in rows:
        day_str = ts.date().isoformat()
        danger_level = to_danger_level(value, unit, taxon_key=taxon.key)
        payload = {
            "date": day_str,
            "raw_value": value,
            "unit": unit,
            "value_label": describe_measurement(value, unit, taxon_key=taxon.key),
            "danger_level": danger_level,
            "danger_label": overall_label(danger_level)["label"],
        }

        series_by_source.setdefault(source_key, {})
        series_by_source[source_key][day_str] = payload

        # На день берём источник с максимальным priority
        cur_best = best_by_day.get(day_str)
        if (cur_best is None) or (priority > cur_best[0]):
            best_by_day[day_str] = (priority, source_key, payload | {"source": source_key})

    # На выходе у каждого источника должен быть полный список дней
    series = []
    for source_key, m in series_by_source.items():
        points = [
            m.get(d)
            or {
                "date": d,
                "raw_value": None,
                "unit": None,
                "danger_level": 0,
                "danger_label": overall_label(0)["label"],
            }
            for d in days_list
        ]
        series.append({"source": source_key, "points": points})

    # Это приоритетная линия, которую потом проще всего показать как основную
    best_points = []
    for d in days_list:
        if d in best_by_day:
            best_points.append(best_by_day[d][2] | {"source": best_by_day[d][1]})
        else:
            best_points.append({
                "date": d,
                "raw_value": None,
                "unit": None,
                "danger_level": 0,
                "danger_label": overall_label(0)["label"],
                "source": None,
            })

    # Для стабильного порядка ставим manual выше, потом сайты, потом api
    priority_map = {r[3]: r[4] for r in rows}  # source_key -> priority, карта может быть неполной
    series.sort(key=lambda s: priority_map.get(s["source"], 0), reverse=True)

    return {
        "location": requested_location,
        "taxon": {"key": taxon.key, "name_ru": taxon.name_ru},
        "days": days_list,
        "series": series,
        "best": best_points,
        "note": note,
    }

@router.get(
    "/heatmap/db",
    summary="Слой карты из БД",
    description=(
        "Возвращает точки выбранного источника и аллергена из БД на указанную дату. "
        "Для каждой локации используется последнее доступное значение не позже выбранной даты."
    ),
)
def heatmap_db(
    source_key: str = Query(..., description="Напр.: pgniu_manual"),
    taxon_key: str = Query(..., description="birch/grass/alder/mugwort/ragweed"),
    day: date | None = Query(None, description="Например 2026-02-27 (если пусто — сегодня)"),
    min_lat: float | None = Query(None),
    max_lat: float | None = Query(None),
    min_lon: float | None = Query(None),
    max_lon: float | None = Query(None),
    db: Session = Depends(get_db),
):
    if source_key not in ACTIVE_PUBLIC_SOURCE_KEYS:
        raise HTTPException(status_code=404, detail="Источник недоступен в публичной карте")

    src = db.scalar(select(DataSource).where(DataSource.key == source_key))
    if not src:
        raise HTTPException(status_code=404, detail="Источник не найден (source_key)")

    taxon = db.scalar(select(PollenTaxon).where(PollenTaxon.key == taxon_key))
    if not taxon:
        raise HTTPException(status_code=400, detail="Неизвестный taxon_key")

    requested_day = day or date.today()
    rows = _heatmap_rows_for_day(
        db,
        source_id=src.id,
        taxon_id=taxon.id,
        day=requested_day,
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
    )
    if source_key != "pgniu_manual":
        rows = _external_heatmap_rows_for_day(
            db,
            source_id=src.id,
            taxon_id=taxon.id,
            day=requested_day,
            min_lat=min_lat,
            max_lat=max_lat,
            min_lon=min_lon,
            max_lon=max_lon,
        )

    points = []
    effective_day = None
    for loc_id, name, kind, lat0, lon0, observed_at, value, unit in rows:
        danger_level = to_danger_level(value, unit, taxon_key=taxon_key)
        observed_day = observed_at.date().isoformat() if observed_at else None
        if observed_day is not None and (effective_day is None or observed_day > effective_day):
            effective_day = observed_day
        points.append({
            "location": {"id": loc_id, "name": name, "kind": kind},
            "lat": lat0,
            "lon": lon0,
            "observed_at": observed_at.isoformat() if observed_at else None,
            "raw_value": value,
            "unit": unit,
            "value_label": describe_measurement(value, unit, taxon_key=taxon_key),
            "danger_level": danger_level,
            "danger_label": overall_label(danger_level)["label"],
            "source": source_key,
        })

    return {
        "day": requested_day.isoformat(),
        "effective_day": effective_day,
        "taxon_key": taxon_key,
        "source": source_key,
        "points": points,
    }
