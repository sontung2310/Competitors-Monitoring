"""Opt-in live Layer 1 verification for the two ongoing test websites.

Run from the repository root with:

    RUN_LIVE_DISCOVERY=1 python3 tests/live_discovery_verification.py

The candidate ceiling is intentionally tunable while the default remains 60:

    DISCOVERY_LIVE_CANDIDATE_CEILING=60

The run uses live robots/sitemap/homepage-link discovery and an in-memory repository
with the deterministic classifier. It does not require MongoDB or an LLM call.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.discovery.classification import DeterministicStubClassifier
from backend.flask.discovery.service import DiscoveryService


LIVE_CANDIDATE_CEILING = int(
    os.environ.get("DISCOVERY_LIVE_CANDIDATE_CEILING", "60")
)
SITES = (
    ("lyfemarketing.com", "https://www.lyfemarketing.com/"),
    ("brownbagmarketing.com", "https://brownbagmarketing.com/"),
)
LYFE_REQUIRED_PATHS = {
    "/blog",
    "/services",
    "/case-study-archive",
    "/small-business-success-stories",
    "/client-testimonials",
    "/lyfe-marketing-reviews",
    "/about-lyfe-marketing",
}
LYFE_INDEX_PATHS = {
    "/blog",
    "/services",
    "/case-study-archive",
    "/small-business-success-stories",
    "/client-testimonials",
    "/lyfe-marketing-reviews",
    "/about-lyfe-marketing",
}


class _LiveCompetitorRepository:
    def __init__(self, competitor: dict[str, str]):
        self.competitor = competitor

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


def run_live_verification() -> dict[str, list[dict[str, object]]]:
    """Run and assert live discovery for every acceptance-test website."""

    if LIVE_CANDIDATE_CEILING < 1:
        raise AssertionError("DISCOVERY_LIVE_CANDIDATE_CEILING must be positive")

    verified: dict[str, list[dict[str, object]]] = {}
    for label, website_url in SITES:
        targets = _MemoryMonitoringTargetRepository()
        service = DiscoveryService(
            _LiveCompetitorRepository(
                {"id": label, "user_id": "live-verification", "website_url": website_url}
            ),
            targets,
            fallback_classifier=DeterministicStubClassifier(),
        )
        results = service.discover_website(label, user_id="live-verification")
        summary = service.last_summary
        if summary is None:
            raise AssertionError(f"{label}: discovery did not produce a summary")
        if len(results) > LIVE_CANDIDATE_CEILING:
            raise AssertionError(
                f"{label}: {len(results)} candidates exceeds ceiling "
                f"{LIVE_CANDIDATE_CEILING}"
            )

        suggested_paths = {
            _path_without_trailing_slash(record["url"])
            for record in results
            if record["discovery_status"] == "SUGGESTED"
        }
        if label == "lyfemarketing.com":
            missing = LYFE_REQUIRED_PATHS - suggested_paths
            if missing:
                raise AssertionError(f"Lyfe missing suggested paths: {sorted(missing)}")
            for record in results:
                path = _path_without_trailing_slash(record["url"])
                if any(path.startswith(index_path + "/") for index_path in LYFE_INDEX_PATHS):
                    raise AssertionError(
                        f"Lyfe index leaf survived normalization: {record['url']}"
                    )

        verified[label] = results
        _print_report(label, results, summary)

    return verified


def _path_without_trailing_slash(url: object) -> str:
    path = urlsplit(str(url)).path
    return path.rstrip("/") or "/"


def _print_report(label, results, summary) -> None:
    print(f"\n=== {label} ===")
    print(
        f"total={len(results)} suggested={summary.suggested_count} "
        f"discarded={summary.discarded_count}"
    )
    for source, counts in summary.source_breakdown.items():
        print(
            f"{source}: raw={counts.raw_count} normalized={counts.normalized_count} "
            f"sampled={counts.sampled_count} declared_sitemaps={counts.declared_sitemaps}"
        )
    print("SUGGESTED:")
    for record in results:
        if record["discovery_status"] == "SUGGESTED":
            print(f"  {record['url']}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run_live_verification()
