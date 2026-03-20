from __future__ import annotations

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...services.pollen_import_service import (
    backfill_available_history,
    import_dwd_snapshot,
    import_meteoswiss_snapshot,
    import_norkko_snapshot,
    import_open_meteo_snapshot,
)
from .auth import require_roles

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post(
    "/import-open-meteo",
    summary="Запустить импорт Open-Meteo",
    description="Ручной импорт данных Open-Meteo в БД для выбранной даты.",
)
async def import_open_meteo(
    day: date | None = Query(None, description="Дата, например 2026-03-01 (если пусто — сегодня)"),
    db: Session = Depends(get_db),
    _=Depends(require_roles("admin", "scientist")),
):
    try:
        return await import_open_meteo_snapshot(db, day)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Open-Meteo ошибка: {e}")


@router.post(
    "/import-norkko",
    summary="Запустить импорт Norkko",
    description="Ручной импорт данных Norkko в БД для выбранной даты бюллетеня.",
)
async def import_norkko(
    day: date | None = Query(None, description="Дата бюллетеня Norkko (today или внутри forecast range)"),
    db: Session = Depends(get_db),
    _=Depends(require_roles("admin", "scientist")),
):
    try:
        return await import_norkko_snapshot(db, day)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Norkko ошибка: {e}")


@router.post(
    "/import-meteoswiss",
    summary="Запустить импорт MeteoSwiss",
    description="Ручной импорт данных MeteoSwiss в БД для выбранной даты.",
)
async def import_meteoswiss(
    day: date | None = Query(None, description="Дата для daily recent CSV MeteoSwiss"),
    db: Session = Depends(get_db),
    _=Depends(require_roles("admin", "scientist")),
):
    try:
        return await import_meteoswiss_snapshot(db, day)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"MeteoSwiss ошибка: {e}")


@router.post(
    "/import-dwd",
    summary="Запустить импорт DWD",
    description="Ручной импорт данных DWD в БД для выбранного доступного дня.",
)
async def import_dwd(
    day: date | None = Query(None, description="today / tomorrow / dayafter_to относительно DWD last_update"),
    db: Session = Depends(get_db),
    _=Depends(require_roles("admin", "scientist")),
):
    try:
        return await import_dwd_snapshot(db, day)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"DWD ошибка: {e}")


@router.post(
    "/backfill-week",
    summary="Добрать доступную историю",
    description="Пытается дозагрузить доступные исторические данные источников за последние дни.",
)
async def backfill_week(
    days: int = Query(7, ge=1, le=14, description="Сколько дней назад попытаться добрать"),
    db: Session = Depends(get_db),
    _=Depends(require_roles("admin", "scientist")),
):
    try:
        return await backfill_available_history(db, days=days)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Backfill ошибка: {e}")
