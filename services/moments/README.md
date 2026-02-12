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

- итоговый `src` в HTML: `/media/IMG_001.jpg`
- `moments` валидирует `filename`, извлекает basename (`IMG_001`) и уже сервером запрашивает `photostock`:
  `GET ${PHOTOSTOCK_BASE_URL}/images/IMG_001`

Важно: браузер не обращается к `PHOTOSTOCK_BASE_URL` напрямую, этот URL используется только сервисом `moments`.

## Run

```bash
docker compose up --build
```
