from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from types import SimpleNamespace

from backend.flask.discovery.classification import (
    CandidateForClassification,
    ClassificationResult,
    DeterministicStubClassifier,
    OpenAIClassifier,
    OpenAIClassifierConfigurationError,
    classify_by_rules,
    classify_candidates,
)
from backend.flask.discovery.normalization import (
    discovery_scope,
    is_html_candidate_url,
    is_system_path,
    normalize_url,
)
from backend.flask.discovery.service import DiscoveryError, DiscoveryService
from backend.flask.discovery.sources import (
    DiscoveredURL,
    FetchResponse,
    InternalLinkSource,
    SitemapSource,
    dedupe_discovered_urls,
    parse_robots_sitemaps,
    parse_sitemap,
)
from backend.flask.website_monitoring.service import HttpResponse, fetch_page


class _FakeCompetitorRepository:
    def __init__(self, competitor):
        self.competitor = competitor

    def get(self, competitor_id, *, user_id=None):
        if competitor_id == self.competitor["id"] and (
            user_id is None or user_id == self.competitor["user_id"]
        ):
            return self.competitor
        return None


class _FakeTargetRepository:
    def __init__(self):
        self.saved = []

    def upsert_discovered_candidate(self, **candidate):
        result = {"id": f"candidate-{len(self.saved) + 1}", **candidate, "active": False}
        self.saved.append(result)
        return result


class _ReviewTargetRepository:
    """Repository double exposing the operations used by candidate review."""

    def __init__(self, candidates=()):
        self.records = [dict(candidate) for candidate in candidates]
        self.next_id = len(self.records) + 1

    def list_for_competitor(self, competitor_id, *, discovery_status=None):
        records = [
            record
            for record in self.records
            if record["competitor_id"] == competitor_id
            and (
                discovery_status is None
                or record.get("discovery_status") == discovery_status
            )
        ]
        return [dict(record) for record in records]

    def list_active_targets(self, competitor_id=None):
        return [
            dict(record)
            for record in self.records
            if record.get("active") is True
            and record.get("discovery_status") == "ACTIVE"
            and (competitor_id is None or record.get("competitor_id") == competitor_id)
        ]

    def get(self, candidate_id, *, competitor_id=None):
        for record in self.records:
            if record["id"] == candidate_id and (
                competitor_id is None or record["competitor_id"] == competitor_id
            ):
                return dict(record)
        return None

    def find_by_url(self, competitor_id, url):
        for record in self.records:
            if record["competitor_id"] == competitor_id and record["url"] == url:
                return dict(record)
        return None

    def create(self, **candidate):
        record = {"id": f"candidate-{self.next_id}", **candidate}
        self.next_id += 1
        self.records.append(record)
        return dict(record)

    def update(self, candidate_id, updates=None, *, competitor_id=None, **fields):
        values = {**(updates or {}), **fields}
        for record in self.records:
            if record["id"] == candidate_id and (
                competitor_id is None or record["competitor_id"] == competitor_id
            ):
                record.update(values)
                return dict(record)
        return None

    def delete(self, candidate_id, *, competitor_id=None):
        for index, record in enumerate(self.records):
            if record["id"] == candidate_id and (
                competitor_id is None or record["competitor_id"] == competitor_id
            ):
                del self.records[index]
                return True
        return False


class _Source:
    def __init__(self, candidates=()):
        self.candidates = tuple(candidates)

    def discover(self, website_url, declared_sitemaps=()):
        return self.candidates


class _Robots:
    def __init__(self, sitemap_urls=()):
        self.sitemaps = tuple(sitemap_urls)

    def sitemap_urls(self, website_url):
        return self.sitemaps


class _RecordingClassifier:
    def __init__(self):
        self.batches = []

    def classify(self, candidates):
        self.batches.append(tuple(candidates))
        return tuple(
            ClassificationResult(
                url=candidate.url,
                page_type="OTHER",
                discovery_status="DISCARDED",
                classification_method="LLM",
            )
            for candidate in candidates
        )


