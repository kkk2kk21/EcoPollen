from __future__ import annotations

from .pollen_taxa_catalog import (
    DEFAULT_CONCENTRATION_THRESHOLDS,
    POLLEN_TAXA_BY_KEY,
)

INDEX_EPSILON = 1e-9

MEASUREMENT_LEVEL_LABELS = (
    "Опасности нет",
    "Очень низкий",
    "Низкий",
    "Ощутимый",
    "Умеренный",
    "Значительный",
    "Высокий",
)
MEASUREMENT_LEVEL_RANKS = {
    label: index for index, label in enumerate(MEASUREMENT_LEVEL_LABELS)
}

DANGER_LEVEL_THRESHOLDS = [1, 10, 50]


def concentration_thresholds_for_taxon(taxon_key: str | None) -> tuple[float, ...]:
    if not taxon_key:
        return DEFAULT_CONCENTRATION_THRESHOLDS
    item = POLLEN_TAXA_BY_KEY.get(str(taxon_key).lower())
    if not item:
        return DEFAULT_CONCENTRATION_THRESHOLDS
    return tuple(item.get("concentration_thresholds") or DEFAULT_CONCENTRATION_THRESHOLDS)


def clamp_0_3(x: float) -> int:
    if x is None:
        return 0
    if x < 0:
        return 0
    if x > 3:
        return 3
    return int(round(x))


def grains_m3_to_danger_level(value: float | None, taxon_key: str | None = None) -> int:
    if value is None:
        return 0
    numeric = float(value)
    if numeric <= 0:
        return 0
    thresholds = concentration_thresholds_for_taxon(taxon_key)
    if numeric < thresholds[0]:
        return 1
    if numeric < thresholds[1]:
        return 1
    if numeric < thresholds[3]:
        return 2
    return 3


def to_danger_level(value: float | None, unit: str, taxon_key: str | None = None) -> int:
    unit = (unit or "unknown").lower().strip()

    if unit in ("danger_0_3", "score_0_3", "index_0_3", "level_0_3"):
        return clamp_0_3(0 if value is None else float(value))

    if unit in ("grains/m3", "grains/m³", "pollen/m3", "pollen/m³"):
        return grains_m3_to_danger_level(value, taxon_key=taxon_key)

    return 0


def describe_measurement(value: float | None, unit: str, taxon_key: str | None = None) -> str | None:
    unit = (unit or "unknown").lower().strip()

    if unit in ("danger_0_3", "score_0_3", "index_0_3", "level_0_3"):
        return describe_index_0_3(value)

    if unit in ("grains/m3", "grains/m³", "pollen/m3", "pollen/m³"):
        return describe_concentration_level(value, taxon_key=taxon_key)

    return None


def describe_index_0_3(value: float | None) -> str | None:
    if value is None:
        return None

    numeric = float(value)
    if numeric <= 0 + INDEX_EPSILON:
        return "Опасности нет"
    if numeric < 1 - INDEX_EPSILON:
        return "Очень низкий"
    if abs(numeric - 1) <= INDEX_EPSILON:
        return "Низкий"
    if numeric < 2 - INDEX_EPSILON:
        return "Ощутимый"
    if abs(numeric - 2) <= INDEX_EPSILON:
        return "Умеренный"
    if numeric < 3 - INDEX_EPSILON:
        return "Значительный"
    return "Высокий"


def describe_concentration_level(
    value: float | None,
    taxon_key: str | None = None,
) -> str | None:
    if value is None:
        return None

    numeric = float(value)
    if numeric <= 0:
        return MEASUREMENT_LEVEL_LABELS[0]
    thresholds = concentration_thresholds_for_taxon(taxon_key)
    for index, threshold in enumerate(thresholds):
        if numeric < threshold:
            return MEASUREMENT_LEVEL_LABELS[index + 1]
    return MEASUREMENT_LEVEL_LABELS[-1]


def measurement_label_rank(label: str | None) -> int:
    if label is None:
        return -1
    return MEASUREMENT_LEVEL_RANKS.get(label, -1)


def overall_label(level: int) -> dict:
    mapping = {
        0: {"label": "Минимальный", "color": "green"},
        1: {"label": "Низкий", "color": "yellowgreen"},
        2: {"label": "Умеренный", "color": "orange"},
        3: {"label": "Высокий", "color": "red"},
    }
    return mapping.get(int(level), mapping[0])


def recommendations(overall: int) -> list[str]:
    if overall <= 0:
        return ["Ограничения не требуются.", "Обычная активность допустима."]
    if overall == 1:
        return ["При чувствительности лучше сократить длительные прогулки.", "После улицы стоит умыться и сменить одежду."]
    if overall == 2:
        return ["Лучше сократить время на улице, особенно днём.", "Окна стоит держать закрытыми в часы пика.", "После улицы полезно промыть нос и принять душ."]
    return ["По возможности избегайте длительного пребывания на улице.", "На улице лучше использовать маску и очки.", "Окна держите закрытыми, дома поможет очиститель воздуха."]
