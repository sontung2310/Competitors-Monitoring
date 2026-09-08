"""Opt-in end-to-end verification for the company-scoped backend PoC.

Run from the repository root with the dedicated Atlas test database and the
OpenAI provider configured:

    set -a
    source .env.mongodb
    source .env
    set +a
    export MONGODB_DATABASE=competitors_monitoring_test
    RUN_LIVE_POC=1 python -u tests/live_poc_backend_verification.py

This intentionally leaves the tagged simulated snapshots/changes and genuine
monitoring runs in the test database as evidence. It must never be pointed at
another database.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Mapping

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.app import create_app
from backend.flask.change_detection.repository import ChangeRepository
from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.database.connection import MongoSettings, connect_database
from backend.flask.snapshot.repository import SnapshotRepository
from backend.flask.website_monitoring.repository import MonitoringTargetRepository


TEST_DATABASE = "competitors_monitoring_test"


def run_live_verification() -> dict[str, Any]:
    if os.environ.get("RUN_LIVE_POC") != "1":
        raise SystemExit("Set RUN_LIVE_POC=1 to run live PoC verification")

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
        app = create_app(
            database=database,
            user_id="live-verification",
            testing=True,
        )
        http = app.test_client()
        companies = _expect(http.get("/api/companies"), 200)
        if len(companies) != 2:
            raise AssertionError(f"expected exactly two companies, got {companies!r}")
        companies_by_name = {company["name"]: company for company in companies}
        expected_company_names = {"Marketing Eye", "The Athletes Foot"}
        if set(companies_by_name) != expected_company_names:
            raise AssertionError(
                f"unexpected PoC companies: {sorted(companies_by_name)}"
            )

        marketing_eye = companies_by_name["Marketing Eye"]
        athletes_foot = companies_by_name["The Athletes Foot"]
        marketing_id = marketing_eye["id"]
        athletes_id = athletes_foot["id"]

        scoped_marketing = _expect(
            http.get(f"/api/competitors?company_id={marketing_id}"),
            200,
        )
        scoped_athletes = _expect(
            http.get(f"/api/competitors?company_id={athletes_id}"),
            200,
        )
        if len(scoped_marketing) != 1 or len(scoped_athletes) != 1:
            raise AssertionError(
                "company-scoped competitor lists did not contain exactly one record"
            )
        if "lyfe" not in scoped_marketing[0]["website_url"].lower():
            raise AssertionError(f"Marketing Eye scope is wrong: {scoped_marketing!r}")
        if "jd-sports" not in scoped_athletes[0]["website_url"].lower():
            raise AssertionError(f"The Athletes Foot scope is wrong: {scoped_athletes!r}")

        all_competitors = _expect(http.get("/api/competitors"), 200)
        unassigned_names = {
            row["name"]
            for row in all_competitors
            if "company_id" not in row
        }
        if not {"Brown Bag Marketing", "Elevation Marketing"}.issubset(unassigned_names):
            raise AssertionError(
                f"Brown Bag/Elevation were not left unassigned: {all_competitors!r}"
            )

        lyfe_id = scoped_marketing[0]["id"]
        jd_id = scoped_athletes[0]["id"]
        lyfe_discovery = _expect(
            http.post(f"/api/competitors/{lyfe_id}/discover?company_id={marketing_id}"),
            200,
        )
        if lyfe_discovery["summary"] is None:
            raise AssertionError("real discovery endpoint returned no summary")

        targets = MonitoringTargetRepository.from_database(database)
        snapshots = SnapshotRepository.from_database(database)
        changes = ChangeRepository.from_database(database)
        lyfe_blog = _find_active_target(
            _expect(http.get(f"/api/monitoring-targets?company_id={marketing_id}"), 200),
            page_type="BLOG",
        )
        jd_product = _find_active_target(
            _expect(http.get(f"/api/monitoring-targets?company_id={athletes_id}"), 200),
            page_type="PRODUCT_LISTING",
        )

        blog_baseline = _latest_real_snapshot(snapshots, lyfe_blog["id"])
        blog_simulation = _expect(
            http.post(
                f"/api/monitoring-targets/{lyfe_blog['id']}/simulate?company_id={marketing_id}"
            ),
            200,
        )
        _assert_simulation_response(blog_simulation, expected_page_type="BLOG")
        if blog_simulation["change"]["change_type"] != "NEW_BLOG":
            raise AssertionError(f"blog simulation had the wrong event: {blog_simulation!r}")
        _assert_persisted_simulation(
            snapshots,
            changes,
            blog_simulation,
        )
        blog_monitor = app.extensions["api_services"]["monitoring"].monitor_target(
            lyfe_blog["id"]
        )
        _assert_real_monitor_used_baseline(blog_monitor, blog_baseline, blog_simulation)

        jd_baseline = _latest_real_snapshot(snapshots, jd_product["id"])
        product_simulation = _expect(
            http.post(
                f"/api/monitoring-targets/{jd_product['id']}/simulate?company_id={athletes_id}",
                json={"mutation_type": "NEW_PRODUCT"},
            ),
            200,
        )
        _assert_simulation_response(
            product_simulation,
            expected_page_type="PRODUCT_LISTING",
        )
        if product_simulation.get("mutation_type") != "NEW_PRODUCT":
            raise AssertionError(f"product simulation did not honor mutation_type: {product_simulation!r}")
        if product_simulation["change"]["change_type"] != "NEW_PRODUCT":
            raise AssertionError(f"product simulation had the wrong event: {product_simulation!r}")
        _assert_persisted_simulation(snapshots, changes, product_simulation)
        jd_monitor = app.extensions["api_services"]["monitoring"].monitor_target(
            jd_product["id"]
        )
        _assert_real_monitor_used_baseline(jd_monitor, jd_baseline, product_simulation)

        feed = _expect(
            http.get(f"/api/changes?company_id={marketing_id}&limit=100"),
            200,
        )
        if not any(
            row.get("id") == blog_simulation["change"]["id"]
            and row.get("is_simulated") is True
            for row in feed
        ):
            raise AssertionError("simulated blog change was not visible in the scoped feed")

        report = {
            "database": database.name,
            "companies": companies,
            "scoped_competitors": {
                "Marketing Eye": scoped_marketing,
                "The Athletes Foot": scoped_athletes,
            },
            "unassigned_competitors": sorted(unassigned_names),
            "discovery": {
                "competitor_id": lyfe_discovery["competitor_id"],
                "summary": lyfe_discovery["summary"],
                "candidate_count": len(lyfe_discovery["candidates"]),
            },
            "blog": _simulation_report(blog_simulation, blog_monitor, blog_baseline),
            "product": _simulation_report(product_simulation, jd_monitor, jd_baseline),
            "scoped_feed_contains_simulated_blog": True,
            "snapshot_counts": {
                "lyfe_blog": len(targets.list_for_competitor(lyfe_id)),
                "jd_product": len(targets.list_for_competitor(jd_id)),
            },
        }
        _print_report(report)
        return report
    finally:
        mongo_client.close()


def _find_active_target(rows: list[dict[str, Any]], *, page_type: str) -> dict[str, Any]:
    for row in rows:
        if (
            row.get("page_type") == page_type
            and row.get("active") is True
            and row.get("discovery_status") == "ACTIVE"
        ):
            return row
    raise AssertionError(f"no active {page_type} target found in {rows!r}")


def _latest_real_snapshot(repository: SnapshotRepository, target_id: str) -> dict[str, Any] | None:
    rows = repository.list_for_target(target_id, include_simulated=False)
    return rows[0] if rows else None


def _assert_simulation_response(
    response: Mapping[str, Any],
    *,
    expected_page_type: str,
) -> None:
    if response.get("page_type") != expected_page_type:
        raise AssertionError(f"wrong simulation page type: {response!r}")
    if response.get("is_simulated") is not True:
        raise AssertionError(f"simulation response is not tagged: {response!r}")
    if response.get("snapshot", {}).get("is_simulated") is not True:
        raise AssertionError(f"simulated snapshot is not tagged: {response!r}")
    if not response.get("changes") or response["change"] is None:
        raise AssertionError(f"simulation returned no persisted change: {response!r}")
    if any(change.get("is_simulated") is not True for change in response["changes"]):
        raise AssertionError(f"simulated changes are not tagged: {response!r}")


def _assert_persisted_simulation(
    snapshots: SnapshotRepository,
    changes: ChangeRepository,
    response: Mapping[str, Any],
) -> None:
    stored_snapshot = snapshots.get(response["snapshot"]["id"])
    stored_change = changes.get(response["change"]["id"])
    if stored_snapshot is None or stored_snapshot.get("is_simulated") is not True:
        raise AssertionError(f"simulation snapshot was not persisted/tagged: {stored_snapshot!r}")
    if stored_change is None or stored_change.get("is_simulated") is not True:
        raise AssertionError(f"simulation change was not persisted/tagged: {stored_change!r}")


def _assert_real_monitor_used_baseline(
    monitor_result: Mapping[str, Any],
    baseline: Mapping[str, Any] | None,
    simulation: Mapping[str, Any],
) -> None:
    if monitor_result["run"]["status"] != "SUCCESS":
        raise AssertionError(f"genuine monitor failed: {monitor_result!r}")
    previous = monitor_result.get("previous_snapshot")
    expected_id = baseline["id"] if baseline is not None else simulation["previous_snapshot"]["id"]
    if previous is None or previous.get("id") != expected_id:
        raise AssertionError(
            f"genuine monitor did not use the pre-simulation real baseline: "
            f"expected={expected_id!r} previous={previous!r}"
        )
    if previous.get("is_simulated") is True:
        raise AssertionError("genuine monitor compared against a simulated snapshot")


def _simulation_report(
    simulation: Mapping[str, Any],
    monitor: Mapping[str, Any],
    baseline: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "target_id": simulation["monitoring_target_id"],
        "page_type": simulation["page_type"],
        "mutation_type": simulation.get("mutation_type"),
        "baseline_snapshot_id": baseline["id"] if baseline else simulation["previous_snapshot"]["id"],
        "simulated_snapshot_id": simulation["snapshot"]["id"],
        "simulated_change_ids": [change["id"] for change in simulation["changes"]],
        "simulated_change_types": [change["change_type"] for change in simulation["changes"]],
        "genuine_monitor_run_id": monitor["run"]["id"],
        "genuine_monitor_previous_snapshot_id": monitor["previous_snapshot"]["id"],
    }


def _expect(response: Any, status_code: int) -> Any:
    if response.status_code != status_code:
        raise AssertionError(
            f"expected HTTP {status_code}, got {response.status_code}: "
            f"{response.get_json(silent=True)!r}"
        )
    return response.get_json()


def _print_report(report: Mapping[str, Any]) -> None:
    print(f"database={report['database']}")
    print(f"companies={[company['name'] for company in report['companies']]}")
    print(f"scoped_competitors={report['scoped_competitors']}")
    print(f"unassigned_competitors={report['unassigned_competitors']}")
    print(f"discovery={report['discovery']}")
    print(f"blog={report['blog']}")
    print(f"product={report['product']}")
    print(f"scoped_feed_contains_simulated_blog={report['scoped_feed_contains_simulated_blog']}")


if __name__ == "__main__":
    run_live_verification()
