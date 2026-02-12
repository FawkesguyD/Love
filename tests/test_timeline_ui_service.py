import asyncio
import unittest

import httpx

import services.timeline_ui.app.main as main


class TimelineUiServiceTests(unittest.TestCase):
    def _get(self, path: str) -> httpx.Response:
        async def _request() -> httpx.Response:
            transport = httpx.ASGITransport(app=main.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.get(path)

        return asyncio.run(_request())

    def test_root_returns_timeline_shell(self) -> None:
        response = self._get("/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/html"))
        self.assertIn('id="timeline-app"', response.text)
        self.assertIn('id="countdown"', response.text)
        self.assertIn("Вместе уже", response.text)
        self.assertIn('src="/static/timeline-app.mjs"', response.text)
        self.assertIn('href="/static/timeline.css"', response.text)

    def test_health_returns_ok(self) -> None:
        response = self._get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "service": "timeline-ui"})

    def test_timeline_static_assets_are_served(self) -> None:
        css = self._get("/static/timeline.css")
        js = self._get("/static/timeline-app.mjs")

        self.assertEqual(css.status_code, 200)
        self.assertTrue(css.headers["content-type"].startswith("text/css"))
        self.assertIn(".timeline-card", css.text)

        self.assertEqual(js.status_code, 200)
        self.assertIn("javascript", js.headers["content-type"])
        self.assertIn("getCardsList", js.text)
        self.assertIn("getTimer", js.text)


if __name__ == "__main__":
    unittest.main()
