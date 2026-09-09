"""Persistence-enabled simulation flow for the clickable PoC demo.

The read-only helpers in :mod:`simulated_verification` are intentionally left
unchanged. This module is the explicit exception: it calls those helpers,
then writes only records marked ``is_simulated=True`` through the normal
snapshot and change services.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable, Mapping

from backend.flask.database.base_repository import utc_now
from backend.flask.errors import NotFoundError
from backend.flask.llm_provider import OpenAIProvider
from backend.flask.snapshot.repository import SnapshotRepository
from backend.flask.snapshot.service import SnapshotService

from .content_processing import resolve_content_processor
from .service import FetchResult, fetch_page
from .simulated_verification import (
    ProductSimulationResult,
    SimulatedVerificationError,
    simulate_blog_change,
    simulate_product_listing_change,
    simulate_product_mutation,
    simulate_services_change,
    simulate_text_change,
)


class SimulationPersistenceError(RuntimeError):
    """Raised when a persistence-enabled PoC simulation cannot complete."""

    status_code = 422
    code = "simulation_error"


class SimulationPersistenceService:
    """Run one LLM mutation and persist its explicitly simulated result."""

    def __init__(
        self,
        target_repository: Any,
        snapshot_repository: Any,
        snapshot_service: Any,
        change_service: Any,
        *,
        competitor_repository: Any | None = None,
        provider_factory: Callable[[], Any] = OpenAIProvider.from_env,
        fetcher: Callable[[str], FetchResult] = fetch_page,
        snapshot_content_loader: Callable[[Mapping[str, Any]], str] | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.target_repository = target_repository
        self.snapshot_repository = snapshot_repository
        self.snapshot_service = snapshot_service
        self.change_service = change_service
        self.competitor_repository = competitor_repository
        self.provider_factory = provider_factory
        self.fetcher = fetcher
        self.snapshot_content_loader = snapshot_content_loader
        self.clock = clock

    @classmethod
    def from_database(
        cls,
        database: Any,
        *,
        storage_root: str | None = None,
        fetcher: Callable[[str], FetchResult] = fetch_page,
        provider_factory: Callable[[], Any] = OpenAIProvider.from_env,
        narrative_provider_factory: Callable[[], Any] | None = None,
    ) -> "SimulationPersistenceService":
        """Build a repository-backed simulator using the normal storage path."""

        from backend.flask.change_detection.repository import ChangeRepository
        from backend.flask.change_detection.service import ChangeService
        from backend.flask.competitors.repository import CompetitorRepository
        from backend.flask.snapshot.storage import SnapshotStorage
        from backend.flask.website_monitoring.repository import MonitoringTargetRepository

        target_repository = MonitoringTargetRepository.from_database(database)
        snapshot_repository = SnapshotRepository.from_database(database)
        storage = SnapshotStorage(storage_root)
        snapshot_service = SnapshotService(snapshot_repository, storage)
        loader = lambda snapshot: storage.read_snapshot_bytes(
            snapshot["storage_path"]
        ).decode("utf-8")
        change_service = ChangeService(
            ChangeRepository.from_database(database),
            target_repository,
            snapshot_content_loader=loader,
            narrative_provider_factory=(
                narrative_provider_factory
                if narrative_provider_factory is not None
                else provider_factory
            ),
        )
        return cls(
            target_repository,
            snapshot_repository,
            snapshot_service,
            change_service,
            competitor_repository=CompetitorRepository.from_database(database),
            provider_factory=provider_factory,
            fetcher=fetcher,
            snapshot_content_loader=loader,
        )

    def simulate_and_persist_change(
        self,
        target_id: Any,
        *,
        company_id: Any | None = None,
        mutation_type: str | None = None,
    ) -> dict[str, Any]:
        """Persist one tagged simulated snapshot and its tagged events.

        A real baseline is created first when a target has never been checked.
        The simulation itself never updates target scheduling metadata, and
        genuine monitoring excludes the resulting snapshot explicitly.
        """

        target = self.target_repository.get(target_id)
        if target is None:
            raise NotFoundError(f"monitoring target {target_id!r} was not found")
        if not _is_active_target(target):
            raise SimulationPersistenceError(
                f"monitoring target {target_id!r} is not an active target"
            )
        self._assert_company_scope(target, company_id)

        fetched = self.fetcher(target["url"])
        _validate_fetch_result(fetched, target["url"])
        baseline = self._latest_real_snapshot(target_id)
        if baseline is None:
            baseline = self._create_real_baseline(target, fetched)
        baseline = self._with_content(baseline)

        provider = self.provider_factory()
        page_type = str(target.get("page_type", "OTHER")).strip().upper()
        try:
            current_content, events, resolved_mutation_type = self._mutate(
                page_type,
                fetched.content,
                provider,
                baseline,
                mutation_type,
            )
        except SimulatedVerificationError:
            raise
        except Exception as exc:
            raise SimulationPersistenceError(
                f"could not generate a simulated {page_type} change"
            ) from exc

        simulated_snapshot = self.snapshot_service.create_snapshot(
            target_id,
            current_content,
            fetch_method=fetched.fetch_method,
            http_status=fetched.http_status,
            captured_at=self.clock(),
            is_simulated=True,
        )
        persisted_changes: list[dict[str, Any]] = []
        detected_at = self.clock()
        for event in events:
            change_type = event.get("change_type")
            summary = event.get("summary")
            if not isinstance(change_type, str) or not change_type.strip():
                raise SimulationPersistenceError("simulated event has no change_type")
            if not isinstance(summary, str) or not summary.strip():
                raise SimulationPersistenceError("simulated event has no summary")
            persisted_changes.append(
                self.change_service.create_change(
                    target_id,
                    baseline,
                    simulated_snapshot,
                    detected_at=detected_at,
                    change_type=change_type,
                    summary=summary,
                    is_simulated=True,
                    narrative_provider=provider,
                )
            )
        if not persisted_changes:
            raise SimulationPersistenceError("simulation produced no change events")

        result = {
            "monitoring_target_id": str(target_id),
            "page_type": page_type,
            "is_simulated": True,
            "previous_snapshot": _metadata_only(baseline),
            "snapshot": simulated_snapshot,
            "changes": persisted_changes,
            "change": persisted_changes[0] if len(persisted_changes) == 1 else None,
        }
        if resolved_mutation_type is not None:
            result["mutation_type"] = resolved_mutation_type
        return result

    def _assert_company_scope(self, target: Mapping[str, Any], company_id: Any | None) -> None:
        if company_id is None:
            return
        if self.competitor_repository is None:
            raise SimulationPersistenceError(
                "company-scoped simulation requires a competitor repository"
            )
        competitor = self.competitor_repository.get(
            target.get("competitor_id"),
            company_id=company_id,
        )
        if competitor is None:
            raise NotFoundError(f"monitoring target is outside company {company_id!r}")

    def _latest_real_snapshot(self, target_id: Any) -> dict[str, Any] | None:
        try:
            snapshots = self.snapshot_repository.list_for_target(
                target_id,
                include_simulated=False,
            )
        except TypeError as exc:
            if "include_simulated" not in str(exc):
                raise
            snapshots = self.snapshot_repository.list_for_target(target_id)
        real_snapshots = [
            snapshot
            for snapshot in snapshots
            if snapshot.get("is_simulated") is not True
        ]
        return real_snapshots[0] if real_snapshots else None

    def _create_real_baseline(
        self,
        target: Mapping[str, Any],
        fetched: FetchResult,
    ) -> dict[str, Any]:
        processor = resolve_content_processor(str(target.get("page_type", "OTHER")))
        baseline_result = processor.process(fetched.content, None)
        return self.snapshot_service.create_snapshot(
            target["id"],
            baseline_result.snapshot_content,
            fetch_method=fetched.fetch_method,
            http_status=fetched.http_status,
            captured_at=self.clock(),
            is_simulated=False,
        )

    def _with_content(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        if isinstance(snapshot.get("content"), str):
            return dict(snapshot)
        if isinstance(snapshot.get("normalized_content"), str):
            return dict(snapshot)
        if self.snapshot_content_loader is None:
            raise SimulationPersistenceError(
                "real baseline snapshot content is unavailable"
            )
        loaded = dict(snapshot)
        loaded["content"] = self.snapshot_content_loader(snapshot)
        return loaded

    def _mutate(
        self,
        page_type: str,
        raw_content: str,
        provider: Any,
        baseline: Mapping[str, Any],
        mutation_type: str | None,
    ) -> tuple[str, tuple[dict[str, Any], ...], str | None]:
        if page_type == "PRODUCT_LISTING":
            if mutation_type is None:
                result = simulate_product_listing_change(raw_content, provider)
                resolved = None
            else:
                result = simulate_product_mutation(
                    raw_content,
                    provider,
                    mutation_type=mutation_type,
                )
                resolved = result.mutation_type
            if not isinstance(result, ProductSimulationResult):
                raise SimulationPersistenceError("invalid product simulation result")
            return (
                _serialize_products(result.mutated_products),
                tuple(dict(event) for event in result.events),
                resolved,
            )

        if page_type == "BLOG":
            result = simulate_blog_change(raw_content, provider, previous_snapshot=baseline)
        elif page_type == "SERVICES":
            result = simulate_services_change(raw_content, provider, previous_snapshot=baseline)
        else:
            result = simulate_text_change(
                raw_content,
                provider,
                page_type=page_type,
                previous_snapshot=baseline,
            )
        return (
            result.process_result.snapshot_content,
            tuple(dict(event) for event in result.process_result.change_events),
            None,
        )


def _serialize_products(products: tuple[Mapping[str, str], ...]) -> str:
    return json.dumps(
        [dict(product) for product in products],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _metadata_only(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in snapshot.items() if key not in {"content", "normalized_content"}}


def _is_active_target(target: Mapping[str, Any]) -> bool:
    return target.get("active") is True and target.get("discovery_status") == "ACTIVE"


def _validate_fetch_result(result: Any, url: str) -> None:
    if not isinstance(result, FetchResult):
        raise SimulationPersistenceError(
            f"fetcher returned an invalid result for {url!r}"
        )
    if not isinstance(result.content, str) or not result.content.strip():
        raise SimulationPersistenceError(f"fetch returned empty content for {url!r}")
    if not isinstance(result.fetch_method, str) or not result.fetch_method.strip():
        raise SimulationPersistenceError(f"fetch returned no method for {url!r}")
    if (
        isinstance(result.http_status, bool)
        or not isinstance(result.http_status, int)
        or not 100 <= result.http_status <= 599
    ):
        raise SimulationPersistenceError(f"fetch returned invalid status for {url!r}")


__all__ = ["SimulationPersistenceError", "SimulationPersistenceService"]