class _FakeOpenAIResponses:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=json.dumps(self.payload))


class _FakeOpenAIClient:
    def __init__(self, payload):
        self.responses = _FakeOpenAIResponses(payload)


@dataclass
class _StaticFetcher:
    responses: dict[str, FetchResponse]

    def fetch(self, url):
        return self.responses[url]


class DiscoveryTests(unittest.TestCase):
    def test_page_type_aware_normalization(self):
        self.assertEqual(
            normalize_url("https://example.com/blog/new-launch"),
            "https://example.com/blog",
        )
        self.assertEqual(
            normalize_url("https://example.com/products/12345"),
            "https://example.com/products/12345",
        )
        self.assertEqual(
            normalize_url("https://example.com/pages/dasdasdasd12323"),
            "https://example.com/pages",
        )
        self.assertEqual(
            normalize_url("https://example.com/pricing?utm_source=newsletter&plan=pro"),
            "https://example.com/pricing?plan=pro",
        )
        self.assertEqual(
            normalize_url("https://example.com/case-study-archive/customer-story"),
            "https://example.com/case-study-archive",
        )
        self.assertEqual(
            normalize_url(
                "https://example.com/blog-posts/local-seo-mastery"
            ),
            "https://example.com/blog-posts",
        )
        self.assertEqual(
            normalize_url("https://example.com/service/social-media"),
            "https://example.com/services",
        )
        self.assertEqual(
            normalize_url("https://example.com/result/customer"),
            "https://example.com/results",
        )
        self.assertEqual(
            discovery_scope("https://example.com/products/widget"),
            "ITEM",
        )
        self.assertEqual(
            discovery_scope("https://example.com/blog-posts/local-seo-mastery"),
            "INDEX",
        )
        for segment in (
            "news-posts",
            "press-releases",
            "client-testimonials",
            "client-reviews",
            "about-lyfe-marketing",
            "career-opportunities",
            "team-members",
        ):
            self.assertEqual(
                discovery_scope(f"https://example.com/{segment}/entry"),
                "INDEX",
            )
            self.assertEqual(
                normalize_url(f"https://example.com/{segment}/entry"),
                f"https://example.com/{segment}",
            )
        self.assertEqual(
            discovery_scope("https://example.com/what-your-score-says-about-you-2"),
            "SECTION",
        )
        self.assertEqual(
            discovery_scope("https://example.com/newsletter"),
            "SECTION",
        )
        self.assertEqual(
            normalize_url("https://example.com/newsletter/latest"),
            "https://example.com/newsletter/latest",
        )
        self.assertEqual(
            discovery_scope("https://example.com/opaque/deep-page"),
            "UNMATCHED",
        )

    def test_universal_candidate_filters_reject_assets_and_system_paths(self):
        self.assertFalse(is_html_candidate_url("https://example.com/logo.png"))
        self.assertTrue(is_html_candidate_url("https://example.com/pricing?page=2"))
        self.assertTrue(is_system_path("https://example.com/wp-json"))
        self.assertTrue(
            is_system_path(
                normalize_url("https://example.com/blog-catagories/google")
            )
        )
        self.assertFalse(
            is_system_path(normalize_url("https://example.com/blog/category/news"))
        )

    def test_source_parsers_handle_robots_namespaces_and_internal_links(self):
        robots = "User-agent: *\nSitemap: /sitemap.xml\nSitemap: https://example.com/sitemap.xml\n"
        self.assertEqual(
            parse_robots_sitemaps(robots, "https://example.com"),
            ("https://example.com/sitemap.xml",),
        )
        kind, locations = parse_sitemap(
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://example.com/pricing</loc></url></urlset>"
        )
        self.assertEqual(kind, "urlset")
        self.assertEqual(locations, ("https://example.com/pricing",))

        fetcher = _StaticFetcher(
            {
                "https://example.com/": FetchResponse(
                    "https://example.com/",
                    200,
                    '<a href="/blog">Blog</a><a href="https://other.example/pricing">No</a>',
                    {},
                )
            }
        )
        links = InternalLinkSource(fetcher).discover("https://example.com")
        self.assertEqual([link.raw_url for link in links], ["https://example.com/blog"])
        self.assertEqual(links[0].title, "Blog")

    def test_homepage_links_prioritize_navigation_over_body_links(self):
        fetcher = _StaticFetcher(
            {
                "https://example.com/": FetchResponse(
                    "https://example.com/",
                    200,
                    "<main><a href='/body-page'>Body</a></main>"
                    "<footer><a href='/footer-page'>Footer</a></footer>"
                    "<header><nav><a href='/services'>Services</a></nav></header>",
                    {},
                )
            }
        )

        links = InternalLinkSource(fetcher).discover("https://example.com")
        self.assertEqual(
            [link.raw_url for link in links],
            [
                "https://example.com/services",
                "https://example.com/footer-page",
                "https://example.com/body-page",
            ],
        )

    def test_sitemap_index_is_collected_recursively(self):
        fetcher = _StaticFetcher(
            {
                "https://example.com/sitemap.xml": FetchResponse(
                    "https://example.com/sitemap.xml",
                    200,
                    '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    "<sitemap><loc>/pages.xml</loc></sitemap></sitemapindex>",
                    {},
                ),
                "https://example.com/sitemap_index.xml": FetchResponse(
                    "https://example.com/sitemap_index.xml", 404, "", {}
                ),
                "https://example.com/pages.xml": FetchResponse(
                    "https://example.com/pages.xml",
                    200,
                    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    "<url><loc>https://example.com/about</loc></url></urlset>",
                    {},
                ),
            }
        )
        results = SitemapSource(fetcher).discover("https://example.com")
        self.assertEqual([result.raw_url for result in results], ["https://example.com/about"])

    def test_sitemap_does_not_suggest_inferred_parent_without_explicit_location(self):
        article_url = (
            "https://www.elevationmarketing.au/blog-posts/"
            "local-seo-mastery-how-to-dominate-your-area-in-google-rankings"
        )
        xml = (
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"<url><loc>{article_url}</loc></url>"
            "</urlset>"
        )
        fetcher = _StaticFetcher(
            {
                "https://elevationmarketing.au/sitemap.xml": FetchResponse(
                    "https://elevationmarketing.au/sitemap.xml", 404, "", {}
                ),
                "https://elevationmarketing.au/sitemap_index.xml": FetchResponse(
                    "https://elevationmarketing.au/sitemap_index.xml", 404, "", {}
                ),
                "https://www.elevationmarketing.au/sitemap.xml": FetchResponse(
                    "https://www.elevationmarketing.au/sitemap.xml", 200, xml, {}
                ),
            }
        )

        results = SitemapSource(fetcher).discover(
            "https://elevationmarketing.au/",
            ("https://www.elevationmarketing.au/sitemap.xml",),
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].raw_url, "https://www.elevationmarketing.au/blog-posts")
        self.assertTrue(results[0].force_discarded)

        target_repository = _FakeTargetRepository()
        service = DiscoveryService(
            _FakeCompetitorRepository(
                {
                    "id": "elevation",
                    "user_id": "company-a",
                    "website_url": "https://elevationmarketing.au/",
                }
            ),
            target_repository,
            fallback_classifier=DeterministicStubClassifier(),
            robots_source=_Robots(("https://www.elevationmarketing.au/sitemap.xml",)),
            sitemap_source=_Source(results),
            link_source=_Source(),
        )
        persisted = service.discover_website("elevation", user_id="company-a")
        self.assertEqual(persisted[0]["url"], "https://elevationmarketing.au/blog-posts")
        self.assertEqual(persisted[0]["discovery_status"], "DISCARDED")
        self.assertEqual(persisted[0]["classification_method"], "RULE")

    def test_large_sitemap_samples_raw_unmatched_entries_before_normalization(self):
        locations = (
            "https://example.com/blog/post-1",
            "https://example.com/blog/post-2",
            "https://example.com/services/seo",
            "https://example.com/products/widget",
            "https://example.com/opaque/one",
            "https://example.com/opaque/two",
            "https://example.com/opaque/three",
            "https://example.com/logo.png",
        )
        xml = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(
            f"<url><loc>{location}</loc></url>" for location in locations
        ) + "</urlset>"
        fetcher = _StaticFetcher(
            {
                "https://example.com/sitemap.xml": FetchResponse(
                    "https://example.com/sitemap.xml", 404, "", {}
                ),
                "https://example.com/sitemap_index.xml": FetchResponse(
                    "https://example.com/sitemap_index.xml", 404, "", {}
                ),
                "https://example.com/content.xml": FetchResponse(
                    "https://example.com/content.xml", 200, xml, {}
                ),
            }
        )

        source = SitemapSource(
            fetcher,
            large_sitemap_threshold=3,
            sample_urls_per_large_sitemap=2,
        )
        results = source.discover(
            "https://example.com",
            ("https://example.com/content.xml",),
        )

        urls = {result.raw_url for result in results}
        self.assertIn("https://example.com/blog", urls)
        self.assertIn("https://example.com/services", urls)
        self.assertIn("https://example.com/products/widget", urls)
        self.assertNotIn("https://example.com/blog/post-1", urls)
        self.assertNotIn("https://example.com/logo.png", urls)
        self.assertEqual(source.last_stats.raw_count, 8)
        self.assertEqual(source.last_stats.sampled_count, 2)
        self.assertEqual(len(results), 5)

    def test_classification_batches_only_unresolved_candidates(self):
        candidates = (
            CandidateForClassification("https://example.com/pricing", "https://example.com/pricing"),
            CandidateForClassification("https://example.com/opaque", "https://example.com/opaque"),
        )
        classifier = _RecordingClassifier()
        results = classify_candidates(candidates, classifier)
        self.assertEqual(results[0].page_type, "PRICING")
        self.assertEqual(results[0].classification_method, "RULE")
        self.assertEqual(len(classifier.batches), 1)
        self.assertEqual([candidate.url for candidate in classifier.batches[0]], ["https://example.com/opaque"])

    def test_flat_leaf_slugs_do_not_match_index_page_types(self):
        false_positive_paths = (
            "/instagram-video-for-business-review",
            "/website-design-review",
            "/careers-lyfe-saver",
            "/attracting-students-via-social-media",
            "/roi-benefits-social-media-marketing",
            "/social-media-the-student-housing-industrys-best-marketing-source",
        )
        for path in false_positive_paths:
            with self.subTest(path=path):
                result = classify_by_rules(
                    CandidateForClassification(
                        f"https://www.lyfemarketing.com{path}",
                        f"https://www.lyfemarketing.com{path}",
                    )
                )
                self.assertIsNone(result)
                self.assertEqual(
                    discovery_scope(f"https://www.lyfemarketing.com{path}"),
                    "SECTION",
                )

    def test_large_sitemap_sampling_happens_before_normalization(self):
        locations = (
            "https://example.com/opaque/alpha1234567890",
            "https://example.com/opaque/beta1234567890",
            "https://example.com/opaque/gamma1234567890",
            "https://example.com/opaque/delta1234567890",
        )
        xml = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(
            f"<url><loc>{location}</loc></url>" for location in locations
        ) + "</urlset>"
        fetcher = _StaticFetcher(
            {
                "https://example.com/sitemap.xml": FetchResponse(
                    "https://example.com/sitemap.xml", 404, "", {}
                ),
                "https://example.com/sitemap_index.xml": FetchResponse(
                    "https://example.com/sitemap_index.xml", 404, "", {}
                ),
                "https://example.com/content.xml": FetchResponse(
                    "https://example.com/content.xml", 200, xml, {}
                ),
            }
        )

        source = SitemapSource(
            fetcher,
            large_sitemap_threshold=3,
            sample_urls_per_large_sitemap=2,
        )
        results = source.discover(
            "https://example.com",
            ("https://example.com/content.xml",),
        )

        self.assertEqual(source.last_stats.sampled_count, 2)
        self.assertEqual([result.raw_url for result in results], ["https://example.com/opaque"])

    def test_forced_discard_bypasses_rule_classification(self):
        candidate = CandidateForClassification(
            "https://example.com/opaque-pricing-leaf",
            "https://example.com/opaque-pricing-leaf",
            force_discarded=True,
        )
        results = classify_candidates((candidate,), _RecordingClassifier())
        self.assertEqual(results[0].discovery_status, "DISCARDED")
        self.assertEqual(results[0].classification_method, "RULE")

    def test_deterministic_stub_returns_structured_fallback_results(self):
        candidates = (
            CandidateForClassification("raw", "https://example.com/opaque"),
        )
        result = DeterministicStubClassifier().classify(candidates)[0]
        self.assertEqual(result.page_type, "OTHER")
        self.assertEqual(result.discovery_status, "DISCARDED")
        self.assertEqual(result.classification_method, "LLM")

    def test_openai_classifier_uses_configured_model_and_structured_batch(self):
        candidates = (
            CandidateForClassification(
                "https://example.com/opaque",
                "https://example.com/opaque",
                title="Opaque page",
                sources=("SITEMAP",),
            ),
        )
        client = _FakeOpenAIClient(
            {
                "classifications": [
                    {
                        "url": "https://example.com/opaque",
                        "page_type": "OTHER",
                        "discovery_status": "DISCARDED",
                    }
                ]
            }
        )

        classifier = OpenAIClassifier.from_env(
            {
                "OPENAI_KEY": "test-key-not-used",
                "DISCOVERY_CLASSIFIER_MODEL": "test-model",
            },
            client=client,
        )
        results = classifier.classify(candidates)

        self.assertEqual(results[0].classification_method, "LLM")
        self.assertEqual(client.responses.calls[0]["model"], "test-model")
        self.assertEqual(client.responses.calls[0]["store"], False)
        self.assertEqual(
            json.loads(client.responses.calls[0]["input"])["candidates"][0]["url"],
            "https://example.com/opaque",
        )
        self.assertEqual(
            client.responses.calls[0]["text"]["format"]["type"],
            "json_schema",
        )

    def test_openai_classifier_requires_api_key_without_injected_client(self):
        with self.assertRaises(OpenAIClassifierConfigurationError):
            OpenAIClassifier.from_env({})

    def test_discovery_service_collects_dedupes_classifies_and_persists(self):
        competitor = {
            "id": "competitor-1",
            "user_id": "company-a",
            "website_url": "https://example.com",
        }
        target_repository = _FakeTargetRepository()
        classifier = _RecordingClassifier()
        service = DiscoveryService(
            _FakeCompetitorRepository(competitor),
            target_repository,
            fallback_classifier=classifier,
            robots_source=_Robots(("https://example.com/sitemap.xml",)),
            sitemap_source=_Source(
                (
                    DiscoveredURL("https://example.com/blog/post-1", "SITEMAP"),
                    DiscoveredURL("https://example.com/opaque", "SITEMAP"),
                )
            ),
            link_source=_Source(
                (DiscoveredURL("https://example.com/blog/post-1", "LINKS", "Blog"),)
            ),
            liveness_checker=lambda url: True,
        )

        results = service.discover_website("competitor-1", user_id="company-a")
        self.assertEqual([result["url"] for result in results], [
            "https://example.com/blog",
            "https://example.com/opaque",
        ])
        self.assertEqual(results[0]["discovery_status"], "SUGGESTED")
        self.assertEqual(results[0]["classification_method"], "RULE")
        self.assertEqual(results[1]["discovery_status"], "DISCARDED")
        self.assertEqual(len(classifier.batches), 1)
        self.assertEqual(len(target_repository.saved), 2)
        self.assertNotIn("SEARCH", service.last_summary.source_breakdown)

    def test_liveness_gate_discards_collapsed_index_after_404(self):
        article_url = (
            "https://elevationmarketing.au/blog-posts/"
            "local-seo-mastery-how-to-dominate-your-area-in-google-rankings"
        )
        liveness_calls = []

        def dead_liveness(url):
            liveness_calls.append(url)
            return fetch_page(
                url,
                http_fetcher=lambda _: HttpResponse(
                    "<html><body>Not found</body></html>",
                    404,
                    {"Content-Type": "text/html"},
                ),
            )

        target_repository = _FakeTargetRepository()
        service = DiscoveryService(
            _FakeCompetitorRepository(
                {
                    "id": "elevation",
                    "user_id": "company-a",
                    "website_url": "https://elevationmarketing.au/",
                }
            ),
            target_repository,
            fallback_classifier=DeterministicStubClassifier(),
            robots_source=_Robots(),
            sitemap_source=_Source((DiscoveredURL(article_url, "SITEMAP"),)),
            link_source=_Source(),
            liveness_checker=dead_liveness,
        )

        persisted = service.discover_website("elevation", user_id="company-a")

        self.assertEqual(
            liveness_calls,
            ["https://elevationmarketing.au/blog-posts"],
        )
        self.assertEqual(persisted[0]["url"], "https://elevationmarketing.au/blog-posts")
        self.assertEqual(persisted[0]["discovery_status"], "DISCARDED")
        self.assertEqual(persisted[0]["classification_method"], "RULE")

    def test_discovery_service_rejects_unknown_competitors(self):
        service = DiscoveryService(
            _FakeCompetitorRepository({"id": "competitor-1", "user_id": "company-a"}),
            _FakeTargetRepository(),
            fallback_classifier=DeterministicStubClassifier(),
            robots_source=_Robots(),
            sitemap_source=_Source(),
            link_source=_Source(),
        )
        with self.assertRaises(DiscoveryError):
            service.discover_website("missing")


