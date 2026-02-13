import base64
import html
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import FastAPI, Path as PathParam, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.collection import Collection
from pymongo.errors import PyMongoError
from dotenv import load_dotenv

logger = logging.getLogger("moments")

TITLE_MAX_LENGTH = 200
TEXT_MAX_LENGTH = 5000
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
MAX_FILENAME_LENGTH = 255
SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9._ -]+$")
SAFE_PHOTOSTOCK_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
TRUE_VALUES = {"true", "1", "yes"}
FALSE_VALUES = {"false", "0", "no"}

def load_project_env() -> None:
    current_file = Path(__file__).resolve()
    for parent in current_file.parents:
        env_path = parent / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
            return

    # Fallback to default dotenv lookup (uses cwd and parent traversal).
    load_dotenv(override=False)


load_project_env()


def require_env_vars(names: list[str]) -> None:
    missing = [name for name in names if not os.getenv(name, "").strip()]
    if missing:
        missing_list = ", ".join(missing)
        raise RuntimeError(f"Missing required environment variables: {missing_list}")


require_env_vars(["MONGO_URI", "MONGO_DB_NAME"])

MONGO_URI = os.getenv("MONGO_URI", "").strip()
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "").strip()
PHOTOSTOCK_BASE_URL = os.getenv("PHOTOSTOCK_BASE_URL", "").strip().rstrip("/")


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


PHOTOSTOCK_TIMEOUT_MS = parse_int_env("PHOTOSTOCK_TIMEOUT_MS", 2000)
MEDIA_STREAM_CHUNK_SIZE = 64 * 1024
MAX_VIEW_IMAGES = 6


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def create_mongo_client() -> MongoClient:
    return MongoClient(MONGO_URI, tz_aware=True, serverSelectionTimeoutMS=2000)


MONGO_CLIENT = create_mongo_client()
MOMENTS_COLLECTION: Collection = MONGO_CLIENT[MONGO_DB_NAME]["moments"]


def validate_image_filename(value: str) -> str:
    normalized = value.strip()

    if not normalized:
        raise ValueError("must not be empty")

    if len(normalized) > MAX_FILENAME_LENGTH:
        raise ValueError(f"must be at most {MAX_FILENAME_LENGTH} characters")

    if "/" in normalized or "\\" in normalized:
        raise ValueError("must not contain path separators")

    if ".." in normalized or normalized in {".", ".."}:
        raise ValueError("must not contain '..'")

    if "://" in normalized or "?" in normalized or "#" in normalized:
        raise ValueError("must be a file name without URL or query string")

    if not SAFE_FILENAME_RE.fullmatch(normalized):
        raise ValueError("contains unsupported characters")

    return normalized


def normalize_image_filenames(images: list[str]) -> list[str]:
    return [validate_image_filename(image_name) for image_name in images]


def extract_filename_from_legacy_key(value: str) -> str | None:
    key = value.strip().replace("\\", "/")
    if not key:
        return None

    filename = key.rsplit("/", 1)[-1]
    if not filename:
        return None

    try:
        return validate_image_filename(filename)
    except ValueError:
        return None


def normalize_stored_images(
    images: Any,
    *,
    moment_id: ObjectId | None = None,
    fail_on_invalid: bool,
) -> list[str]:
    if not isinstance(images, list):
        if fail_on_invalid:
            raise ValueError("images must be an array")
        logger.warning("Moment '%s' has invalid 'images' type: %s", moment_id, type(images).__name__)
        return []

    sortable_items: list[tuple[int, int, Any]] = []
    for index, item in enumerate(images):
        sort_order = index
        if isinstance(item, dict):
            order = item.get("order")
            if isinstance(order, int) and order >= 0:
                sort_order = order
        sortable_items.append((sort_order, index, item))

    normalized_images: list[str] = []
    for _, _, item in sorted(sortable_items, key=lambda entry: (entry[0], entry[1])):
        normalized_name: str | None = None

        if isinstance(item, str):
            try:
                normalized_name = validate_image_filename(item)
            except ValueError:
                normalized_name = None
        elif isinstance(item, dict):
            key_value = item.get("key")
            if isinstance(key_value, str):
                normalized_name = extract_filename_from_legacy_key(key_value)

        if normalized_name is None:
            if fail_on_invalid:
                raise ValueError("contains unsupported image entries")
            logger.warning("Skipping invalid image in moment '%s': %r", moment_id, item)
            continue

        normalized_images.append(normalized_name)

    if fail_on_invalid and not normalized_images:
        raise ValueError("must contain at least one valid image")

    return normalized_images


