from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    String, Integer, Float, DateTime, ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..core.db import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="student")  # student/scientist/admin
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)  # open_meteo, pgniu_manual
    name: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(30))  # api/scrape/manual
    priority: Mapped[int] = mapped_column(Integer, default=10)  # больше = важнее
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)


class MapCircleStyle(Base):
    __tablename__ = "map_circle_styles"
    __table_args__ = (
        UniqueConstraint("source_id", name="uq_map_circle_styles_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    base_radius_m: Mapped[int] = mapped_column(Integer)
    step_radius_m: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    source: Mapped[DataSource] = relationship()


class ExternalTimeseriesDistanceSetting(Base):
    __tablename__ = "external_timeseries_distance_settings"
    __table_args__ = (
        UniqueConstraint("location_kind", name="uq_external_timeseries_distance_settings_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_kind: Mapped[str] = mapped_column(String(30), index=True)
    max_distance_m: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    kind: Mapped[str] = mapped_column(String(30), default="custom")  # trap/custom


class ExternalLocation(Base):
    __tablename__ = "external_locations"
    __table_args__ = (
        UniqueConstraint("source_id", "kind", "native_key", name="uq_external_locations_source_kind_native_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    native_key: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    kind: Mapped[str] = mapped_column(String(30), default="station")  # station/region/open_meteo_grid

    source: Mapped[DataSource] = relationship()

class PollenTaxon(Base):
    __tablename__ = "pollen_taxa"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)  # birch, grass, mugwort...
    name_ru: Mapped[str] = mapped_column(String(255))
    emoji: Mapped[str | None] = mapped_column(String(10), nullable=True)
    group: Mapped[str] = mapped_column(String(30), default="other")  # tree/grass/weed/other

class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (
        UniqueConstraint("source_id", "location_id", "taxon_id", "ts", name="uq_obs_source_loc_taxon_ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), index=True)
    taxon_id: Mapped[int] = mapped_column(ForeignKey("pollen_taxa.id"), index=True)

    ts: Mapped[datetime] = mapped_column(DateTime, index=True)  # время (для MVP можно "день")
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(50), default="unknown")  # grains/m3, pollen/m3, index_0_3, danger_0_3
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    source: Mapped[DataSource] = relationship()
    location: Mapped[Location] = relationship()
    taxon: Mapped[PollenTaxon] = relationship()


class ExternalObservation(Base):
    __tablename__ = "external_observations"
    __table_args__ = (
        UniqueConstraint("external_location_id", "taxon_id", "ts", name="uq_external_obs_loc_taxon_ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_location_id: Mapped[int] = mapped_column(ForeignKey("external_locations.id"), index=True)
    taxon_id: Mapped[int] = mapped_column(ForeignKey("pollen_taxa.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(50), default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    external_location: Mapped[ExternalLocation] = relationship()
    taxon: Mapped[PollenTaxon] = relationship()
