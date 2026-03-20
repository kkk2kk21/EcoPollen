from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .external_pollen_sources import (
    fetch_dwd_records,
    fetch_meteoswiss_records,
    fetch_norkko_records,
)
from ..domain.models import DataSource, PollenTaxon, ExternalLocation, ExternalObservation
from .open_meteo_client import (
    MAX_POINTS_PER_REQUEST,
    POLLEN_VAR,
    PollenUnavailableError,
    fetch_current_pollen_multi,
    is_cams_europe_point,
)
from ..geo.open_meteo_region import (
    OPEN_METEO_GRID_KIND,
    OPEN_METEO_GRID_TARGET,
    generate_open_meteo_grid_points,
)
from ..domain.pollen_taxa_catalog import OPEN_METEO_SUPPORTED_TAXA

OPEN_METEO_IMPORT_BATCH_DELAY_SECONDS = float(
    os.getenv("OPEN_METEO_IMPORT_BATCH_DELAY_SECONDS", "10")
)


def get_or_create_source(
    db: Session,
    key: str,
    name: str,
    source_type: str,
    priority: int,
    url: str | None = None,
) -> DataSource:
    src = db.scalar(select(DataSource).where(DataSource.key == key))
    if src:
        src.name = name
        src.source_type = source_type
        src.priority = priority
        src.url = url
        db.commit()
        db.refresh(src)
        return src

    src = DataSource(
        key=key,
        name=name,
        source_type=source_type,
        priority=priority,
        url=url,
    )
    db.add(src)
    db.commit()
    db.refresh(src)
    return src


def get_or_create_external_location(
    db: Session,
    *,
    source: DataSource,
    native_key: str,
    name: str,
    lat: float,
    lon: float,
    kind: str,
) -> ExternalLocation:
    loc = db.scalar(
        select(ExternalLocation).where(
            ExternalLocation.source_id == source.id,
            ExternalLocation.kind == kind,
            ExternalLocation.native_key == native_key,
        )
    )
    if loc is None:
        # Мягкая миграция старых записей: если location уже существовала по имени,
        # переиспользуем её и проставляем новый source-native ключ.
        loc = db.scalar(
            select(ExternalLocation).where(
                ExternalLocation.source_id == source.id,
                ExternalLocation.kind == kind,
                ExternalLocation.name == name,
            )
        )
    if loc:
        if (
            loc.native_key != native_key
            or loc.name != name
            or loc.lat != lat
            or loc.lon != lon
        ):
            loc.native_key = native_key
            loc.name = name
            loc.lat = lat
            loc.lon = lon
            db.commit()
            db.refresh(loc)
        return loc

    loc = ExternalLocation(
        source_id=source.id,
        native_key=native_key,
        name=name,
        lat=lat,
        lon=lon,
        kind=kind,
    )
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return loc


def upsert_external_records(
    db: Session,
    *,
    source: DataSource,
    records: list[dict[str, Any]],
) -> int:
    taxa = db.scalars(select(PollenTaxon)).all()
    taxon_by_key = {taxon.key: taxon for taxon in taxa}
    location_cache: dict[tuple[str, str], ExternalLocation] = {}
    saved = 0

    for record in records:
        taxon = taxon_by_key.get(record["taxon_key"])
        if not taxon:
            continue

        location_key = (record["kind"], record["native_key"])
        loc = location_cache.get(location_key)
        if loc is None:
            loc = get_or_create_external_location(
                db,
                source=source,
                native_key=record["native_key"],
                name=record["location_name"],
                lat=float(record["lat"]),
                lon=float(record["lon"]),
                kind=record["kind"],
            )
            location_cache[location_key] = loc

        ts0 = datetime.combine(record["day"], time.min, tzinfo=timezone.utc)
        stmt = insert(ExternalObservation).values(
            external_location_id=loc.id,
            taxon_id=taxon.id,
            ts=ts0,
            value=float(record["value"]),
            unit=str(record["unit"]),
            created_at=datetime.utcnow(),
        ).on_conflict_do_update(
            index_elements=["external_location_id", "taxon_id", "ts"],
            set_={
                "value": float(record["value"]),
                "unit": str(record["unit"]),
                "created_at": datetime.utcnow(),
            },
        )
        db.execute(stmt)
        saved += 1

    db.commit()
    return saved


