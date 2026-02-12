import asyncio
import unittest

import httpx

import services.moments.app.main as main


class MomentsTimelinePageTests(unittest.TestCase):
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
        self.assertIn('src="/static/timeline-app.mjs"', response.text)
        self.assertIn('href="/static/timeline.css"', response.text)

    def test_timeline_static_assets_are_served(self) -> None:
        css = self._get("/static/timeline.css")
        js = self._get("/static/timeline-app.mjs")

        self.assertEqual(css.status_code, 200)
        self.assertTrue(css.headers["content-type"].startswith("text/css"))
        self.assertIn(".timeline-card", css.text)

        self.assertEqual(js.status_code, 200)
        self.assertIn("javascript", js.headers["content-type"])
        self.assertIn("fetchTimelineMoments", js.text)


if __name__ == "__main__":
    unittest.main()
