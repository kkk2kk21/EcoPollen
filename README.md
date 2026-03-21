# EcoPollen

EcoPollen - веб-приложение для мониторинга пыльцы, просмотра карты слоев и поиска публикаций по аллергенам.

## Что нужно для запуска

Docker

## Юнит-тесты

Юнит-тесты вынесены отдельно от основного кода:

backend: `tests/backend`
frontend: `frontend/tests`

## Структура

`backend` - API и работа с базой данных
`frontend` - клиентская часть
`docker-compose.yml` - основной файл запуска проекта

## Запуск

```powershell
Заполнить .env.example своими значениями
Убрать .example из .env.example
Выполнить docker compose up -d --build в корне проекта
```

После запуска:

сайт: `http://localhost`
Swagger: `http://localhost/docs`