def ensure_open_meteo_grid_locations(db: Session, source: DataSource) -> list[ExternalLocation]:
    specs = generate_open_meteo_grid_points()
    expected_native_keys = {str(spec["native_key"]) for spec in specs}
    existing = db.scalars(
        select(ExternalLocation)
        .where(
            ExternalLocation.source_id == source.id,
            ExternalLocation.kind == OPEN_METEO_GRID_KIND,
        )
        .order_by(ExternalLocation.id.asc())
    ).all()

    by_native_key: dict[str, ExternalLocation] = {}
    stale_location_ids: list[int] = []
    changed = False

    for loc in existing:
        if loc.native_key not in expected_native_keys:
            stale_location_ids.append(loc.id)
            continue
        if loc.native_key in by_native_key:
            stale_location_ids.append(loc.id)
            continue
        by_native_key[loc.native_key] = loc

    if stale_location_ids:
        db.execute(delete(ExternalObservation).where(ExternalObservation.external_location_id.in_(stale_location_ids)))
        db.execute(delete(ExternalLocation).where(ExternalLocation.id.in_(stale_location_ids)))
        changed = True

    for spec in specs:
        native_key = str(spec["native_key"])
        loc = by_native_key.get(native_key)
        if loc is None:
            db.add(
                ExternalLocation(
                    source_id=source.id,
                    native_key=native_key,
                    name=spec["name"],
                    lat=float(spec["lat"]),
                    lon=float(spec["lon"]),
                    kind=OPEN_METEO_GRID_KIND,
                )
            )
            changed = True
            continue

        if (
            loc.native_key != native_key
            or loc.name != spec["name"]
            or
            float(loc.lat) != float(spec["lat"])
            or float(loc.lon) != float(spec["lon"])
            or loc.kind != OPEN_METEO_GRID_KIND
        ):
            loc.native_key = native_key
            loc.name = str(spec["name"])
            loc.lat = float(spec["lat"])
            loc.lon = float(spec["lon"])
            loc.kind = OPEN_METEO_GRID_KIND
            changed = True

    if changed:
        db.commit()

    refreshed = db.scalars(
        select(ExternalLocation)
        .where(
            ExternalLocation.source_id == source.id,
            ExternalLocation.kind == OPEN_METEO_GRID_KIND,
            ExternalLocation.native_key.in_([str(spec["native_key"]) for spec in specs]),
        )
        .order_by(ExternalLocation.id.asc())
    ).all()
    refreshed_by_native_key = {loc.native_key: loc for loc in refreshed}

    ordered = [refreshed_by_native_key[str(spec["native_key"])] for spec in specs]
    if len(ordered) != OPEN_METEO_GRID_TARGET:
        raise RuntimeError(
            f"Ожидалось {OPEN_METEO_GRID_TARGET} grid-локаций Open-Meteo, получено {len(ordered)}"
        )
    return ordered


