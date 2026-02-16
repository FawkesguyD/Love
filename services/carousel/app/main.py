import logging
import mimetypes
import os
import random
import re
from pathlib import Path
from threading import Lock

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response

app = FastAPI(title="Carousel Service")
logger = logging.getLogger("carousel")

ALLOWED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")
EXTENSION_PRIORITY = {
    ".webp": 0,
    ".png": 1,
    ".jpg": 2,
    ".jpeg": 3,
    ".gif": 4,
}
TRUE_VALUES = {"true", "1", "yes"}
FALSE_VALUES = {"false", "0", "no"}
SAFE_IMAGE_RE = re.compile(r"^[A-Za-z0-9_-]+$")
VIEW_DEFAULT_REFRESH_SECONDS = 10

# .env is loaded only for local development; in Docker, env vars come from compose
env_file = Path(__file__).resolve().parents[1] / ".env"
if env_file.exists():
    load_dotenv(env_file, override=False)


def require_env_vars(names: list[str]) -> None:
    missing = [name for name in names if not os.getenv(name, "").strip()]
    if missing:
        missing_list = ", ".join(missing)
        raise RuntimeError(f"Missing required environment variables: {missing_list}")


require_env_vars(["S3_ENDPOINT", "S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_BUCKET"])

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "").strip()
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "").strip()
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "").strip()
S3_BUCKET = os.getenv("S3_BUCKET", "").strip()
S3_REGION = os.getenv("S3_REGION", "us-east-1").strip() or "us-east-1"
S3_USE_SSL = os.getenv("S3_USE_SSL", "false").strip().lower() in TRUE_VALUES
S3_FORCE_PATH_STYLE = os.getenv("S3_FORCE_PATH_STYLE", "true").strip().lower() in TRUE_VALUES

_selection_cursor = 0
_selection_lock = Lock()


class RandomValidationError(ValueError):
    pass


class RefreshValidationError(ValueError):
    pass


class StorageAccessError(RuntimeError):
    pass


def create_s3_client():
    s3_config = Config(
        region_name=S3_REGION,
        retries={"max_attempts": 3, "mode": "standard"},
        s3={"addressing_style": "path" if S3_FORCE_PATH_STYLE else "auto"},
    )
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=S3_REGION,
        use_ssl=S3_USE_SSL,
        config=s3_config,
    )


S3_CLIENT = create_s3_client()


def parse_random_mode(value: str | None) -> bool:
    if value is None:
        return False

    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False

    raise RandomValidationError("Invalid 'random' value. Use one of: true/false, 1/0, yes/no")


def parse_view_refresh_seconds(value: str | None) -> int:
    if value is None:
        return VIEW_DEFAULT_REFRESH_SECONDS

    raw = value.strip()
    if not raw:
        raise RefreshValidationError("Invalid 'refresh' value. Use integer seconds between 1 and 3600")

    try:
        seconds = int(raw)
    except ValueError as exc:
        raise RefreshValidationError(
            "Invalid 'refresh' value. Use integer seconds between 1 and 3600"
        ) from exc

    if not (1 <= seconds <= 3600):
        raise RefreshValidationError("Invalid 'refresh' value. Must be between 1 and 3600")

    return seconds


def ensure_refresh_not_supported(request: Request) -> None:
    if "refresh" in request.query_params:
        raise HTTPException(
            status_code=400,
            detail="Query parameter 'refresh' is no longer supported",
        )


def sanitize_image_base_name(value: str) -> str | None:
    name = value.strip()
    if not name:
        return None

    if "/" in name or "\\" in name or "\x00" in name or "." in name:
        return None

    if not SAFE_IMAGE_RE.fullmatch(name):
        return None

    return name


def list_s3_keys() -> list[str]:
    keys: list[str] = []
    continuation: str | None = None

    while True:
        payload = {
            "Bucket": S3_BUCKET,
            "MaxKeys": 1000,
        }
        if continuation is not None:
            payload["ContinuationToken"] = continuation

        try:
            response = S3_CLIENT.list_objects_v2(**payload)
        except (ClientError, BotoCoreError) as exc:
            logger.exception("Failed to list objects in bucket '%s'", S3_BUCKET)
            raise StorageAccessError("Image storage is unavailable") from exc

        for item in response.get("Contents", []):
            key = item.get("Key")
            if isinstance(key, str):
                keys.append(key)

        if not response.get("IsTruncated"):
            break

        continuation = response.get("NextContinuationToken")
        if not continuation:
            break

    return keys


