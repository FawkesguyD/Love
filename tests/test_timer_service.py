import asyncio
import unittest
from datetime import datetime

import httpx

import services.timer.app.main as main


class TimerServiceTests(unittest.TestCase):
    def _get(self, path: str) -> httpx.Response:
        async def _request() -> httpx.Response:
            transport = httpx.ASGITransport(app=main.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.get(path)

        return asyncio.run(_request())

    def test_health_returns_ok(self) -> None:
        response = self._get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_time_response_format_and_ranges(self) -> None:
        response = self._get("/time")

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["since"], "2025-03-06T18:00:00.000Z")
        self.assertIn("now", payload)
        datetime.fromisoformat(payload["now"].replace("Z", "+00:00"))

        self.assertIn("elapsed", payload)
        elapsed = payload["elapsed"]

        self.assertIsInstance(elapsed["years"], int)
        self.assertIsInstance(elapsed["days"], int)
        self.assertIsInstance(elapsed["hours"], int)
        self.assertIsInstance(elapsed["minutes"], int)
        self.assertIsInstance(elapsed["seconds"], int)
        self.assertIsInstance(payload["totalSeconds"], int)

        self.assertGreaterEqual(elapsed["years"], 0)
        self.assertGreaterEqual(elapsed["days"], 0)
        self.assertGreaterEqual(elapsed["hours"], 0)
        self.assertGreaterEqual(elapsed["minutes"], 0)
        self.assertGreaterEqual(elapsed["seconds"], 0)
        self.assertGreaterEqual(payload["totalSeconds"], 0)

        self.assertLess(elapsed["hours"], 24)
        self.assertLess(elapsed["minutes"], 60)
        self.assertLess(elapsed["seconds"], 60)

    def test_view_returns_html(self) -> None:
        response = self._get("/view")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/html"))
        self.assertIn("Timer", response.text)
        self.assertIn("This timer will never stop", response.text)
        self.assertIn("setInterval", response.text)
        self.assertIn("fetch(\"/time\")", response.text)
        self.assertIn('data-theme="light"', response.text)
        self.assertNotIn("Since:", response.text)
        self.assertNotIn("Now (UTC):", response.text)
        self.assertNotIn("Theme:", response.text)

    def test_view_dark_theme(self) -> None:
        response = self._get("/view?theme=dark")

        self.assertEqual(response.status_code, 200)
        self.assertIn('data-theme="dark"', response.text)


if __name__ == "__main__":
    unittest.main()
