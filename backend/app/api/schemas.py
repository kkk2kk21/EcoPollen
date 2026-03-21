from __future__ import annotations

from datetime import date, datetime
from typing import Dict, Optional

from pydantic import BaseModel, Field


class LocationRef(BaseModel):
    # Можно передать либо id существующей локации,
    # либо координаты+название для новой ловушки.
    id: Optional[int] = None
    name: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    kind: str = "trap"


class MeasurementValue(BaseModel):
    value: Optional[float] = None
    unit: Optional[str] = None  # если не указано, возьмем default_unit


class MeasurementsCreate(BaseModel):
    ts: date | datetime = Field(..., description="Дата/время замера. Можно '2026-02-27'")
    location: LocationRef
    default_unit: str = "grains/m3"
    values: Dict[str, MeasurementValue] = Field(
        ...,
        description="Словарь: ключ аллергена -> {value, unit}. Например: {'birch': {'value': 12}}",
    )


class MapCircleStyleUpdateItem(BaseModel):
    source_key: str
    base_radius_m: int = Field(..., ge=0, le=100000)
    step_radius_m: int = Field(..., ge=0, le=100000)


class MapCircleStylesUpdate(BaseModel):
    items: list[MapCircleStyleUpdateItem]


class ExternalTimeseriesDistanceSettingUpdateItem(BaseModel):
    location_kind: str
    max_distance_m: float = Field(..., ge=0, le=5_000_000)


class ExternalTimeseriesDistanceSettingsUpdate(BaseModel):
    items: list[ExternalTimeseriesDistanceSettingUpdateItem]


class TrapUpsert(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    lat: float
    lon: float
