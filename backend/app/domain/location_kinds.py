INTERNAL_LOCATION_KINDS = ("trap", "custom")
EXTERNAL_LOCATION_KINDS = ("station", "region", "open_meteo_grid")


def is_internal_location_kind(kind: str | None) -> bool:
    return (kind or "").strip().lower() in INTERNAL_LOCATION_KINDS


def is_external_location_kind(kind: str | None) -> bool:
    return (kind or "").strip().lower() in EXTERNAL_LOCATION_KINDS
