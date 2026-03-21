from __future__ import annotations

from datetime import datetime, date, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from ...core.db import get_db
from ...services.map_circle_styles import (
    MAP_CIRCLE_STYLE_SOURCE_KEYS,
    list_map_circle_styles,
)
from ...services.external_timeseries_distance_settings import (
    EXTERNAL_TIMESERIES_DISTANCE_KIND_ORDER,
    list_external_timeseries_distance_settings,
)
from ...domain.models import (
    DataSource,
    ExternalTimeseriesDistanceSetting,
    Location,
    MapCircleStyle,
    Observation,
    PollenTaxon,
)
from ..schemas import (
    ExternalTimeseriesDistanceSettingsUpdate,
    MapCircleStylesUpdate,
    MeasurementsCreate,
    TrapUpsert,
)
from .auth import require_roles

router = APIRouter(prefix="/science", tags=["science"])


def _day_start_utc(ts: date | datetime) -> datetime:
    if isinstance(ts, datetime):
        d = ts.date()
    else:
        d = ts
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def _get_or_create_source(db: Session, key: str, name: str, source_type: str, priority: int) -> DataSource:
    src = db.scalar(select(DataSource).where(DataSource.key == key))
    if src:
        return src
    src = DataSource(key=key, name=name, source_type=source_type, priority=priority)
    db.add(src)
    db.commit()
    db.refresh(src)
    return src


def _get_or_create_location(db: Session, loc_in) -> Location:
    # Если пришёл id, просто берём готовую локацию
    if loc_in.id is not None:
        loc = db.get(Location, loc_in.id)
        if not loc:
            raise HTTPException(status_code=404, detail="Локация (location.id) не найдена")
        return loc

    # Если id нет, ждём координаты
    if loc_in.lat is None or loc_in.lon is None:
        raise HTTPException(status_code=400, detail="Нужно либо location.id, либо location.lat+location.lon")

    name = (loc_in.name or f"Ловушка {loc_in.lat:.4f},{loc_in.lon:.4f}").strip()
    kind = (loc_in.kind or "trap").strip().lower()
    if kind != "trap":
        raise HTTPException(status_code=400, detail="kind должен быть: trap")

    existing_by_name = db.scalar(select(Location).where(Location.kind == "trap", Location.name == name))
    if existing_by_name:
        return existing_by_name

    loc = Location(name=name, lat=float(loc_in.lat), lon=float(loc_in.lon), kind="trap")
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return loc


def _get_source_by_key(db: Session, source_key: str) -> DataSource:
    source = db.scalar(select(DataSource).where(DataSource.key == source_key))
    if source is None:
        raise HTTPException(status_code=404, detail=f"Источник {source_key} не найден")
    return source


def _serialize_location(loc: Location) -> dict:
    return {
        "id": loc.id,
        "name": loc.name,
        "lat": loc.lat,
        "lon": loc.lon,
        "kind": loc.kind,
    }


def _get_trap_or_404(db: Session, trap_id: int) -> Location:
    trap = db.scalar(select(Location).where(Location.id == trap_id, Location.kind == "trap"))
    if trap is None:
        raise HTTPException(status_code=404, detail="Ловушка не найдена")
    return trap


def _ensure_trap_name_available(db: Session, name: str, exclude_id: int | None = None) -> None:
    q = select(Location).where(Location.kind == "trap", Location.name == name)
    if exclude_id is not None:
        q = q.where(Location.id != exclude_id)
    existing = db.scalar(q)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Ловушка с таким названием уже существует")


@router.post("/traps", summary="Создать ловушку")
def create_trap(
    payload: TrapUpsert,
    db: Session = Depends(get_db),
    _=Depends(require_roles("scientist", "admin")),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Название ловушки не должно быть пустым")

    _ensure_trap_name_available(db, name)

    trap = Location(
        name=name,
        lat=float(payload.lat),
        lon=float(payload.lon),
        kind="trap",
    )
    db.add(trap)
    db.commit()
    db.refresh(trap)

    return {"status": "ok", "location": _serialize_location(trap)}


@router.put("/traps/{trap_id}", summary="Обновить ловушку")
def update_trap(
    trap_id: int,
    payload: TrapUpsert,
    db: Session = Depends(get_db),
    _=Depends(require_roles("scientist", "admin")),
):
    trap = _get_trap_or_404(db, trap_id)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Название ловушки не должно быть пустым")

    _ensure_trap_name_available(db, name, exclude_id=trap.id)

    trap.name = name
    trap.lat = float(payload.lat)
    trap.lon = float(payload.lon)
    db.commit()
    db.refresh(trap)

    return {"status": "ok", "location": _serialize_location(trap)}


@router.delete("/traps/{trap_id}", summary="Удалить ловушку")
def delete_trap(
    trap_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_roles("scientist", "admin")),
):
    trap = _get_trap_or_404(db, trap_id)

    deleted_measurements = db.query(Observation).filter(Observation.location_id == trap.id).count()
    db.execute(delete(Observation).where(Observation.location_id == trap.id))
    db.delete(trap)
    db.commit()

    return {
        "status": "deleted",
        "location": _serialize_location(trap),
        "deleted_measurements": deleted_measurements,
    }