async def import_open_meteo_snapshot(
    db: Session,
    day: date | None = None,
) -> dict[str, Any]:
    d = day or datetime.now(timezone.utc).date()
    ts0 = datetime.combine(d, time.min, tzinfo=timezone.utc)
    day_end = ts0 + timedelta(days=1)

    src = get_or_create_source(
        db,
        key="open_meteo",
        name="Open-Meteo / CAMS Europe",
        source_type="api",
        priority=90,
        url="https://open-meteo.com/",
    )

    taxa = db.scalars(select(PollenTaxon)).all()
    taxon_by_key = {taxon.key: taxon for taxon in taxa}
    taxa_keys = [taxon.key for taxon in taxa if taxon.key in OPEN_METEO_SUPPORTED_TAXA]
    supported_taxon_ids = [taxon_by_key[key].id for key in taxa_keys]

    locs = ensure_open_meteo_grid_locations(db, src)
    location_ids = [loc.id for loc in locs]

    complete_rows = db.execute(
        select(
            ExternalObservation.external_location_id,
            func.count(func.distinct(ExternalObservation.taxon_id)).label("taxa_count"),
        )
        .where(
            ExternalObservation.external_location_id.in_(location_ids),
            ExternalObservation.taxon_id.in_(supported_taxon_ids),
            ExternalObservation.ts >= ts0,
            ExternalObservation.ts < day_end,
        )
        .group_by(ExternalObservation.external_location_id)
    ).all()
    required_taxa_count = len(taxa_keys)
    complete_location_ids = {
        location_id
        for location_id, taxa_count in complete_rows
        if int(taxa_count or 0) >= required_taxa_count
    }

    pending_locs = [loc for loc in locs if loc.id not in complete_location_ids]
    skipped = len(complete_location_ids)

    if not pending_locs:
        return {
            "status": "ok",
            "day": d.isoformat(),
            "saved": 0,
            "source": src.key,
            "locations_total": len(locs),
            "locations_loaded": 0,
            "locations_skipped": skipped,
            "batch_delay_seconds": OPEN_METEO_IMPORT_BATCH_DELAY_SECONDS,
            "note": "Дневной импорт Open-Meteo уже полностью загружен",
        }

    supported_locs = [
        loc for loc in pending_locs if is_cams_europe_point(float(loc.lat), float(loc.lon))
    ]
    unsupported_locs = [
        loc for loc in pending_locs if not is_cams_europe_point(float(loc.lat), float(loc.lon))
    ]

    note_parts: list[str] = []
    batch_error: str | None = None

    saved = 0

    def upsert_open_meteo_rows(batch_locs: list[ExternalLocation], batch_rows: list[dict[str, Any]]) -> int:
        batch_saved = 0
        for index, loc in enumerate(batch_locs):
            row = batch_rows[index] if index < len(batch_rows) else {}
            cur = row.get("current") or {}
            units = row.get("current_units") or {}

            for taxon_key in taxa_keys:
                variable_name = POLLEN_VAR[taxon_key]
                raw = cur.get(variable_name)
                unit = units.get(variable_name) or "grains/m3"
                value = 0 if raw is None else float(raw)

                stmt = insert(ExternalObservation).values(
                    external_location_id=loc.id,
                    taxon_id=taxon_by_key[taxon_key].id,
                    ts=ts0,
                    value=value,
                    unit=str(unit),
                    created_at=datetime.utcnow(),
                ).on_conflict_do_update(
                    index_elements=["external_location_id", "taxon_id", "ts"],
                    set_={
                        "value": value,
                        "unit": str(unit),
                        "created_at": datetime.utcnow(),
                    },
                )
                db.execute(stmt)
                batch_saved += 1
        db.commit()
        return batch_saved

    if supported_locs:
        total_batches = (len(supported_locs) + MAX_POINTS_PER_REQUEST - 1) // MAX_POINTS_PER_REQUEST
        season_note_added = False
        for start in range(0, len(supported_locs), MAX_POINTS_PER_REQUEST):
            batch_locs = supported_locs[start : start + MAX_POINTS_PER_REQUEST]
            batch_index = start // MAX_POINTS_PER_REQUEST + 1
            try:
                rows = await fetch_current_pollen_multi(
                    [float(loc.lat) for loc in batch_locs],
                    [float(loc.lon) for loc in batch_locs],
                    taxa_keys,
                    chunk_delay_seconds=0,
                )
            except PollenUnavailableError:
                rows = [{"current": {}, "current_units": {}} for _ in batch_locs]
                if not season_note_added:
                    note_parts.append(
                        "Open-Meteo: пыльца недоступна вне сезона, для поддерживаемой зоны сохранены нулевые значения"
                    )
                    season_note_added = True
            except Exception as exc:
                batch_error = str(exc)
                note_parts.append(
                    f"Open-Meteo: импорт остановлен на батче {batch_index} из {total_batches}. Уже загруженные точки сохранены, недостающие будут дозалиты следующим циклом."
                )
                break

            saved += upsert_open_meteo_rows(batch_locs, rows)

            has_more_batches = start + MAX_POINTS_PER_REQUEST < len(supported_locs)
            if has_more_batches and OPEN_METEO_IMPORT_BATCH_DELAY_SECONDS > 0:
                await asyncio.sleep(OPEN_METEO_IMPORT_BATCH_DELAY_SECONDS)

    if unsupported_locs:
        note_parts.append(
            f"Вне зоны CAMS Europe сохранены нули для {len(unsupported_locs)} точек"
        )
        saved += upsert_open_meteo_rows(
            unsupported_locs,
            [{"current": {}, "current_units": {}} for _ in unsupported_locs],
        )

    return {
        "status": "partial" if batch_error else "ok",
        "day": d.isoformat(),
        "saved": saved,
        "source": src.key,
        "locations_total": len(locs),
        "locations_loaded": saved // required_taxa_count if required_taxa_count else 0,
        "locations_skipped": skipped,
        "batch_delay_seconds": OPEN_METEO_IMPORT_BATCH_DELAY_SECONDS,
        "note": " ".join(note_parts) if note_parts else None,
    }


