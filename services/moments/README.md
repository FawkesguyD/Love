# Moments Service

FastAPI-сервис для хранения метаданных карточек в MongoDB.

`images` хранится как массив имен файлов (`string[]`), например:

```json
{
  "images": ["IMG_001.jpg", "IMG_002.png"]
}
```

При старте сервис делает ленивую миграцию legacy-документов, где `images` были в формате объектов (`key/name/order`), и приводит их к `string[]` по basename из `key`.

## Endpoints

- `GET /` (Timeline SPA)
- `GET /health`
- `POST /api/v1/cards`
- `GET /api/v1/cards`
- `GET /api/v1/cards/{id}`
- `PATCH /api/v1/cards/{id}`
- `DELETE /api/v1/cards/{id}`
- `GET /media/{filename}`
- `GET /cards/view`
- `GET /cards/view/{id}`

Legacy aliases (обратная совместимость):

- `/api/v1/moments...` -> алиас к `/api/v1/cards...`
- `/view...` -> алиас к `/cards/view...`

## Timeline SPA

`GET /` возвращает одностраничный timeline UI:

- вертикальная линия времени и точки
- карточки с фото, датой, текстом
- сортировка по дате (`asc`) и группировка по дню
- состояния `loading`, `empty`, `error + retry`
- lazy-loading изображений и scroll reveal анимации
- keyboard navigation (Arrow Up/Down по карточкам)

По умолчанию страница использует проксированные endpoint-ы:

- `/api/cards`
- `/api/cards/{id}`
- `/api/images/{image_id}`

## HTML Viewer

### `GET /cards/view`

Отображает одну карточку Card в браузере:

- по умолчанию (`random=false`) выбирается latest момент в стабильном порядке `date desc, _id desc`
- `random=true` выбирает случайный момент через MongoDB `$sample`
- если коллекция пустая, отображается HTML-страница `No moments yet`
- UI: центрированная square-card (`aspect-ratio: 1/1`) с `title`, `date`, `text` и фотоблоком
- фотоблок: deterministic Fibonacci/spiral grid для первых 6 изображений; если изображений больше, показывается `+X more`

Примеры:

- `http://localhost:8002/cards/view`
- `http://localhost:8002/cards/view?random=true`

### `GET /cards/view/{id}`

Отображает конкретный момент в том же HTML-дизайне.

- если moment не найден, возвращается `404` с HTML-страницей `Moment not found`

### Визуальные состояния (скриншот-описание)

- `latest`: крупный заголовок сверху карточки, muted-дата, текст с аккуратным overflow и фотомозаика в стиле золотой спирали.
- `random`: тот же макет карточки, но карточка выбирается случайно (`/cards/view?random=true`), навигация `Latest`/`Random` под карточкой.

## ENV

- `MONGO_URI` (default: `mongodb://mongo:27017`)
- `MONGO_DB_NAME` (default: `app`)
- `PHOTOSTOCK_BASE_URL` (required for server-side media proxy, example: `http://photostock:8000`)
- `PHOTOSTOCK_TIMEOUT_MS` (optional, default: `2000`)
- `TIMELINE_CARDS_LIST_ENDPOINT` (default: `/api/cards`)
- `TIMELINE_CARD_DETAILS_ENDPOINT` (default: `/api/cards/{id}`)
- `TIMELINE_IMAGES_ENDPOINT` (default: `/api/images`)
- `TIMELINE_REQUEST_TIMEOUT_MS` (default: `6000`)
- `TIMELINE_CACHE_TTL_MS` (default: `45000`)
- `TIMELINE_MAX_MOMENTS` (default: `500`)
- `TIMELINE_BATCH_SIZE` (default: `16`)
- `HOST` (default: `0.0.0.0`)
- `PORT` (default: `8002`)

## Images Contract

`moments` хранит только filename в `images`:

```json
{
  "images": ["IMG_001.jpg", "IMG_002.png"]
}
```

Для HTML viewer картинка отдается через same-origin proxy в `moments`:

- итоговый `src` в HTML: `/api/images/IMG_001`
- filename нормализуется до basename (`IMG_001`), после чего запрос уходит в `photostock`:
  `GET /images/IMG_001`

Важно: браузер не обращается к `PHOTOSTOCK_BASE_URL` напрямую, этот URL используется только сервисом `moments`.

## Run

```bash
docker compose up --build
```

Фронтенд unit/snapshot тесты:

```bash
node --test services/moments/app/static/tests/*.test.mjs
```
