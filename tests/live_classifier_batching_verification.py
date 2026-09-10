"""Opt-in live evidence for bounded classifier batches and failure isolation.

Run from the repository root with network access:

    RUN_LIVE_CLASSIFIER_BATCHING=1 \
      ./.venv/bin/python -u tests/live_classifier_batching_verification.py

The website sources, liveness checks, and candidate counts are real. The
classifier double records the production batch boundary so the verification
does not make uncontrolled external LLM calls.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.discovery.classification import (
    CandidateForClassification,
    ClassificationResult,
)
try:
    from backend.flask.discovery.classification import DEFAULT_CLASSIFIER_BATCH_SIZE
except ImportError:  # pragma: no cover - compatibility for the pre-batching baseline
    DEFAULT_CLASSIFIER_BATCH_SIZE = 0
from backend.flask.discovery.service import DiscoveryService


WEBSITE_URL = "https://www.jd-sports.com.au/"
LIVE_CANDIDATE_CEILING = int(
    os.environ.get("DISCOVERY_LIVE_CANDIDATE_CEILING", "600")
)
FORCED_FAILURE_BATCH = int(os.environ.get("CLASSIFIER_FORCE_FAIL_BATCH", "0"))


class _LiveCompetitorRepository:
    def __init__(self, website_url: str):
        self.competitor = {
            "id": website_url,
            "user_id": "live-classifier-batching-verification",
            "website_url": website_url,
        }

    def get(self, competitor_id: str, *, user_id: str | None = None):
        if competitor_id != self.competitor["id"]:
            return None
        if user_id is not None and user_id != self.competitor["user_id"]:
            return None
        return self.competitor


class _MemoryMonitoringTargetRepository:
    def __init__(self):
        self.records: list[dict[str, object]] = []

    def upsert_discovered_candidate(self, **candidate):
        record = {"id": str(len(self.records) + 1), **candidate, "active": False}
        self.records.append(record)
        return record

    def discard_discovered_candidates_by_url_patterns(
        self, competitor_id: str, *, url_patterns: tuple[str, ...]
    ) -> int:
        return 0


class _RecordingClassifier:
    def __init__(self, *, fail_on_batch: int = 0):
        self.fail_on_batch = fail_on_batch
        self.batches: list[tuple[CandidateForClassification, ...]] = []

    def classify(self, candidates):
        batch = tuple(candidates)
        self.batches.append(batch)
        if self.fail_on_batch and len(self.batches) == self.fail_on_batch:
            raise RuntimeError("forced classifier batch failure")
        return tuple(
            ClassificationResult(
                url=candidate.url,
                page_type="SERVICES",
                discovery_status="SUGGESTED",
                classification_method="LLM",
            )
            for candidate in batch
        )


def run_live_verification() -> None:
    if os.environ.get("RUN_LIVE_CLASSIFIER_BATCHING") != "1":
        raise SystemExit("Set RUN_LIVE_CLASSIFIER_BATCHING=1 to run live verification")
    if LIVE_CANDIDATE_CEILING < 1:
        raise AssertionError("DISCOVERY_LIVE_CANDIDATE_CEILING must be positive")

    target_repository = _MemoryMonitoringTargetRepository()
    classifier = _RecordingClassifier(fail_on_batch=FORCED_FAILURE_BATCH)
    service = DiscoveryService(
        _LiveCompetitorRepository(WEBSITE_URL),
        target_repository,
        fallback_classifier=classifier,
    )
    results = service.discover_website(
        WEBSITE_URL,
        user_id="live-classifier-batching-verification",
    )
    if len(results) > LIVE_CANDIDATE_CEILING:
        raise AssertionError(
            f"{len(results)} candidates exceeds ceiling {LIVE_CANDIDATE_CEILING}"
        )

    failed_batch_size = (
        len(classifier.batches[FORCED_FAILURE_BATCH - 1])
        if FORCED_FAILURE_BATCH and FORCED_FAILURE_BATCH <= len(classifier.batches)
        else 0
    )
    print(f"site={WEBSITE_URL}")
    print(f"total_candidates={len(results)}")
    print(f"suggested={sum(row['discovery_status'] == 'SUGGESTED' for row in results)}")
    print(f"discarded={sum(row['discovery_status'] == 'DISCARDED' for row in results)}")
    print(f"configured_batch_size={getattr(service, 'classifier_batch_size', DEFAULT_CLASSIFIER_BATCH_SIZE)}")
    print(f"fallback_batch_sizes={[len(batch) for batch in classifier.batches]}")
    print(f"fallback_batch_count={len(classifier.batches)}")
    print(f"forced_failure_batch={FORCED_FAILURE_BATCH}")
    print(f"forced_failure_batch_size={failed_batch_size}")
    if FORCED_FAILURE_BATCH:
        failed_urls = {
            candidate.url
            for candidate in classifier.batches[FORCED_FAILURE_BATCH - 1]
        }
        failed_rows = [row for row in results if row["url"] in failed_urls]
        print(
            "failed_batch_results="
            f"{[(row['page_type'], row['discovery_status']) for row in failed_rows]}"
        )
        print(
            "successful_batch_count="
            f"{len(classifier.batches) - 1}"
        )
        print(
            "successful_batch_suggested_rows="
            f"{sum(row['discovery_status'] == 'SUGGESTED' for row in results if row['url'] not in failed_urls)}"
        )


if __name__ == "__main__":
    run_live_verification()
