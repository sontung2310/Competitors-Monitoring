"""Real browser-fallback coverage using a local JS-rendered page."""

from __future__ import annotations

import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from backend.flask.website_monitoring.service import (
    BROWSER_FETCH_METHOD,
    HttpPageFetcher,
    MIN_RENDERABLE_TEXT_LENGTH,
    _visible_text,
    fetch_page,
)


class _JavaScriptPageHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib handler API
        body = b"""<!doctype html>
<html><body>
  <main id="root"></main>
  <script>
    setTimeout(() => {
      document.getElementById('root').textContent =
        'Rendered by JavaScript in the browser fallback.';
    }, 50);
  </script>
</body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002 - stdlib handler API
        return


class BrowserFetcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _JavaScriptPageHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/js-page"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def test_real_browser_fallback_renders_content_http_does_not(self):
        raw_http = HttpPageFetcher(timeout_seconds=5).fetch(self.url)
        self.assertLess(len(_visible_text(raw_http.content)), MIN_RENDERABLE_TEXT_LENGTH)

        result = fetch_page(self.url)

        self.assertEqual(result.fetch_method, BROWSER_FETCH_METHOD)
        self.assertEqual(result.http_status, 200)
        self.assertIn("Rendered by JavaScript", result.content)


if __name__ == "__main__":
    unittest.main()
