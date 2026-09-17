"""Production service graph: DynamoDB targets/snapshots, RM Mongo changes.

This is what the SQS worker actually runs against — a different graph from
``backend.flask.app._build_services()``, which stays Mongo-only for the
Flask HTTP app and local/dev use. Only ``monitoring_targets``, ``snapshots``,
and ``changes`` differ (see ``docs/production-plan.md`` section 5);
``companies``, ``competitors``, ``monitoring_runs``, and ``discovery_runs``
are unaffected and still come from this application's own MongoDB database.
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional

from backend.flask.change_detection.rm_repository import RmChangeRepository
from backend.flask.change_detection.service import ChangeService
from backend.flask.companies.repository import CompanyRepository
from backend.flask.companies.service import CompanyService
from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.competitors.service import CompetitorService
from backend.flask.database.connection import MongoSettings, connect_database
from backend.flask.discovery.repository import DiscoveryRunRepository
from backend.flask.discovery.service import DiscoveryService, configured_discovery_audit
from backend.flask.llm_provider import OpenAIProvider
from backend.flask.snapshot.dynamodb_service import DynamoDBSnapshotService
from backend.flask.website_monitoring.dynamodb_repository import (
    DynamoDBMonitoringTargetRepository,
)
from backend.flask.website_monitoring.repository import MonitoringRunRepository
from backend.flask.website_monitoring.service import MonitoringRunService


def _snapshot_reference(snapshot: Mapping[str, Any], label: str) -> dict[str, str]:
    """Extract the DynamoDB {monitoring_target_id, captured_at} key pair.

    Injected into ChangeService in place of the default single-id extractor,
    since a DynamoDB snapshot has no single opaque id (see
    change_detection/rm_repository.py).
    """

    monitoring_target_id = snapshot.get("monitoring_target_id")
    captured_at = snapshot.get("captured_at")
    if not isinstance(monitoring_target_id, str) or not monitoring_target_id.strip():
        raise ValueError(f"{label} has no monitoring_target_id")
    if not isinstance(captured_at, str) or not captured_at.strip():
        raise ValueError(f"{label} has no captured_at")
    return {"monitoring_target_id": monitoring_target_id, "captured_at": captured_at}


def _always_trackable(_target: Mapping[str, Any]) -> bool:
    """A DynamoDB target repository only ever returns rows that are tracked
    (see docs/production-plan.md 5.1) — existence is proof enough, unlike
    dev's active=True/discovery_status="ACTIVE" check."""

    return True


def build_production_services(
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    """Build the full production service graph for the SQS worker."""

    values = environ if environ is not None else os.environ
    app_database_settings = MongoSettings.from_env(values)
    _, app_database = connect_database(app_database_settings)

    company_repository = CompanyRepository.from_database(app_database)
    competitor_repository = CompetitorRepository.from_database(app_database)
    run_repository = MonitoringRunRepository.from_database(app_database)
    discovery_run_repository = DiscoveryRunRepository.from_database(app_database)

    for repository in (
        company_repository,
        competitor_repository,
        run_repository,
        discovery_run_repository,
    ):
        repository.ensure_indexes()

    company_service = CompanyService(company_repository)
    competitor_service = CompetitorService(competitor_repository)

    target_repository = DynamoDBMonitoringTargetRepository.from_settings()
    snapshot_service = DynamoDBSnapshotService.from_settings()
    change_repository = RmChangeRepository.from_env(values)

    discovery_service = DiscoveryService(
        competitor_repository,
        target_repository,
        audit_classifier=configured_discovery_audit(),
        snapshot_repository=snapshot_service,
        change_repository=change_repository,
        run_repository=discovery_run_repository,
    )

    change_service = ChangeService(
        change_repository,
        target_repository,
        narrative_provider_factory=OpenAIProvider.from_env,
        snapshot_reference_extractor=_snapshot_reference,
    )

    monitoring_service = MonitoringRunService(
        target_repository,
        run_repository,
        snapshot_service,
        snapshot_service,
        change_service,
        active_target_check=_always_trackable,
    )

    return {
        "companies": company_service,
        "competitors": competitor_service,
        "discovery": discovery_service,
        "monitoring": monitoring_service,
    }


def build_production_scheduler(
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> Any:
    """Build the scheduler that runs as its own process alongside the SQS
    worker (not instead of it) — closing the gap where nothing previously
    checked each DynamoDB-tracked page on its own interval.

    ``SchedulerService`` itself needs no DynamoDB-specific code at all: it
    only calls ``target_repository.list_active_targets()`` with no
    competitor_id (a full table Scan) and reads ``id``/``check_interval_minutes``/
    ``last_checked_at`` off whatever comes back, which the DynamoDB
    repository already returns in the same shape as the Mongo one.
    """

    from backend.flask.scheduler.service import SchedulerService

    services = build_production_services(environ=environ)
    target_repository = DynamoDBMonitoringTargetRepository.from_settings()
    return SchedulerService(target_repository, services["monitoring"].monitor_target)


__all__ = ["build_production_scheduler", "build_production_services"]
