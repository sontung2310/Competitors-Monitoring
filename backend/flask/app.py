"""Flask application factory for the website-monitoring API."""

from __future__ import annotations

import logging
import os
from typing import Any, Mapping

from flask import Flask
from werkzeug.exceptions import HTTPException

from backend.flask.change_detection.repository import ChangeRepository
from backend.flask.change_detection.routes import changes_blueprint
from backend.flask.change_detection.service import ChangeService
from backend.flask.companies.repository import CompanyRepository
from backend.flask.companies.routes import companies_blueprint
from backend.flask.companies.service import CompanyService
from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.competitors.routes import competitors_blueprint
from backend.flask.competitors.service import CompetitorService
from backend.flask.database.connection import MongoSettings, connect_database
from backend.flask.discovery.routes import discovery_blueprint
from backend.flask.discovery.repository import DiscoveryRunRepository
from backend.flask.discovery.service import DiscoveryService, configured_discovery_audit
from backend.flask.errors import APIError, error_from_exception
from backend.flask.llm_provider import OpenAIProvider
from backend.flask.snapshot.repository import SnapshotRepository
from backend.flask.snapshot.service import SnapshotService
from backend.flask.snapshot.storage import SnapshotStorage
from backend.flask.website_monitoring.simulated_persistence import SimulationPersistenceService
from backend.flask.website_monitoring.repository import (
    MonitoringRunRepository,
    MonitoringTargetRepository,
)
from backend.flask.website_monitoring.routes import monitoring_blueprint
from backend.flask.website_monitoring.service import (
    MonitoringRunService,
    MonitoringTargetService,
)


logger = logging.getLogger(__name__)


def create_app(
    database: Any | None = None,
    *,
    settings: MongoSettings | None = None,
    user_id: str | None = None,
    storage_root: str | None = None,
    services: Mapping[str, Any] | None = None,
    testing: bool = False,
    llm_provider_factory: Any = OpenAIProvider.from_env,
) -> Flask:
    """Build a configured Flask app.

    With no injected services, the factory creates repository-backed domain
    services against the configured MongoDB database. Tests can inject service
    doubles without changing route code or production wiring.
    """

    app = Flask(__name__)
    app.config.update(
        TESTING=testing,
        API_USER_ID=user_id or os.environ.get("APP_USER_ID", "default-user"),
    )

    client = None
    if services is None:
        if database is None:
            client, database = connect_database(settings)
        services = _build_services(
            database,
            user_id=app.config["API_USER_ID"],
            storage_root=storage_root,
            llm_provider_factory=llm_provider_factory,
        )
    app.extensions["api_services"] = dict(services)
    if database is not None:
        app.extensions["database"] = database
    if client is not None:
        app.extensions["mongo_client"] = client

    app.register_blueprint(competitors_blueprint, url_prefix="/api")
    app.register_blueprint(companies_blueprint, url_prefix="/api")
    app.register_blueprint(discovery_blueprint, url_prefix="/api")
    app.register_blueprint(monitoring_blueprint, url_prefix="/api")
    app.register_blueprint(changes_blueprint, url_prefix="/api")
    _register_error_handlers(app)
    return app


def _build_services(
    database: Any,
    *,
    user_id: str,
    storage_root: str | None,
    llm_provider_factory: Any,
) -> dict[str, Any]:
    competitor_repository = CompetitorRepository.from_database(database)
    company_repository = CompanyRepository.from_database(database)
    target_repository = MonitoringTargetRepository.from_database(database)
    snapshot_repository = SnapshotRepository.from_database(database)
    change_repository = ChangeRepository.from_database(database)
    run_repository = MonitoringRunRepository.from_database(database)
    discovery_run_repository = DiscoveryRunRepository.from_database(database)

    # Index creation belongs to repositories; the factory only invokes their
    # public setup operation before exposing them to business services.
    for repository in (
        company_repository,
        competitor_repository,
        target_repository,
        snapshot_repository,
        change_repository,
        run_repository,
        discovery_run_repository,
    ):
        repository.ensure_indexes()

    company_service = CompanyService(company_repository)
    demo_companies = company_service.ensure_demo_companies()
    company_by_host = {
        "lyfemarketing.com": demo_companies[0]["id"],
        "jd-sports.com.au": demo_companies[1]["id"],
    }
    competitor_repository.migrate_legacy_user_ids(company_by_host)

    discovery_service = DiscoveryService(
        competitor_repository,
        target_repository,
        audit_classifier=configured_discovery_audit(),
        snapshot_repository=snapshot_repository,
        change_repository=change_repository,
        run_repository=discovery_run_repository,
    )
    change_service = ChangeService(
        change_repository,
        target_repository,
        competitor_repository=competitor_repository,
        narrative_provider_factory=llm_provider_factory,
    )
    target_service = MonitoringTargetService(
        target_repository,
        discovery_service,
        competitor_repository=competitor_repository,
    )
    monitoring_service = MonitoringRunService.from_database(
        database,
        storage_root=storage_root,
        narrative_provider_factory=llm_provider_factory,
    )
    simulation_service = SimulationPersistenceService.from_database(
        database,
        storage_root=storage_root,
        provider_factory=llm_provider_factory,
        narrative_provider_factory=llm_provider_factory,
    )
    return {
        "companies": company_service,
        "competitors": CompetitorService(competitor_repository, user_id=user_id),
        "discovery": discovery_service,
        "targets": target_service,
        "changes": change_service,
        "monitoring": monitoring_service,
        "simulation": simulation_service,
    }


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(Exception)
    def handle_exception(error: Exception):
        if isinstance(error, HTTPException):
            payload = {
                "error": {
                    "code": error.name.lower().replace(" ", "_"),
                    "message": error.description,
                }
            }
            return payload, error.code or 500

        mapped = error_from_exception(error)
        if mapped is None:
            logger.exception("unhandled Flask API error")
            mapped = APIError(
                "an unexpected server error occurred",
                status_code=500,
                code="internal_error",
            )
        return {"error": {"code": mapped.code, "message": str(mapped)}}, mapped.status_code