class MomentCreatePayload(BaseModel):
    title: str = Field(..., min_length=1, max_length=TITLE_MAX_LENGTH)
    text: str | None = Field(default=None, max_length=TEXT_MAX_LENGTH)
    date: datetime
    images: list[str] = Field(..., min_length=1)
    visibility: Literal["draft", "public"] = "public"
    tags: list[str] | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("must include timezone")
        return value.astimezone(timezone.utc)

    @field_validator("images")
    @classmethod
    def validate_images(cls, value: list[str]) -> list[str]:
        return normalize_image_filenames(value)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None

        normalized_tags: list[str] = []
        for tag in value:
            normalized = tag.strip()
            if not normalized:
                raise ValueError("must not contain empty values")
            normalized_tags.append(normalized)

        return normalized_tags


class MomentPatchPayload(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=TITLE_MAX_LENGTH)
    text: str | None = Field(default=None, max_length=TEXT_MAX_LENGTH)
    date: datetime | None = None
    images: list[str] | None = Field(default=None, min_length=1)
    visibility: Literal["draft", "public"] | None = None
    tags: list[str] | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("must include timezone")
        return value.astimezone(timezone.utc)

    @field_validator("images")
    @classmethod
    def validate_images(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return normalize_image_filenames(value)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None

        normalized_tags: list[str] = []
        for tag in value:
            normalized = tag.strip()
            if not normalized:
                raise ValueError("must not contain empty values")
            normalized_tags.append(normalized)

        return normalized_tags


class CursorPayload(BaseModel):
    date: datetime
    id: str
    order: Literal["asc", "desc"]

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("must include timezone")
        return value.astimezone(timezone.utc)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        try:
            ObjectId(value)
        except InvalidId as exc:
            raise ValueError("must be a valid ObjectId") from exc

        return value


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_error_response(
    status_code: int,
    code: str,
    message: str,
    details: Any | None = None,
) -> JSONResponse:
    payload: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
        }
    }
    if details is not None:
        payload["error"]["details"] = details

    return JSONResponse(status_code=status_code, content=payload)


