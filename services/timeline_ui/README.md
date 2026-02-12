# Timeline UI Service

Standalone UI microservice for the Valentine timeline landing page.

## Endpoints

- `GET /` - SPA timeline page
- `GET /health` - health check

## Features

- Sticky elapsed timer block (uses Timer API)
- Vertical timeline with cards and dots
- Multi-image golden-spiral gallery (3-6 photos)
- Loading/empty/error states and retry
- Lazy image loading and incremental rendering

## ENV

- `API_BASE_URL` (default: empty, same-origin)
- `CARDS_LIST_PATH` (default: `/api/cards`)
- `CARD_BY_ID_PATH_TEMPLATE` (default: `/api/cards/{id}`)
- `IMAGES_PATH` (default: `/api/images`)
- `TIMER_PATH` (default: `/api/timer`)
- `REQUEST_TIMEOUT_MS` (default: `6000`)
- `CACHE_TTL_MS` (default: `45000`)
- `MAX_MOMENTS` (default: `500`)
- `BATCH_SIZE` (default: `16`)
- `MAX_RETRIES` (default: `2`)
- `TIMER_SYNC_INTERVAL_MS` (default: `20000`)
- `HOST` (default: `0.0.0.0`)
- `PORT` (default: `8010`)

## Run

```bash
docker compose up --build timeline-ui
```
