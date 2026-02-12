# Timer Service

FastAPI-сервис, который возвращает прошедшее время от фиксированной точки UTC без хранения состояния.

## Endpoints

- `GET /health`
- `GET /time`
- `GET /view`

## ENV

- `HOST` (default: `0.0.0.0`)
- `PORT` (default: `8003`)

## Run

```bash
docker compose up --build
```

## Usage

```bash
curl http://localhost:8003/time
```

Открыть HTML-страницу в браузере:

`http://localhost:8003/view`

Тема по умолчанию: `light`.

Темная тема:

`http://localhost:8003/view?theme=dark`
