import asyncio
import copy
import os
import random
import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

import httpx
from bson import ObjectId

os.environ.setdefault("MONGO_URI", "mongodb://test_user:test_password@localhost:27017/?authSource=admin")
os.environ.setdefault("MONGO_DB_NAME", "app")

import services.moments.app.main as main


@dataclass
class FakeInsertOneResult:
    inserted_id: ObjectId


@dataclass
class FakeDeleteResult:
    deleted_count: int


@dataclass
class FakeUpdateResult:
    matched_count: int


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self._documents = documents
        self._limit: int | None = None

    def sort(self, sort_spec: list[tuple[str, int]]) -> "FakeCursor":
        for field, direction in reversed(sort_spec):
            reverse = direction == -1
            self._documents.sort(key=lambda document: document.get(field), reverse=reverse)
        return self

    def limit(self, value: int) -> "FakeCursor":
        self._limit = value
        return self

    def __iter__(self):
        if self._limit is None:
            return iter(self._documents)
        return iter(self._documents[: self._limit])


class FakeCollection:
    def __init__(self) -> None:
        self._documents: list[dict[str, Any]] = []

    def create_index(self, *_args, **_kwargs) -> str:
        return "index"

    def insert_one(self, document: dict[str, Any]) -> FakeInsertOneResult:
        stored = copy.deepcopy(document)
        stored["_id"] = stored.get("_id", ObjectId())
        self._documents.append(stored)
        return FakeInsertOneResult(inserted_id=stored["_id"])

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for document in self._documents:
            if self._matches(document, query):
                return copy.deepcopy(document)
        return None

    def find(self, query: dict[str, Any]) -> FakeCursor:
        filtered = [copy.deepcopy(document) for document in self._documents if self._matches(document, query)]
        return FakeCursor(filtered)

    def aggregate(self, pipeline: list[dict[str, Any]]):
        documents = [copy.deepcopy(document) for document in self._documents]
        for stage in pipeline:
            sample_stage = stage.get("$sample")
            if sample_stage is not None:
                size = sample_stage.get("size", 0)
                if not isinstance(size, int) or size <= 0:
                    return iter([])
                if size >= len(documents):
                    return iter(documents)
                return iter(random.sample(documents, k=size))
        return iter(documents)

    def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> FakeUpdateResult:
        for index, document in enumerate(self._documents):
            if self._matches(document, query):
                next_document = copy.deepcopy(document)
                next_document.update(update.get("$set", {}))
                self._documents[index] = next_document
                return FakeUpdateResult(matched_count=1)
        return FakeUpdateResult(matched_count=0)

    def find_one_and_update(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
        return_document: Any | None = None,
    ) -> dict[str, Any] | None:
        _ = return_document
        for index, document in enumerate(self._documents):
            if self._matches(document, query):
                next_document = copy.deepcopy(document)
                next_document.update(update.get("$set", {}))
                self._documents[index] = next_document
                return copy.deepcopy(next_document)
        return None

    def delete_one(self, query: dict[str, Any]) -> FakeDeleteResult:
        for index, document in enumerate(self._documents):
            if self._matches(document, query):
                del self._documents[index]
                return FakeDeleteResult(deleted_count=1)
        return FakeDeleteResult(deleted_count=0)

    def _matches(self, document: dict[str, Any], query: dict[str, Any]) -> bool:
        if not query:
            return True

        for key, value in query.items():
            if key == "$and":
                if not all(self._matches(document, part) for part in value):
                    return False
                continue

            if key == "$or":
                if not any(self._matches(document, part) for part in value):
                    return False
                continue

            field_value = document.get(key)

            if isinstance(value, dict):
                for operator, expected in value.items():
                    if operator == "$gte" and not (field_value >= expected):
                        return False
                    if operator == "$lte" and not (field_value <= expected):
                        return False
                    if operator == "$gt" and not (field_value > expected):
                        return False
                    if operator == "$lt" and not (field_value < expected):
                        return False
                continue

            if field_value != value:
                return False

        return True


class FakeAdmin:
    def command(self, _name: str) -> dict[str, int]:
        return {"ok": 1}


class FakeMongoClient:
    def __init__(self) -> None:
        self.admin = FakeAdmin()


class FakeUrlopenResponse:
    def __init__(self, *, chunks: list[bytes], status: int = 200, headers: dict[str, str] | None = None) -> None:
        self._chunks = list(chunks)
        self.status = status
        self.headers = headers or {}
        self.closed = False

    def read(self, _size: int = -1) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)

    def close(self) -> None:
        self.closed = True


class MomentsServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_collection = main.MOMENTS_COLLECTION
        self.original_mongo_client = main.MONGO_CLIENT
        self.original_photostock_base_url = main.PHOTOSTOCK_BASE_URL

        main.MOMENTS_COLLECTION = FakeCollection()
        main.MONGO_CLIENT = FakeMongoClient()
        main.PHOTOSTOCK_BASE_URL = "http://photostock:8000"

    def tearDown(self) -> None:
        main.MOMENTS_COLLECTION = self.original_collection
        main.MONGO_CLIENT = self.original_mongo_client
        main.PHOTOSTOCK_BASE_URL = self.original_photostock_base_url

    def _request(self, method: str, path: str, json_payload: dict[str, Any] | None = None) -> httpx.Response:
        async def _send() -> httpx.Response:
            transport = httpx.ASGITransport(app=main.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.request(method, path, json=json_payload)

        return asyncio.run(_send())

    def _create(self, title: str, date_value: datetime) -> dict[str, Any]:
        response = self._request(
            "POST",
            "/api/v1/cards",
            {
                "title": title,
                "date": date_value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "images": [f"{title}-1.jpg", f"{title}-2.jpg"],
            },
        )
        self.assertEqual(response.status_code, 201)
        return response.json()

    def test_create_moment_accepts_filename_list(self) -> None:
        response = self._request(
            "POST",
            "/api/v1/cards",
            {
                "title": "Trip",
                "text": "Morning walk",
                "date": "2026-02-10T12:00:00.000Z",
                "images": ["IMG_001.jpg", "IMG_002.webp"],
            },
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()

        self.assertEqual(payload["title"], "Trip")
        self.assertEqual(payload["visibility"], "public")
        self.assertEqual(payload["images"], ["IMG_001.jpg", "IMG_002.webp"])
        self.assertIn("createdAt", payload)
        self.assertIn("updatedAt", payload)

    def test_create_moment_rejects_image_with_slash(self) -> None:
        response = self._request(
            "POST",
            "/api/v1/cards",
            {
                "title": "Trip",
                "date": "2026-02-10T12:00:00.000Z",
                "images": ["photos/IMG_001.jpg"],
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def test_create_moment_rejects_image_with_dotdot(self) -> None:
        response = self._request(
            "POST",
            "/api/v1/cards",
            {
                "title": "Trip",
                "date": "2026-02-10T12:00:00.000Z",
                "images": ["IMG..001.jpg"],
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def test_create_moment_rejects_empty_image_name(self) -> None:
        response = self._request(
            "POST",
            "/api/v1/cards",
            {
                "title": "Trip",
                "date": "2026-02-10T12:00:00.000Z",
                "images": ["   "],
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def test_patch_replaces_images(self) -> None:
        created = self._create("trip", datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc))

        response = self._request(
            "PATCH",
            f"/api/v1/cards/{created['_id']}",
            {
                "images": ["NEW_001.jpg", "NEW_002.png"],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["images"], ["NEW_001.jpg", "NEW_002.png"])

    def test_migrate_legacy_images_converts_key_objects(self) -> None:
        legacy_document = {
            "_id": ObjectId(),
            "title": "legacy",
            "text": "old",
            "date": datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc),
            "images": [
                {"name": "cover", "key": "photos/a.jpg", "order": 1},
                {"name": "first", "key": "photos/b.png", "order": 0},
            ],
            "visibility": "public",
            "tags": [],
            "createdAt": datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc),
            "updatedAt": datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc),
        }
        main.MOMENTS_COLLECTION.insert_one(legacy_document)

        main.migrate_legacy_images()

        stored = main.MOMENTS_COLLECTION.find_one({"_id": legacy_document["_id"]})
        self.assertIsNotNone(stored)
        self.assertEqual(stored["images"], ["b.png", "a.jpg"])

    def test_list_uses_cursor_without_duplicates(self) -> None:
        created_a = self._create("alpha", datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc))
        created_b = self._create("beta", datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc))
        created_c = self._create("gamma", datetime(2026, 2, 9, 12, 0, 0, tzinfo=timezone.utc))

        first_page = self._request("GET", "/api/v1/cards?limit=2&order=desc")
        self.assertEqual(first_page.status_code, 200)

        first_payload = first_page.json()
        first_ids = [moment["_id"] for moment in first_payload["moments"]]
        self.assertEqual(len(first_ids), 2)
        self.assertIsNotNone(first_payload["nextCursor"])

        second_page = self._request(
            "GET",
            f"/api/v1/cards?limit=2&order=desc&cursor={first_payload['nextCursor']}",
        )
        self.assertEqual(second_page.status_code, 200)

        second_payload = second_page.json()
        second_ids = [moment["_id"] for moment in second_payload["moments"]]

        self.assertEqual(len(second_ids), 1)
        self.assertEqual(set(first_ids).intersection(second_ids), set())
        self.assertEqual(set(first_ids).union(second_ids), {created_a["_id"], created_b["_id"], created_c["_id"]})

    def test_view_returns_html_with_latest_moment(self) -> None:
        self._create("older", datetime(2026, 2, 9, 12, 0, 0, tzinfo=timezone.utc))
        latest = self._create("latest", datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc))

        response = self._request("GET", "/cards/view")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/html"))
        self.assertIn("latest", response.text)
        self.assertNotIn("older", response.text)
        self.assertIn(f"/api/v1/cards/{latest['_id']}", response.text)
        self.assertIn('data-testid="moment-card"', response.text)
        self.assertIn('data-testid="moment-title"', response.text)
        self.assertIn('data-testid="moment-date"', response.text)
        self.assertIn("2026-02-10T12:00Z", response.text)
        self.assertIn('src="/api/images/latest-1"', response.text)
        self.assertNotIn("http://photostock:8000/images/", response.text)

    def test_view_random_accepts_parameter(self) -> None:
        self._create("alpha", datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc))
        self._create("beta", datetime(2026, 2, 11, 12, 0, 0, tzinfo=timezone.utc))

        response = self._request("GET", "/cards/view?random=true")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/html"))
        self.assertIn('data-testid="moment-card"', response.text)

    def test_view_limits_spiral_gallery_to_six_images(self) -> None:
        response_create = self._request(
            "POST",
            "/api/v1/cards",
            {
                "title": "spiral",
                "date": "2026-02-11T12:00:00.000Z",
                "images": [
                    "spiral-1.jpg",
                    "spiral-2.jpg",
                    "spiral-3.jpg",
                    "spiral-4.jpg",
                    "spiral-5.jpg",
                    "spiral-6.jpg",
                    "spiral-7.jpg",
                    "spiral-8.jpg",
                ],
            },
        )
        self.assertEqual(response_create.status_code, 201)

        response = self._request("GET", "/cards/view")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text.count('src="/api/images/spiral-'), 6)
        self.assertIn("+2 more", response.text)

    def test_view_by_id_returns_200_and_404(self) -> None:
        created = self._create("one", datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc))

        found = self._request("GET", f"/cards/view/{created['_id']}")
        self.assertEqual(found.status_code, 200)
        self.assertTrue(found.headers["content-type"].startswith("text/html"))
        self.assertIn("one", found.text)
        self.assertIn('src="/api/images/one-1"', found.text)
        self.assertNotIn("http://photostock:8000/images/", found.text)

        missing = self._request("GET", f"/cards/view/{ObjectId()}")
        self.assertEqual(missing.status_code, 404)
        self.assertTrue(missing.headers["content-type"].startswith("text/html"))
        self.assertIn("Moment not found", missing.text)

    def test_media_proxy_streams_image_from_photostock(self) -> None:
        captured_calls: list[tuple[str, float]] = []
        upstream_response = FakeUrlopenResponse(
            chunks=[b"abc", b"def"],
            status=200,
            headers={
                "Content-Type": "image/jpeg",
                "Cache-Control": "public, max-age=3600",
            },
        )

        def fake_urlopen(url: str, timeout: float):
            captured_calls.append((url, timeout))
            return upstream_response

        with patch.object(main, "urlopen", side_effect=fake_urlopen):
            response = self._request("GET", "/media/second_date-1.jpg")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"abcdef")
        self.assertEqual(response.headers["content-type"], "image/jpeg")
        self.assertEqual(response.headers["cache-control"], "public, max-age=3600")
        self.assertEqual(
            captured_calls,
            [("http://photostock:8000/images/second_date-1", main.PHOTOSTOCK_TIMEOUT_MS / 1000)],
        )
        self.assertTrue(upstream_response.closed)

    def test_media_proxy_rejects_invalid_filename(self) -> None:
        with patch.object(main, "urlopen") as mocked_urlopen:
            response_with_dotdot = self._request("GET", "/media/%2E%2E.jpg")
            response_with_slash = self._request("GET", "/media/a%2Fb.jpg")

        self.assertEqual(response_with_dotdot.status_code, 400)
        self.assertEqual(response_with_slash.status_code, 400)
        mocked_urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