async def import_norkko_snapshot(
    db: Session,
    day: date | None = None,
) -> dict[str, Any]:
    source = get_or_create_source(
        db,
        key="norkko",
        name="Norkko / University of Turku",
        source_type="scrape",
        priority=82,
        url="https://norkko.fi/",
    )

    bulletin_day, records, note = await fetch_norkko_records(day)
    if not records:
        return {
            "status": "ok",
            "day": (day or bulletin_day).isoformat(),
            "saved": 0,
            "source": source.key,
            "note": note,
        }

    saved = upsert_external_records(db, source=source, records=records)
    return {
        "status": "ok",
        "day": records[0]["day"].isoformat(),
        "saved": saved,
        "source": source.key,
        "note": note,
    }


async def import_meteoswiss_snapshot(
    db: Session,
    day: date | None = None,
) -> dict[str, Any]:
    source = get_or_create_source(
        db,
        key="meteoswiss",
        name="MeteoSwiss Open Data",
        source_type="api",
        priority=88,
        url="https://www.meteoswiss.admin.ch/services-and-publications/service/open-data.html",
    )

    imported_day, records, note = await fetch_meteoswiss_records(day)
    if not records:
        return {
            "status": "ok",
            "day": day.isoformat() if day else None,
            "saved": 0,
            "source": source.key,
            "note": note,
        }

    saved = upsert_external_records(db, source=source, records=records)
    return {
        "status": "ok",
        "day": (day or imported_day).isoformat() if (day or imported_day) else None,
        "saved": saved,
        "source": source.key,
        "locations": len({record["location_name"] for record in records}),
        "note": note,
    }


async def import_dwd_snapshot(
    db: Session,
    day: date | None = None,
) -> dict[str, Any]:
    source = get_or_create_source(
        db,
        key="dwd",
        name="DWD Pollenflug-Gefahrenindex",
        source_type="api",
        priority=76,
        url="https://opendata.dwd.de/climate_environment/health/alerts/s31fg.json",
    )

    base_day, records, note = await fetch_dwd_records(day)
    if not records:
        return {
            "status": "ok",
            "day": (day or base_day).isoformat(),
            "saved": 0,
            "source": source.key,
            "note": note,
        }

    saved = upsert_external_records(db, source=source, records=records)
    return {
        "status": "ok",
        "day": records[0]["day"].isoformat(),
        "saved": saved,
        "source": source.key,
        "locations": len({record["location_name"] for record in records}),
        "note": note,
    }


async def import_all_external_sources(db: Session) -> list[dict[str, Any]]:
    return [
        await import_norkko_snapshot(db),
        await import_meteoswiss_snapshot(db),
        await import_dwd_snapshot(db),
        await import_open_meteo_snapshot(db),
    ]


async def backfill_available_history(
    db: Session,
    *,
    days: int = 7,
) -> dict[str, Any]:
    today = datetime.now(timezone.utc).date()
    meteoswiss_results: list[dict[str, Any]] = []

    for offset in range(days - 1, -1, -1):
        target_day = today - timedelta(days=offset)
        result = await import_meteoswiss_snapshot(db, target_day)
        meteoswiss_results.append(result)

    current_results = [
        await import_norkko_snapshot(db),
        await import_dwd_snapshot(db),
        await import_open_meteo_snapshot(db),
    ]

    return {
        "status": "ok",
        "days_requested": days,
        "range": {
            "from": (today - timedelta(days=days - 1)).isoformat(),
            "to": today.isoformat(),
        },
        "meteoswiss_backfill": meteoswiss_results,
        "current_snapshots": current_results,
        "note": (
            "MeteoSwiss backfill выполнен за доступные последние дни. "
            "Norkko, DWD и Open-Meteo добраны только по текущему доступному срезу, "
            "потому что их текущие публичные feed'ы не дают полную прошлую неделю."
        ),
    }
