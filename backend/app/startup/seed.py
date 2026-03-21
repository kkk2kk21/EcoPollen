import os

from sqlalchemy.orm import Session
from sqlalchemy import select

from ..services.external_timeseries_distance_settings import ensure_external_timeseries_distance_settings
from ..services.map_circle_styles import ensure_map_circle_styles
from ..domain.models import DataSource, PollenTaxon, User
from ..domain.pollen_taxa_catalog import POLLEN_TAXA_CATALOG
from ..domain.pollen_sources import ACTIVE_PUBLIC_SOURCES
from ..core.security import hash_password

DEFAULT_ADMIN_EMAIL = os.getenv("DEFAULT_ADMIN_EMAIL", "admin@example.local").strip().lower()
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "ChangeMe123!")
TAXON_MODEL_FIELDS = ("key", "name_ru", "emoji", "group")


def _taxon_model_payload(item: dict) -> dict:
    return {field: item[field] for field in TAXON_MODEL_FIELDS if field in item}


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

    # 2) Источники данных
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
            db.add(PollenTaxon(**_taxon_model_payload(item)))
            taxa_changed = True
            continue

        for field in ("name_ru", "emoji", "group"):
            value = item[field]
            if getattr(taxon, field) != value:
                setattr(taxon, field, value)
                taxa_changed = True

    if taxa_changed:
        db.commit()
