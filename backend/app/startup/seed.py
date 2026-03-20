import os

from sqlalchemy.orm import Session
from sqlalchemy import delete, select

from ..domain.location_kinds import INTERNAL_LOCATION_KINDS
from ..services.external_timeseries_distance_settings import ensure_external_timeseries_distance_settings
from ..services.map_circle_styles import ensure_map_circle_styles
from ..domain.models import DataSource, Observation, ExternalLocation, ExternalObservation, PollenTaxon, Location, User
from ..domain.pollen_taxa_catalog import POLLEN_TAXA_CATALOG
from ..domain.pollen_sources import (
    ACTIVE_PUBLIC_SOURCES,
    DEPRECATED_POLLEN_SOURCE_KEYS,
    REMOVED_POLLEN_SOURCE_KEYS,
)
from ..core.security import hash_password

DEFAULT_ADMIN_EMAIL = os.getenv("DEFAULT_ADMIN_EMAIL", "admin@example.local").strip().lower()
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "ChangeMe123!")

def seed_if_empty(db: Session) -> None:
    # 1) Админ для теста (создаётся только если пользователей нет)
    existing_user = db.scalars(select(User)).first()
    if not existing_user:
        admin = User(
            email=DEFAULT_ADMIN_EMAIL,
            password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
            role="admin",
        )
        db.add(admin)
        db.commit()

    # 2) Источники данных: держим только живые публичные источники и ручной ввод.
    existing_sources = {
        source.key: source
        for source in db.scalars(select(DataSource)).all()
    }

    changed = False
    for source_spec in ACTIVE_PUBLIC_SOURCES:
        source = existing_sources.get(source_spec["key"])
        if source is None:
            db.add(DataSource(**source_spec))
            changed = True
            continue

        for field in ("name", "source_type", "priority", "url"):
            value = source_spec[field]
            if getattr(source, field) != value:
                setattr(source, field, value)
                changed = True

    for key in REMOVED_POLLEN_SOURCE_KEYS:
        source = existing_sources.get(key)
        if source is None:
            continue

        external_location_ids = db.scalars(
            select(ExternalLocation.id).where(ExternalLocation.source_id == source.id)
        ).all()
        if external_location_ids:
            db.execute(
                delete(ExternalObservation).where(
                    ExternalObservation.external_location_id.in_(external_location_ids)
                )
            )
            db.execute(
                delete(ExternalLocation).where(ExternalLocation.id.in_(external_location_ids))
            )

        db.execute(delete(Observation).where(Observation.source_id == source.id))
        db.delete(source)
        changed = True

    for key in DEPRECATED_POLLEN_SOURCE_KEYS:
        source = existing_sources.get(key)
        if source is None:
            continue

        has_observations = db.scalar(
            select(Observation.id)
            .where(Observation.source_id == source.id)
            .limit(1)
        )
        has_external_observations = db.scalar(
            select(ExternalObservation.id)
            .join(ExternalLocation, ExternalObservation.external_location_id == ExternalLocation.id)
            .where(ExternalLocation.source_id == source.id)
            .limit(1)
        )
        if has_observations is None and has_external_observations is None:
            db.delete(source)
            changed = True

    if changed:
        db.commit()

    ensure_map_circle_styles(db)
    ensure_external_timeseries_distance_settings(db)

    # 3) Справочник аллергенов
    existing_taxa = {
        taxon.key: taxon
        for taxon in db.scalars(select(PollenTaxon)).all()
    }
    taxa_changed = False
    for item in POLLEN_TAXA_CATALOG:
        taxon = existing_taxa.get(item["key"])
        if taxon is None:
            db.add(PollenTaxon(**item))
            taxa_changed = True
            continue

        for field in ("name_ru", "emoji", "group"):
            value = item[field]
            if getattr(taxon, field) != value:
                setattr(taxon, field, value)
                taxa_changed = True

    if taxa_changed:
        db.commit()

    # 4) Базовые локации
    existing_locations = {
        location.name: location
        for location in db.scalars(
            select(Location).where(Location.kind.in_(INTERNAL_LOCATION_KINDS))
        ).all()
    }

    legacy_city_ids = db.scalars(
        select(Location.id).where(Location.kind == "city")
    ).all()
    if legacy_city_ids:
        db.execute(delete(Observation).where(Observation.location_id.in_(legacy_city_ids)))
        db.execute(delete(Location).where(Location.id.in_(legacy_city_ids)))
        db.commit()
