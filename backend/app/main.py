from contextlib import asynccontextmanager

from fastapi import FastAPI

from .core.db import Base, engine, SessionLocal
from .services.pollen_scheduler import start_pollen_scheduler, stop_pollen_scheduler
from .startup.seed import seed_if_empty

from .api.routes import pollen
from .api.routes import auth
from .api.routes import admin
from .api.routes import library
from .api.routes import science
from .api.routes import jobs

OPENAPI_TAGS = [
    {
        "name": "public",
        "description": "Публичные данные для главной страницы, карты и справочников.",
    },
    {
        "name": "auth",
        "description": "Регистрация, вход и сведения о текущем пользователе.",
    },
    {
        "name": "library",
        "description": "Поиск научных публикаций по аллергенам.",
    },
    {
        "name": "science",
        "description": "Кабинет исследователя: ловушки, ручные замеры и настройки карты.",
    },
    {
        "name": "admin",
        "description": "Администрирование пользователей.",
    },
    {
        "name": "jobs",
        "description": "Служебные ручные задачи импорта данных в БД.",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_if_empty(db)

    scheduler_task = await start_pollen_scheduler()
    try:
        yield
    finally:
        await stop_pollen_scheduler(scheduler_task)


app = FastAPI(
    title="EcoPollen API",
    version="0.2.0",
    description=(
        "API платформы EcoPollen. Публичные маршруты обслуживают главную страницу, карту и справочники. "
        "Маршруты кабинета исследователя и администратора требуют авторизации."
    ),
    openapi_tags=OPENAPI_TAGS,
    swagger_ui_parameters={
        "defaultModelsExpandDepth": -1,
        "displayRequestDuration": True,
    },
    lifespan=lifespan,
)

app.include_router(pollen.router, prefix="/api/v1")

app.include_router(auth.router, prefix="/api/v1")

app.include_router(admin.router, prefix="/api/v1")

app.include_router(library.router, prefix="/api/v1")
app.include_router(science.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")

@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}
