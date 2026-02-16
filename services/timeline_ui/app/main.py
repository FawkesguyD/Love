import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("timeline-ui")


def parse_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default)).strip()

    try:
        parsed = int(raw_value)
    except ValueError:
        logger.warning("Invalid %s value '%s', fallback to %s", name, raw_value, default)
        return default

    if parsed < 1:
        logger.warning("Invalid %s value '%s', fallback to %s", name, raw_value, default)
        return default

    return parsed


API_BASE_URL = os.getenv("API_BASE_URL", "").strip().rstrip("/")
CARDS_LIST_PATH = os.getenv("CARDS_LIST_PATH", "/api/cards").strip() or "/api/cards"
CARD_BY_ID_PATH_TEMPLATE = os.getenv("CARD_BY_ID_PATH_TEMPLATE", "/api/cards/{id}").strip() or "/api/cards/{id}"
IMAGES_PATH = os.getenv("IMAGES_PATH", "/api/images").strip() or "/api/images"
TIMER_PATH = os.getenv("TIMER_PATH", "/api/timer").strip() or "/api/timer"
REQUEST_TIMEOUT_MS = parse_int_env("REQUEST_TIMEOUT_MS", 6000)
CACHE_TTL_MS = parse_int_env("CACHE_TTL_MS", 45000)
MAX_MOMENTS = parse_int_env("MAX_MOMENTS", 500)
BATCH_SIZE = parse_int_env("BATCH_SIZE", 16)
MAX_RETRIES = parse_int_env("MAX_RETRIES", 2)
TIMER_SYNC_INTERVAL_MS = parse_int_env("TIMER_SYNC_INTERVAL_MS", 20000)


app = FastAPI(title="Timeline UI Service")
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def to_safe_json_script(value: dict[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":")).replace("</", "<\\/")


def build_page_html() -> str:
    config = {
        "apiBaseUrl": API_BASE_URL,
        "cardsListPath": CARDS_LIST_PATH,
        "cardByIdPathTemplate": CARD_BY_ID_PATH_TEMPLATE,
        "imagesPath": IMAGES_PATH,
        "timerPath": TIMER_PATH,
        "requestTimeoutMs": REQUEST_TIMEOUT_MS,
        "cacheTtlMs": CACHE_TTL_MS,
        "maxMoments": MAX_MOMENTS,
        "batchSize": BATCH_SIZE,
        "maxRetries": MAX_RETRIES,
        "timerSyncIntervalMs": TIMER_SYNC_INTERVAL_MS,
    }

    config_script = to_safe_json_script(config)

    return (
        "<!doctype html>"
        "<html lang=\"en\">"
        "<head>"
        "<meta charset=\"utf-8\" />"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />"
        "<title>Valentine Timeline</title>"
        "<link rel=\"stylesheet\" href=\"/static/timeline.css\" />"
        "</head>"
        "<body>"
        "<main class=\"timeline-shell\" id=\"timeline-app\">"
        "<section class=\"countdown\" id=\"countdown\" aria-live=\"polite\">"
        "<p class=\"countdown-label\">Вместе уже</p>"
        "<p class=\"countdown-value\" id=\"countdown-value\">...</p>"
        "<p class=\"countdown-meta\" id=\"countdown-meta\"></p>"
        "</section>"
        "<header class=\"timeline-hero\">"
        "<p class=\"timeline-kicker\">Наши моменты</p>"
        "<h1>Любовь это все <span aria-hidden=\"true\">&#9825;</span></h1>"
        "<p class=\"timeline-subtitle\">То что не получится забыть</p>"
        "</header>"
        "<p id=\"timeline-status\" class=\"sr-only\" aria-live=\"polite\"></p>"
        "<section id=\"timeline\" class=\"timeline\" aria-label=\"Moments timeline\" role=\"list\"></section>"
        "<div id=\"timeline-sentinel\" class=\"timeline-sentinel\" aria-hidden=\"true\"></div>"
        "</main>"
        "<noscript>"
        "<section class=\"timeline-noscript\">"
        "<h2>JavaScript is required</h2>"
        "<p>Please enable JavaScript to view the interactive timeline.</p>"
        "</section>"
        "</noscript>"
        f"<script>window.__TIMELINE_CONFIG__={config_script};</script>"
        "<script type=\"module\" src=\"/static/timeline-app.mjs\"></script>"
        "</body>"
        "</html>"
    )


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse(content={"status": "ok", "service": "timeline-ui"})


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse(content=build_page_html())
