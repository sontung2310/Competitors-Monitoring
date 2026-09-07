"""Unit coverage for the standalone Layer 2 monitoring mechanics."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.flask.website_monitoring.service import (
    BROWSER_FETCH_METHOD,
    HTTP_FETCH_METHOD,
    BrowserFetchError,
    FetchResult,
    HttpResponse,
    compare_hashes,
    fetch_page,
    generate_diff,
    hash_content,
    normalize_content,
)


class MonitoringEngineTests(unittest.TestCase):
    def test_normalization_removes_request_and_render_noise(self):
        first = """
        <!doctype html>
        <html><head>
          <style>.ad { display: block; }</style>
          <script nonce="request-one">window.renderedAt = 1;</script>
        </head><body>
          <!-- rendered at 2026-09-04T04:00:00Z -->
          <main id="main">
            <h1>Competitor monitoring</h1>
            <p>Stable   visible content.</p>
            <form><input type="hidden" name="csrfmiddlewaretoken" value="token-one"></form>
            <iframe id="ad-12345" src="/ad?cb=111&utm_source=one&slot=hero"></iframe>
          </main>
        </body></html>
        """
        second = """
        <HTML><HEAD>
          <STYLE>.ad { display: none; }</STYLE>
          <SCRIPT nonce="request-two">window.renderedAt = 2;</SCRIPT>
        </HEAD><BODY>
          <!-- rendered at 2026-09-04T04:00:01Z -->
          <MAIN id="main"><H1>Competitor monitoring</H1>
          <P>Stable visible   content.</P>
          <FORM><INPUT value="token-two" name="csrfmiddlewaretoken" type="hidden"></FORM>
          <IFRAME src="/ad?slot=hero&cb=222&utm_source=two" id="ad-999999"></IFRAME>
          </MAIN>
        </BODY></HTML>
        """

        normalized_first = normalize_content(first)
        normalized_second = normalize_content(second)

        self.assertEqual(normalized_first, normalized_second)
        self.assertEqual(
            hash_content(normalized_first),
            hash_content(normalized_second),
        )

    def test_normalization_preserves_meaningful_content_and_query_changes(self):
        first = '<main><h1>Services</h1><a href="/services?id=1&utm_source=a">View</a></main>'
        second = '<main><h1>Different services</h1><a href="/services?id=2&utm_source=b">View</a></main>'

        self.assertNotEqual(normalize_content(first), normalize_content(second))
        self.assertNotEqual(
            hash_content(normalize_content(first)),
            hash_content(normalize_content(second)),
        )

    def test_normalization_removes_wordpress_comment_form_plugin_noise(self):
        first = (
            '<main><div class="gf_browser_chrome gform_wrapper">'
            '<p>Meaningful form introduction.</p>'
            '<input class="gform_hidden" name="state_5" type="hidden" value="token-one" />'
            '<input name="campaign" type="hidden" value="spring-sale" />'
            '<li class="gfield gfield--type-honeypot"><label>Email</label>'
            '<input name="input_10" type="text" value="" /></li>'
            '<p class="akismet-fields-container" data-prefix="ak_">'
            '<textarea name="ak_hp_textarea"></textarea>'
            '<input id="ak_js_1" name="ak_js" type="hidden" value="146" />'
            '</p></div></main>'
        )
        second = (
            '<main><div class="gf_browser_unknown gform_wrapper">'
            '<p>Meaningful form introduction.</p>'
            '<input class="gform_hidden" name="state_5" type="hidden" value="token-two" />'
            '<input name="campaign" type="hidden" value="spring-sale" />'
            '<li class="gfield gfield--type-honeypot"><label>Phone</label>'
            '<input name="input_10" type="text" value="" /></li>'
            '<p class="akismet-fields-container" data-prefix="ak_">'
            '<textarea name="ak_hp_textarea"></textarea>'
            '<input id="ak_js_1" name="ak_js" type="hidden" value="219" />'
            '</p></div></main>'
        )

        first_normalized = normalize_content(first)
        second_normalized = normalize_content(second)

        self.assertEqual(first_normalized, second_normalized)
        self.assertIn("gform_wrapper", first_normalized)
        self.assertIn("spring-sale", first_normalized)
        self.assertNotIn("gf_browser_", first_normalized)
        self.assertNotIn("honeypot", first_normalized)
        self.assertNotIn("akismet", first_normalized)
        self.assertNotIn("ak_js", first_normalized)
        self.assertIn("&lt;volatile&gt;", first_normalized)

    def test_hash_comparison_is_deterministic(self):
        normalized = normalize_content("<p>Same content</p>")
        digest = hash_content(normalized)

        self.assertEqual(digest, hash_content(normalized))
        self.assertTrue(compare_hashes(digest, digest))
        self.assertFalse(compare_hashes(digest, hash_content("<p>Changed</p>")))

    def test_http_response_is_returned_without_browser_when_usable(self):
        calls: list[str] = []

        def http_fetcher(url: str) -> HttpResponse:
            calls.append(f"http:{url}")
            return HttpResponse(
                "<html><body>This page has enough visible content to be usable.</body></html>",
                200,
                {"Content-Type": "text/html; charset=utf-8"},
            )

        def browser_fetcher(url: str) -> HttpResponse:
            calls.append(f"browser:{url}")
            return HttpResponse("browser result", 200)

        result = fetch_page(
            "https://example.com/",
            http_fetcher=http_fetcher,
            browser_fetcher=browser_fetcher,
        )

        self.assertEqual(
            result,
            FetchResult(
                content="<html><body>This page has enough visible content to be usable.</body></html>",
                fetch_method=HTTP_FETCH_METHOD,
                http_status=200,
            ),
        )
        self.assertEqual(calls, ["http:https://example.com/"])

    def test_browser_fallback_is_used_for_unusable_http_response(self):
        calls: list[str] = []

        def http_fetcher(url: str) -> HttpResponse:
            calls.append("http")
            return HttpResponse(
                '<html><body><div id="root"></div></body></html>',
                200,
                {"Content-Type": "text/html"},
            )

        def browser_fetcher(url: str) -> HttpResponse:
            calls.append("browser")
            return HttpResponse(
                "<html><body>Rendered content loaded by the browser fallback.</body></html>",
                200,
                {"Content-Type": "text/html"},
            )

        result = fetch_page(
            "https://example.com/app",
            http_fetcher=http_fetcher,
            browser_fetcher=browser_fetcher,
        )

        self.assertEqual(result.fetch_method, BROWSER_FETCH_METHOD)
        self.assertEqual(result.http_status, 200)
        self.assertIn("Rendered content", result.content)
        self.assertEqual(calls, ["http", "browser"])

    def test_unusable_http_without_browser_adapter_is_explicit(self):
        with self.assertRaises(BrowserFetchError):
            fetch_page(
                "https://example.com/app",
                http_fetcher=lambda url: HttpResponse("<div id='root'></div>", 200),
            )

    def test_changed_content_produces_non_empty_diff(self):
        previous = "<main>Old service copy</main>\n"
        current = "<main>New service copy</main>\n"
        previous_hash = hash_content(normalize_content(previous))
        current_hash = hash_content(normalize_content(current))

        self.assertFalse(compare_hashes(previous_hash, current_hash))
        diff = generate_diff(previous, current)

        self.assertTrue(diff)
        self.assertIn("Old service copy", diff)
        self.assertIn("New service copy", diff)

    def test_identical_content_skips_diff_call(self):
        content = "<main>Unchanged service copy</main>\n"
        previous_hash = hash_content(normalize_content(content))
        current_hash = hash_content(normalize_content(content))

        with patch(
            "backend.flask.website_monitoring.service.generate_diff",
            wraps=generate_diff,
        ) as diff_mock:
            if not compare_hashes(previous_hash, current_hash):
                generate_diff(content, content)

        diff_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
