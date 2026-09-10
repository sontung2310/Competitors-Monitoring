"""Opt-in live evidence for the production second-pass discovery audit.

Run from the repository root with network access and the configured OpenAI
credentials (the provider also loads ``.env``):

    RUN_LIVE_DISCOVERY_SECOND_PASS_AUDIT=1 \
      ./.venv/bin/python -u tests/live_discovery_second_pass_audit_verification.py

The real-site run uses in-memory competitor/target repositories, so it never
writes application MongoDB data. The forced redundancy and forced failure
checks exercise the same service path without external calls.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.discovery.audit import (
    DiscoveryAuditResult,
    OpenAIDiscoveryAudit,
    RedundancyFlag,
)
from backend.flask.discovery.classification import (
    DeterministicStubClassifier,
    OpenAIClassifier,
)
from backend.flask.discovery.service import DiscoveryService
from backend.flask.discovery.sources import DiscoveredURL
from backend.flask.website_monitoring.service import FetchResult


SITE_ID = "lyfemarketing.com"
SITE_URL = "https://www.lyfemarketing.com/"


class _MemoryCompetitorRepository:
    def __init__(self, competitor_id: str, website_url: str):
        self.competitor = {
            "id": competitor_id,
            "user_id": "live-second-pass-audit",
            "website_url": website_url,
        }

    def get(self, competitor_id: str, *, user_id: str | None = None, company_id: Any = None):
        if competitor_id != self.competitor["id"]:
            return None
        if user_id is not None and user_id != self.competitor["user_id"]:
            return None
        return dict(self.competitor)

    def update(self, competitor_id: str, updates=None, *, user_id=None, company_id=None, **fields):
        if competitor_id != self.competitor["id"]:
            return None
        if user_id is not None and user_id != self.competitor["user_id"]:
            return None
        self.competitor.update({**(updates or {}), **fields})
        return dict(self.competitor)


class _MemoryTargetRepository:
    def __init__(self):
        self.records: list[dict[str, object]] = []

    def upsert_discovered_candidate(self, **candidate):
        record = {"id": str(len(self.records) + 1), **candidate, "active": False}
        self.records.append(record)
        return dict(record)

    def get(self, candidate_id, *, competitor_id=None):
        for record in self.records:
            if record["id"] == candidate_id and (
                competitor_id is None or record.get("competitor_id") == competitor_id
            ):
                return dict(record)
        return None

    def update(self, candidate_id, updates=None, *, competitor_id=None, **fields):
        for record in self.records:
            if record["id"] == candidate_id and (
                competitor_id is None or record.get("competitor_id") == competitor_id
            ):
                record.update({**(updates or {}), **fields})
                return dict(record)
        return None

    def discard_discovered_candidates_by_url_patterns(self, competitor_id, *, url_patterns):
        return 0


class _StaticSource:
    def __init__(self, candidates=(), homepage_metadata=None):
        self.candidates = tuple(candidates)
        self.last_homepage_metadata = homepage_metadata or {
            "title": None,
            "meta_description": None,
        }

    def discover(self, website_url, declared_sitemaps=()):
        return self.candidates


class _StaticRobots:
    def sitemap_urls(self, website_url):
        return ()


class _RecordingAudit:
    def __init__(self, inner):
        self.inner = inner
        self.calls = []
        self.result = None

    def audit(self, candidates, *, homepage_title, homepage_meta_description):
        self.calls.append(
            {
                "candidates": tuple(candidates),
                "homepage_title": homepage_title,
                "homepage_meta_description": homepage_meta_description,
            }
        )
        self.result = self.inner.audit(
            candidates,
            homepage_title=homepage_title,
            homepage_meta_description=homepage_meta_description,
        )
        return self.result


class _FixedAudit:
    def __init__(self, result):
        self.result = result

    def audit(self, candidates, *, homepage_title, homepage_meta_description):
        return self.result


class _FailingAudit:
    def audit(self, candidates, *, homepage_title, homepage_meta_description):
        raise RuntimeError("forced audit outage")


def _run_real_site() -> dict[str, object]:
    try:
        classifier = OpenAIClassifier.from_env()
        auditor = _RecordingAudit(OpenAIDiscoveryAudit.from_env())
    except Exception as exc:
        raise SystemExit(f"OpenAI provider configuration failed: {exc}") from exc

    competitors = _MemoryCompetitorRepository(SITE_ID, SITE_URL)
    targets = _MemoryTargetRepository()
    service = DiscoveryService(
        competitors,
        targets,
        fallback_classifier=classifier,
        audit_classifier=auditor,
    )
    results = service.discover_website(SITE_ID, user_id="live-second-pass-audit")
    if len(auditor.calls) != 1:
        raise AssertionError(f"expected one audit call, got {len(auditor.calls)}")
    audit_input = auditor.calls[0]
    flagged_urls = [flag.url for flag in auditor.result.flagged_redundant]
    flagged_rows = [row["url"] for row in results if row["url"] in flagged_urls]
    if any(
        row["discovery_status"] != "DISCARDED" for row in results if row["url"] in flagged_urls
    ):
        raise AssertionError("an audit-flagged suggestion was not discarded")
    report = {
        "site": SITE_ID,
        "homepage": {
            "title": audit_input["homepage_title"],
            "meta_description": audit_input["homepage_meta_description"],
        },
        "first_pass_suggested_count": len(audit_input["candidates"]),
        "audit_call_count": len(auditor.calls),
        "audit_input_sample": [candidate.__dict__ for candidate in audit_input["candidates"][:10]],
        "flagged_redundant": [flag.__dict__ for flag in auditor.result.flagged_redundant],
        "flagged_redundant_rows_after_audit": flagged_rows,
        "flagged_missing_categories": [
            flag.__dict__ for flag in auditor.result.flagged_missing_categories
        ],
        "persisted_discovery_gap_flags": competitors.competitor.get(
            "discovery_gap_flags", []
        ),
        "final_suggested_count": sum(
            row["discovery_status"] == "SUGGESTED" for row in results
        ),
        "final_discarded_count": sum(
            row["discovery_status"] == "DISCARDED" for row in results
        ),
    }
    return report


def _build_forced_service(audit) -> DiscoveryService:
    competitors = _MemoryCompetitorRepository("forced", "https://example.com/")
    targets = _MemoryTargetRepository()
    return DiscoveryService(
        competitors,
        targets,
        fallback_classifier=DeterministicStubClassifier(
            page_type="SERVICES", discovery_status="SUGGESTED"
        ),
        audit_classifier=audit,
        robots_source=_StaticRobots(),
        sitemap_source=_StaticSource(
            (
                DiscoveredURL("https://example.com/consulting", "SITEMAP"),
                DiscoveredURL("https://example.com/strategy", "SITEMAP"),
            )
        ),
        link_source=_StaticSource(),
        liveness_checker=lambda url: FetchResult("<html></html>", "HTTP", 200),
    )


def _run_forced_checks() -> dict[str, object]:
    redundancy_service = _build_forced_service(
        _FixedAudit(
            DiscoveryAuditResult(
                flagged_redundant=(
                    RedundancyFlag(
                        "https://example.com/strategy",
                        "Duplicate service section.",
                    ),
                ),
                flagged_missing_categories=(),
            )
        )
    )
    redundancy_rows = redundancy_service.discover_website(
        "forced", user_id="live-second-pass-audit"
    )
    statuses = {row["url"]: row["discovery_status"] for row in redundancy_rows}
    if statuses["https://example.com/strategy"] != "DISCARDED":
        raise AssertionError(f"forced redundancy was not discarded: {statuses}")
    if statuses["https://example.com/consulting"] != "SUGGESTED":
        raise AssertionError(f"unflagged suggestion changed: {statuses}")

    failure_service = _build_forced_service(_FailingAudit())
    failure_rows = failure_service.discover_website(
        "forced", user_id="live-second-pass-audit"
    )
    if any(row["discovery_status"] != "SUGGESTED" for row in failure_rows):
        raise AssertionError("audit failure changed first-pass results")
    if failure_service.last_audit_error is None:
        raise AssertionError("audit failure was not recorded")
    return {
        "forced_redundancy_statuses": statuses,
        "forced_failure_statuses": {
            row["url"]: row["discovery_status"] for row in failure_rows
        },
        "forced_failure_error": failure_service.last_audit_error,
    }


def run_live_verification() -> None:
    if os.environ.get("RUN_LIVE_DISCOVERY_SECOND_PASS_AUDIT") != "1":
        raise SystemExit(
            "Set RUN_LIVE_DISCOVERY_SECOND_PASS_AUDIT=1 to run live verification"
        )
    print(json.dumps({"real_site": _run_real_site(), "forced_checks": _run_forced_checks()}, indent=2))


if __name__ == "__main__":
    run_live_verification()
