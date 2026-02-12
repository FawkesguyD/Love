# PhotoStock + Carousel + Moments + Timer + MongoDB

Репозиторий содержит сервисы:

- `photostock` (`services/photostock`) — API для выдачи изображения по имени без расширения
- `carousel` (`services/carousel`) — API выдачи изображений по очереди/случайно + viewer
- `moments` (`services/moments`) — API метаданных моментов (MongoDB)
- `timer` (`services/timer`) — API расчета прошедшего времени от фиксированной UTC-точки
- `s3` (MinIO) — S3-совместимое хранилище изображений
- `s3-init` — инициализация bucket и seed-данных
- `mongo` — MongoDB для `moments`
- `mongo-express` — web UI для MongoDB

## Что происходит при старте compose

При `docker compose up --build`:

1. `s3-init` ждёт готовности MinIO
2. `s3-init` создаёт bucket `images` (если отсутствует)
3. `s3-init` загружает все файлы из `./images` в bucket `images`
4. `moments` подключается к `mongo`, создаёт индексы и мигрирует legacy `images` (объекты `key/name/order`) в `images: string[]`

## Запуск локально

```bash
docker compose up --build
```

После старта:

- Image API: `http://localhost:8000/images/cat?display=true`
- Carousel image: `http://localhost:8001/carousel`
- Carousel viewer: `http://localhost:8001/carousel/view?refresh=10`
- Moments API: `http://localhost:8002/api/v1/cards`
- Moments health: `http://localhost:8002/health`
- Moments view (latest): `http://localhost:8002/cards/view`
- Moments view (random): `http://localhost:8002/cards/view?random=true`
- Timer API: `http://localhost:8003/time`
- Timer view: `http://localhost:8003/view`
- Timer health: `http://localhost:8003/health`
- MinIO S3 API: `http://localhost:9000`
- MinIO Console: `http://localhost:9001` (`dev` / `devpassword`)
- MongoDB: `mongodb://localhost:27017` (`dev` / `devpassword`, `authSource=admin`)
- Mongo Express: `http://localhost:8088` (`admin` / `adminpassword`)

## Image/Carousel API

### Image API

`GET /images/{image}?display=<true|false>`

- `image` — только базовое имя без расширения
- поддерживаемые расширения: `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`
- `display=true` (по умолчанию) -> `Content-Disposition: inline`
- `display=false` -> `Content-Disposition: attachment`

### Carousel API

`GET /carousel?random=<true|false>`

- возвращает изображение (binary, inline)
- `random` по умолчанию `false`
- при `random=false`: выдача циклично по очереди
- при `random=true`: случайная выдача
- `refresh` для `/carousel` не поддерживается

`GET /carousel/view?random=<true|false>&refresh=<seconds>`

- возвращает fullscreen HTML viewer
- viewer по таймеру обновляет `<img>` и запрашивает `/carousel`

## Moments API

Базовый путь: `/api/v1`

### POST `/api/v1/cards`

```bash
curl -X POST http://localhost:8002/api/v1/cards \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "Trip to mountains",
    "text": "Cold morning and clear sky",
    "date": "2026-02-10T12:00:00.000Z",
    "images": ["IMG_001.jpg", "IMG_002.jpg"],
    "visibility": "public",
    "tags": ["travel", "winter"]
  }'
```

- `images` хранится как массив имен файлов (`string[]`)
- имя файла должно быть без пути (`/`, `\`), без `..`, без URL/query

### GET `/api/v1/cards`

Параметры:

- `limit` (default `20`, max `100`)
- `order=desc|asc` (default `desc`)
- `cursor` (cursor pagination по `date` + `_id`)
- `from`, `to` (ISO даты для диапазона)
- `visibility` (`draft|public`)

Пример первой страницы:

```bash
curl 'http://localhost:8002/api/v1/cards?limit=2&order=desc'
```

Пример следующей страницы через `nextCursor`:

```bash
NEXT_CURSOR=$(curl -s 'http://localhost:8002/api/v1/cards?limit=2&order=desc' | jq -r '.nextCursor')
curl "http://localhost:8002/api/v1/cards?limit=2&order=desc&cursor=${NEXT_CURSOR}"
```

### GET `/api/v1/cards/:id`

```bash
curl http://localhost:8002/api/v1/cards/<card_id>
```

### HTML viewer `/cards/view`

- `GET /cards/view` -> показывает одну карточку (по умолчанию latest по `date desc, _id desc`)
- `GET /cards/view?random=true` -> показывает случайную карточку через `$sample`
- `GET /cards/view/:id` -> показывает конкретную карточку
- если нет данных -> HTML `No moments yet`
- если id не найден -> `404` HTML `Moment not found`

### PATCH `/api/v1/cards/:id`

```bash
curl -X PATCH http://localhost:8002/api/v1/cards/<card_id> \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "Updated title",
    "images": ["NEW_MAIN.jpg", "NEW_EXTRA.jpg"],
    "visibility": "draft"
  }'
