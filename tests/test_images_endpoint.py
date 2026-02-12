import asyncio
import unittest

import httpx

import services.photostock.app.main as main
from fake_s3 import FakeS3Client


class ImagesEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_s3_client = main.S3_CLIENT
        self.original_s3_bucket = main.S3_BUCKET

        self.s3_client = FakeS3Client()
        main.S3_CLIENT = self.s3_client
        main.S3_BUCKET = "images"

    def tearDown(self) -> None:
        main.S3_CLIENT = self.original_s3_client
        main.S3_BUCKET = self.original_s3_bucket

    def _put(self, key: str, content: bytes = b"fake", content_type: str | None = None) -> None:
        self.s3_client.put_object(key=key, data=content, content_type=content_type)

    def _get(self, path: str) -> httpx.Response:
        async def _request() -> httpx.Response:
            transport = httpx.ASGITransport(app=main.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.get(path)

        return asyncio.run(_request())

    def test_find_matching_keys_by_name_without_extension(self) -> None:
        matches = main.find_matching_keys(
            image_name="cat",
            object_keys=["cat.jpg", "dog.png", "cat.webp", "dir/cat.png", "cat.txt"],
        )

        self.assertEqual(matches, ["cat.jpg", "cat.webp"])

    def test_inline_success(self) -> None:
        self._put("cat.png", content_type="image/png")

        response = self._get("/images/cat?display=true")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(
            response.headers["content-disposition"],
            'inline; filename="cat.png"',
        )
        self.assertIn("cache-control", response.headers)

    def test_attachment_success(self) -> None:
        self._put("cat.jpg", content_type="image/jpeg")

        response = self._get("/images/cat?display=false")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/jpeg")
        self.assertEqual(
            response.headers["content-disposition"],
            'attachment; filename="cat.jpg"',
        )

    def test_display_default_inline(self) -> None:
        self._put("cat.webp", content_type="image/webp")

        response = self._get("/images/cat")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["content-disposition"],
            'inline; filename="cat.webp"',
        )

    def test_multiple_variants_return_409(self) -> None:
        self._put("cat.webp", content_type="image/webp")
        self._put("cat.png", content_type="image/png")

        response = self._get("/images/cat")

        self.assertEqual(response.status_code, 409)
        self.assertIn("Multiple files found", response.json()["detail"])

    def test_image_with_extension_returns_400(self) -> None:
        response = self._get("/images/cat.png")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "image must be without extension")

    def test_image_with_forbidden_symbols_returns_400(self) -> None:
        response = self._get("/images/ca%24t")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid 'image' name", response.json()["detail"])

    def test_missing_image_returns_404(self) -> None:
        response = self._get("/images/dog")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Image not found")


if __name__ == "__main__":
    unittest.main()
