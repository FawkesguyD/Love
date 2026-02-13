import logging
import mimetypes
import os
import re
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Path as PathParam, Query
from fastapi.responses import Response

app = FastAPI(title="Image API")
logger = logging.getLogger("photostock")

ALLOWED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")
TRUE_VALUES = {"true", "1", "yes"}
FALSE_VALUES = {"false", "0", "no"}
SAFE_IMAGE_RE = re.compile(r"^[A-Za-z0-9_-]+$")
CACHE_CONTROL_VALUE = "public, max-age=3600"

load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)


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


def parse_display(value: str | None) -> bool:
    if value is None:
        return True

    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False

    raise HTTPException(
        status_code=400,
        detail="Invalid 'display' value. Use one of: true/false, 1/0, yes/no",
    )


def validate_image_name(image: str) -> str:
    image_name = image.strip()
    path = Path(image_name)

    if (
        not image_name
        or image_name in {".", ".."}
        or "/" in image_name
        or "\\" in image_name
        or "\x00" in image_name
        or path.is_absolute()
        or path.name != image_name
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid 'image' path. Use a file name without directories",
        )

    if "." in image_name:
        raise HTTPException(status_code=400, detail="image must be without extension")

    if not SAFE_IMAGE_RE.fullmatch(image_name):
        raise HTTPException(
            status_code=400,
            detail="Invalid 'image' name. Use only letters, numbers, '-' and '_'",
        )

    return image_name


def list_s3_keys(prefix: str) -> list[str]:
    keys: list[str] = []
    continuation: str | None = None

    while True:
        payload = {
            "Bucket": S3_BUCKET,
            "Prefix": prefix,
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


def find_matching_keys(image_name: str, object_keys: list[str]) -> list[str]:
    matches: list[str] = []

    for key in object_keys:
        if "/" in key or "\\" in key or "\x00" in key:
            continue

        stem, ext = os.path.splitext(key)
        if stem != image_name:
            continue

        if ext.lower() not in ALLOWED_EXTENSIONS:
            continue

        matches.append(key)

    return sorted(matches)


def find_image_key(image_name: str) -> str:
    object_keys = list_s3_keys(prefix=f"{image_name}.")
    matches = find_matching_keys(image_name=image_name, object_keys=object_keys)

    if not matches:
        raise HTTPException(status_code=404, detail="Image not found")

    if len(matches) > 1:
        variants = ", ".join(sorted(matches))
        raise HTTPException(
            status_code=409,
            detail=f"Multiple files found for '{image_name}': {variants}",
        )

    return matches[0]


def load_image_object(key: str) -> tuple[bytes, str, str]:
    try:
        response = S3_CLIENT.get_object(Bucket=S3_BUCKET, Key=key)
    except ClientError as exc:
        logger.exception("Failed to fetch object '%s' from bucket '%s'", key, S3_BUCKET)
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"NoSuchKey", "404"}:
            raise HTTPException(status_code=404, detail="Image not found") from exc
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


@app.get("/images/{image}")
def get_image(
    image: str = PathParam(..., description="Image base name without extension"),
    display: str | None = Query(default=None),
) -> Response:
    image_name = validate_image_name(image)
    display_inline = parse_display(display)

    try:
        key = find_image_key(image_name)
    except StorageAccessError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    body, media_type, filename = load_image_object(key)

    disposition = "inline" if display_inline else "attachment"
    headers = {
        "Content-Disposition": f'{disposition}; filename="{filename}"',
        "Cache-Control": CACHE_CONTROL_VALUE,
    }

    return Response(content=body, media_type=media_type, headers=headers)