@router.post(
    "/measurements",
    summary="Сохранить ручные замеры",
    description="Сохраняет набор значений по аллергенам для выбранной ловушки и даты.",
)
def create_measurements(
    payload: MeasurementsCreate,
    db: Session = Depends(get_db),
    _=Depends(require_roles("scientist", "admin")),
):
    source = _get_or_create_source(
        db,
        key="pgniu_manual",
        name="Замеры ПГНИУ",
        source_type="manual",
        priority=100,
    )

    loc = _get_or_create_location(db, payload.location)
    ts0 = _day_start_utc(payload.ts)

    # Справочник аллергенов держим под рукой, чтобы сразу валидировать ключи
    taxa = db.scalars(select(PollenTaxon)).all()
    taxon_by_key = {t.key: t for t in taxa}

    created = []

    for taxon_key, mv in payload.values.items():
        taxon_key = (taxon_key or "").strip()
        if taxon_key not in taxon_by_key:
            raise HTTPException(status_code=400, detail=f"Неизвестный аллерген: {taxon_key}")

        if mv.value is None:
            continue  # пустые значения просто пропускаем

        unit = (mv.unit or payload.default_unit or "grains/m3").strip().lower()
        taxon = taxon_by_key[taxon_key]

        # Если запись на этот день уже есть, просто аккуратно обновляем её
        stmt = insert(Observation).values(
            source_id=source.id,
            location_id=loc.id,
            taxon_id=taxon.id,
            ts=ts0,
            value=float(mv.value),
            unit=unit,
            created_at=datetime.utcnow(),
        ).on_conflict_do_update(
            index_elements=["source_id", "location_id", "taxon_id", "ts"],
            set_={
                "value": float(mv.value),
                "unit": unit,
                "created_at": datetime.utcnow(),
            },
        )
        db.execute(stmt)
        created.append({"taxon_key": taxon_key, "value": float(mv.value), "unit": unit})

    db.commit()

    return {
        "status": "ok",
        "source": source.key,
        "location": _serialize_location(loc),
        "ts": ts0.isoformat(),
        "saved": created,
    }


@router.get("/map-circle-styles", summary="Получить настройки радиусов")
def get_map_circle_styles(
    db: Session = Depends(get_db),
    _=Depends(require_roles("scientist", "admin")),
):
    return list_map_circle_styles(db)


@router.put("/map-circle-styles", summary="Обновить настройки радиусов")
def update_map_circle_styles(
    payload: MapCircleStylesUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_roles("scientist", "admin")),
):
    updated = []

    for item in payload.items:
        source_key = (item.source_key or "").strip()
        if source_key not in MAP_CIRCLE_STYLE_SOURCE_KEYS:
            continue

        source = _get_source_by_key(db, source_key)
        style = db.scalar(select(MapCircleStyle).where(MapCircleStyle.source_id == source.id))
        if style is None:
            style = MapCircleStyle(
                source_id=source.id,
                base_radius_m=int(item.base_radius_m),
                step_radius_m=int(item.step_radius_m),
            )
            db.add(style)
        else:
            style.base_radius_m = int(item.base_radius_m)
            style.step_radius_m = int(item.step_radius_m)

        updated.append(source_key)

    db.commit()

    return {
        "status": "ok",
        "updated": updated,
        "items": list_map_circle_styles(db),
    }


@router.get("/timeseries-distance-settings", summary="Получить пороги близости источников")
def get_timeseries_distance_settings(
    db: Session = Depends(get_db),
    _=Depends(require_roles("scientist", "admin")),
):
    return list_external_timeseries_distance_settings(db)


@router.put("/timeseries-distance-settings", summary="Обновить пороги близости источников")
def update_timeseries_distance_settings(
    payload: ExternalTimeseriesDistanceSettingsUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_roles("scientist", "admin")),
):
    updated = []

    for item in payload.items:
        location_kind = (item.location_kind or "").strip()
        if location_kind not in EXTERNAL_TIMESERIES_DISTANCE_KIND_ORDER:
            continue

        setting = db.scalar(
            select(ExternalTimeseriesDistanceSetting).where(
                ExternalTimeseriesDistanceSetting.location_kind == location_kind
            )
        )
        if setting is None:
            setting = ExternalTimeseriesDistanceSetting(
                location_kind=location_kind,
                max_distance_m=float(item.max_distance_m),
            )
            db.add(setting)
        else:
            setting.max_distance_m = float(item.max_distance_m)

        updated.append(location_kind)

    db.commit()

    return {
        "status": "ok",
        "updated": updated,
        "items": list_external_timeseries_distance_settings(db),
    }


@router.get(
    "/measurements",
    summary="История ручных замеров",
    description="Возвращает сохранённые ручные замеры с фильтрами по ловушке и дате.",
)
def list_measurements(
    location_id: int | None = Query(None),
    day: date | None = Query(None, description="Например 2026-02-27"),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    _=Depends(require_roles("scientist", "admin")),
):
    q = (
        select(Observation.id, Observation.ts, Observation.value, Observation.unit,
               Location.id, Location.name, Location.lat, Location.lon, Location.kind,
               PollenTaxon.key, PollenTaxon.name_ru,
               DataSource.key)
        .join(Location, Observation.location_id == Location.id)
        .join(PollenTaxon, Observation.taxon_id == PollenTaxon.id)
        .join(DataSource, Observation.source_id == DataSource.id)
        .order_by(Observation.ts.desc(), Observation.id.desc())
    )

    if location_id is not None:
        q = q.where(Location.id == location_id)

    if day is not None:
        start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        q = q.where(Observation.ts >= start, Observation.ts < end)

    rows = db.execute(q.limit(limit)).all()

    out = []
    for r in rows:
        out.append({
            "id": r[0],
            "ts": r[1].isoformat(),
            "value": r[2],
            "unit": r[3],
            "location": {"id": r[4], "name": r[5], "lat": r[6], "lon": r[7], "kind": r[8]},
            "taxon": {"key": r[9], "name_ru": r[10]},
            "source": r[11],
        })
    return out


@router.delete("/measurements/{obs_id}", summary="Удалить замер")
def delete_measurement(
    obs_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_roles("scientist", "admin")),
):
    obs = db.get(Observation, obs_id)
    if not obs:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    db.delete(obs)
    db.commit()
    return {"status": "deleted", "id": obs_id}