class CandidateReviewTests(unittest.TestCase):
    def setUp(self):
        self.competitor = {
            "id": "competitor-1",
            "user_id": "company-a",
            "website_url": "https://example.com",
        }
        self.target_repository = _ReviewTargetRepository(
            (
                {
                    "id": "candidate-1",
                    "competitor_id": "competitor-1",
                    "raw_url": "https://example.com/blog",
                    "url": "https://example.com/blog",
                    "page_type": "BLOG",
                    "discovery_status": "SUGGESTED",
                    "classification_method": "RULE",
                    "active": False,
                },
                {
                    "id": "candidate-2",
                    "competitor_id": "competitor-1",
                    "raw_url": "https://example.com/pricing",
                    "url": "https://example.com/pricing",
                    "page_type": "PRICING",
                    "discovery_status": "SUGGESTED",
                    "classification_method": "RULE",
                    "active": False,
                },
                {
                    "id": "candidate-3",
                    "competitor_id": "competitor-1",
                    "raw_url": "https://example.com/opaque",
                    "url": "https://example.com/opaque",
                    "page_type": "OTHER",
                    "discovery_status": "DISCARDED",
                    "classification_method": "LLM",
                    "active": False,
                },
            )
        )
        self.service = DiscoveryService(
            _FakeCompetitorRepository(self.competitor),
            self.target_repository,
            fallback_classifier=DeterministicStubClassifier(),
            robots_source=_Robots(),
            sitemap_source=_Source(),
            link_source=_Source(),
        )

    def test_list_candidates_defaults_to_suggested_and_all_retains_discarded(self):
        suggested = self.service.list_candidates("competitor-1")
        self.assertEqual({candidate["id"] for candidate in suggested}, {"candidate-1", "candidate-2"})

        all_candidates = self.service.list_candidates("competitor-1", status="ALL")
        self.assertEqual(
            {candidate["id"] for candidate in all_candidates},
            {"candidate-1", "candidate-2", "candidate-3"},
        )
        discarded = next(candidate for candidate in all_candidates if candidate["id"] == "candidate-3")
        self.assertEqual(discarded["discovery_status"], "DISCARDED")

    def test_activate_candidate_is_idempotent_and_promotes_the_existing_row(self):
        activated = self.service.activate_candidate("candidate-1")
        self.assertTrue(activated["active"])
        self.assertEqual(activated["discovery_status"], "ACTIVE")
        self.assertEqual(len(self.target_repository.records), 3)

        activated_again = self.service.activate_candidate("candidate-1")
        self.assertEqual(activated_again["id"], activated["id"])
        self.assertEqual(len(self.target_repository.records), 3)

    def test_activate_candidate_rejects_discarded_candidate(self):
        with self.assertRaisesRegex(DiscoveryError, "DISCARDED"):
            self.service.activate_candidate("candidate-3")
        discarded = self.target_repository.get("candidate-3")
        self.assertFalse(discarded["active"])
        self.assertEqual(discarded["discovery_status"], "DISCARDED")

    def test_list_active_targets_excludes_candidates_and_malformed_rows(self):
        self.target_repository.records.extend(
            (
                {
                    "id": "target-1",
                    "competitor_id": "competitor-1",
                    "url": "https://example.com/active",
                    "active": True,
                    "discovery_status": "ACTIVE",
                },
                {
                    "id": "malformed-discarded",
                    "competitor_id": "competitor-1",
                    "url": "https://example.com/discarded",
                    "active": True,
                    "discovery_status": "DISCARDED",
                },
                {
                    "id": "malformed-missing-active",
                    "competitor_id": "competitor-1",
                    "url": "https://example.com/missing-active",
                    "discovery_status": "ACTIVE",
                },
            )
        )
        active_targets = self.service.list_active_targets("competitor-1")
        self.assertEqual([target["id"] for target in active_targets], ["target-1"])

    def test_add_candidate_creates_a_manual_suggested_candidate(self):
        added = self.service.add_candidate(
            "competitor-1",
            "https://example.com/manual-page?utm_source=test#section",
        )
        self.assertEqual(added["url"], "https://example.com/manual-page")
        self.assertEqual(added["discovery_status"], "SUGGESTED")
        self.assertEqual(added["classification_method"], "MANUAL")
        self.assertFalse(added["active"])
        self.assertIn(
            added["id"],
            {candidate["id"] for candidate in self.service.list_candidates("competitor-1")},
        )

    def test_edit_candidate_updates_unactivated_candidate_url(self):
        edited = self.service.edit_candidate(
            "candidate-2",
            "https://example.com/new-pricing",
        )
        self.assertEqual(edited["url"], "https://example.com/new-pricing")
        self.assertEqual(edited["raw_url"], "https://example.com/new-pricing")

    def test_edit_candidate_rejects_activated_candidate(self):
        self.service.activate_candidate("candidate-1")
        with self.assertRaisesRegex(DiscoveryError, "already activated"):
            self.service.edit_candidate("candidate-1", "https://example.com/edited")

    def test_remove_candidate_deletes_unactivated_and_blocks_activated(self):
        self.assertTrue(self.service.remove_candidate("candidate-2"))
        self.assertIsNone(self.target_repository.get("candidate-2"))

        self.service.activate_candidate("candidate-1")
        with self.assertRaisesRegex(DiscoveryError, "activated"):
            self.service.remove_candidate("candidate-1")
        self.assertIsNotNone(self.target_repository.get("candidate-1"))


if __name__ == "__main__":
    unittest.main()
