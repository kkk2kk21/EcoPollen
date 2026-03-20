from __future__ import annotations

DEFAULT_CONCENTRATION_THRESHOLDS = (1, 10, 25, 50, 100)


POLLEN_TAXA_CATALOG = (
    {
        "key": "alder",
        "name_ru": "Ольха",
        "emoji": "🌳",
        "group": "tree",
        "concentration_thresholds": (1, 11, 40, 70, 250),
    },
    {
        "key": "hazel",
        "name_ru": "Лещина",
        "emoji": "🌳",
        "group": "tree",
        "concentration_thresholds": (1, 11, 40, 70, 250),
    },
    {
        "key": "birch",
        "name_ru": "Берёза",
        "emoji": "🌳",
        "group": "tree",
        "concentration_thresholds": (1, 11, 40, 70, 300),
    },
    {
        "key": "ash",
        "name_ru": "Ясень",
        "emoji": "🌳",
        "group": "tree",
        "concentration_thresholds": (1, 11, 55, 100, 350),
    },
    {
        "key": "beech",
        "name_ru": "Бук",
        "emoji": "🌳",
        "group": "tree",
        "concentration_thresholds": (1, 50, 90, 130, 400),
    },
    {
        "key": "oak",
        "name_ru": "Дуб",
        "emoji": "🌳",
        "group": "tree",
        "concentration_thresholds": (1, 50, 90, 130, 400),
    },
    {
        "key": "olive",
        "name_ru": "Олива",
        "emoji": "🌿",
        "group": "tree",
        "concentration_thresholds": (1, 50, 100, 200, 300),
    },
    {
        "key": "grass",
        "name_ru": "Злаки",
        "emoji": "🌾",
        "group": "grass",
        "concentration_thresholds": (1, 20, 35, 50, 150),
    },
    {
        "key": "rye",
        "name_ru": "Рожь",
        "emoji": "🌾",
        "group": "grass",
        "concentration_thresholds": (1, 20, 35, 50, 150),
    },
    {
        "key": "mugwort",
        "name_ru": "Полынь",
        "emoji": "🌿",
        "group": "weed",
        "concentration_thresholds": (1, 6, 15, 25, 50),
    },
    {
        "key": "ragweed",
        "name_ru": "Амброзия",
        "emoji": "🌿",
        "group": "weed",
        "concentration_thresholds": (1, 6, 11, 20, 40),
    },
)

ALL_POLLEN_TAXON_KEYS = tuple(item["key"] for item in POLLEN_TAXA_CATALOG)
POLLEN_TAXA_BY_KEY = {item["key"]: item for item in POLLEN_TAXA_CATALOG}

OPEN_METEO_SUPPORTED_TAXA = (
    "alder",
    "birch",
    "grass",
    "mugwort",
    "olive",
    "ragweed",
)

NORKKO_SUPPORTED_TAXA = (
    "hazel",
    "alder",
    "birch",
    "grass",
    "mugwort",
    "ragweed",
)

METEOSWISS_SUPPORTED_TAXA = (
    "alder",
    "ash",
    "birch",
    "beech",
    "hazel",
    "oak",
    "grass",
)

DWD_SUPPORTED_TAXA = (
    "alder",
    "hazel",
    "ash",
    "birch",
    "grass",
    "rye",
    "mugwort",
    "ragweed",
)
