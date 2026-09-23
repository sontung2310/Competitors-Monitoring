from __future__ import annotations

import json
import re
import unittest
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch

from backend.flask.discovery.classification import (
    CandidateForClassification,
    ClassificationError,
    ClassifierConfigurationError,
    ClassificationResult,
    DeterministicStubClassifier,
    OpenJevClassifier,
    OpenJevClassifierConfigurationError,
    OpenAIClassifier,
    OpenAIClassifierConfigurationError,
    build_classifier_from_env,
    classify_by_rules,
    classify_candidates,
    resolve_classifier_batch_size,
)
from backend.flask.discovery.audit import (
    CORE_PAGE_TYPES,
    DiscoveryAuditResult,
    MissingCategoryFlag,
    OpenAIDiscoveryAudit,
    RedundancyFlag,
    SuggestedCandidateForAudit,
)
from backend.flask.discovery.normalization import (
    discovery_scope,
    extract_meta_description,
    extract_page_title,
    has_recognized_final_segment,
    is_html_candidate_url,
    is_item_type_excluded,
    is_locale_segment,
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
from backend.flask.website_monitoring.service import (
    BrowserFetchError,
    FetchResult,
    HttpResponse,
    MonitoringError,
    fetch_page,
)


class _FakeCompetitorRepository:
    def __init__(self, competitor):
        self.competitor = competitor

    def get(self, competitor_id, *, user_id=None):
        if competitor_id == self.competitor["id"] and (
            user_id is None or user_id == self.competitor["user_id"]
        ):
            return self.competitor
        return None

    def update(self, competitor_id, updates=None, *, user_id=None, company_id=None, **fields):
        values = {**(updates or {}), **fields}
        if competitor_id != self.competitor["id"]:
            return None
        if user_id is not None and self.competitor.get("user_id") != user_id:
            return None
        if company_id is not None and self.competitor.get("company_id") != company_id:
            return None
        self.competitor.update(values)
        return dict(self.competitor)


class _FakeTargetRepository:
    def __init__(self, candidates=()):
        self.saved = [dict(candidate) for candidate in candidates]

    def upsert_discovered_candidate(self, **candidate):
        result = {"id": f"candidate-{len(self.saved) + 1}", **candidate, "active": False}
        self.saved.append(result)
        return result

    def list_for_competitor(self, competitor_id, *, discovery_status=None):
        return [
            dict(candidate)
            for candidate in self.saved
            if candidate.get("competitor_id") == competitor_id
            and (
                discovery_status is None
                or candidate.get("discovery_status") == discovery_status
            )
        ]

    def get(self, candidate_id, *, competitor_id=None):
        for candidate in self.saved:
            if candidate["id"] == candidate_id and (
                competitor_id is None
                or candidate.get("competitor_id") == competitor_id
            ):
                return dict(candidate)
        return None

    def update(self, candidate_id, updates=None, *, competitor_id=None, **fields):
        values = {**(updates or {}), **fields}
        for candidate in self.saved:
            if candidate["id"] == candidate_id and (
                competitor_id is None
                or candidate.get("competitor_id") == competitor_id
            ):
                candidate.update(values)
                return dict(candidate)
        return None

    def mark_activated(self, candidate_id, *, competitor_id=None, check_interval_minutes=None):
        updates = {"active": True, "discovery_status": "ACTIVE"}
        if check_interval_minutes is not None:
            updates["check_interval_minutes"] = check_interval_minutes
        return self.update(candidate_id, updates, competitor_id=competitor_id)

    def mark_discarded(self, candidate_id, *, competitor_id=None):
        return self.update(
            candidate_id,
            {"active": False, "discovery_status": "DISCARDED"},
            competitor_id=competitor_id,
        )

    def discard_discovered_candidates_by_url_patterns(
        self, competitor_id, *, url_patterns
    ):
        changed = 0
        for candidate in self.saved:
            if (
                candidate.get("competitor_id") != competitor_id
                or candidate.get("active") is True
                or candidate.get("discovery_status") == "ACTIVE"
                or candidate.get("discovery_source") not in {"SITEMAP", "LINKS"}
                or not any(
                    re.search(pattern, candidate.get("url", ""), flags=re.IGNORECASE)
                    for pattern in url_patterns
                )
            ):
                continue
            candidate.update(
                {
                    "active": False,
                    "page_type": "OTHER",
                    "discovery_status": "DISCARDED",
                    "classification_method": "RULE",
                }
            )
            changed += 1
        return changed


class _FakeDiscoveryRunTracker:
    def __init__(self):
        self.records = {}

    def start(self, run_id, *, competitor_id, company_id=None):
        self.records[run_id] = {
            "run_id": run_id,
            "competitor_id": competitor_id,
            "company_id": company_id,
            "status": "RUNNING",
        }
        return self.records[run_id]

    def succeed(self, run_id, *, candidate_count, summary=None):
        self.records[run_id].update(
            status="SUCCESS",
            candidate_count=candidate_count,
            summary=summary,
        )
        return self.records[run_id]

    def fail(self, run_id, error_message):
        self.records[run_id].update(status="FAILED", error_message=error_message)
        return self.records[run_id]

    def get(self, run_id):
        return self.records.get(run_id)


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

    def mark_activated(self, candidate_id, *, competitor_id=None, check_interval_minutes=None):
        updates = {"active": True, "discovery_status": "ACTIVE"}
        if check_interval_minutes is not None:
            updates["check_interval_minutes"] = check_interval_minutes
        return self.update(candidate_id, updates, competitor_id=competitor_id)

    def mark_discarded(self, candidate_id, *, competitor_id=None):
        return self.update(
            candidate_id,
            {"active": False, "discovery_status": "DISCARDED"},
            competitor_id=competitor_id,
        )

    def delete(self, candidate_id, *, competitor_id=None):
        for index, record in enumerate(self.records):
            if record["id"] == candidate_id and (
                competitor_id is None or record["competitor_id"] == competitor_id
            ):
                del self.records[index]
                return True
        return False


class _HistoryRepository:
    def __init__(self, target_ids=()):
        self.target_ids = set(target_ids)

    def list_for_target(self, target_id):
        if target_id in self.target_ids:
            return [{"id": f"history-for-{target_id}"}]
        return []


class _Source:
    def __init__(self, candidates=(), homepage_metadata=None):
        self.candidates = tuple(candidates)
        self.last_homepage_metadata = dict(
            homepage_metadata
            or {"title": None, "meta_description": None}
        )

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


class _FakeChatCompletions:
    def __init__(self, output: str):
        self.output = output
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.output))]
        )


class _FakeChatClient:
    """OpenRouter-shaped fake client (Chat Completions API)."""

    def __init__(self, output: str):
        self.completions = _FakeChatCompletions(output)
        self.chat = SimpleNamespace(completions=self.completions)


class _RecordingLLMProvider:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def generate_json(self, prompt, *, instructions, response_format):
        self.calls.append(
            {
                "prompt": prompt,
                "instructions": instructions,
                "response_format": response_format,
            }
        )
        return self.payload


def _open_jev_payload(
    *,
    page_type="SERVICES",
    discovery_status="SUGGESTED",
    page_type_confidence=0.9,
    status_confidence=0.9,
):
    page_type_labels = ["BLOG", "NEWS", "PRICING", "PRODUCTS", "SERVICES", "PRESS", "OTHER"]
    page_type_rest = (1 - page_type_confidence) / (len(page_type_labels) - 1)
    page_type_probabilities = {
        label: (page_type_confidence if label == page_type else page_type_rest)
        for label in page_type_labels
    }
    status_labels = ["SUGGESTED", "DISCARDED"]
    status_probabilities = {
        label: (status_confidence if label == discovery_status else 1 - status_confidence)
        for label in status_labels
    }
    return {
        "answers": {
            "page_type": {
                "type": "choice",
                "choice": page_type,
                "probabilities": page_type_probabilities,
                "confidence": page_type_confidence,
            },
            "discovery_status": {
                "type": "choice",
                "choice": discovery_status,
                "probabilities": status_probabilities,
                "confidence": status_confidence,
            },
        }
    }


class _RecordingOpenJevProvider:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def ask(self, state, questions):
        self.calls.append({"state": state, "questions": questions})
        return self.payload


class _FailingOpenJevProvider:
    def ask(self, state, questions):
        raise RuntimeError("Open-Jev unavailable")


class _FailingClassifier:
    def __init__(self):
        self.calls = 0

    def classify(self, candidates):
        self.calls += 1
        raise RuntimeError("forced classifier outage")


class _FailOneBatchClassifier:
    def __init__(self, failing_batch=2):
        self.failing_batch = failing_batch
        self.batches = []

    def classify(self, candidates):
        self.batches.append(tuple(candidates))
        if len(self.batches) == self.failing_batch:
            raise RuntimeError("forced one-batch outage")
        return tuple(
            ClassificationResult(
                url=candidate.url,
                page_type="SERVICES",
                discovery_status="SUGGESTED",
                classification_method="LLM",
            )
            for candidate in candidates
        )


class _RecordingAudit:
    def __init__(self, result=None):
        self.result = result or DiscoveryAuditResult()
        self.calls = []

    def audit(self, candidates, *, homepage_title, homepage_meta_description):
        self.calls.append(
            {
                "candidates": tuple(candidates),
                "homepage_title": homepage_title,
                "homepage_meta_description": homepage_meta_description,
            }
        )
        return self.result


