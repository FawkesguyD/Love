import asyncio
import os
import unittest

import boto3
import httpx
from botocore.config import Config

os.environ.setdefault("S3_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("S3_ACCESS_KEY", "test_s3_access_key")
os.environ.setdefault("S3_SECRET_KEY", "test_s3_secret_key")
os.environ.setdefault("S3_BUCKET", "images")

import services.carousel.app.main as carousel_main
import services.photostock.app.main as image_main


RUN_MINIO_INTEGRATION = os.getenv("RUN_MINIO_INTEGRATION", "0") == "1"


@unittest.skipUnless(RUN_MINIO_INTEGRATION, "Set RUN_MINIO_INTEGRATION=1 to run MinIO integration tests")
class MinioIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        endpoint = os.getenv("S3_ENDPOINT", "http://localhost:9000")
        access_key = os.getenv("S3_ACCESS_KEY", "test_s3_access_key")
        secret_key = os.getenv("S3_SECRET_KEY", "test_s3_secret_key")
        region = os.getenv("S3_REGION", "us-east-1")
        bucket = os.getenv("S3_TEST_BUCKET", "images-integration")

        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            use_ssl=False,
            config=Config(s3={"addressing_style": "path"}),
        )

        try:
            client.create_bucket(Bucket=bucket)
        except Exception:
            pass

        client.put_object(Bucket=bucket, Key="integration-cat.png", Body=b"cat", ContentType="image/png")
        client.put_object(Bucket=bucket, Key="integration-dog.jpg", Body=b"dog", ContentType="image/jpeg")

        cls.bucket = bucket
        cls.s3_client = client

        cls.original_image_client = image_main.S3_CLIENT
        cls.original_image_bucket = image_main.S3_BUCKET
        image_main.S3_CLIENT = client
        image_main.S3_BUCKET = bucket

        cls.original_carousel_client = carousel_main.S3_CLIENT
        cls.original_carousel_bucket = carousel_main.S3_BUCKET
        cls.original_last_image_name = carousel_main._last_image_name
        carousel_main.S3_CLIENT = client
        carousel_main.S3_BUCKET = bucket
        carousel_main._last_image_name = None

    @classmethod
    def tearDownClass(cls) -> None:
        image_main.S3_CLIENT = cls.original_image_client
        image_main.S3_BUCKET = cls.original_image_bucket

        carousel_main.S3_CLIENT = cls.original_carousel_client
        carousel_main.S3_BUCKET = cls.original_carousel_bucket
        carousel_main._last_image_name = cls.original_last_image_name

    def _get(self, app, path: str) -> httpx.Response:
        async def _request() -> httpx.Response:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.get(path)

        return asyncio.run(_request())

    def test_images_endpoint_reads_from_minio(self) -> None:
        response = self._get(image_main.app, "/images/integration-cat?display=true")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(response.headers["content-disposition"], 'inline; filename="integration-cat.png"')

    def test_carousel_image_reads_from_minio(self) -> None:
        first = self._get(carousel_main.app, "/carousel")
        second = self._get(carousel_main.app, "/carousel")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(first.headers["content-type"].startswith("image/"))
        self.assertTrue(second.headers["content-type"].startswith("image/"))
        self.assertNotEqual(first.headers["x-carousel-image"], second.headers["x-carousel-image"])

    def test_carousel_view_uses_carousel_endpoint(self) -> None:
        response = self._get(carousel_main.app, "/carousel/view?random=true")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/html"))
        self.assertIn("/carousel?random=true", response.text)
        self.assertNotIn("/carousel/image", response.text)


if __name__ == "__main__":
    unittest.main()
