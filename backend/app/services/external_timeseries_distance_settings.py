from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.models import ExternalTimeseriesDistanceSetting

EXTERNAL_TIMESERIES_DISTANCE_DEFAULTS = {
    "trap": {
        "label": "Ловушки ПГНИУ",
        "max_distance_m": 44400.0,
    },
    "open_meteo_grid": {
        "label": "Ячейки Open-Meteo / CAMS",
        "max_distance_m": 133200.0,
    },
    "station": {
        "label": "Станции Norkko и MeteoSwiss",
        "max_distance_m": 166500.0,
    },
    "region": {
        "label": "Регионы DWD",
        "max_distance_m": 388500.0,
    },
}

EXTERNAL_TIMESERIES_DISTANCE_KIND_ORDER = tuple(EXTERNAL_TIMESERIES_DISTANCE_DEFAULTS.keys())


def ensure_external_timeseries_distance_settings(db: Session) -> None:
    existing_by_kind = {
        item.location_kind: item
        for item in db.scalars(select(ExternalTimeseriesDistanceSetting)).all()
    }

    changed = False
    for kind, defaults in EXTERNAL_TIMESERIES_DISTANCE_DEFAULTS.items():
        if kind in existing_by_kind:
            continue
        db.add(
            ExternalTimeseriesDistanceSetting(
                location_kind=kind,
                max_distance_m=float(defaults["max_distance_m"]),
            )
        )
        changed = True

    if changed:
        db.commit()


def list_external_timeseries_distance_settings(
    db: Session,
) -> list[dict[str, str | float]]:
    rows = {
        item.location_kind: item
        for item in db.scalars(select(ExternalTimeseriesDistanceSetting)).all()
    }

    items = []
    for kind in EXTERNAL_TIMESERIES_DISTANCE_KIND_ORDER:
        defaults = EXTERNAL_TIMESERIES_DISTANCE_DEFAULTS[kind]
        row = rows.get(kind)
        items.append(
            {
                "location_kind": kind,
                "label": defaults["label"],
                "max_distance_m": float(
                    row.max_distance_m if row is not None else defaults["max_distance_m"]
                ),
            }
        )

    return items


def get_external_timeseries_distance_map(db: Session) -> dict[str, float]:
    return {
        item["location_kind"]: float(item["max_distance_m"])
        for item in list_external_timeseries_distance_settings(db)
    }