class _FailingAudit:
    def __init__(self):
        self.calls = 0

    def audit(self, candidates, *, homepage_title, homepage_meta_description):
        self.calls += 1
        raise RuntimeError("forced audit outage")


@dataclass
class _StaticFetcher:
    responses: dict[str, FetchResponse]

    def fetch(self, url):
        return self.responses[url]


class DiscoveryTests(unittest.TestCase):
    def test_extract_meta_description_normalizes_and_bounds_content(self):
        description = extract_meta_description(
            '<html><head><meta CONTENT="  A  useful\n summary  " '
            'NAME="description"><meta name="description" content="ignored"></head></html>'
        )
        self.assertEqual(description, "A useful summary")

        long_description = "x" * 600
        self.assertEqual(
            len(extract_meta_description(f'<meta name="description" content="{long_description}">')),
            500,
        )
        self.assertIsNone(extract_meta_description("<html><head></head></html>"))

    def test_extract_page_title_normalizes_and_bounds_content(self):
        self.assertEqual(
            extract_page_title("<title>  A\n useful   homepage </title>"),
            "A useful homepage",
        )
        self.assertEqual(
            len(extract_page_title(f"<title>{'x' * 600}</title>")),
            500,
        )

    def test_openai_audit_sends_only_lightweight_metadata_and_core_types(self):
        provider = _RecordingLLMProvider(
            {
                "flagged_redundant": [
                    {
                        "url": "https://example.com/services/one",
                        "reason": "The second services entry duplicates this section.",
                    }
                ],
                "flagged_missing_categories": [
                    {
                        "page_type": "BLOG",
                        "reason": "Homepage navigation references a blog, but no blog was suggested.",
                    }
                ],
            }
        )
        auditor = OpenAIDiscoveryAudit(provider=provider)

        result = auditor.audit(
            (
                SuggestedCandidateForAudit(
                    "https://example.com/services/one",
                    "SERVICES",
                    "One service",
                    "Service summary",
                ),
            ),
            homepage_title="Example homepage",
            homepage_meta_description="Example business summary",
        )

        request = json.loads(provider.calls[0]["prompt"])
        instructions = provider.calls[0]["instructions"]
        self.assertEqual(request["core_page_types"], list(CORE_PAGE_TYPES))
        self.assertEqual(request["suggested_candidates"][0]["meta_description"], "Service summary")
        self.assertEqual(request["homepage"]["title"], "Example homepage")
        self.assertIn("positive evidence", instructions)
        self.assertIn("absence of a category", instructions.lower())
        self.assertIn("never evidence", instructions.lower())
        self.assertIn("consulting, or agency business", instructions)
        self.assertIn("speculation", instructions)
        self.assertIn("prefer an empty array over speculative noise", instructions)
        self.assertEqual(result.flagged_redundant[0].url, "https://example.com/services/one")
        self.assertEqual(result.flagged_missing_categories[0].page_type, "BLOG")

    def test_second_pass_audit_discards_only_existing_suggestions_and_persists_gaps(self):
        competitor = {
            "id": "competitor-1",
            "user_id": "company-a",
            "website_url": "https://example.com",
        }
        target_repository = _FakeTargetRepository(
            (
                {
                    "id": "old-discarded",
                    "competitor_id": "competitor-1",
                    "url": "https://example.com/old-discarded",
                    "discovery_status": "DISCARDED",
                    "active": False,
                },
            )
        )
        audit = _RecordingAudit(
            DiscoveryAuditResult(
                flagged_redundant=(
                    RedundancyFlag(
                        "https://example.com/en/services",
                        "Duplicate of the first services entry.",
                    ),
                    RedundancyFlag(
                        "https://example.com/old-discarded",
                        "Not part of this run and must be ignored.",
                    ),
                ),
                flagged_missing_categories=(
                    MissingCategoryFlag(
                        "BLOG",
                        "The homepage references a blog but no blog was suggested.",
                    ),
                ),
            )
        )
        service = DiscoveryService(
            _FakeCompetitorRepository(competitor),
            target_repository,
            fallback_classifier=DeterministicStubClassifier(
                page_type="SERVICES",
                discovery_status="SUGGESTED",
            ),
            audit_classifier=audit,
            robots_source=_Robots(),
            sitemap_source=_Source(
                (
                    DiscoveredURL("https://example.com/services", "SITEMAP"),
                    DiscoveredURL("https://example.com/en/services", "SITEMAP"),
                )
            ),
            link_source=_Source(
                homepage_metadata={
                    "title": "Example homepage",
                    "meta_description": "A services-led business",
                }
            ),
            liveness_checker=lambda url: FetchResult(
                '<meta name="description" content="Service summary">',
                "HTTP",
                200,
            ),
        )

        persisted = service.discover_website("competitor-1", user_id="company-a")

        self.assertEqual(len(audit.calls), 1)
        self.assertEqual(
            [candidate.url for candidate in audit.calls[0]["candidates"]],
            [
                "https://example.com/services",
                "https://example.com/en/services",
            ],
        )
        self.assertEqual(
            [row["discovery_status"] for row in persisted],
            ["SUGGESTED", "DISCARDED"],
        )
        self.assertEqual(target_repository.get("old-discarded")["discovery_status"], "DISCARDED")
        self.assertEqual(
            competitor["discovery_gap_flags"],
            [
                {
                    "page_type": "BLOG",
                    "reason": "The homepage references a blog but no blog was suggested.",
                }
            ],
        )

    def test_second_pass_audit_failure_preserves_first_pass_results(self):
        competitor = {
            "id": "competitor-1",
            "user_id": "company-a",
            "website_url": "https://example.com",
        }
        audit = _FailingAudit()
        service = DiscoveryService(
            _FakeCompetitorRepository(competitor),
            _FakeTargetRepository(),
            fallback_classifier=DeterministicStubClassifier(
                page_type="SERVICES",
                discovery_status="SUGGESTED",
            ),
            audit_classifier=audit,
            robots_source=_Robots(),
            sitemap_source=_Source(
                (DiscoveredURL("https://example.com/services", "SITEMAP"),)
            ),
            link_source=_Source(),
            liveness_checker=lambda url: True,
        )

        persisted = service.discover_website("competitor-1", user_id="company-a")

        self.assertEqual(audit.calls, 1)
        self.assertIsNotNone(service.last_audit_error)
        self.assertEqual(persisted[0]["discovery_status"], "SUGGESTED")
        self.assertNotIn("discovery_gap_flags", competitor)

    def test_second_pass_audit_ignores_speculative_redundancy_flags(self):
        competitor = {
            "id": "competitor-1",
            "user_id": "company-a",
            "website_url": "https://example.com",
        }
        audit = _RecordingAudit(
            DiscoveryAuditResult(
                flagged_redundant=(
                    RedundancyFlag(
                        "https://example.com/consulting",
                        "This is likely covered by the broader services page.",
                    ),
                ),
            )
        )
        service = DiscoveryService(
            _FakeCompetitorRepository(competitor),
            _FakeTargetRepository(),
            fallback_classifier=DeterministicStubClassifier(
                page_type="SERVICES",
                discovery_status="SUGGESTED",
            ),
            audit_classifier=audit,
            robots_source=_Robots(),
            sitemap_source=_Source(
                (DiscoveredURL("https://example.com/consulting", "SITEMAP"),)
            ),
            link_source=_Source(),
            liveness_checker=lambda url: True,
        )

        persisted = service.discover_website("competitor-1", user_id="company-a")

        self.assertEqual(persisted[0]["discovery_status"], "SUGGESTED")

    def test_second_pass_audit_requires_structural_overlap_for_flat_service_pages(self):
        competitor = {
            "id": "competitor-1",
            "user_id": "company-a",
            "website_url": "https://example.com",
        }
        audit = _RecordingAudit(
            DiscoveryAuditResult(
                flagged_redundant=(
                    RedundancyFlag(
                        "https://example.com/pittsburgh-seo-company",
                        "Duplicate of the general services page.",
                    ),
                ),
            )
        )
        service = DiscoveryService(
            _FakeCompetitorRepository(competitor),
            _FakeTargetRepository(),
            fallback_classifier=DeterministicStubClassifier(
                page_type="SERVICES",
                discovery_status="SUGGESTED",
            ),
            audit_classifier=audit,
            robots_source=_Robots(),
            sitemap_source=_Source(
                (
                    DiscoveredURL("https://example.com/services", "SITEMAP"),
                    DiscoveredURL(
                        "https://example.com/pittsburgh-seo-company", "SITEMAP"
                    ),
                )
            ),
            link_source=_Source(),
            liveness_checker=lambda url: True,
        )

        persisted = service.discover_website("competitor-1", user_id="company-a")

        self.assertEqual(
            [row["discovery_status"] for row in persisted],
            ["SUGGESTED", "SUGGESTED"],
        )

    def test_second_pass_audit_discards_extension_only_duplicate(self):
        # Mirrors marketingeye.com.au/press-releases (a soft-404 that returns
        # HTTP 200) vs press-releases.html (the real page): same path except
        # for the extension, so the structural-overlap check must recognize
        # them as related, and the audit's "appears to" phrasing must not be
        # treated as a hedge that blocks an otherwise well-evidenced flag.
        competitor = {
            "id": "competitor-1",
            "user_id": "company-a",
            "website_url": "https://example.com",
        }
        audit = _RecordingAudit(
            DiscoveryAuditResult(
                flagged_redundant=(
                    RedundancyFlag(
                        "https://example.com/press-releases",
                        "This page appears to be a duplicate or error page of "
                        "'https://example.com/press-releases.html', as it lacks "
                        "unique content.",
                    ),
                ),
            )
        )
        service = DiscoveryService(
            _FakeCompetitorRepository(competitor),
            _FakeTargetRepository(),
            fallback_classifier=DeterministicStubClassifier(
                page_type="PRESS",
                discovery_status="SUGGESTED",
            ),
            audit_classifier=audit,
            robots_source=_Robots(),
            sitemap_source=_Source(
                (
                    DiscoveredURL("https://example.com/press-releases", "SITEMAP"),
                    DiscoveredURL("https://example.com/press-releases.html", "SITEMAP"),
                )
            ),
            link_source=_Source(),
            liveness_checker=lambda url: True,
        )

        persisted = service.discover_website("competitor-1", user_id="company-a")

        statuses = {row["url"]: row["discovery_status"] for row in persisted}
        self.assertEqual(statuses["https://example.com/press-releases"], "DISCARDED")
        self.assertEqual(statuses["https://example.com/press-releases.html"], "SUGGESTED")

    def test_classifier_batch_size_can_be_configured(self):
        self.assertEqual(resolve_classifier_batch_size(environ={}), 25)
        self.assertEqual(
            resolve_classifier_batch_size(environ={"DISCOVERY_CLASSIFIER_BATCH_SIZE": "7"}),
            7,
        )
        with self.assertRaisesRegex(ValueError, "positive integer"):
            resolve_classifier_batch_size(environ={"DISCOVERY_CLASSIFIER_BATCH_SIZE": "0"})

    def test_classification_uses_bounded_batches(self):
        candidates = tuple(
            CandidateForClassification(f"raw-{index}", f"https://example.com/opaque-{index}")
            for index in range(5)
        )
        classifier = _RecordingClassifier()

        results = classify_candidates(candidates, classifier, batch_size=2)

        self.assertEqual([len(batch) for batch in classifier.batches], [2, 2, 1])
        self.assertEqual(len(results), 5)
        self.assertTrue(all(result.page_type == "OTHER" for result in results))

    def test_classification_isolates_one_failed_batch(self):
        candidates = tuple(
            CandidateForClassification(f"raw-{index}", f"https://example.com/opaque-{index}")
            for index in range(5)
        )
        classifier = _FailOneBatchClassifier(failing_batch=2)

        results = classify_candidates(candidates, classifier, batch_size=2)

        self.assertEqual([len(batch) for batch in classifier.batches], [2, 2, 1])
        self.assertEqual(
            [(result.page_type, result.discovery_status) for result in results],
            [
                ("SERVICES", "SUGGESTED"),
                ("SERVICES", "SUGGESTED"),
                ("OTHER", "DISCARDED"),
                ("OTHER", "DISCARDED"),
                ("SERVICES", "SUGGESTED"),
            ],
        )

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
            "https://example.com/case-study-archive/customer-story",
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
            "https://example.com/result/customer",
        )
        self.assertEqual(
            discovery_scope("https://example.com/products/widget"),
            "ITEM",
        )
        self.assertTrue(
            is_item_type_excluded(
                "https://www.jd-sports.com.au/product/blue-shoe/16486396_jdsportsau/"
            )
        )
        self.assertFalse(
            is_item_type_excluded("https://www.jd-sports.com.au/product/blue-shoe")
        )
        self.assertFalse(is_item_type_excluded("https://www.jd-sports.com.au/sale/"))
        self.assertEqual(
            discovery_scope("https://example.com/blog-posts/local-seo-mastery"),
            "INDEX",
        )
        for segment in ("news-posts", "press-releases"):
            self.assertEqual(
                discovery_scope(f"https://example.com/{segment}/entry"),
                "INDEX",
            )
            self.assertEqual(
                normalize_url(f"https://example.com/{segment}/entry"),
                f"https://example.com/{segment}",
            )
        for segment in (
            "client-testimonials",
            "client-reviews",
            "about-lyfe-marketing",
            "career-opportunities",
            "team-members",
        ):
            self.assertEqual(
                discovery_scope(f"https://example.com/{segment}/entry"),
                "UNMATCHED",
            )
            self.assertEqual(
                normalize_url(f"https://example.com/{segment}/entry"),
                f"https://example.com/{segment}/entry",
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

    def test_extensioned_and_locale_prefixed_variants_still_match_index_scope(self):
        # Enterprise/legacy-CMS sites commonly suffix content pages with a
        # file extension and prefix them with a country+language path (e.g.
        # kpmg.com/ch/en/insights.html), rather than a clean /insights.
        self.assertEqual(
            discovery_scope("https://kpmg.com/ch/en/insights.html"),
            "INDEX",
        )
        self.assertEqual(
            discovery_scope("https://kpmg.com/au/en/services.html"),
            "INDEX",
        )
        # A single real locale segment continues to work, extension or not.
        self.assertEqual(
            discovery_scope("https://example.com/en/insights.html"),
            "INDEX",
        )
        # An extensioned leaf that doesn't match any known variant is still
        # correctly rejected -- extension-stripping doesn't loosen precision.
        self.assertEqual(
            discovery_scope("https://example.com/au/en/leadership-team.html"),
            "UNMATCHED",
        )
        # A non-locale two-segment prefix must still fail, extension or not
        # -- only genuine locale-shaped segments extend the match window.
        self.assertEqual(
            discovery_scope("https://example.com/opaque/insights.html"),
            "UNMATCHED",
        )

    def test_is_locale_segment_requires_exactly_two_letters(self):
        # Real locale codes seen in production sitemaps are all 2 letters.
        for code in ("au", "en", "de", "fr", "ch", "in", "es", "en-au"):
            with self.subTest(code=code):
                self.assertTrue(is_locale_segment(code))
        # 3-letter words are ordinary content-section names, not locales --
        # "api" (openai.com's API sitemap) and "men" (a gendered product
        # section) both false-matched the old 2-3 letter regex.
        for word in ("api", "men", "faq", "opaque"):
            with self.subTest(word=word):
                self.assertFalse(is_locale_segment(word))

    def test_has_recognized_final_segment_ignores_prefix(self):
        # A recognized final word counts regardless of what precedes it --
        # unlike discovery_scope's INDEX check, no locale constraint here.
        for url in (
            "https://www.oliverwyman.com/our-expertise/insights.html",
            "https://example.com/blog",
            "https://kpmg.com/au/en/media.html",
        ):
            with self.subTest(url=url):
                self.assertTrue(has_recognized_final_segment(url))
        # An unrecognized final word never counts, no matter the prefix --
        # this is what keeps KPMG's flood of /industries/healthcare.html,
        # /services/tax.html-shaped pages excluded.
        for url in (
            "https://kpmg.com/xx/en/what-we-do/industries/healthcare.html",
            "https://kpmg.com/xx/en/what-we-do/services/tax.html",
            "https://example.com/about-us",
        ):
            with self.subTest(url=url):
                self.assertFalse(has_recognized_final_segment(url))

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
                ),
                "https://example.com/blog": FetchResponse(
                    "https://example.com/blog", 404, "", {}
                ),
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
                ),
                "https://example.com/body-page": FetchResponse(
                    "https://example.com/body-page", 404, "", {}
                ),
                "https://example.com/footer-page": FetchResponse(
                    "https://example.com/footer-page", 404, "", {}
                ),
                "https://example.com/services": FetchResponse(
                    "https://example.com/services", 404, "", {}
                ),
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

    def test_link_source_crawls_to_max_depth_and_stops(self):
        # homepage (depth 0) -> /level1 (depth 1, fetched) -> /level2
        # (depth 2, fetched) -> /level3 (depth 3, collected but NOT fetched,
        # so /level3's own link to /level4 must never appear).
        fetcher = _StaticFetcher(
            {
                "https://example.com/": FetchResponse(
                    "https://example.com/", 200, '<a href="/level1">L1</a>', {}
                ),
                "https://example.com/level1": FetchResponse(
                    "https://example.com/level1", 200, '<a href="/level2">L2</a>', {}
                ),
                "https://example.com/level2": FetchResponse(
                    "https://example.com/level2", 200, '<a href="/level3">L3</a>', {}
                ),
                "https://example.com/level3": FetchResponse(
                    "https://example.com/level3", 200, '<a href="/level4">L4</a>', {}
                ),
            }
        )

        links = InternalLinkSource(fetcher, max_depth=3, max_pages=100).discover(
            "https://example.com"
        )

        urls = {link.raw_url for link in links}
        self.assertEqual(
            urls,
            {
                "https://example.com/level1",
                "https://example.com/level2",
                "https://example.com/level3",
            },
        )
        self.assertNotIn("https://example.com/level4", urls)

    def test_link_source_stops_at_max_pages(self):
        # Ten pages are each fetchable and each link to the next, but the
        # crawl must stop after fetching exactly max_pages of them.
        responses = {
            "https://example.com/": FetchResponse(
                "https://example.com/", 200, '<a href="/page-1">P1</a>', {}
            )
        }
        for i in range(1, 10):
            responses[f"https://example.com/page-{i}"] = FetchResponse(
                f"https://example.com/page-{i}",
                200,
                f'<a href="/page-{i + 1}">next</a>',
                {},
            )
        fetcher = _StaticFetcher(responses)

        source = InternalLinkSource(fetcher, max_depth=10, max_pages=3)
        links = source.discover("https://example.com")

        # max_pages=3 fetches homepage, page-1, page-2 -- collecting
        # page-1 (depth 1), page-2 (depth 2), page-3 (depth 3, collected off
        # page-2 but never itself fetched).
        urls = {link.raw_url for link in links}
        self.assertEqual(
            urls,
            {
                "https://example.com/page-1",
                "https://example.com/page-2",
                "https://example.com/page-3",
            },
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

    def test_sitemap_index_prefers_au_sub_sitemap(self):
        # Mirrors kpmg.com/sitemap-index.xml: dozens of per-country
        # sub-sitemaps, one of which is the Australian one. The German and
        # French sub-sitemaps are deliberately *not* registered with the
        # fetcher -- fetching them would raise KeyError, proving they were
        # skipped rather than merely unused in the assertion.
        fetcher = _StaticFetcher(
            {
                "https://example.com/sitemap.xml": FetchResponse(
                    "https://example.com/sitemap.xml",
                    200,
                    '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    "<sitemap><loc>https://example.com/de/sitemap.xml</loc></sitemap>"
                    "<sitemap><loc>https://example.com/au/sitemap.xml</loc></sitemap>"
                    "<sitemap><loc>https://example.com/fr/sitemap.xml</loc></sitemap>"
                    "</sitemapindex>",
                    {},
                ),
                "https://example.com/sitemap_index.xml": FetchResponse(
                    "https://example.com/sitemap_index.xml", 404, "", {}
                ),
                "https://example.com/au/sitemap.xml": FetchResponse(
                    "https://example.com/au/sitemap.xml",
                    200,
                    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    "<url><loc>https://example.com/au/insights.html</loc></url></urlset>",
                    {},
                ),
            }
        )
        results = SitemapSource(fetcher).discover("https://example.com")
        self.assertEqual(
            [result.raw_url for result in results],
            ["https://example.com/au/insights.html"],
        )

    def test_sitemap_index_falls_back_to_locale_free_default_without_au(self):
        # Mirrors oliverwyman.com/sitemap.xml: no Australian sub-sitemap, but
        # a clear multi-region split (India, Spain) alongside a locale-free
        # default. India/Spain are not registered with the fetcher, so
        # fetching them would raise KeyError.
        fetcher = _StaticFetcher(
            {
                "https://example.com/sitemap.xml": FetchResponse(
                    "https://example.com/sitemap.xml",
                    200,
                    '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    "<sitemap><loc>https://example.com/in/sitemap.xml</loc></sitemap>"
                    "<sitemap><loc>https://example.com/es/sitemap.xml</loc></sitemap>"
                    "<sitemap><loc>https://example.com/global-sitemap.xml</loc></sitemap>"
                    "</sitemapindex>",
                    {},
                ),
                "https://example.com/sitemap_index.xml": FetchResponse(
                    "https://example.com/sitemap_index.xml", 404, "", {}
                ),
                "https://example.com/global-sitemap.xml": FetchResponse(
                    "https://example.com/global-sitemap.xml",
                    200,
                    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    "<url><loc>https://example.com/insights.html</loc></url></urlset>",
                    {},
                ),
            }
        )
        results = SitemapSource(fetcher).discover("https://example.com")
        self.assertEqual(
            [result.raw_url for result in results],
            ["https://example.com/insights.html"],
        )

    def test_sitemap_index_with_content_taxonomy_names_crawls_everything(self):
        # Mirrors openai.com/sitemap.xml: split by content category (api,
        # chatgpt, company), not by country. None of these are locale-shaped,
        # so the region filter must leave the full set untouched.
        fetcher = _StaticFetcher(
            {
                "https://example.com/sitemap.xml": FetchResponse(
                    "https://example.com/sitemap.xml",
                    200,
                    '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    "<sitemap><loc>https://example.com/api-sitemap.xml</loc></sitemap>"
                    "<sitemap><loc>https://example.com/company-sitemap.xml</loc></sitemap>"
                    "</sitemapindex>",
                    {},
                ),
                "https://example.com/sitemap_index.xml": FetchResponse(
                    "https://example.com/sitemap_index.xml", 404, "", {}
                ),
                "https://example.com/api-sitemap.xml": FetchResponse(
                    "https://example.com/api-sitemap.xml",
                    200,
                    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    "<url><loc>https://example.com/api/docs</loc></url></urlset>",
                    {},
                ),
                "https://example.com/company-sitemap.xml": FetchResponse(
                    "https://example.com/company-sitemap.xml",
                    200,
                    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    "<url><loc>https://example.com/company/about</loc></url></urlset>",
                    {},
                ),
            }
        )
        results = SitemapSource(fetcher).discover("https://example.com")
        self.assertEqual(
            sorted(result.raw_url for result in results),
            ["https://example.com/api/docs", "https://example.com/company/about"],
        )

    def test_sitemap_emits_inferred_parent_for_liveness_gate(self):
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
        self.assertFalse(results[0].force_discarded)

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

    def test_large_sitemap_prefers_recent_lastmod_when_every_url_declares_one(self):
        # Every <url> declares <lastmod> -- the "current type of sitemap" the
        # feature is scoped to. The most-recently-modified opaque URLs must
        # be kept even when even-spaced sampling would have picked others.
        entries = (
            ("https://example.com/opaque/one", "2020-01-01"),
            ("https://example.com/opaque/two", "2023-06-01"),
            ("https://example.com/opaque/three", "2021-01-01"),
            ("https://example.com/opaque/four", "2022-06-01"),
        )
        xml = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(
            f"<url><loc>{loc}</loc><lastmod>{lastmod}</lastmod></url>"
            for loc, lastmod in entries
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
            recency_sample_limit=2,
        )
        results = source.discover(
            "https://example.com",
            ("https://example.com/content.xml",),
        )

        urls = {result.raw_url for result in results}
        self.assertEqual(urls, {"https://example.com/opaque/two", "https://example.com/opaque/four"})

    def test_large_sitemap_falls_back_to_even_sampling_when_lastmod_is_incomplete(self):
        # Same shape as above, but one <url> is missing <lastmod> -- the
        # schema isn't fully supported, so this must fall back to the
        # existing even-spaced sampling rather than guess at the missing date.
        xml = (
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://example.com/opaque/one</loc>"
            "<lastmod>2020-01-01</lastmod></url>"
            "<url><loc>https://example.com/opaque/two</loc>"
            "<lastmod>2023-06-01</lastmod></url>"
            "<url><loc>https://example.com/opaque/three</loc></url>"
            "<url><loc>https://example.com/opaque/four</loc>"
            "<lastmod>2022-06-01</lastmod></url>"
            "</urlset>"
        )
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
            recency_sample_limit=2,
        )
        results = source.discover(
            "https://example.com",
            ("https://example.com/content.xml",),
        )

        # Even-spacing over 4 opaque URLs with a cap of 2 picks positions 0
        # and 3 (one, four) -- not the recency-based {two, four}.
        urls = {result.raw_url for result in results}
        self.assertEqual(urls, {"https://example.com/opaque/one", "https://example.com/opaque/four"})

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

    def test_production_rule_schema_only_suggests_six_core_types(self):
        core_paths = {
            "/blog": "BLOG",
            "/news": "NEWS",
            "/pricing": "PRICING",
            "/sale": "PRODUCTS",
            "/services": "SERVICES",
            "/press": "PRESS",
            "/product/blue-shoe": "PRODUCTS",
            "/solutions": "PRODUCTS",
        }
        for path, expected_type in core_paths.items():
            with self.subTest(path=path):
                result = classify_by_rules(
                    CandidateForClassification(
                        f"https://example.com{path}",
                        f"https://example.com{path}",
                    )
                )
                self.assertIsNotNone(result)
                self.assertEqual(result.page_type, expected_type)
                self.assertEqual(result.discovery_status, "SUGGESTED")

        removed_paths = (
            "/about-us",
            "/careers",
            "/work",
            "/contact",
            "/case-study-archive",
            "/packages",
        )
        for path in removed_paths:
            with self.subTest(path=path):
                result = classify_by_rules(
                    CandidateForClassification(
                        f"https://example.com{path}",
                        f"https://example.com{path}",
                    )
                )
                self.assertIsNone(result)
                fallback = classify_candidates(
                    (
                        CandidateForClassification(
                            f"https://example.com{path}",
                            f"https://example.com{path}",
                        ),
                    ),
                    DeterministicStubClassifier(),
                )[0]
                self.assertEqual(fallback.page_type, "OTHER")
                self.assertEqual(fallback.discovery_status, "DISCARDED")

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

    def test_other_page_type_is_coerced_to_discarded(self):
        # Observed with gpt-5-nano: a classifier can return page_type=OTHER
        # with discovery_status=SUGGESTED, a combination our own prompt says
        # is invalid ("mark DISCARDED with page_type OTHER"). classify_
        # candidates must not trust that pairing from any classifier.
        class _InconsistentClassifier:
            def classify(self, candidates):
                return tuple(
                    ClassificationResult(
                        url=candidate.url,
                        page_type="OTHER",
                        discovery_status="SUGGESTED",
                        classification_method="LLM",
                    )
                    for candidate in candidates
                )

        results = classify_candidates(
            (
                CandidateForClassification(
                    "https://example.com/opaque", "https://example.com/opaque"
                ),
            ),
            _InconsistentClassifier(),
        )
        self.assertEqual(results[0].page_type, "OTHER")
        self.assertEqual(results[0].discovery_status, "DISCARDED")

    def test_classify_by_rules_resolves_extensioned_locale_prefixed_urls(self):
        # kpmg.com/au/en/insights.html: discovery_scope already calls this
        # INDEX (extension-stripping + locale-prefix tolerance); classify_by_
        # rules must resolve it the same way instead of falling through to
        # the LLM for something already resolvable for free.
        result = classify_by_rules(
            CandidateForClassification(
                "https://kpmg.com/au/en/insights.html",
                "https://kpmg.com/au/en/insights.html",
            )
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.page_type, "BLOG")
        self.assertEqual(result.discovery_status, "SUGGESTED")
        self.assertEqual(result.classification_method, "RULE")

    def test_classify_by_rules_recognizes_expanded_press_vocabulary(self):
        for path, expected_type in (
            ("/media", "PRESS"),
            ("/media-center", "PRESS"),
            ("/media-centre", "PRESS"),
            ("/newsroom", "PRESS"),
            ("/press-room", "PRESS"),
        ):
            with self.subTest(path=path):
                result = classify_by_rules(
                    CandidateForClassification(
                        f"https://example.com{path}",
                        f"https://example.com{path}",
                    )
                )
                self.assertIsNotNone(result)
                self.assertEqual(result.page_type, expected_type)
                self.assertEqual(discovery_scope(f"https://example.com{path}"), "INDEX")

    def test_deterministic_stub_returns_structured_fallback_results(self):
        candidates = (
            CandidateForClassification("raw", "https://example.com/opaque"),
        )
        result = DeterministicStubClassifier().classify(candidates)[0]
        self.assertEqual(result.page_type, "OTHER")
        self.assertEqual(result.discovery_status, "DISCARDED")
        self.assertEqual(result.classification_method, "LLM")

    def test_open_jev_classifier_parses_typed_choices_and_sends_candidate_state(self):
        candidate = CandidateForClassification(
            "https://example.com/raw-services",
            "https://example.com/services",
            title="Services",
            meta_description="Our service categories",
            sources=("SITEMAP", "LINKS"),
        )
        provider = _RecordingOpenJevProvider(_open_jev_payload())

        result = OpenJevClassifier(provider=provider).classify((candidate,))[0]

        self.assertEqual(result.page_type, "SERVICES")
        self.assertEqual(result.discovery_status, "SUGGESTED")
        self.assertEqual(result.classification_method, "JEV")
        self.assertEqual(
            provider.calls[0]["state"],
            {
                "url": "https://example.com/services",
                "title": "Services",
                "meta_description": "Our service categories",
                "discovery_sources": ["SITEMAP", "LINKS"],
            },
        )
        self.assertEqual(
            set(provider.calls[0]["questions"]),
            {"page_type", "discovery_status"},
        )
        self.assertTrue(
            all(
                question["type"] == "choice"
                for question in provider.calls[0]["questions"].values()
            )
        )

    def test_open_jev_confidence_gate_is_inclusive_at_threshold(self):
        candidate = CandidateForClassification("raw", "https://example.com/opaque")
        for confidence, expected_status in (
            (0.74, "DISCARDED"),
            (0.75, "SUGGESTED"),
            (0.76, "SUGGESTED"),
        ):
            with self.subTest(confidence=confidence):
                classifier = OpenJevClassifier(
                    provider=_RecordingOpenJevProvider(
                        _open_jev_payload(
                            page_type_confidence=confidence,
                            status_confidence=confidence,
                        )
                    )
                )
                result = classifier.classify((candidate,))[0]
                self.assertEqual(result.discovery_status, expected_status)
                self.assertEqual(result.classification_method, "JEV")

    def test_open_jev_other_is_always_discarded(self):
        candidate = CandidateForClassification("raw", "https://example.com/opaque")
        result = OpenJevClassifier(
            provider=_RecordingOpenJevProvider(
                _open_jev_payload(
                    page_type="OTHER",
                    discovery_status="SUGGESTED",
                    page_type_confidence=0.99,
                    status_confidence=0.99,
                )
            )
        ).classify((candidate,))[0]

        self.assertEqual(result.page_type, "OTHER")
        self.assertEqual(result.discovery_status, "DISCARDED")
        self.assertEqual(result.classification_method, "JEV")

    def test_open_jev_rejects_malformed_incomplete_and_unexpected_answers(self):
        candidate = CandidateForClassification("raw", "https://example.com/opaque")
        malformed_payloads = []

        missing_answer = _open_jev_payload()
        del missing_answer["answers"]["page_type"]
        malformed_payloads.append(missing_answer)

        extra_answer = _open_jev_payload()
        extra_answer["answers"]["unexpected"] = {}
        malformed_payloads.append(extra_answer)

        wrong_type = _open_jev_payload()
        wrong_type["answers"]["page_type"]["type"] = "text"
        malformed_payloads.append(wrong_type)

        invalid_choice = _open_jev_payload()
        invalid_choice["answers"]["page_type"]["choice"] = "CAREERS"
        malformed_payloads.append(invalid_choice)

        missing_probability = _open_jev_payload()
        del missing_probability["answers"]["page_type"]["probabilities"]["OTHER"]
        malformed_payloads.append(missing_probability)

        out_of_range_probability = _open_jev_payload()
        out_of_range_probability["answers"]["page_type"]["probabilities"]["SERVICES"] = 1.1
        malformed_payloads.append(out_of_range_probability)

        invalid_confidence = _open_jev_payload()
        invalid_confidence["answers"]["discovery_status"]["confidence"] = -0.01
        malformed_payloads.append(invalid_confidence)

        for payload in malformed_payloads:
            with self.subTest(payload=payload), self.assertRaises(ClassificationError):
                OpenJevClassifier(
                    provider=_RecordingOpenJevProvider(payload)
                ).classify((candidate,))

    def test_classifier_factory_selects_open_jev_and_validates_configuration(self):
        classifier = build_classifier_from_env(
            {
                "DISCOVERY_CLASSIFIER_PROVIDER": "open-jev",
                "OPEN_JEV_ENDPOINT": "http://jev.test/v1/systemone",
                "OPEN_JEV_MODEL": "jev-test",
                "OPEN_JEV_TIMEOUT_SECONDS": "4.5",
                "DISCOVERY_JEV_MIN_CONFIDENCE": "0.76",
            },
            opener=lambda request, timeout: None,
        )

        self.assertIsInstance(classifier, OpenJevClassifier)
        self.assertEqual(classifier.endpoint, "http://jev.test/v1/systemone")
        self.assertEqual(classifier.model, "jev-test")
        self.assertEqual(classifier.timeout_seconds, 4.5)
        self.assertEqual(classifier.min_confidence, 0.76)

        with self.assertRaises(ClassifierConfigurationError):
            build_classifier_from_env({"DISCOVERY_CLASSIFIER_PROVIDER": "anthropic"})
        with self.assertRaises(OpenJevClassifierConfigurationError):
            build_classifier_from_env(
                {
                    "DISCOVERY_CLASSIFIER_PROVIDER": "open-jev",
                    "DISCOVERY_JEV_MIN_CONFIDENCE": "1.1",
                },
                opener=lambda request, timeout: None,
            )

    def test_classifier_factory_keeps_openai_as_default(self):
        classifier = build_classifier_from_env(
            {"OPENAI_KEY": "test-key-not-used"},
            client=_FakeOpenAIClient({"classifications": []}),
        )
        self.assertIsInstance(classifier, OpenAIClassifier)

    def test_classifier_factory_selects_openrouter_without_changing_llm_contract(self):
        classifier = build_classifier_from_env(
            {
                "DISCOVERY_CLASSIFIER_PROVIDER": "openrouter",
                "OPENROUTER_API_KEY": "test-key-not-used",
            },
            client=_FakeChatClient(
                json.dumps(
                    {
                        "classifications": [],
                    }
                )
            ),
        )
        self.assertIsInstance(classifier, OpenAIClassifier)

    def test_openai_classifier_uses_configured_model_and_structured_batch(self):
        candidates = (
            CandidateForClassification(
                "https://example.com/opaque",
                "https://example.com/opaque",
                title="Opaque page",
                meta_description="A concise description of the opaque page.",
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
            json.loads(client.responses.calls[0]["input"])["candidates"][0][
                "meta_description"
            ],
            "A concise description of the opaque page.",
        )
        self.assertEqual(
            client.responses.calls[0]["text"]["format"]["type"],
            "json_schema",
        )

    def test_openai_classifier_requires_api_key_without_injected_client(self):
        with self.assertRaises(OpenAIClassifierConfigurationError):
            OpenAIClassifier.from_env({})

    def test_openai_classifier_wraps_shared_provider_and_defaults_to_gpt4o(self):
        provider = _RecordingLLMProvider(
            {
                "classifications": [
                    {
                        "url": "https://example.com/ambiguous",
                        "page_type": "SERVICES",
                        "discovery_status": "SUGGESTED",
                    }
                ]
            }
        )
        classifier = OpenAIClassifier(provider=provider)

        result = classifier.classify(
            (
                CandidateForClassification(
                    "https://example.com/ambiguous",
                    "https://example.com/ambiguous",
                ),
            )
        )

        self.assertEqual(classifier.model, "gpt-5-nano")
        self.assertIs(classifier.provider, provider)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result[0].classification_method, "LLM")
        self.assertEqual(classifier.last_results, result)

    def test_openai_classifier_prompt_requires_layer2_layer3_distinction(self):
        provider = _RecordingLLMProvider(
            {
                "classifications": [
                    {
                        "url": "https://example.com/ambiguous",
                        "page_type": "OTHER",
                        "discovery_status": "DISCARDED",
                    }
                ]
            }
        )
        classifier = OpenAIClassifier(provider=provider)

        classifier.classify(
            (
                CandidateForClassification(
                    "https://example.com/ambiguous",
                    "https://example.com/ambiguous",
                ),
            )
        )

        instructions = " ".join(provider.calls[0]["instructions"].split())
        self.assertIn("Layer 3", instructions)
        self.assertIn("meta description", instructions)
        self.assertIn("near-identical siblings", instructions)
        self.assertIn(
            'a flat, descriptive slug for one service/product (e.g. "/seo-consultant-melbourne"',
            instructions,
        )
        self.assertIn(
            'a specific named program, package, or numbered offer (e.g. "30-Day SEO Stream"',
            instructions,
        )
        self.assertIn("an industry/vertical-specific landing page", instructions)
        self.assertIn("a resource/asset/template library", instructions)
        self.assertIn('"what we do" / "our approach" / "about us" page', instructions)
        self.assertIn('Never suggest the homepage ("/")', instructions)
        self.assertIn("When ambiguous, choose OTHER/DISCARDED", instructions)
        self.assertIn(
            "BLOG, NEWS, PRICING, PRODUCTS, SERVICES, PRESS, OTHER",
            instructions,
        )
        for removed_type in (
            "CAREERS",
            "TEAM",
            "CEO",
            "ABOUT",
            "CASE_STUDIES",
            "SUCCESS_STORIES",
            "TESTIMONIALS",
            "REVIEWS",
            "INDUSTRIES",
            "CONTACT",
            "WORK",
            "RESULTS",
            "PORTFOLIO",
            "PACKAGES",
        ):
            self.assertNotIn(removed_type, instructions)

        page_type_schema = provider.calls[0]["response_format"]["schema"]
        self.assertEqual(
            page_type_schema["properties"]["classifications"]["items"]["properties"][
                "page_type"
            ]["enum"],
            ["BLOG", "NEWS", "PRICING", "PRODUCTS", "SERVICES", "PRESS", "OTHER"],
        )

    def test_openai_classifier_sends_default_gpt5_nano_to_shared_provider(self):
        client = _FakeOpenAIClient(
            {
                "classifications": [
                    {
                        "url": "https://example.com/ambiguous",
                        "page_type": "OTHER",
                        "discovery_status": "DISCARDED",
                    }
                ]
            }
        )
        classifier = OpenAIClassifier.from_env(
            {"OPENAI_KEY": "test-key-not-used"},
            client=client,
        )

        classifier.classify(
            (
                CandidateForClassification(
                    "https://example.com/ambiguous",
                    "https://example.com/ambiguous",
                ),
            )
        )

        self.assertEqual(client.responses.calls[0]["model"], "gpt-5-nano")

    def test_openai_classifier_switches_to_openrouter_via_provider_flag(self):
        client = _FakeChatClient(
            json.dumps(
                {
                    "classifications": [
                        {
                            "url": "https://example.com/ambiguous",
                            "page_type": "OTHER",
                            "discovery_status": "DISCARDED",
                        }
                    ]
                }
            )
        )
        classifier = OpenAIClassifier.from_env(
            {
                "DISCOVERY_CLASSIFIER_PROVIDER": "openrouter",
                "OPENROUTER_API_KEY": "test-key-not-used",
            },
            client=client,
        )

        classifier.classify(
            (
                CandidateForClassification(
                    "https://example.com/ambiguous",
                    "https://example.com/ambiguous",
                ),
            )
        )

        self.assertEqual(
            client.completions.calls[0]["model"], "deepseek/deepseek-v4-flash-0731"
        )

    def test_openai_classifier_rejects_unknown_provider_flag(self):
        with self.assertRaisesRegex(OpenAIClassifierConfigurationError, "openai.*openrouter"):
            OpenAIClassifier.from_env(
                {"DISCOVERY_CLASSIFIER_PROVIDER": "anthropic"},
                client=_FakeOpenAIClient({"classifications": []}),
            )

    def test_rule_match_never_calls_real_classifier(self):
        provider = _RecordingLLMProvider({"classifications": []})
        classifier = OpenAIClassifier(provider=provider)

        results = classify_candidates(
            (
                CandidateForClassification(
                    "https://example.com/blog",
                    "https://example.com/blog",
                ),
            ),
            classifier,
        )

        self.assertEqual(results[0].page_type, "BLOG")
        self.assertEqual(results[0].classification_method, "RULE")
        self.assertEqual(classifier.call_count, 0)
        self.assertEqual(provider.calls, [])

    def test_fallback_failure_degrades_to_discarded_stub_result(self):
        classifier = _FailingClassifier()
        results = classify_candidates(
            (
                CandidateForClassification(
                    "https://example.com/ambiguous",
                    "https://example.com/ambiguous",
                ),
            ),
            classifier,
        )

        self.assertEqual(classifier.calls, 1)
        self.assertEqual(results[0].page_type, "OTHER")
        self.assertEqual(results[0].discovery_status, "DISCARDED")
        self.assertEqual(results[0].classification_method, "FALLBACK")

    def test_open_jev_failure_degrades_to_fallback_without_a_second_provider(self):
        classifier = OpenJevClassifier(provider=_FailingOpenJevProvider())
        candidate = CandidateForClassification(
            "https://example.com/opaque",
            "https://example.com/opaque",
        )

        results = classify_candidates((candidate,), classifier)

        self.assertEqual(classifier.call_count, 1)
        self.assertEqual(results[0].page_type, "OTHER")
        self.assertEqual(results[0].discovery_status, "DISCARDED")
        self.assertEqual(results[0].classification_method, "FALLBACK")

    def test_discovery_continues_after_one_failed_classifier_batch(self):
        target_repository = _FakeTargetRepository()
        classifier = _FailOneBatchClassifier(failing_batch=2)
        service = DiscoveryService(
            _FakeCompetitorRepository(
                {
                    "id": "competitor-1",
                    "user_id": "company-a",
                    "website_url": "https://example.com",
                }
            ),
            target_repository,
            fallback_classifier=classifier,
            classifier_batch_size=2,
            robots_source=_Robots(),
            sitemap_source=_Source(
                tuple(
                    DiscoveredURL(f"https://example.com/opaque-{index}", "SITEMAP")
                    for index in range(5)
                )
            ),
            link_source=_Source(),
            liveness_checker=lambda url: FetchResult("<html></html>", "HTTP", 200),
        )

        persisted = service.discover_website("competitor-1", user_id="company-a")

        self.assertEqual(len(persisted), 5)
        self.assertEqual([len(batch) for batch in classifier.batches], [2, 2, 1])
        self.assertEqual(
            [row["page_type"] for row in persisted],
            ["SERVICES", "SERVICES", "OTHER", "OTHER", "SERVICES"],
        )
        self.assertEqual(
            [row["discovery_status"] for row in persisted],
            ["SUGGESTED", "SUGGESTED", "DISCARDED", "DISCARDED", "SUGGESTED"],
        )

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

    def test_unmatched_candidate_with_no_recognized_word_stays_force_discarded(self):
        # Mirrors kpmg.com/xx/en/what-we-do/industries/healthcare.html --
        # none of its segments (xx, en, what-we-do, industries, healthcare)
        # match any known vocabulary word, so it must still be auto-discarded
        # before classification. This is the regression guard against
        # reopening the KPMG "30 pages flooded in" problem: only URLs whose
        # *last* segment is a recognized word (see the next test) get a
        # bounded second chance -- an unrecognized word anywhere doesn't.
        competitor = {
            "id": "competitor-1",
            "user_id": "company-a",
            "website_url": "https://example.com",
        }
        classifier = _RecordingClassifier()
        service = DiscoveryService(
            _FakeCompetitorRepository(competitor),
            _FakeTargetRepository(),
            fallback_classifier=classifier,
            robots_source=_Robots(),
            sitemap_source=_Source(
                (
                    DiscoveredURL(
                        "https://example.com/what-we-do/industries/healthcare",
                        "SITEMAP",
                    ),
                )
            ),
            link_source=_Source(),
            liveness_checker=lambda url: True,
        )

        results = service.discover_website("competitor-1", user_id="company-a")

        self.assertEqual(len(classifier.batches), 0)
        self.assertEqual([r["discovery_status"] for r in results], ["DISCARDED"])

    def test_unmatched_candidate_with_recognized_final_segment_reaches_classification(self):
        # Mirrors oliverwyman.com/our-expertise/insights.html: "our-expertise"
        # isn't a locale, so this stays UNMATCHED -- but the last segment
        # ("insights") is a recognized word, so it should now get a bounded
        # chance at LLM judgment instead of being auto-discarded outright.
        competitor = {
            "id": "competitor-1",
            "user_id": "company-a",
            "website_url": "https://example.com",
        }
        classifier = _RecordingClassifier()
        service = DiscoveryService(
            _FakeCompetitorRepository(competitor),
            _FakeTargetRepository(),
            fallback_classifier=classifier,
            robots_source=_Robots(),
            sitemap_source=_Source(
                (DiscoveredURL("https://example.com/our-expertise/insights", "SITEMAP"),)
            ),
            link_source=_Source(),
            liveness_checker=lambda url: True,
        )

        service.discover_website("competitor-1", user_id="company-a")

        self.assertEqual(len(classifier.batches), 1)
        self.assertEqual(
            [c.url for c in classifier.batches[0]],
            ["https://example.com/our-expertise/insights"],
        )

    def test_links_body_link_with_recognized_final_segment_reaches_classification(self):
        # LINKS candidates have a *second*, separate force-discard gate (low-
        # priority body links that aren't structural) -- this is what
        # actually caught oliverwyman.com/our-expertise/insights.html in
        # production, since it was found as a body link (priority 3, inside
        # a <div>-based footer menu, not a semantic <nav>/<header>/<footer>
        # tag) rather than via SITEMAP. That gate must also exempt a
        # recognized final segment, the same as the main gate does.
        competitor = {
            "id": "competitor-1",
            "user_id": "company-a",
            "website_url": "https://example.com",
        }
        classifier = _RecordingClassifier()
        service = DiscoveryService(
            _FakeCompetitorRepository(competitor),
            _FakeTargetRepository(),
            fallback_classifier=classifier,
            robots_source=_Robots(),
            sitemap_source=_Source(),
            link_source=_Source(
                (
                    DiscoveredURL(
                        "https://example.com/our-expertise/insights",
                        "LINKS",
                        "Insights",
                        priority=3,
                    ),
                )
            ),
            liveness_checker=lambda url: True,
        )

        service.discover_website("competitor-1", user_id="company-a")

        self.assertEqual(len(classifier.batches), 1)
        self.assertEqual(
            [c.url for c in classifier.batches[0]],
            ["https://example.com/our-expertise/insights"],
        )

    def test_discovery_run_status_tracks_success_even_when_zero_candidates_persisted(self):
        run_tracker = _FakeDiscoveryRunTracker()
        service = DiscoveryService(
            _FakeCompetitorRepository(
                {
                    "id": "competitor-1",
                    "user_id": "company-a",
                    "website_url": "https://example.com",
                }
            ),
            _FakeTargetRepository(),
            fallback_classifier=_RecordingClassifier(),
            robots_source=_Robots(),
            sitemap_source=_Source(),
            link_source=_Source(),
            liveness_checker=lambda url: True,
            run_repository=run_tracker,
        )

        result = service.discover_website(
            "competitor-1",
            user_id="company-a",
            run_id="run-zero",
        )

        self.assertEqual(result, [])
        self.assertEqual(run_tracker.get("run-zero")["status"], "SUCCESS")
        self.assertEqual(run_tracker.get("run-zero")["candidate_count"], 0)

    def test_product_detail_leaf_is_filtered_but_aggregate_listing_is_not(self):
        target_repository = _FakeTargetRepository()
        classifier = _RecordingClassifier()
        service = DiscoveryService(
            _FakeCompetitorRepository(
                {
                    "id": "competitor-1",
                    "user_id": "company-a",
                    "website_url": "https://example.com",
                }
            ),
            target_repository,
            fallback_classifier=classifier,
            robots_source=_Robots(),
            sitemap_source=_Source(
                (
                    DiscoveredURL(
                        "https://example.com/product/blue-shoe/sku-1",
                        "SITEMAP",
                    ),
                    DiscoveredURL("https://example.com/products", "SITEMAP"),
                )
            ),
            link_source=_Source(),
            liveness_checker=lambda url: True,
        )

        persisted = service.discover_website("competitor-1", user_id="company-a")

        listing = next(row for row in persisted if row["url"].endswith("/products"))
        self.assertEqual(
            [row for row in persisted if "/product/" in row["url"]],
            [],
        )
        self.assertEqual(listing["discovery_status"], "SUGGESTED")
        self.assertEqual(listing["page_type"], "PRODUCTS")
        self.assertEqual(listing["classification_method"], "RULE")
        self.assertEqual(len(classifier.batches), 0)

    def test_discovery_reconciles_old_product_detail_rows_without_touching_manual_or_active(self):
        target_repository = _FakeTargetRepository(
            (
                {
                    "id": "old-product",
                    "competitor_id": "competitor-1",
                    "url": "https://example.com/product/blue-shoe/sku-1",
                    "discovery_source": "SITEMAP",
                    "discovery_status": "SUGGESTED",
                    "classification_method": "RULE",
                    "page_type": "PRODUCTS",
                    "active": False,
                },
                {
                    "id": "manual-product",
                    "competitor_id": "competitor-1",
                    "url": "https://example.com/product/manual/sku-1",
                    "discovery_source": "MANUAL",
                    "discovery_status": "SUGGESTED",
                    "classification_method": "MANUAL",
                    "page_type": "OTHER",
                    "active": False,
                },
                {
                    "id": "active-product",
                    "competitor_id": "competitor-1",
                    "url": "https://example.com/product/active/sku-1",
                    "discovery_source": "SITEMAP",
                    "discovery_status": "ACTIVE",
                    "classification_method": "RULE",
                    "page_type": "PRODUCTS",
                    "active": True,
                },
            )
        )
        service = DiscoveryService(
            _FakeCompetitorRepository(
                {
                    "id": "competitor-1",
                    "user_id": "company-a",
                    "website_url": "https://example.com",
                }
            ),
            target_repository,
            fallback_classifier=DeterministicStubClassifier(),
            robots_source=_Robots(),
            sitemap_source=_Source(),
            link_source=_Source(),
            liveness_checker=lambda url: True,
        )

        service.discover_website("competitor-1", user_id="company-a")

        rows = {row["id"]: row for row in target_repository.saved}
        self.assertEqual(rows["old-product"]["discovery_status"], "DISCARDED")
        self.assertEqual(rows["old-product"]["page_type"], "OTHER")
        self.assertEqual(rows["manual-product"]["discovery_status"], "SUGGESTED")
        self.assertEqual(rows["active-product"]["discovery_status"], "ACTIVE")

    def test_discovery_service_degrades_when_fallback_classifier_fails(self):
        target_repository = _FakeTargetRepository()
        service = DiscoveryService(
            _FakeCompetitorRepository(
                {
                    "id": "competitor-1",
                    "user_id": "company-a",
                    "website_url": "https://example.com",
                }
            ),
            target_repository,
            fallback_classifier=_FailingClassifier(),
            robots_source=_Robots(),
            sitemap_source=_Source(
                (DiscoveredURL("https://example.com/ambiguous", "SITEMAP"),)
            ),
            link_source=_Source(),
            liveness_checker=lambda url: True,
        )

        persisted = service.discover_website("competitor-1", user_id="company-a")

        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0]["url"], "https://example.com/ambiguous")
        self.assertEqual(persisted[0]["page_type"], "OTHER")
        self.assertEqual(persisted[0]["discovery_status"], "DISCARDED")
        self.assertEqual(persisted[0]["classification_method"], "FALLBACK")

    def test_discovery_service_defaults_to_stub_when_provider_is_unconfigured(self):
        target_repository = _FakeTargetRepository()
        with patch(
            "backend.flask.discovery.service.build_classifier_from_env",
            side_effect=ClassifierConfigurationError("OPENAI_KEY is not configured"),
        ):
            service = DiscoveryService(
                _FakeCompetitorRepository(
                    {
                        "id": "competitor-1",
                        "user_id": "company-a",
                        "website_url": "https://example.com",
                    }
                ),
                target_repository,
                robots_source=_Robots(),
                sitemap_source=_Source(
                    (DiscoveredURL("https://example.com/ambiguous", "SITEMAP"),)
                ),
                link_source=_Source(),
                liveness_checker=lambda url: True,
            )

            persisted = service.discover_website(
                "competitor-1",
                user_id="company-a",
            )

        self.assertEqual(persisted[0]["discovery_status"], "DISCARDED")

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
            liveness_sleep=lambda _: None,
        )

        persisted = service.discover_website("elevation", user_id="company-a")

        self.assertEqual(
            liveness_calls,
            [
                "https://elevationmarketing.au/blog-posts",
                "https://elevationmarketing.au/blog-posts",
                "https://elevationmarketing.au/blog-posts",
            ],
        )
        self.assertEqual(persisted[0]["url"], "https://elevationmarketing.au/blog-posts")
        self.assertEqual(persisted[0]["discovery_status"], "DISCARDED")
        self.assertEqual(persisted[0]["classification_method"], "RULE")

    def test_liveness_gate_discards_soft_404_via_page_title(self):
        # Mirrors marketingeye.com.au/press-releases: returns HTTP 200 (so a
        # status-code-only liveness check sees it as "alive"), but the site
        # redirected it to a real error page titled "Page Not Found". Only
        # inspecting the fetched content catches this.
        press_releases_url = "https://example.com/press-releases"
        liveness_calls = []

        def soft_404_liveness(url):
            liveness_calls.append(url)
            return fetch_page(
                url,
                http_fetcher=lambda _: HttpResponse(
                    "<html><head><title>Page Not Found - Example</title></head>"
                    "<body>We can't find that page.</body></html>",
                    200,
                    {"Content-Type": "text/html"},
                ),
            )

        target_repository = _FakeTargetRepository()
        service = DiscoveryService(
            _FakeCompetitorRepository(
                {
                    "id": "competitor-1",
                    "user_id": "company-a",
                    "website_url": "https://example.com",
                }
            ),
            target_repository,
            fallback_classifier=DeterministicStubClassifier(),
            robots_source=_Robots(),
            sitemap_source=_Source((DiscoveredURL(press_releases_url, "SITEMAP"),)),
            link_source=_Source(),
            liveness_checker=soft_404_liveness,
            liveness_sleep=lambda _: None,
        )

        persisted = service.discover_website("competitor-1", user_id="company-a")

        self.assertEqual(liveness_calls, [press_releases_url])
        self.assertEqual(persisted[0]["url"], press_releases_url)
        self.assertEqual(persisted[0]["discovery_status"], "DISCARDED")
        self.assertEqual(persisted[0]["classification_method"], "RULE")

    def test_liveness_gate_keeps_candidate_after_transient_failure(self):
        attempts = []

        def transient_liveness(url):
            attempts.append(url)
            if len(attempts) == 1:
                raise MonitoringError("temporary network failure")
            return FetchResult(
                content="<html><body>Live page with stable content.</body></html>",
                fetch_method="HTTP",
                http_status=200,
            )

        target_repository = _FakeTargetRepository()
        service = DiscoveryService(
            _FakeCompetitorRepository(
                {
                    "id": "competitor-1",
                    "user_id": "company-a",
                    "website_url": "https://example.com/",
                }
            ),
            target_repository,
            fallback_classifier=DeterministicStubClassifier(),
            robots_source=_Robots(),
            sitemap_source=_Source(
                (DiscoveredURL("https://example.com/blog", "SITEMAP"),)
            ),
            link_source=_Source(),
            liveness_checker=transient_liveness,
            liveness_sleep=lambda _: None,
        )

        persisted = service.discover_website("competitor-1", user_id="company-a")

        self.assertEqual(attempts, ["https://example.com/blog"] * 2)
        self.assertEqual(persisted[0]["discovery_status"], "SUGGESTED")
        self.assertEqual(persisted[0]["classification_method"], "RULE")

    def test_liveness_gate_keeps_candidate_when_response_is_anti_bot_blocked(self):
        attempts = []

        def blocked_liveness(url):
            attempts.append(url)
            return fetch_page(
                url,
                http_fetcher=lambda _: HttpResponse(
                    "Forbidden by bot protection",
                    403,
                    {"Content-Type": "text/plain"},
                ),
                browser_fetcher=lambda _: HttpResponse(
                    "Forbidden by bot protection",
                    403,
                    {"Content-Type": "text/plain"},
                ),
            )

        target_repository = _FakeTargetRepository()
        service = DiscoveryService(
            _FakeCompetitorRepository(
                {
                    "id": "competitor-1",
                    "user_id": "company-a",
                    "website_url": "https://example.com/",
                }
            ),
            target_repository,
            fallback_classifier=DeterministicStubClassifier(),
            robots_source=_Robots(),
            sitemap_source=_Source(
                (DiscoveredURL("https://example.com/pricing", "SITEMAP"),)
            ),
            link_source=_Source(),
            liveness_checker=blocked_liveness,
            liveness_sleep=lambda _: None,
        )

        persisted = service.discover_website("competitor-1", user_id="company-a")

        self.assertEqual(attempts, ["https://example.com/pricing"] * 3)
        self.assertEqual(persisted[0]["discovery_status"], "SUGGESTED")
        self.assertEqual(persisted[0]["page_type"], "PRICING")

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
        self.assertEqual(activated["check_interval_minutes"], 180)
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

    def _manual_service(self, liveness_checker=None):
        return DiscoveryService(
            _FakeCompetitorRepository(self.competitor),
            self.target_repository,
            fallback_classifier=DeterministicStubClassifier(),
            robots_source=_Robots(),
            sitemap_source=_Source(),
            link_source=_Source(),
            liveness_checker=liveness_checker or (lambda url: True),
            liveness_attempts=2,
            liveness_backoff_seconds=0,
            liveness_sleep=lambda _: None,
        )

    def test_add_manual_target_resolves_type_defaults_and_activates_immediately(self):
        service = self._manual_service()

        pricing = service.add_manual_target(
            "competitor-1",
            "https://example.com/pricing/",
        )
        sale = service.add_manual_target(
            "competitor-1",
            "https://example.com/sale/",
            page_type="PRODUCT_LISTING",
        )
        other = service.add_manual_target(
            "competitor-1",
            "https://example.com/custom-offer",
        )

        self.assertEqual(pricing["page_type"], "PRICING")
        self.assertEqual(pricing["check_interval_minutes"], 360)
        self.assertEqual(pricing["discovery_status"], "ACTIVE")
        self.assertTrue(pricing["active"])
        self.assertEqual(pricing["classification_method"], "MANUAL")
        self.assertEqual(sale["url"], "https://example.com/sale")
        self.assertEqual(sale["page_type"], "PRODUCT_LISTING")
        self.assertEqual(sale["discovery_status"], "ACTIVE")
        self.assertEqual(other["page_type"], "OTHER")
        self.assertEqual(other["check_interval_minutes"], 1440)
        self.assertEqual(
            {target["id"] for target in service.list_active_targets("competitor-1")},
            {pricing["id"], sale["id"], other["id"]},
        )

    def test_add_manual_target_rejects_dead_url_without_persisting(self):
        def dead_liveness(url):
            raise BrowserFetchError("not found", http_status=404)

        service = self._manual_service(dead_liveness)
        original_count = len(self.target_repository.records)

        with self.assertRaisesRegex(DiscoveryError, "failed liveness checks"):
            service.add_manual_target(
                "competitor-1",
                "https://example.com/not-a-real-page",
            )

        self.assertEqual(len(self.target_repository.records), original_count)
        self.assertIsNone(
            self.target_repository.find_by_url(
                "competitor-1",
                "https://example.com/not-a-real-page",
            )
        )

    def test_add_manual_target_promotes_suggested_and_discarded_duplicates_in_place(self):
        service = self._manual_service()
        original_count = len(self.target_repository.records)

        suggested = service.add_manual_target(
            "competitor-1",
            "https://example.com/blog/",
        )
        discarded = service.add_manual_target(
            "competitor-1",
            "https://example.com/opaque",
            page_type="ABOUT",
        )

        self.assertEqual(suggested["id"], "candidate-1")
        self.assertEqual(suggested["discovery_status"], "ACTIVE")
        self.assertTrue(suggested["active"])
        self.assertEqual(suggested["check_interval_minutes"], 180)
        self.assertEqual(discarded["id"], "candidate-3")
        self.assertEqual(discarded["discovery_status"], "ACTIVE")
        self.assertTrue(discarded["active"])
        self.assertEqual(discarded["page_type"], "ABOUT")
        self.assertEqual(len(self.target_repository.records), original_count)

    def test_add_manual_target_returns_active_duplicate_without_rechecking_or_inserting(self):
        liveness_calls = []

        def live_liveness(url):
            liveness_calls.append(url)
            return True

        service = self._manual_service(live_liveness)
        first = service.add_manual_target(
            "competitor-1",
            "https://example.com/manual-active",
        )
        count_after_first = len(self.target_repository.records)

        second = service.add_manual_target(
            "competitor-1",
            "https://example.com/manual-active/",
        )

        self.assertEqual(second["id"], first["id"])
        self.assertEqual(len(self.target_repository.records), count_after_first)
        self.assertEqual(liveness_calls, ["https://example.com/manual-active"])

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

    def test_remove_candidate_hard_deletes_unactivated_and_historyless_active(self):
        history = _HistoryRepository()
        service = self._manual_service()
        service.snapshot_repository = history
        service.change_repository = history

        self.assertTrue(service.remove_candidate("candidate-2"))
        self.assertIsNone(self.target_repository.get("candidate-2"))

        service.activate_candidate("candidate-1")
        self.assertTrue(service.remove_candidate("candidate-1"))
        self.assertIsNone(self.target_repository.get("candidate-1"))

    def test_remove_candidate_deactivates_active_target_with_history(self):
        history = _HistoryRepository(("candidate-1",))
        service = self._manual_service()
        service.snapshot_repository = history
        service.change_repository = _HistoryRepository()
        service.activate_candidate("candidate-1")

        self.assertTrue(service.remove_candidate("candidate-1"))
        retained = self.target_repository.get("candidate-1")
        self.assertIsNotNone(retained)
        self.assertFalse(retained["active"])
        self.assertEqual(retained["discovery_status"], "ACTIVE")


if __name__ == "__main__":
    unittest.main()
