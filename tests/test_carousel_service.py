import asyncio
import os
import unittest

import httpx

os.environ.setdefault("S3_ENDPOINT", "http://s3:9000")
os.environ.setdefault("S3_ACCESS_KEY", "test_s3_access_key")
os.environ.setdefault("S3_SECRET_KEY", "test_s3_secret_key")
os.environ.setdefault("S3_BUCKET", "images")

import services.carousel.app.main as main
from fake_s3 import FakeS3Client


class CarouselServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_s3_client = main.S3_CLIENT
        self.original_s3_bucket = main.S3_BUCKET
        self.original_cursor = main._selection_cursor

        self.s3_client = FakeS3Client()
        main.S3_CLIENT = self.s3_client
        main.S3_BUCKET = "images"
        main._selection_cursor = 0

    def tearDown(self) -> None:
        main.S3_CLIENT = self.original_s3_client
        main.S3_BUCKET = self.original_s3_bucket
        main._selection_cursor = self.original_cursor

    def _put(self, key: str, content: bytes = b"fake", content_type: str | None = None) -> None:
        self.s3_client.put_object(key=key, data=content, content_type=content_type)

    def _get(self, path: str) -> httpx.Response:
        async def _request() -> httpx.Response:
            transport = httpx.ASGITransport(app=main.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.get(path)

        return asyncio.run(_request())

    def test_build_unique_image_index(self) -> None:
        image_index = main.build_unique_image_index(
            [
                "cat.jpg",
                "cat.webp",
                "dog.png",
                "invalid/key.png",
                "bad$name.png",
                "dog.jpeg",
            ]
        )

        self.assertEqual(image_index["cat"], "cat.webp")
        self.assertEqual(image_index["dog"], "dog.png")
        self.assertNotIn("bad$name", image_index)

    def test_carousel_returns_image_binary(self) -> None:
        self._put("cat.png", content=b"cat", content_type="image/png")

        response = self._get("/carousel")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("image/"))
        self.assertEqual(response.headers["cache-control"], "no-store, max-age=0")
        self.assertIsInstance(response.content, bytes)
        self.assertGreater(len(response.content), 0)

    def test_carousel_random_true_returns_image(self) -> None:
        self._put("cat.png", content_type="image/png")
        self._put("dog.jpg", content_type="image/jpeg")

        response = self._get("/carousel?random=true")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("image/"))
        self.assertEqual(response.headers["x-carousel-mode"], "random")

    def test_carousel_sequence_default_cycles(self) -> None:
        self._put("a-cat.png", content_type="image/png")
        self._put("b-dog.jpg", content_type="image/jpeg")

        first = self._get("/carousel").headers["x-carousel-image"]
        second = self._get("/carousel").headers["x-carousel-image"]
        third = self._get("/carousel").headers["x-carousel-image"]

        self.assertEqual(first, "a-cat")
        self.assertEqual(second, "b-dog")
        self.assertEqual(third, "a-cat")

    def test_refresh_parameter_is_not_supported(self) -> None:
        self._put("cat.png", content_type="image/png")

        response = self._get("/carousel?refresh=10")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Query parameter 'refresh' is no longer supported")

    def test_carousel_view_returns_html_with_timer_and_random_mode(self) -> None:
        response = self._get("/carousel/view?random=true")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/html"))
        self.assertIn("<img id=\"carousel\"", response.text)
        self.assertIn("setInterval", response.text)
        self.assertIn("/carousel?random=true", response.text)
        self.assertIn("const intervalMs = 10000;", response.text)

    def test_carousel_view_accepts_custom_refresh_seconds(self) -> None:
        response = self._get("/carousel/view?random=false&refresh=5")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/html"))
        self.assertIn("/carousel?random=false", response.text)
        self.assertIn("const intervalMs = 5000;", response.text)

    def test_carousel_view_invalid_refresh_returns_400(self) -> None:
        response = self._get("/carousel/view?refresh=0")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Invalid 'refresh' value. Must be between 1 and 3600")

    def test_empty_bucket_returns_404(self) -> None:
        response = self._get("/carousel")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "No images available for carousel")

    def test_carousel_image_endpoint_removed(self) -> None:
        self._put("cat.png", content_type="image/png")

        response = self._get("/carousel/image")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
