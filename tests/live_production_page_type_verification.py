"""Read-only live discovery verification for production's six page types.

Run from the repository root with network access:

    RUN_LIVE_PRODUCTION_PAGE_TYPES=1 \
      ./.venv/bin/python -u tests/live_production_page_type_verification.py

The run uses live robots, sitemap, homepage-link discovery, and liveness checks
but an in-memory target repository. It never writes MongoDB data.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.discovery.classification import DeterministicStubClassifier
from backend.flask.discovery.service import DiscoveryService
from backend.flask.website_monitoring.service import fetch_page


ALLOWED_PAGE_TYPES = frozenset(
    {"BLOG", "NEWS", "PRICING", "PRODUCTS", "SERVICES", "PRESS", "OTHER"}
)
LIVE_CANDIDATE_CEILING = int(
    os.environ.get("DISCOVERY_LIVE_CANDIDATE_CEILING", "100")
)
SITES = (
    ("lyfemarketing.com", "https://www.lyfemarketing.com/"),
    ("jd-sports.com.au", "https://www.jd-sports.com.au/"),
)

# These are known Lyfe pages that the dev classifier used to give dedicated
# labels to. Keep the expected old labels in the report so the production
# regression is visible rather than just asserting a set of allowed values.
LYFE_LEGACY_PAGES = {
    "/about-lyfe-marketing": "ABOUT",
    "/contact-us": "CONTACT",
    "/case-study-archive": "CASE_STUDIES",
    "/client-testimonials": "TESTIMONIALS",
    "/lyfe-marketing-reviews": "REVIEWS",
    "/portfolio-posts": "PORTFOLIO",
}
LYFE_LEGACY_PROBES = {
    "/career-opportunities": "CAREERS",
    "/work": "WORK",
    "/contact": "CONTACT",
}


class _LiveCompetitorRepository:
    def __init__(self, website_url: str):
        self.competitor = {
            "id": website_url,
            "user_id": "live-production-verification",
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


def _path(value: object) -> str:
    return urlsplit(str(value)).path.rstrip("/") or "/"


def _live_probe(url: str) -> str:
    try:
        response = fetch_page(url)
    except Exception as exc:  # pragma: no cover - only exercised by live verification
        return f"unusable ({type(exc).__name__})"
    if response.http_status is None or not 200 <= response.http_status < 400:
        return f"unusable ({response.fetch_method}/{response.http_status})"
    return f"live ({response.fetch_method}/{response.http_status})"


def _run_site(label: str, website_url: str) -> list[dict[str, object]]:
    targets = _MemoryMonitoringTargetRepository()
    service = DiscoveryService(
        _LiveCompetitorRepository(website_url),
        targets,
        fallback_classifier=DeterministicStubClassifier(),
    )
    results = service.discover_website(
        website_url,
        user_id="live-production-verification",
    )
    if len(results) > LIVE_CANDIDATE_CEILING:
        raise AssertionError(
            f"{label}: {len(results)} candidates exceeds the ceiling "
            f"{LIVE_CANDIDATE_CEILING}"
        )
    invalid = [
        (record["url"], record["page_type"])
        for record in results
        if record.get("page_type") not in ALLOWED_PAGE_TYPES
    ]
    if invalid:
        raise AssertionError(f"{label}: invalid production page types: {invalid}")

    print(f"\n=== {label} ===")
    print(
        f"total={len(results)} suggested="
        f"{sum(row.get('discovery_status') == 'SUGGESTED' for row in results)} "
        f"discarded={sum(row.get('discovery_status') == 'DISCARDED' for row in results)}"
    )
    observed_types = sorted({str(row["page_type"]) for row in results})
    print(f"observed_page_types={observed_types}")
    print("suggested:")
    for record in sorted(results, key=lambda row: str(row["url"])):
        if record.get("discovery_status") != "SUGGESTED":
            continue
        print(
            f"  {_path(record['url'])}: page_type={record['page_type']} "
            f"method={record['classification_method']}"
        )
    print("legacy-looking candidates:")
    for record in sorted(results, key=lambda row: str(row["url"])):
        path = _path(record["url"])
        if any(
            token in path
            for token in ("about", "career", "work", "contact", "portfolio", "case", "testimonial", "review")
        ):
            print(
                f"  {path}: page_type={record['page_type']} "
                f"status={record['discovery_status']}"
            )
    return results


def run_live_verification() -> None:
    if os.environ.get("RUN_LIVE_PRODUCTION_PAGE_TYPES") != "1":
        raise SystemExit("Set RUN_LIVE_PRODUCTION_PAGE_TYPES=1 to run live verification")

    lyfe_results = _run_site(*SITES[0])
    jd_results = _run_site(*SITES[1])

    lyfe_by_path = {_path(row["url"]): row for row in lyfe_results}
    print("\n=== Lyfe legacy-label regression ===")
    for page_path, old_type in LYFE_LEGACY_PAGES.items():
        row = lyfe_by_path.get(page_path)
        if row is None:
            probe = _live_probe(f"https://www.lyfemarketing.com{page_path}")
            print(
                f"{page_path}: before={old_type} after=NOT_DISCOVERED "
                f"({probe}; current sources did not emit it)"
            )
            continue
        if row.get("page_type") != "OTHER" or row.get("discovery_status") != "DISCARDED":
            raise AssertionError(
                f"{page_path}: expected OTHER/DISCARDED, got "
                f"{row.get('page_type')}/{row.get('discovery_status')}"
            )
        print(
            f"{page_path}: before={old_type} after={row['page_type']} "
            f"status={row['discovery_status']}"
        )
    for page_path, old_type in LYFE_LEGACY_PROBES.items():
        row = lyfe_by_path.get(page_path)
        if row is None:
            print(
                f"{page_path}: before={old_type} after=NOT_DISCOVERED "
                f"({ _live_probe(f'https://www.lyfemarketing.com{page_path}') }; "
                "current sources did not emit it)"
            )
            continue
        if row.get("page_type") != "OTHER" or row.get("discovery_status") != "DISCARDED":
            raise AssertionError(
                f"{page_path}: expected OTHER/DISCARDED, got "
                f"{row.get('page_type')}/{row.get('discovery_status')}"
            )
        print(
            f"{page_path}: before={old_type} after={row['page_type']} "
            f"status={row['discovery_status']}"
        )

    jd_by_path = {_path(row["url"]): row for row in jd_results}
    sale = jd_by_path.get("/sale")
    if sale is None:
        _assert_live_page("https://www.jd-sports.com.au/sale/")
        raise AssertionError("JD Sports AU live discovery did not emit /sale")
    if sale.get("page_type") != "PRODUCTS" or sale.get("discovery_status") != "SUGGESTED":
        raise AssertionError(
            f"JD Sports AU /sale expected PRODUCTS/SUGGESTED, got "
            f"{sale.get('page_type')}/{sale.get('discovery_status')}"
        )
    print(
        f"/sale: page_type={sale['page_type']} status={sale['discovery_status']} "
        f"method={sale['classification_method']}"
    )


if __name__ == "__main__":
    run_live_verification()