def build_unique_image_index(object_keys: list[str]) -> dict[str, str]:
    image_index: dict[str, str] = {}

    for key in object_keys:
        if "/" in key or "\\" in key or "\x00" in key:
            continue

        stem, ext = os.path.splitext(key)
        normalized_ext = ext.lower()
        if normalized_ext not in ALLOWED_EXTENSIONS:
            continue

        safe_stem = sanitize_image_base_name(stem)
        if safe_stem is None:
            continue

        existing = image_index.get(safe_stem)
        if existing is None:
            image_index[safe_stem] = key
            continue

        existing_ext = os.path.splitext(existing)[1].lower()
        existing_priority = EXTENSION_PRIORITY.get(existing_ext, 999)
        candidate_priority = EXTENSION_PRIORITY.get(normalized_ext, 999)

        if candidate_priority < existing_priority:
            image_index[safe_stem] = key

    return image_index


def list_available_images() -> dict[str, str]:
    object_keys = list_s3_keys()
    return build_unique_image_index(object_keys)


def choose_image(image_index: dict[str, str], use_random: bool) -> tuple[str, str]:
    global _selection_cursor

    if not image_index:
        raise ValueError("image_index must not be empty")

    image_names = sorted(image_index.keys())

    with _selection_lock:
        if use_random:
            selected_name = random.choice(image_names)
        else:
            selected_name = image_names[_selection_cursor % len(image_names)]
            _selection_cursor = (_selection_cursor + 1) % len(image_names)

    selected_key = image_index[selected_name]
    logger.info("Selected carousel image: %s (%s) mode=%s", selected_name, selected_key, "random" if use_random else "sequence")
    return selected_name, selected_key


def load_image_object(key: str) -> tuple[bytes, str, str]:
    try:
        response = S3_CLIENT.get_object(Bucket=S3_BUCKET, Key=key)
    except ClientError as exc:
        logger.exception("Failed to fetch object '%s' from bucket '%s'", key, S3_BUCKET)
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"NoSuchKey", "404"}:
            raise HTTPException(status_code=404, detail="No images available for carousel") from exc
        raise HTTPException(status_code=503, detail="Image storage is unavailable") from exc
    except BotoCoreError as exc:
        logger.exception("Failed to fetch object '%s' from bucket '%s'", key, S3_BUCKET)
        raise HTTPException(status_code=503, detail="Image storage is unavailable") from exc

    body_stream = response["Body"]
    try:
        body = body_stream.read()
    finally:
        close_method = getattr(body_stream, "close", None)
        if callable(close_method):
            close_method()

    filename = Path(key).name.replace("\\", "_").replace('"', "")
    content_type = response.get("ContentType") or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return body, content_type, filename


def build_view_html(use_random: bool, refresh_seconds: int) -> str:
    random_value = "true" if use_random else "false"
    refresh_ms = refresh_seconds * 1000

    return f"""<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>Carousel View</title>
    <style>
      html, body {{
        width: 100%;
        height: 100%;
        margin: 0;
        padding: 0;
        overflow: hidden;
      }}
      img {{
        display: block;
        width: 100vw;
        height: 100vh;
        object-fit: contain;
      }}
    </style>
  </head>
  <body>
    <img id=\"carousel\" alt=\"carousel\" />
    <script>
      const intervalMs = {refresh_ms};
      const image = document.getElementById(\"carousel\");
      const baseUrl = \"/api/carousel?random={random_value}\";

      function nextUrl() {{
        return `${{baseUrl}}&t=${{Date.now()}}`;
      }}

      function reload() {{
        image.src = nextUrl();
      }}

      reload();
      setInterval(reload, intervalMs);
    </script>
  </body>
</html>
"""


@app.get("/carousel")
def carousel_image(
    request: Request,
    random: str | None = Query(default=None),
) -> Response:
    ensure_refresh_not_supported(request)

    try:
        use_random = parse_random_mode(random)
    except RandomValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        image_index = list_available_images()
    except StorageAccessError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not image_index:
        raise HTTPException(status_code=404, detail="No images available for carousel")

    try:
        image_name, selected_key = choose_image(image_index=image_index, use_random=use_random)
    except Exception:
        logger.exception("Failed to choose carousel image")
        raise HTTPException(status_code=500, detail="Failed to choose carousel image")

    body, media_type, filename = load_image_object(selected_key)

    headers = {
        "Content-Disposition": f'inline; filename="{filename}"',
        "Cache-Control": "no-store, max-age=0",
        "Pragma": "no-cache",
        "X-Carousel-Mode": "random" if use_random else "sequence",
        "X-Carousel-Image": image_name,
    }

    return Response(content=body, media_type=media_type, headers=headers)


@app.get("/carousel/view", response_class=HTMLResponse)
def carousel_view(
    random: str | None = Query(default=None),
    refresh: str | None = Query(default=None),
) -> HTMLResponse:
    try:
        use_random = parse_random_mode(random)
    except RandomValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        refresh_seconds = parse_view_refresh_seconds(refresh)
    except RefreshValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    html = build_view_html(use_random=use_random, refresh_seconds=refresh_seconds)
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"})