```

Если в `PATCH` передан `images`, массив заменяется целиком.

### Как получить картинку по filename

`moments` хранит только имя файла (например `IMG_001.jpg`).

Существующий `photostock` endpoint: `GET /images/{image}` принимает базовое имя без расширения.  
Пример: для `IMG_001.jpg` вызывай `GET /images/IMG_001`.

### DELETE `/api/v1/cards/:id`

```bash
curl -X DELETE http://localhost:8002/api/v1/cards/<card_id> -i
```

Ожидаемый статус: `204 No Content`.

Legacy aliases (временная обратная совместимость):

- `/api/v1/moments...` -> алиас к `/api/v1/cards...`
- `/view...` -> алиас к `/cards/view...`

### Формат ошибок moments

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed",
    "details": []
  }
}
```

Коды: `400` (валидация), `404` (не найдено), `500` (unexpected).

## Timer API

`timer` не использует БД и не хранит состояние. Расчет выполняется на лету от UTC-времени.

Фиксированная точка отсчета:

- `START_TIME=2025-03-06T18:00:00.000Z`

### GET `/time`

```bash
curl http://localhost:8003/time
```

Пример ответа:

```json
{
  "since": "2025-03-06T18:00:00.000Z",
  "now": "2026-02-12T18:30:45.123Z",
  "elapsed": {
    "years": 0,
    "days": 343,
    "hours": 0,
    "minutes": 30,
    "seconds": 45
  },
  "totalSeconds": 29637045
}
```

### GET `/health`

```bash
curl http://localhost:8003/health
```

### GET `/view`

- По умолчанию: `theme=light`
- Для темной темы: `theme=dark`

Открыть в браузере:

- `http://localhost:8003/view`
- `http://localhost:8003/view?theme=dark`

## Диагностика внутри docker-сети

Для диагностики добавлен сервис `curl-diag` в той же сети `valentine-default` (профиль `diag`).

Запуск:

```bash
docker compose --profile diag up -d curl-diag
```

Примеры запросов изнутри сети:

```bash
docker compose exec curl-diag curl -i "http://photostock:8000/images/cat"
docker compose exec curl-diag curl -i "http://moments:8002/health"
docker compose exec curl-diag curl -i "http://timer:8003/health"
```

Остановка:

```bash
docker compose --profile diag stop curl-diag
```

## ENV

Для `photostock` и `carousel`:

- `S3_ENDPOINT=http://s3:9000`
- `S3_ACCESS_KEY=dev`
- `S3_SECRET_KEY=devpassword`
- `S3_BUCKET=images`
- `S3_REGION=us-east-1`
- `S3_USE_SSL=false`
- `S3_FORCE_PATH_STYLE=true`

Для `moments`:

- `MONGO_URI=mongodb://dev:devpassword@mongo:27017/?authSource=admin`
- `MONGO_DB_NAME=app`
- `PHOTOSTOCK_BASE_URL=http://photostock:8000`
- `PHOTOSTOCK_TIMEOUT_MS=2000`
- `HOST=0.0.0.0`
- `PORT=8002`

Для `timer`:

- `HOST=0.0.0.0`
- `PORT=8003`

## Mongo Admin UI

1. Открой `http://localhost:8088`
2. Войди `admin` / `adminpassword`
3. Выбери БД `app` и коллекцию `moments`
