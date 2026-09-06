"""Live verification for the concrete browser fallback.

Run directly with:
    python tests/live_browser_fetcher_verification.py

The local page proves JS rendering without depending on a third-party site;
the JD Sports check proves a usable real HTTP response does not launch the
browser fallback.
"""

from __future__ import annotations

import threading
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.website_monitoring.service import (
    BROWSER_FETCH_METHOD,
    BrowserPageFetcher,
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


class _CountingBrowserFetcher:
    def __init__(self):
        self.delegate = BrowserPageFetcher()
        self.calls = 0

    def fetch(self, url):
        self.calls += 1
        return self.delegate.fetch(url)


def _verify_local_js_page() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _JavaScriptPageHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/js-page"
        raw_http = HttpPageFetcher(timeout_seconds=5).fetch(url)
        assert len(_visible_text(raw_http.content)) < MIN_RENDERABLE_TEXT_LENGTH

        result = fetch_page(url)
        assert result.fetch_method == BROWSER_FETCH_METHOD
        assert result.http_status == 200
        assert "Rendered by JavaScript" in result.content
        print(
            "local_js_page: "
            f"http_visible_chars={len(_visible_text(raw_http.content))} "
            f"fetch_method={result.fetch_method} "
            f"http_status={result.http_status} "
            "rendered_marker=True"
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _verify_jd_sports_http_first() -> None:
    browser = _CountingBrowserFetcher()
    result = fetch_page(
        "https://www.jd-sports.com.au/sale/",
        browser_fetcher=browser,
    )
    assert result.fetch_method == "HTTP"
    assert result.http_status == 200
    assert browser.calls == 0
    print(
        "jd_sports_sale: "
        f"fetch_method={result.fetch_method} "
        f"http_status={result.http_status} "
        f"content_chars={len(result.content)} "
        f"browser_fallback_calls={browser.calls}"
    )


if __name__ == "__main__":
    _verify_local_js_page()
    _verify_jd_sports_http_first()