def to_json_compatible(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: to_json_compatible(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_json_compatible(item) for item in value]
    if isinstance(value, tuple):
        return [to_json_compatible(item) for item in value]
    if isinstance(value, Exception):
        return str(value)
    return value


def parse_object_id(raw_id: str, error_code: str = "INVALID_ID", message: str = "Invalid moment id") -> ObjectId:
    try:
        return ObjectId(raw_id)
    except InvalidId as exc:
        raise ApiError(status_code=400, code=error_code, message=message) from exc


def parse_bool_query(value: str | None, *, default: bool, name: str) -> bool:
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False

    raise ValueError(f"Invalid '{name}' value. Use one of: true/false, 1/0, yes/no")


def format_moment_date(value: Any) -> str:
    if not isinstance(value, datetime):
        return "Unknown date"
    return value.astimezone(timezone.utc).isoformat(timespec="minutes").replace("+00:00", "Z")


def to_display_text(value: str | None) -> str:
    if not value:
        return ""
    return html.escape(value).replace("\n", "<br />")


def resolve_image_name_for_photostock(filename: str) -> tuple[str, str]:
    normalized_filename = validate_image_filename(filename)
    stem, dot, _extension = normalized_filename.rpartition(".")
    image_name = stem if dot else normalized_filename
    image_name = image_name.strip()
    if not image_name or "." in image_name:
        raise ValueError("filename must have a valid basename")
    if not SAFE_PHOTOSTOCK_NAME_RE.fullmatch(image_name):
        raise ValueError("filename basename contains unsupported characters")

    return normalized_filename, image_name


def build_media_image_url(filename: str) -> str | None:
    try:
        _, image_name = resolve_image_name_for_photostock(filename)
    except ValueError:
        return None

    return f"/api/images/{quote(image_name, safe='')}"


def iter_stream_chunks(source: Any):
    try:
        while True:
            chunk = source.read(MEDIA_STREAM_CHUNK_SIZE)
            if not chunk:
                break
            yield chunk
    finally:
        close_method = getattr(source, "close", None)
        if callable(close_method):
            close_method()


def build_media_proxy_headers(headers: Any) -> tuple[str | None, dict[str, str]]:
    if headers is None:
        return None, {}

    content_type = headers.get("Content-Type")
    response_headers: dict[str, str] = {}

    cache_control = headers.get("Cache-Control")
    if cache_control:
        response_headers["Cache-Control"] = cache_control

    return content_type, response_headers


def build_images_html(images: list[str], title: str) -> str:
    if not images:
        return ""

    limited_images = images[:MAX_VIEW_IMAGES]
    hidden_count = max(0, len(images) - len(limited_images))
    items: list[str] = []
    for index, image_name in enumerate(limited_images, start=1):
        image_url = build_media_image_url(image_name)
        item_class = f"spiral-item spiral-item-{index}"
        if image_url is None:
            items.append(
                (
                    f"<div class=\"{item_class} spiral-item-unavailable\">"
                    "<p class=\"image-unavailable\">image unavailable</p>"
                    "</div>"
                )
            )
            continue

        alt_text = html.escape(f"{title} image {index}")
        items.append(
            (
                f"<figure class=\"{item_class}\">"
                f"<img src=\"{image_url}\" alt=\"{alt_text}\" loading=\"lazy\" "
                "onerror=\"this.onerror=null;this.style.display='none';"
                "this.insertAdjacentHTML('afterend','<p class=&quot;image-unavailable&quot;>image unavailable</p>');\" />"
                "</figure>"
            )
        )

    count_class = f"count-{max(1, min(len(limited_images), MAX_VIEW_IMAGES))}"
    more_html = f"<p class=\"gallery-more\">+{hidden_count} more</p>" if hidden_count > 0 else ""
    return (
        "<section class=\"media-block\">"
        f"<div class=\"spiral-grid {count_class}\" data-testid=\"moment-gallery\">{''.join(items)}</div>"
        f"{more_html}"
        "</section>"
    )


def build_layout_html(title: str, body: str, *, api_link: str | None = None) -> str:
    api_item = ""
    if api_link:
        api_item = f"<a href=\"{api_link}\">Open JSON</a>"

    return (
        "<!doctype html>"
        "<html lang=\"en\">"
        "<head>"
        "<meta charset=\"utf-8\" />"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />"
        f"<meta name=\"photostock-timeout-ms\" content=\"{PHOTOSTOCK_TIMEOUT_MS}\" />"
        f"<title>{html.escape(title)}</title>"
        "<style>"
        ":root{--card-surface:#fcfcfd;--card-shadow:0 20px 50px rgba(17,24,39,.15);"
        "--muted:#6f7282;--text:#1c1d22;--gap:clamp(10px,1.6vmin,14px)}"
        "html,body{margin:0;min-height:100%;color:var(--text)}"
        "body{font-family:'Avenir Next','Trebuchet MS','Segoe UI',sans-serif;"
        "background:radial-gradient(circle at 14% 20%,#f4f6f8 0,#eef2f4 38%,#e8ecef 100%)}"
        ".page{min-height:100vh;display:grid;place-items:center;padding:20px;box-sizing:border-box}"
        ".canvas{display:grid;justify-items:center;gap:12px;width:100%}"
        ".moment-card{width:min(70vmin,720px,calc(100vw - 30px),calc(100vh - 140px));"
        "aspect-ratio:1/1;background:var(--card-surface);border-radius:24px;padding:clamp(16px,2.7vmin,26px);"
        "box-sizing:border-box;display:grid;grid-template-rows:auto auto minmax(0,1fr);gap:var(--gap);"
        "box-shadow:var(--card-shadow);border:1px solid rgba(255,255,255,.8);overflow:hidden}"
        ".moment-title{margin:0;font-family:'Georgia','Times New Roman',serif;font-size:clamp(30px,5.4vmin,48px);"
        "line-height:1.04;letter-spacing:-.02em;overflow-wrap:anywhere}"
        ".date{margin:0;color:var(--muted);font-size:clamp(12px,1.5vmin,14px)}"
        ".moment-content{min-height:0;display:grid;grid-template-rows:auto minmax(0,1fr);gap:var(--gap)}"
        ".text{margin:0;font-size:clamp(14px,1.9vmin,18px);line-height:1.54;color:#333843;"
        "overflow:auto;max-height:7.7em;padding-right:4px;word-break:break-word}"
        ".media-block{min-height:0;display:grid;grid-template-rows:minmax(0,1fr) auto;gap:8px}"
        ".spiral-grid{min-height:0;height:100%;display:grid;grid-template-columns:repeat(13,minmax(0,1fr));"
        "grid-template-rows:repeat(8,minmax(0,1fr));gap:6px}"
        ".spiral-item{margin:0;position:relative;overflow:hidden;border-radius:10px;background:#e4e8ec}"
        ".spiral-item img{display:block;width:100%;height:100%;object-fit:cover}"
        ".spiral-item .image-unavailable{display:grid;place-items:center;height:100%;margin:0;padding:8px;"
        "color:var(--muted);font-size:12px;background:#f3f4f6}"
        ".spiral-item-1{grid-area:1/1/9/9}"
        ".spiral-item-2{grid-area:1/9/6/14}"
        ".spiral-item-3{grid-area:6/11/9/14}"
        ".spiral-item-4{grid-area:7/9/9/11}"
        ".spiral-item-5{grid-area:6/9/7/10}"
        ".spiral-item-6{grid-area:6/10/7/11}"
        ".spiral-grid.count-1 .spiral-item-1{grid-area:1/1/9/14}"
        ".spiral-grid.count-2 .spiral-item-1{grid-area:1/1/9/9}"
        ".spiral-grid.count-2 .spiral-item-2{grid-area:1/9/9/14}"
        ".spiral-grid.count-3 .spiral-item-3{grid-area:6/9/9/14}"
        ".spiral-grid.count-4 .spiral-item-4{grid-area:6/9/9/11}"
        ".spiral-grid.count-5 .spiral-item-5{grid-area:6/9/7/11}"
        ".gallery-more{margin:0;color:var(--muted);font-size:12px;text-align:right;letter-spacing:.01em}"
        ".nav{display:flex;gap:12px;font-size:13px;color:var(--muted)}"
        ".nav a{color:inherit;text-decoration:none;padding:4px 0;border-bottom:1px solid transparent}"
        ".nav a:hover{border-color:currentColor}"
        ".message-card{width:min(72vmin,520px,calc(100vw - 30px));background:var(--card-surface);"
        "border-radius:20px;padding:22px;box-sizing:border-box;box-shadow:var(--card-shadow)}"
        ".message-card h1{margin:0;font-family:'Georgia','Times New Roman',serif;font-size:clamp(28px,4.6vmin,40px)}"
        ".message-card p{margin:10px 0 0;color:#333843;font-size:16px;line-height:1.5}"
        "@media (max-width:700px){.moment-card{width:min(92vw,calc(100vh - 132px));gap:10px}"
        ".spiral-grid{gap:5px}.nav{font-size:12px;gap:10px}}"
        "</style>"
        "</head>"
        "<body>"
        "<main class=\"page\">"
        "<div class=\"canvas\">"
        f"{body}"
        f"<nav class=\"nav\"><a href=\"/cards/view\">Latest</a><a href=\"/cards/view?random=true\">Random</a>{api_item}</nav>"
        "</div>"
        "</main>"
        "</body>"
        "</html>"
    )


def build_moment_card_html(moment: dict[str, Any]) -> str:
    title = str(moment.get("title") or "Untitled")
    text_html = to_display_text(moment.get("text"))
    text_block = f"<section class=\"text\" data-testid=\"moment-text\">{text_html}</section>" if text_html else ""
    images = moment.get("images", [])
    images_html = build_images_html(images if isinstance(images, list) else [], title)
    date_string = html.escape(format_moment_date(moment.get("date")))

    body = (
        "<article class=\"moment-card\" data-testid=\"moment-card\">"
        f"<h1 class=\"moment-title\" data-testid=\"moment-title\">{html.escape(title)}</h1>"
        f"<p class=\"date\" data-testid=\"moment-date\">{date_string}</p>"
        f"<section class=\"moment-content\">{text_block}{images_html}</section>"
        "</article>"
    )

    moment_id = str(moment.get("_id") or "")
    api_link = f"/api/v1/cards/{quote(moment_id, safe='')}" if moment_id else None
    return build_layout_html(title=title, body=body, api_link=api_link)


def build_message_page(title: str, message: str) -> str:
    body = (
        "<article class=\"message-card\">"
        f"<h1>{html.escape(title)}</h1>"
        f"<p>{html.escape(message)}</p>"
        "</article>"
    )
    return build_layout_html(title=title, body=body)


def find_one_moment_for_view(*, use_random: bool) -> dict[str, Any] | None:
    if use_random:
        sampled = list(MOMENTS_COLLECTION.aggregate([{"$sample": {"size": 1}}]))
        if not sampled:
            return None
        return sampled[0]

    documents = list(
        MOMENTS_COLLECTION.find({}).sort([("date", DESCENDING), ("_id", DESCENDING)]).limit(1)
    )
    if not documents:
        return None
    return documents[0]


def serialize_moment(document: dict[str, Any]) -> dict[str, Any]:
    images = normalize_stored_images(
        document.get("images", []),
        moment_id=document.get("_id"),
        fail_on_invalid=False,
    )

    return {
        "_id": str(document["_id"]),
        "title": document["title"],
        "text": document.get("text"),
        "date": document["date"],
        "images": images,
        "visibility": document.get("visibility", "public"),
        "tags": document.get("tags", []),
        "createdAt": document["createdAt"],
        "updatedAt": document["updatedAt"],
    }


def encode_cursor(date_value: datetime, moment_id: ObjectId, order: str) -> str:
    payload = {
        "date": date_value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "id": str(moment_id),
        "order": order,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8")


def decode_cursor(cursor: str) -> CursorPayload:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
        payload = json.loads(decoded)
        return CursorPayload.model_validate(payload)
    except Exception as exc:
        raise ApiError(status_code=400, code="INVALID_CURSOR", message="Invalid cursor format") from exc


def build_base_filter(
    from_date: datetime | None,
    to_date: datetime | None,
    visibility: Literal["draft", "public"] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}

    if from_date is not None or to_date is not None:
        date_filter: dict[str, Any] = {}
        if from_date is not None:
            date_filter["$gte"] = from_date
        if to_date is not None:
            date_filter["$lte"] = to_date
        payload["date"] = date_filter

    if visibility is not None:
        payload["visibility"] = visibility

    return payload


def build_cursor_filter(cursor_payload: CursorPayload, order: Literal["asc", "desc"]) -> dict[str, Any]:
    if cursor_payload.order != order:
        raise ApiError(
            status_code=400,
            code="INVALID_CURSOR",
            message="Cursor order does not match request order",
        )

    cursor_id = parse_object_id(
        cursor_payload.id,
        error_code="INVALID_CURSOR",
        message="Cursor contains invalid id",
    )

    operation = "$gt" if order == "asc" else "$lt"
    return {
        "$or": [
            {"date": {operation: cursor_payload.date}},
            {"date": cursor_payload.date, "_id": {operation: cursor_id}},
        ]
    }


def merge_filters(base_filter: dict[str, Any], cursor_filter: dict[str, Any] | None) -> dict[str, Any]:
    if cursor_filter is None:
        return base_filter

    if not base_filter:
        return cursor_filter

    return {
        "$and": [
            base_filter,
            cursor_filter,
        ]
    }


def ensure_indexes() -> None:
    MOMENTS_COLLECTION.create_index([("date", DESCENDING)], name="date_desc")
    MOMENTS_COLLECTION.create_index(
        [("visibility", ASCENDING), ("date", DESCENDING)],
        name="visibility_date_desc",
    )


def migrate_legacy_images() -> None:
    migrated_count = 0

    for document in MOMENTS_COLLECTION.find({}):
        raw_images = document.get("images")

        try:
            normalized_images = normalize_stored_images(
                raw_images,
                moment_id=document.get("_id"),
                fail_on_invalid=True,
            )
        except ValueError as exc:
            # Fail-fast: if legacy data cannot be safely normalized to string[],
            # startup should stop so the bad record is fixed explicitly.
            raise RuntimeError(
                f"Moment '{document.get('_id')}' has invalid legacy images and cannot be migrated"
            ) from exc

        if raw_images != normalized_images:
            MOMENTS_COLLECTION.update_one(
                {"_id": document["_id"]},
                {
                    "$set": {
                        "images": normalized_images,
                        "updatedAt": utc_now(),
                    }
                },
            )
            migrated_count += 1

    if migrated_count > 0:
        logger.info("Migrated %s moment documents to images=string[]", migrated_count)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        ensure_indexes()
        migrate_legacy_images()
        logger.info("MongoDB indexes are ready")
    except PyMongoError as exc:
        logger.exception("Failed to initialize MongoDB indexes/migrations")
        raise RuntimeError("Failed to initialize MongoDB indexes/migrations") from exc
    yield


app = FastAPI(title="Moments Service", lifespan=lifespan)


@app.exception_handler(ApiError)
def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
    return build_error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


@app.exception_handler(RequestValidationError)
def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    return build_error_response(
        status_code=400,
        code="VALIDATION_ERROR",
        message="Request validation failed",
        details=to_json_compatible(exc.errors()),
    )


@app.exception_handler(Exception)
def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unexpected error: %s", exc)
    return build_error_response(
        status_code=500,
        code="INTERNAL_ERROR",
        message="Internal server error",
    )


@app.get("/health")
def health() -> JSONResponse:
    try:
        MONGO_CLIENT.admin.command("ping")
    except PyMongoError:
        logger.exception("MongoDB ping failed")
        return JSONResponse(status_code=503, content={"status": "error", "mongo": "down"})

    return JSONResponse(content={"status": "ok", "mongo": "up"})


@app.post("/api/v1/cards", status_code=201)
@app.post("/api/v1/moments", status_code=201, include_in_schema=False)
def create_moment(payload: MomentCreatePayload) -> dict[str, Any]:
    now = utc_now()
    moment_document = {
        "title": payload.title,
        "text": payload.text,
        "date": payload.date,
        "images": payload.images,
        "visibility": payload.visibility,
        "tags": payload.tags or [],
        "createdAt": now,
        "updatedAt": now,
    }

    try:
        insert_result = MOMENTS_COLLECTION.insert_one(moment_document)
        stored_moment = MOMENTS_COLLECTION.find_one({"_id": insert_result.inserted_id})
    except PyMongoError as exc:
        logger.exception("Failed to create moment")
        raise ApiError(status_code=500, code="INTERNAL_ERROR", message="Failed to create moment") from exc

    if stored_moment is None:
        raise ApiError(status_code=500, code="INTERNAL_ERROR", message="Failed to load created moment")

    return serialize_moment(stored_moment)


@app.get("/api/v1/cards")
@app.get("/api/v1/moments", include_in_schema=False)
def list_moments(
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    order: Literal["desc", "asc"] = Query(default="desc"),
    cursor: str | None = Query(default=None),
    from_date: datetime | None = Query(default=None, alias="from"),
    to_date: datetime | None = Query(default=None, alias="to"),
    visibility: Literal["draft", "public"] | None = Query(default=None),
) -> dict[str, Any]:
    if from_date is not None:
        if from_date.tzinfo is None:
            raise ApiError(status_code=400, code="VALIDATION_ERROR", message="'from' must include timezone")
        from_date = from_date.astimezone(timezone.utc)

    if to_date is not None:
        if to_date.tzinfo is None:
            raise ApiError(status_code=400, code="VALIDATION_ERROR", message="'to' must include timezone")
        to_date = to_date.astimezone(timezone.utc)

    if from_date is not None and to_date is not None and from_date > to_date:
        raise ApiError(status_code=400, code="VALIDATION_ERROR", message="'from' must be less than or equal to 'to'")

    base_filter = build_base_filter(from_date=from_date, to_date=to_date, visibility=visibility)
    cursor_filter: dict[str, Any] | None = None

    if cursor:
        decoded_cursor = decode_cursor(cursor)
        cursor_filter = build_cursor_filter(decoded_cursor, order=order)

    query_payload = merge_filters(base_filter=base_filter, cursor_filter=cursor_filter)

    sort_direction = DESCENDING if order == "desc" else ASCENDING

    try:
        query = MOMENTS_COLLECTION.find(query_payload).sort(
            [("date", sort_direction), ("_id", sort_direction)]
        )
        documents = list(query.limit(limit + 1))
    except PyMongoError as exc:
        logger.exception("Failed to list moments")
        raise ApiError(status_code=500, code="INTERNAL_ERROR", message="Failed to list moments") from exc

    has_next = len(documents) > limit
    page_documents = documents[:limit]

    next_cursor: str | None = None
    if has_next and page_documents:
        last_document = page_documents[-1]
        next_cursor = encode_cursor(
            date_value=last_document["date"],
            moment_id=last_document["_id"],
            order=order,
        )

    return {
        "moments": [serialize_moment(document) for document in page_documents],
        "nextCursor": next_cursor,
    }


@app.get("/cards/view", response_class=HTMLResponse)
@app.get("/view", response_class=HTMLResponse, include_in_schema=False)
def view_moment(random: str | None = Query(default=None)) -> HTMLResponse:
    try:
        use_random = parse_bool_query(random, default=False, name="random")
    except ValueError as exc:
        return HTMLResponse(
            status_code=400,
            content=build_message_page("Bad request", str(exc)),
        )

    try:
        stored_moment = find_one_moment_for_view(use_random=use_random)
    except PyMongoError as exc:
        logger.exception("Failed to load moment for /cards/view")
        return HTMLResponse(
            status_code=500,
            content=build_message_page("Internal error", "Failed to load moment"),
        )

    if stored_moment is None:
        return HTMLResponse(content=build_message_page("No moments yet", "No moments yet"))

    return HTMLResponse(content=build_moment_card_html(serialize_moment(stored_moment)))


@app.get("/media/{filename:path}")
def proxy_media(filename: str = PathParam(..., min_length=1)) -> Response:
    if not PHOTOSTOCK_BASE_URL:
        return Response(status_code=503, content="Media service is not configured")

    try:
        _, image_name = resolve_image_name_for_photostock(filename)
    except ValueError as exc:
        raise ApiError(status_code=400, code="VALIDATION_ERROR", message=f"Invalid filename: {exc}") from exc

    url = f"{PHOTOSTOCK_BASE_URL}/images/{quote(image_name, safe='')}"
    timeout_seconds = PHOTOSTOCK_TIMEOUT_MS / 1000

    try:
        upstream = urlopen(url, timeout=timeout_seconds)
        content_type, response_headers = build_media_proxy_headers(getattr(upstream, "headers", None))
        status_code = int(getattr(upstream, "status", 200))
        return StreamingResponse(
            iter_stream_chunks(upstream),
            status_code=status_code,
            media_type=content_type,
            headers=response_headers,
        )
    except HTTPError as exc:
        content_type, response_headers = build_media_proxy_headers(getattr(exc, "headers", None))
        return StreamingResponse(
            iter_stream_chunks(exc),
            status_code=exc.code,
            media_type=content_type,
            headers=response_headers,
        )
    except URLError:
        logger.exception("Failed to proxy image '%s' via photostock", filename)
        return Response(status_code=503, content="Media service is unavailable")
    except OSError:
        logger.exception("Failed to proxy image '%s' via photostock", filename)
        return Response(status_code=503, content="Media service is unavailable")


@app.get("/cards/view/{moment_id}", response_class=HTMLResponse)
@app.get("/view/{moment_id}", response_class=HTMLResponse, include_in_schema=False)
def view_moment_by_id(moment_id: str = PathParam(..., min_length=1)) -> HTMLResponse:
    try:
        object_id = ObjectId(moment_id)
    except InvalidId:
        return HTMLResponse(status_code=404, content=build_message_page("Moment not found", "Moment not found"))

    try:
        stored_moment = MOMENTS_COLLECTION.find_one({"_id": object_id})
    except PyMongoError as exc:
        logger.exception("Failed to load moment '%s' for /cards/view", moment_id)
        return HTMLResponse(
            status_code=500,
            content=build_message_page("Internal error", "Failed to load moment"),
        )

    if stored_moment is None:
        return HTMLResponse(status_code=404, content=build_message_page("Moment not found", "Moment not found"))

    return HTMLResponse(content=build_moment_card_html(serialize_moment(stored_moment)))


@app.get("/api/v1/cards/{moment_id}")
@app.get("/api/v1/moments/{moment_id}", include_in_schema=False)
def get_moment(moment_id: str = PathParam(..., min_length=1)) -> dict[str, Any]:
    object_id = parse_object_id(moment_id)

    try:
        stored_moment = MOMENTS_COLLECTION.find_one({"_id": object_id})
    except PyMongoError as exc:
        logger.exception("Failed to load moment '%s'", moment_id)
        raise ApiError(status_code=500, code="INTERNAL_ERROR", message="Failed to load moment") from exc

    if stored_moment is None:
        raise ApiError(status_code=404, code="NOT_FOUND", message="Moment not found")

    return serialize_moment(stored_moment)


@app.patch("/api/v1/cards/{moment_id}")
@app.patch("/api/v1/moments/{moment_id}", include_in_schema=False)
def update_moment(
    payload: MomentPatchPayload,
    moment_id: str = PathParam(..., min_length=1),
) -> dict[str, Any]:
    object_id = parse_object_id(moment_id)

    update_payload = payload.model_dump(exclude_unset=True)
    if not update_payload:
        raise ApiError(
            status_code=400,
            code="VALIDATION_ERROR",
            message="At least one field is required for patch",
        )

    if "images" in update_payload and update_payload["images"] is None:
        raise ApiError(
            status_code=400,
            code="VALIDATION_ERROR",
            message="'images' must be a non-empty array",
        )

    if "tags" in update_payload:
        update_payload["tags"] = update_payload["tags"] or []

    update_payload["updatedAt"] = utc_now()

    try:
        updated_moment = MOMENTS_COLLECTION.find_one_and_update(
            {"_id": object_id},
            {"$set": update_payload},
            return_document=ReturnDocument.AFTER,
        )
    except PyMongoError as exc:
        logger.exception("Failed to update moment '%s'", moment_id)
        raise ApiError(status_code=500, code="INTERNAL_ERROR", message="Failed to update moment") from exc

    if updated_moment is None:
        raise ApiError(status_code=404, code="NOT_FOUND", message="Moment not found")

    return serialize_moment(updated_moment)


@app.delete("/api/v1/cards/{moment_id}", status_code=204)
@app.delete("/api/v1/moments/{moment_id}", status_code=204, include_in_schema=False)
def delete_moment(moment_id: str = PathParam(..., min_length=1)) -> Response:
    object_id = parse_object_id(moment_id)

    try:
        delete_result = MOMENTS_COLLECTION.delete_one({"_id": object_id})
    except PyMongoError as exc:
        logger.exception("Failed to delete moment '%s'", moment_id)
        raise ApiError(status_code=500, code="INTERNAL_ERROR", message="Failed to delete moment") from exc

    if delete_result.deleted_count == 0:
        raise ApiError(status_code=404, code="NOT_FOUND", message="Moment not found")

    return Response(status_code=204)
