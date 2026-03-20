# EcoPollen

EcoPollen - веб-приложение для мониторинга пыльцы, просмотра карты слоев и поиска публикаций по аллергенам.

## Что нужно для запуска

- Docker
- Docker Compose

## Юнит-тесты

Юнит-тесты вынесены отдельно от основного кода:

- backend: `tests/backend`
- frontend: `frontend/tests`

## Структура

- `backend` - API и работа с базой данных
- `frontend` - клиентская часть
- `docker-compose.yml` - основной файл запуска проекта

## Запуск

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

После запуска:

- сайт: `http://localhost`
- Swagger: `http://localhost/docs`
