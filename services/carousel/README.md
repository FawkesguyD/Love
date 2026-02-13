# Carousel Service

FastAPI-сервис карусели, использующий S3/MinIO bucket `images` как источник изображений.

## Endpoints

- `GET /carousel?random=<true|false>`
  - Возвращает изображение (binary, inline)
  - `random` (default: `false`)
  - `random=false`: последовательная циклическая выдача по списку
  - `random=true`: случайная выдача
  - Валидация `random`: `true/false`, `1/0`, `yes/no`
  - Параметр `refresh` больше не поддерживается
  - Заголовки:
    - `Cache-Control: no-store, max-age=0`
    - `Content-Disposition: inline; filename="..."`
    - `X-Carousel-Mode`
    - `X-Carousel-Image`

- `GET /carousel/view?random=<true|false>&refresh=<seconds>`
  - Возвращает минимальную HTML-страницу fullscreen
  - Страница по таймеру обновляет `<img>` (по умолчанию каждые 10 секунд) и запрашивает `/carousel?random=...&t=...`

## ENV

- `S3_ENDPOINT` (required)
- `S3_ACCESS_KEY` (required)
- `S3_SECRET_KEY` (required)
- `S3_BUCKET` (required)
- `S3_REGION` (default: `us-east-1`)
- `S3_USE_SSL` (default: `false`)
- `S3_FORCE_PATH_STYLE` (default: `true`)
- `HOST` (default: `0.0.0.0`)
- `PORT` (default: `8001`)

## Запуск

```bash
docker compose up --build
```

Примеры:

```bash
curl -i "http://localhost:8001/carousel"
curl -i "http://localhost:8001/carousel?random=true"
```

Открыть viewer в браузере:

`http://localhost:8001/carousel/view?random=false&refresh=10`
