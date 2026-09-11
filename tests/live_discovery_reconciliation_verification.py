"""Opt-in live evidence for automatic discovery reconciliation.

This verification intentionally writes discovery-run and target-state changes
to the existing dedicated ``competitors_monitoring_test`` database. It does
not create competitors, snapshots, monitoring runs, or AWS resources.

Run from the repository root with:

    RUN_LIVE_DISCOVERY_RECONCILIATION=1 \
      ./.venv/bin/python -u tests/live_discovery_reconciliation_verification.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from backend.flask.change_detection.repository import ChangeRepository
from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.database.connection import MongoSettings, connect_database
from backend.flask.discovery.classification import DeterministicStubClassifier
from backend.flask.discovery.repository import DiscoveryRunRepository
from backend.flask.discovery.service import DiscoveryService
from backend.flask.snapshot.repository import SnapshotRepository
from backend.flask.website_monitoring.repository import MonitoringTargetRepository


TEST_DATABASE = "competitors_monitoring_test"
LYFE_ID = "6a9a44e4ba8f10678b8e30b9"
LYFE_COMPANY_ID = "6a9fdbf0c6ea2d18a14a6615"
MAX_RECONCILIATION_SECONDS = float(
    os.environ.get("RECONCILIATION_MAX_SECONDS", "840")
)


def _active_urls(repository: MonitoringTargetRepository, competitor_id: str) -> list[str]:
    return sorted(
        str(target["url"])
        for target in repository.list_active_targets(competitor_id)
    )


def run_live_verification() -> dict[str, object]:
    if os.environ.get("RUN_LIVE_DISCOVERY_RECONCILIATION") != "1":
        raise SystemExit(
            "Set RUN_LIVE_DISCOVERY_RECONCILIATION=1 to run live verification"
        )
    if MAX_RECONCILIATION_SECONDS <= 0:
        raise AssertionError("RECONCILIATION_MAX_SECONDS must be positive")

    load_dotenv(override=False)
    settings = MongoSettings.from_env()
    if settings.database_name != TEST_DATABASE:
        raise RuntimeError(
            f"refusing to write outside {TEST_DATABASE!r}; "
            f"configured database is {settings.database_name!r}"
        )

    mongo_client, database = connect_database(
        settings,
        serverSelectionTimeoutMS=15_000,
    )
    try:
        mongo_client.admin.command("ping")
        competitors = CompetitorRepository.from_database(database)
        targets = MonitoringTargetRepository.from_database(database)
        runs = DiscoveryRunRepository.from_database(database)
        competitor = competitors.get(LYFE_ID, company_id=LYFE_COMPANY_ID)
        if competitor is None:
            raise AssertionError(f"Lyfe competitor {LYFE_ID!r} was not found")

        before_latest = runs.find_latest_successful(
            LYFE_ID,
            company_id=LYFE_COMPANY_ID,
        )
        before_active = _active_urls(targets, LYFE_ID)
        snapshot_count_before = database["snapshots"].count_documents({})
        monitoring_run_count_before = database["monitoring_runs"].count_documents({})

        service = DiscoveryService(
            competitors,
            targets,
            fallback_classifier=DeterministicStubClassifier(),
            snapshot_repository=SnapshotRepository.from_database(database),
            change_repository=ChangeRepository.from_database(database),
            run_repository=runs,
        )
        run_id = f"live-reconcile-{uuid4().hex}"
        started = time.monotonic()
        result = service.discover_and_reconcile(
            LYFE_ID,
            company_id=LYFE_COMPANY_ID,
            run_id=run_id,
        )
        elapsed = time.monotonic() - started

        after_latest = runs.find_latest_successful(
            LYFE_ID,
            company_id=LYFE_COMPANY_ID,
        )
        after_active = _active_urls(targets, LYFE_ID)
        snapshot_count_after = database["snapshots"].count_documents({})
        monitoring_run_count_after = database["monitoring_runs"].count_documents({})
        persisted_run = runs.get(run_id)

        if persisted_run is None or persisted_run.get("status") != "SUCCESS":
            raise AssertionError(f"reconciliation run did not succeed: {persisted_run}")
        if after_latest is None or after_latest.get("run_id") != run_id:
            raise AssertionError("latest successful run did not advance to live run")
        if elapsed >= MAX_RECONCILIATION_SECONDS:
            raise AssertionError(
                f"reconciliation took {elapsed:.2f}s, exceeding the "
                f"{MAX_RECONCILIATION_SECONDS:.2f}s bound"
            )
        if snapshot_count_after != snapshot_count_before:
            raise AssertionError("reconciliation unexpectedly created a snapshot")
        if monitoring_run_count_after != monitoring_run_count_before:
            raise AssertionError("reconciliation unexpectedly created a monitoring run")

        evidence = {
            "competitor": competitor["name"],
            "competitor_id": LYFE_ID,
            "before_latest_successful_run": before_latest,
            "reconciliation_run": persisted_run,
            "elapsed_seconds": round(elapsed, 2),
            "active_before": before_active,
            "active_after": after_active,
            "activated_target_ids": list(result.activated_target_ids),
            "deactivated_target_ids": list(result.deactivated_target_ids),
            "discovered_count": result.discovered_count,
            "suggested_count": result.suggested_count,
            "snapshot_count_unchanged": snapshot_count_after == snapshot_count_before,
            "monitoring_run_count_unchanged": (
                monitoring_run_count_after == monitoring_run_count_before
            ),
            "visibility_timeout_bound_seconds": MAX_RECONCILIATION_SECONDS,
        }
        print(json.dumps(evidence, default=str, indent=2, sort_keys=True))
        return evidence
    finally:
        mongo_client.close()


if __name__ == "__main__":
    run_live_verification()
