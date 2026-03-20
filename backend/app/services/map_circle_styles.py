from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.models import DataSource, MapCircleStyle

MAP_CIRCLE_STYLE_DEFAULTS = {
    "pgniu_manual": {"base_radius_m": 5000, "step_radius_m": 3300},
    "norkko": {"base_radius_m": 5200, "step_radius_m": 2735},
    "meteoswiss": {"base_radius_m": 4800, "step_radius_m": 2535},
    "dwd": {"base_radius_m": 9000, "step_radius_m": 4335},
}

MAP_CIRCLE_STYLE_FALLBACK = {
    "base_radius_m": 1200,
    "step_radius_m": 1065,
}

MAP_CIRCLE_STYLE_SOURCE_KEYS = tuple(MAP_CIRCLE_STYLE_DEFAULTS.keys())


def ensure_map_circle_styles(db: Session) -> None:
    source_by_key = {
        source.key: source
        for source in db.scalars(
            select(DataSource).where(DataSource.key.in_(MAP_CIRCLE_STYLE_SOURCE_KEYS))
        ).all()
    }
    existing_by_source_id = {
        style.source_id: style
        for style in db.scalars(select(MapCircleStyle)).all()
    }

    changed = False
    for source_key, defaults in MAP_CIRCLE_STYLE_DEFAULTS.items():
        source = source_by_key.get(source_key)
        if source is None:
            continue

        if source.id in existing_by_source_id:
            continue

        db.add(
            MapCircleStyle(
                source_id=source.id,
                base_radius_m=int(defaults["base_radius_m"]),
                step_radius_m=int(defaults["step_radius_m"]),
            )
        )
        changed = True

    if changed:
        db.commit()


def list_map_circle_styles(db: Session) -> list[dict[str, int | str | bool]]:
    rows = db.execute(
        select(
            DataSource.key,
            DataSource.name,
            DataSource.priority,
            MapCircleStyle.base_radius_m,
            MapCircleStyle.step_radius_m,
        )
        .join(MapCircleStyle, MapCircleStyle.source_id == DataSource.id, isouter=True)
        .where(DataSource.key.in_(MAP_CIRCLE_STYLE_SOURCE_KEYS))
        .order_by(DataSource.priority.desc(), DataSource.name.asc())
    ).all()

    items = []
    for source_key, source_name, _priority, base_radius_m, step_radius_m in rows:
        defaults = MAP_CIRCLE_STYLE_DEFAULTS[source_key]
        items.append(
            {
                "source_key": source_key,
                "source_name": source_name,
                "base_radius_m": int(base_radius_m or defaults["base_radius_m"]),
                "step_radius_m": int(step_radius_m or defaults["step_radius_m"]),
                "is_fallback": False,
            }
        )

    items.append(
        {
            "source_key": "default",
            "source_name": "Другие источники",
            "base_radius_m": int(MAP_CIRCLE_STYLE_FALLBACK["base_radius_m"]),
            "step_radius_m": int(MAP_CIRCLE_STYLE_FALLBACK["step_radius_m"]),
            "is_fallback": True,
        }
    )

    return items
