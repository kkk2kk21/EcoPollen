from __future__ import annotations

import re

from sqlalchemy import delete, inspect, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ..domain.location_kinds import EXTERNAL_LOCATION_KINDS
from ..domain.models import DataSource, ExternalLocation, ExternalObservation, Location, Observation


def run_schema_migrations(engine: Engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        if "observations" not in existing_tables:
            return

        if "external_locations" in existing_tables:
            external_location_columns = {
                column["name"] for column in inspector.get_columns("external_locations")
            }
            if "native_key" not in external_location_columns:
                conn.execute(
                    text("ALTER TABLE external_locations ADD COLUMN native_key VARCHAR(255)")
                )

            conn.execute(
                text(
                    """
                    UPDATE external_locations
                    SET native_key = CONCAT('legacy:', source_id, ':', kind, ':', name)
                    WHERE native_key IS NULL
                    """
                )
            )
            conn.execute(text("ALTER TABLE external_locations ALTER COLUMN native_key SET NOT NULL"))
            conn.execute(
                text("ALTER TABLE external_locations DROP CONSTRAINT IF EXISTS uq_external_locations_source_kind_name")
            )
            conn.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM information_schema.table_constraints
                            WHERE table_schema = 'public'
                              AND table_name = 'external_locations'
                              AND constraint_name = 'uq_external_locations_source_kind_native_key'
                        ) THEN
                            ALTER TABLE external_locations
                            ADD CONSTRAINT uq_external_locations_source_kind_native_key
                            UNIQUE (source_id, kind, native_key);
                        END IF;
                    END
                    $$;
                    """
                )
            )

        observation_columns = {column["name"] for column in inspector.get_columns("observations")}
        if "external_location_id" in observation_columns:
            conn.execute(
                text(
                    """
                    INSERT INTO external_observations (external_location_id, taxon_id, ts, value, unit, created_at)
                    SELECT external_location_id, taxon_id, ts, value, unit, created_at
                    FROM observations
                    WHERE external_location_id IS NOT NULL
                    ON CONFLICT (external_location_id, taxon_id, ts) DO UPDATE
                    SET value = EXCLUDED.value,
                        unit = EXCLUDED.unit,
                        created_at = EXCLUDED.created_at
                    """
                )
            )
            conn.execute(text("DELETE FROM observations WHERE external_location_id IS NOT NULL"))

            conn.execute(text("DROP INDEX IF EXISTS ix_observations_external_location_id"))
            conn.execute(
                text("ALTER TABLE observations DROP CONSTRAINT IF EXISTS uq_obs_source_external_loc_taxon_ts")
            )
            conn.execute(
                text("ALTER TABLE observations DROP CONSTRAINT IF EXISTS ck_obs_one_location_ref")
            )
            conn.execute(
                text("ALTER TABLE observations DROP CONSTRAINT IF EXISTS fk_observations_external_location_id")
            )
            conn.execute(text("ALTER TABLE observations DROP COLUMN IF EXISTS external_location_id"))

        conn.execute(text("DELETE FROM observations WHERE location_id IS NULL"))
        conn.execute(text("ALTER TABLE observations ALTER COLUMN location_id SET NOT NULL"))

        if "external_timeseries_distance_settings" in existing_tables:
            distance_columns = {
                column["name"] for column in inspector.get_columns("external_timeseries_distance_settings")
            }
            if "max_distance_m" not in distance_columns:
                conn.execute(
                    text(
                        "ALTER TABLE external_timeseries_distance_settings ADD COLUMN max_distance_m DOUBLE PRECISION"
                    )
                )

            if "max_distance_deg" in distance_columns:
                conn.execute(
                    text(
                        """
                        UPDATE external_timeseries_distance_settings
                        SET max_distance_m = COALESCE(max_distance_m, max_distance_deg * 111000.0)
                        """
                    )
                )
                conn.execute(
                    text(
                        "ALTER TABLE external_timeseries_distance_settings DROP COLUMN IF EXISTS max_distance_deg"
                    )
                )

            conn.execute(
                text(
                    """
                    UPDATE external_timeseries_distance_settings
                    SET max_distance_m = CASE location_kind
                        WHEN 'trap' THEN 44400.0
                        WHEN 'open_meteo_grid' THEN 133200.0
                        WHEN 'station' THEN 166500.0
                        WHEN 'region' THEN 388500.0
                        ELSE max_distance_m
                    END
                    WHERE max_distance_m IS NULL
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO external_timeseries_distance_settings (location_kind, max_distance_m, created_at, updated_at)
                    SELECT 'trap', 44400.0, NOW(), NOW()
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM external_timeseries_distance_settings
                        WHERE location_kind = 'trap'
                    )
                    """
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE external_timeseries_distance_settings ALTER COLUMN max_distance_m SET NOT NULL"
                )
            )


def migrate_external_locations(db: Session) -> None:
    legacy_rows = db.execute(
        select(
            Observation.id,
            Observation.source_id,
            Observation.taxon_id,
            Observation.ts,
            Observation.value,
            Observation.unit,
            Observation.created_at,
            Location.id,
            Location.name,
            Location.lat,
            Location.lon,
            Location.kind,
        )
        .join(Location, Observation.location_id == Location.id)
        .where(Location.kind.in_(EXTERNAL_LOCATION_KINDS))
    ).all()

    external_by_key = {
        (loc.source_id, loc.kind, loc.native_key): loc
        for loc in db.scalars(select(ExternalLocation)).all()
    }

    migrated_obs_ids: list[int] = []
    for (
        obs_id,
        source_id,
        taxon_id,
        ts,
        value,
        unit,
        created_at,
        legacy_location_id,
        name,
        lat,
        lon,
        kind,
    ) in legacy_rows:
        external_key = (source_id, kind, f"legacy:{source_id}:{kind}:{legacy_location_id}")
        ext_loc = external_by_key.get(external_key)
        if ext_loc is None:
            ext_loc = ExternalLocation(
                source_id=source_id,
                native_key=external_key[2],
                name=name,
                lat=float(lat),
                lon=float(lon),
                kind=kind,
            )
            db.add(ext_loc)
            db.flush()
            external_by_key[external_key] = ext_loc

        db.execute(
            insert(ExternalObservation)
            .values(
                external_location_id=ext_loc.id,
                taxon_id=taxon_id,
                ts=ts,
                value=float(value),
                unit=unit,
                created_at=created_at,
            )
            .on_conflict_do_update(
                index_elements=["external_location_id", "taxon_id", "ts"],
                set_={
                    "value": float(value),
                    "unit": unit,
                    "created_at": created_at,
                },
            )
        )
        migrated_obs_ids.append(obs_id)

    if migrated_obs_ids:
        db.execute(delete(Observation).where(Observation.id.in_(migrated_obs_ids)))
        db.commit()

    stale_external_locations = db.scalars(
        select(Location).where(Location.kind.in_(EXTERNAL_LOCATION_KINDS))
    ).all()

    stale_ids = [loc.id for loc in stale_external_locations]
    if stale_ids:
        still_used_ids = set(
            db.scalars(
                select(Observation.location_id).where(Observation.location_id.in_(stale_ids))
            ).all()
        )
        removable_ids = [loc_id for loc_id in stale_ids if loc_id not in still_used_ids]
        if removable_ids:
            db.execute(delete(Location).where(Location.id.in_(removable_ids)))
            db.commit()

    db.execute(text("DELETE FROM observations WHERE location_id IS NULL"))
    db.commit()
    _normalize_known_external_native_keys(db)


def _normalize_known_external_native_keys(db: Session) -> None:
    changed = False
    source_by_id = {
        source.id: source.key
        for source in db.scalars(select(DataSource)).all()
    }

    for loc in db.scalars(select(ExternalLocation)).all():
        source_key = source_by_id.get(loc.source_id)
        normalized_native_key = _build_known_native_key(
            source_key=source_key,
            kind=loc.kind,
            name=loc.name,
        )
        if normalized_native_key and loc.native_key != normalized_native_key:
            loc.native_key = normalized_native_key
            changed = True

    if changed:
        db.commit()


def _build_known_native_key(
    *,
    source_key: str | None,
    kind: str,
    name: str,
) -> str | None:
    normalized_name = (name or "").strip()

    if source_key == "norkko" and kind == "station":
        city = normalized_name.split(",", 1)[0].strip().lower()
        if city:
            return f"norkko:{city}"

    if source_key == "open_meteo" and kind == "open_meteo_grid":
        match = re.search(r"#(\d+)", normalized_name)
        if match:
            return f"open-meteo-grid-{int(match.group(1)):04d}"

    return None
