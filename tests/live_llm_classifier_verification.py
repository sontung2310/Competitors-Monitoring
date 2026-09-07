"""Opt-in live verification for the real Layer 1 LLM classifier.

Run from the repository root with the dedicated Atlas test database and the
OpenAI key configured in the environment or local ``.env`` file:

    set -a
    source .env.mongodb
    source .env
    set +a
    export MONGODB_DATABASE=competitors_monitoring_test
    export RUN_LIVE_LLM_DISCOVERY=1
    /Users/sontung/miniconda3/bin/python -u \
      tests/live_llm_classifier_verification.py

The script writes only the normal discovered-candidate updates to the
dedicated test database. It never touches snapshots, changes, or monitoring
runs. A provider failure is injected through the classifier boundary for one
real discovery pass to prove the service falls back without crashing.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.database.connection import MongoSettings, connect_database
from backend.flask.discovery.classification import (
    CandidateForClassification,
    OpenAIClassifier,
    classify_candidates,
)
from backend.flask.discovery.service import DiscoveryService
from backend.flask.website_monitoring.repository import MonitoringTargetRepository


TEST_DATABASE = "competitors_monitoring_test"
USER_ID = "live-verification"
SITES = (
    ("lyfemarketing.com", "https://www.lyfemarketing.com/"),
    ("brownbagmarketing.com", "https://brownbagmarketing.com/"),
)

# These are the candidates that the pre-fix live run promoted through the LLM
# fallback. Keep this review set explicit so a corrected run re-checks the
# exact same candidates even after their persisted status has changed.
PREVIOUS_LLM_PROMOTIONS = {
    "lyfemarketing.com": (
        "https://www.lyfemarketing.com/website-design-services-for-small-businesses",
        "https://www.lyfemarketing.com/director-of-digital-marketing",
        "https://www.lyfemarketing.com/roi-benefits-social-media-marketing",
        "https://www.lyfemarketing.com/how-to-grow-a-church",
        "https://www.lyfemarketing.com/8-quick-tips-email-marketing",
        "https://www.lyfemarketing.com/beyonce-uses-social-media-promote-album-release",
        "https://www.lyfemarketing.com/social-media-the-student-housing-industrys-best-marketing-source",
    ),
    "brownbagmarketing.com": (
        "https://brownbagmarketing.com/paid-media-advertising",
        "https://brownbagmarketing.com/atlanta-social-media-marketing-company",
        "https://brownbagmarketing.com/veterinarians-digital-marketing",
        "https://brownbagmarketing.com/atlanta-brand-marketing-agency",
        "https://brownbagmarketing.com/aeo-content-strategies-for-nonprofits",
        "https://brownbagmarketing.com/airbnb-new-logo-faces-backlash-all-part-of-the-plan",
        "https://brownbagmarketing.com/marketing-it-so-happy-together-part-1",
        "https://brownbagmarketing.com/snaping-into-snapchat-spectacles",
    ),
}


class _FailingProvider:
    """Provider double used only to inject a real fallback-path failure."""

    def __init__(self) -> None:
        self.calls = 0

    def generate_json(self, prompt, *, instructions, response_format):
        self.calls += 1
        raise RuntimeError("forced OpenAI outage for live degradation check")


def _path_without_trailing_slash(value: object) -> str:
    return urlsplit(str(value)).path.rstrip("/") or "/"


def _find_competitor(repository: CompetitorRepository, website_url: str) -> dict[str, object]:
    expected_host = urlsplit(website_url).netloc.lower()
    for competitor in repository.list_for_user(USER_ID):
        if urlsplit(str(competitor.get("website_url"))).netloc.lower() == expected_host:
            return competitor
    raise RuntimeError(
        f"no {website_url!r} competitor exists for user {USER_ID!r} in "
        f"{TEST_DATABASE!r}"
    )


def _counts(rows: list[dict[str, object]]) -> dict[str, int]:
    return {
        "total": len(rows),
        "suggested": sum(row.get("discovery_status") == "SUGGESTED" for row in rows),
        "discarded": sum(row.get("discovery_status") == "DISCARDED" for row in rows),
        "active": sum(
            row.get("active") is True and row.get("discovery_status") == "ACTIVE"
            for row in rows
        ),
    }


def _run_real_discovery(
    competitors: CompetitorRepository,
    targets: MonitoringTargetRepository,
    competitor: dict[str, object],
    classifier: OpenAIClassifier,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    before_rows = targets.list_for_competitor(competitor["id"])
    before_by_url = {str(row["url"]): row for row in before_rows}
    service = DiscoveryService(
        competitors,
        targets,
        fallback_classifier=classifier,
    )
    discovered = service.discover_website(
        competitor["id"],
        user_id=USER_ID,
    )
    after_rows = targets.list_for_competitor(competitor["id"])
    newly_suggested = [
        {
            "url": row["url"],
            "page_type": row["page_type"],
            "classification_method": row["classification_method"],
        }
        for row in after_rows
        if before_by_url.get(str(row["url"]), {}).get("discovery_status") == "DISCARDED"
        and row.get("discovery_status") == "SUGGESTED"
    ]
    llm_records = []
    for result in classifier.last_results:
        persisted = next(
            row for row in after_rows if row.get("url") == result.url
        )
        if persisted.get("classification_method") != "LLM":
            raise AssertionError(
                f"LLM result for {result.url!r} was not persisted with method LLM"
            )
        llm_records.append(
            {
                "url": result.url,
                "page_type": result.page_type,
                "discovery_status": result.discovery_status,
                "classification_method": persisted["classification_method"],
            }
        )
    summary = service.last_summary
    return after_rows, {
        "discovered_count": len(discovered),
        "before": _counts(before_rows),
        "after": _counts(after_rows),
        "llm_calls": classifier.call_count,
        "llm_results": llm_records,
        "newly_suggested_from_discarded": newly_suggested,
        "summary": summary,
    }


def _reclassify_previous_llm_promotions(
    targets: MonitoringTargetRepository,
    competitor: dict[str, object],
    urls: tuple[str, ...],
    classifier: OpenAIClassifier,
) -> list[dict[str, object]]:
    """Run the fixed fallback against the exact pre-fix review set."""

    candidates = []
    existing_rows = []
    for url in urls:
        row = targets.find_by_url(competitor["id"], url)
        if row is None:
            raise AssertionError(f"review candidate disappeared from Atlas: {url}")
        existing_rows.append(row)
        candidates.append(
            CandidateForClassification(
                raw_url=str(row.get("raw_url") or row["url"]),
                url=str(row["url"]),
                title=row.get("title"),
                sources=("REVIEW_SET",),
            )
        )

    results = classify_candidates(tuple(candidates), classifier)
    persisted = []
    for row, result in zip(existing_rows, results):
        updated = targets.upsert_discovered_candidate(
            competitor_id=competitor["id"],
            raw_url=str(row.get("raw_url") or row["url"]),
            url=result.url,
            page_type=result.page_type,
            discovery_source=str(row.get("discovery_source") or "REVIEW_SET"),
            discovery_status=result.discovery_status,
            classification_method=result.classification_method,
        )
        persisted.append(
            {
                "id": updated["id"],
                "url": updated["url"],
                "page_type": updated["page_type"],
                "discovery_status": updated["discovery_status"],
                "classification_method": updated["classification_method"],
            }
        )
    return persisted


def _run_forced_failure(
    competitors: CompetitorRepository,
    targets: MonitoringTargetRepository,
    competitor: dict[str, object],
) -> dict[str, object]:
    provider = _FailingProvider()
    classifier = OpenAIClassifier(provider=provider)
    service = DiscoveryService(
        competitors,
        targets,
        fallback_classifier=classifier,
    )
    try:
        rows = service.discover_website(competitor["id"], user_id=USER_ID)
    except Exception as exc:
        raise AssertionError(
            "discovery crashed instead of degrading after the injected provider failure"
        ) from exc
    if provider.calls < 1:
        raise AssertionError("forced-failure discovery did not reach the classifier")
    return {
        "provider_calls": provider.calls,
        "classifier_calls": classifier.call_count,
        "rows_returned": len(rows),
        "discarded_rows": sum(
            row.get("discovery_status") == "DISCARDED" for row in rows
        ),
    }


def run_live_verification() -> dict[str, object]:
    if os.environ.get("RUN_LIVE_LLM_DISCOVERY") != "1":
        raise SystemExit("Set RUN_LIVE_LLM_DISCOVERY=1 to run live verification")

    settings = MongoSettings.from_env()
    if settings.database_name != TEST_DATABASE:
        raise RuntimeError(
            f"refusing to write outside {TEST_DATABASE!r}; "
            f"configured database is {settings.database_name!r}"
        )

    client, database = connect_database(
        settings,
        serverSelectionTimeoutMS=15_000,
    )
    try:
        client.admin.command("ping")
        competitors = CompetitorRepository.from_database(database)
        targets = MonitoringTargetRepository.from_database(database)
        competitors.ensure_indexes()
        targets.ensure_indexes()

        rule_classifier = OpenAIClassifier.from_env()
        rule_results = classify_candidates(
            (
                CandidateForClassification(
                    "https://www.lyfemarketing.com/blog",
                    "https://www.lyfemarketing.com/blog",
                ),
            ),
            rule_classifier,
        )
        if rule_results[0].classification_method != "RULE":
            raise AssertionError("/blog did not remain a rule classification")
        if rule_classifier.call_count != 0:
            raise AssertionError("/blog incorrectly triggered an LLM call")

        reports: dict[str, object] = {
            "database": settings.database_name,
            "rules_priority": {
                "url": rule_results[0].url,
                "page_type": rule_results[0].page_type,
                "classification_method": rule_results[0].classification_method,
                "llm_calls": rule_classifier.call_count,
            },
            "sites": {},
        }

        first_competitor = None
        for label, website_url in SITES:
            competitor = _find_competitor(competitors, website_url)
            if first_competitor is None:
                first_competitor = competitor
            classifier = OpenAIClassifier.from_env()
            rows, report = _run_real_discovery(
                competitors,
                targets,
                competitor,
                classifier,
            )
            if report["llm_calls"] < 1:
                raise AssertionError(
                    f"{label}: full discovery produced no unresolved candidate to classify"
                )
            if label == SITES[0][0]:
                # Run the failure-degradation check before the corrected
                # review-set pass so that the report's final counts reflect
                # the fixed classifier rather than the deterministic failure
                # fallback's discarded updates.
                reports["forced_failure"] = _run_forced_failure(
                    competitors,
                    targets,
                    competitor,
                )
            review_classifier = OpenAIClassifier.from_env()
            review_rows = _reclassify_previous_llm_promotions(
                targets,
                competitor,
                PREVIOUS_LLM_PROMOTIONS[label],
                review_classifier,
            )
            final_rows = targets.list_for_competitor(competitor["id"])
            reports["sites"][label] = {
                "competitor_id": competitor["id"],
                "website_url": website_url,
                "classifier_model": classifier.model,
                **{key: value for key, value in report.items() if key != "summary"},
                "review_set_llm_calls": review_classifier.call_count,
                "review_set_results": review_rows,
                "final": _counts(final_rows),
                "source_summary": report["summary"],
                "sample_persisted_rows": [
                    {
                        "url": row["url"],
                        "page_type": row["page_type"],
                        "discovery_status": row["discovery_status"],
                        "classification_method": row["classification_method"],
                    }
                    for row in rows
                    if row.get("classification_method") == "LLM"
                ][:10],
            }

        if first_competitor is None or "forced_failure" not in reports:
            raise AssertionError("no live competitor was selected")
        return reports
    finally:
        client.close()


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    report = run_live_verification()
    print(f"database={report['database']}")
    print(
        "rules_priority="
        f"{report['rules_priority']}"
    )
    for label, site_report in report["sites"].items():
        print(f"\n=== {label} ===")
        for key in (
            "competitor_id",
            "website_url",
            "classifier_model",
            "before",
            "after",
            "final",
            "llm_calls",
            "newly_suggested_from_discarded",
            "llm_results",
            "sample_persisted_rows",
            "review_set_llm_calls",
            "review_set_results",
        ):
            print(f"{key}={site_report[key]}")
        summary = site_report["source_summary"]
        if summary is not None:
            print(
                "discovery_summary="
                f"raw={summary.raw_count} normalized={summary.normalized_count} "
                f"suggested={summary.suggested_count} discarded={summary.discarded_count}"
            )
    print(f"\nforced_failure={report['forced_failure']}")
