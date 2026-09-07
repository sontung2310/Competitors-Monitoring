"""Live HTTP verification for the Step 2 Flask API against Atlas.

Run from the repository root after loading the existing Mongo environment:

    set -a; source .env.mongodb; set +a
    export MONGODB_DATABASE=competitors_monitoring_test
    RUN_LIVE_HTTP=1 python -u tests/live_http_api_verification.py

The script exercises the Flask routes with an Atlas-backed application. It
creates and removes one temporary competitor and candidate, while preserving
the existing Lyfe/Brown Bag data and asserting snapshot/change/run counts are
unchanged.
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.app import create_app
from backend.flask.change_detection.repository import ChangeRepository
from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.database.connection import MongoSettings, connect_database
from backend.flask.snapshot.repository import SnapshotRepository
from backend.flask.website_monitoring.repository import (
    MonitoringRunRepository,
    MonitoringTargetRepository,
)


TEST_DATABASE = "competitors_monitoring_test"
USER_ID = "live-verification"
LYFE_ID = "6a9a44e4ba8f10678b8e30b9"


def run_live_verification() -> dict[str, Any]:
    if os.environ.get("RUN_LIVE_HTTP") != "1":
        raise SystemExit("Set RUN_LIVE_HTTP=1 to run live HTTP verification")

    settings = MongoSettings.from_env()
    if settings.database_name != TEST_DATABASE:
        raise RuntimeError(
            f"refusing to run outside {TEST_DATABASE!r}; "
            f"configured database is {settings.database_name!r}"
        )

    mongo_client, database = connect_database(
        settings,
        serverSelectionTimeoutMS=15_000,
    )
    try:
        mongo_client.admin.command("ping")
        baseline = _counts(database)
        app = create_app(database=database, user_id=USER_ID, testing=True)
        http = app.test_client()

        competitors = CompetitorRepository.from_database(database)
        lyfe = competitors.get(LYFE_ID, user_id=USER_ID)
        if lyfe is None:
            raise AssertionError(f"Lyfe competitor {LYFE_ID!r} was not found")

        checks: dict[str, Any] = {}
        checks["competitor_list"] = _expect(http.get("/api/competitors"), 200)
        checks["competitor_get"] = _expect(http.get(f"/api/competitors/{LYFE_ID}"), 200)
        checks["suggested_candidates"] = _expect(
            http.get(f"/api/competitors/{LYFE_ID}/candidates?status=SUGGESTED"),
            200,
        )
        checks["discarded_candidates"] = _expect(
            http.get(f"/api/competitors/{LYFE_ID}/candidates?status=DISCARDED"),
            200,
        )
        checks["all_candidates"] = _expect(
            http.get(f"/api/competitors/{LYFE_ID}/candidates?status=ALL"),
            200,
        )
        checks["target_list"] = _expect(
            http.get(f"/api/monitoring-targets?competitor_id={LYFE_ID}"),
            200,
        )
        changes = _expect(http.get(f"/api/changes?competitor_id={LYFE_ID}&limit=5"), 200)
        checks["change_feed"] = changes
        if changes:
            checks["change_get"] = _expect(
                http.get(f"/api/changes/{changes[0]['id']}"),
                200,
            )

        checks["missing_competitor"] = _expect(
            http.get("/api/competitors/000000000000000000000000"),
            404,
        )
        checks["invalid_competitor_body"] = _expect(
            http.post("/api/competitors", json={"name": "missing-url"}),
            400,
        )

        temporary_competitor_id = None
        try:
            unique_host = f"step2-api-{uuid.uuid4().hex}.example"
            created = _expect(
                http.post(
                    "/api/competitors",
                    json={
                        "name": "Step 2 temporary API probe",
                        "website_url": f"https://{unique_host}/",
                    },
                ),
                201,
            )
            temporary_competitor_id = created["id"]
            checks["competitor_create"] = created
            updated = _expect(
                http.patch(
                    f"/api/competitors/{temporary_competitor_id}",
                    json={"name": "Step 2 temporary API probe updated"},
                ),
                200,
            )
            checks["competitor_update"] = updated

            candidate = _expect(
                http.post(
                    f"/api/competitors/{temporary_competitor_id}/candidates",
                    json={"url": f"https://{unique_host}/about"},
                ),
                201,
            )
            candidate_id = candidate["id"]
            checks["candidate_create"] = candidate
            checks["candidate_list_after_create"] = _expect(
                http.get(
                    f"/api/competitors/{temporary_competitor_id}/candidates?status=ALL"
                ),
                200,
            )
            edited = _expect(
                http.patch(
                    f"/api/candidates/{candidate_id}",
                    json={"url": f"https://{unique_host}/contact"},
                ),
                200,
            )
            checks["candidate_edit"] = edited
            activated = _expect(
                http.post(f"/api/candidates/{candidate_id}/activate"),
                200,
            )
            checks["candidate_activate"] = activated
            target_patch = _expect(
                http.patch(
                    f"/api/monitoring-targets/{candidate_id}",
                    json={"active": False, "check_interval_minutes": 1440},
                ),
                200,
            )
            checks["target_update"] = target_patch
            checks["target_get"] = _expect(
                http.get(f"/api/monitoring-targets/{candidate_id}"),
                200,
            )
            _expect(http.delete(f"/api/monitoring-targets/{candidate_id}"), 204)

            disposable_candidate = _expect(
                http.post(
                    f"/api/competitors/{temporary_competitor_id}/candidates",
                    json={"url": f"https://{unique_host}/pricing"},
                ),
                201,
            )
            checks["candidate_remove"] = _expect(
                http.delete(f"/api/candidates/{disposable_candidate['id']}"),
                204,
            )

            discardable_candidate = _expect(
                http.post(
                    f"/api/competitors/{temporary_competitor_id}/candidates",
                    json={"url": f"https://{unique_host}/news"},
                ),
                201,
            )
            checks["candidate_discard"] = _expect(
                http.post(
                    f"/api/candidates/{discardable_candidate['id']}/discard"
                ),
                200,
            )
            if checks["candidate_discard"]["discovery_status"] != "DISCARDED":
                raise AssertionError("discard endpoint did not preserve DISCARDED status")
            _expect(
                http.delete(f"/api/candidates/{discardable_candidate['id']}"),
                204,
            )

            dead = _expect(
                http.post(
                    "/api/monitoring-targets",
                    json={
                        "competitor_id": LYFE_ID,
                        "url": "https://www.lyfemarketing.com/step2-api-probe-does-not-exist-404",
                    },
                ),
                400,
            )
            checks["dead_manual_target_rejection"] = dead

            # Existing ACTIVE duplicate handling is intentionally idempotent;
            # this route call must not create a second row.
            duplicate_target = _expect(
                http.post(
                    "/api/monitoring-targets",
                    json={
                        "competitor_id": LYFE_ID,
                        "url": "https://www.lyfemarketing.com/blog",
                    },
                ),
                201,
            )
            checks["active_target_duplicate"] = duplicate_target
        finally:
            if temporary_competitor_id is not None:
                _expect(
                    http.delete(f"/api/competitors/{temporary_competitor_id}"),
                    204,
                )

        after = _counts(database)
        if after != baseline:
            raise AssertionError(f"Atlas counts changed: before={baseline} after={after}")

        report = {
            "database": database.name,
            "counts_before": baseline,
            "counts_after": after,
            "checks": checks,
            "error_shapes": {
                "missing_competitor": checks["missing_competitor"]["error"],
                "invalid_body": checks["invalid_competitor_body"]["error"],
                "dead_target": checks["dead_manual_target_rejection"]["error"],
            },
        }
        _print_report(report)
        return report
    finally:
        mongo_client.close()


def _counts(database: Any) -> dict[str, int]:
    return {
        name: int(database[name].count_documents({}))
        for name in ("competitors", "monitoring_targets", "snapshots", "changes", "monitoring_runs")
    }


def _expect(response: Any, status: int) -> Any:
    if response.status_code != status:
        raise AssertionError(
            f"expected HTTP {status}, got {response.status_code}: {response.get_json()}"
        )
    if status == 204:
        return None
    payload = response.get_json()
    if payload is None:
        raise AssertionError(f"expected JSON response for HTTP {status}")
    return payload


def _print_report(report: dict[str, Any]) -> None:
    print(f"database={report['database']}")
    print(f"counts_before={report['counts_before']}")
    print(f"counts_after={report['counts_after']}")
    print("endpoint checks:")
    for name, payload in report["checks"].items():
        if isinstance(payload, list):
            print(f"  {name}: HTTP 200 list_count={len(payload)}")
        elif isinstance(payload, dict) and "error" in payload:
            print(f"  {name}: error={payload['error']}")
        elif isinstance(payload, dict):
            print(f"  {name}: id={payload.get('id')} status={payload.get('discovery_status', payload.get('status'))}")
        else:
            print(f"  {name}: {payload!r}")
    print(f"error_shapes={report['error_shapes']}")


if __name__ == "__main__":
    run_live_verification()
