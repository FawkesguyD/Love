#!/bin/bash
set -eu

MINIO_ALIAS="${MINIO_ALIAS:-local}"
S3_ENDPOINT="${S3_ENDPOINT:-http://s3:9000}"
S3_ACCESS_KEY="${S3_ACCESS_KEY:-dev}"
S3_SECRET_KEY="${S3_SECRET_KEY:-devpassword}"
S3_BUCKET="${S3_BUCKET:-images}"
SEED_IMAGES_DIR="${SEED_IMAGES_DIR:-/seed-images}"

attempt=1
max_attempts=60

echo "[s3-init] Waiting for MinIO at ${S3_ENDPOINT}"
until mc alias set "${MINIO_ALIAS}" "${S3_ENDPOINT}" "${S3_ACCESS_KEY}" "${S3_SECRET_KEY}" >/dev/null 2>&1; do
  if [ "${attempt}" -ge "${max_attempts}" ]; then
    echo "[s3-init] MinIO is not ready after ${max_attempts} attempts" >&2
    exit 1
  fi

  attempt=$((attempt + 1))
  sleep 2
done

echo "[s3-init] Creating bucket '${S3_BUCKET}' if needed"
mc mb -p "${MINIO_ALIAS}/${S3_BUCKET}" >/dev/null 2>&1 || true

if [ -d "${SEED_IMAGES_DIR}" ]; then
  echo "[s3-init] Mirroring seed images from ${SEED_IMAGES_DIR}"
  mc mirror --overwrite "${SEED_IMAGES_DIR}" "${MINIO_ALIAS}/${S3_BUCKET}"
else
  echo "[s3-init] Seed directory does not exist: ${SEED_IMAGES_DIR}" >&2
fi

echo "[s3-init] Done"
