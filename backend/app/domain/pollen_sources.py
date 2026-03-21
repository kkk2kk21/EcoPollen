from __future__ import annotations

ACTIVE_PUBLIC_SOURCES = (
    {
        "key": "pgniu_manual",
        "name": "Замеры ПГНИУ",
        "source_type": "manual",
        "priority": 100,
        "url": None,
    },
    {
        "key": "meteoswiss",
        "name": "MeteoSwiss Open Data",
        "source_type": "api",
        "priority": 88,
        "url": "https://www.meteoswiss.admin.ch/services-and-publications/service/open-data.html",
    },
    {
        "key": "norkko",
        "name": "Norkko / University of Turku",
        "source_type": "scrape",
        "priority": 82,
        "url": "https://norkko.fi/",
    },
    {
        "key": "dwd",
        "name": "DWD Pollenflug-Gefahrenindex",
        "source_type": "api",
        "priority": 76,
        "url": "https://opendata.dwd.de/climate_environment/health/alerts/s31fg.json",
    },
    {
        "key": "open_meteo",
        "name": "Open-Meteo / CAMS Europe",
        "source_type": "api",
        "priority": 90,
        "url": "https://open-meteo.com/",
    },
)

ACTIVE_PUBLIC_SOURCE_KEYS = tuple(source["key"] for source in ACTIVE_PUBLIC_SOURCES)
