"""Lightweight, repository-backed scheduling for website monitoring.

The scheduler owns only *when* monitoring is attempted.  It obtains eligible
rows through ``MonitoringTargetRepository.list_active_targets`` and delegates
the actual fetch, comparison, persistence, and concurrency guard to an
injected ``monitor_target`` callable from ``website_monitoring``.

The PoC uses one deterministic tick plus an optional fixed-cadence loop.  A
single loop avoids creating and removing one timer per target as candidates are
activated or deactivated, and keeps the tick directly testable without waiting
for a wall-clock timer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import Event
from typing import Any, Callable, Mapping, Protocol

from backend.flask.database.base_repository import utc_now
from backend.flask.website_monitoring.repository import MonitoringTargetRepository


DEFAULT_SCHEDULER_CADENCE_SECONDS = 60.0
SUCCESS = "SUCCESS"
FAILED = "FAILED"

logger = logging.getLogger(__name__)


class ActiveTargetReader(Protocol):
    """Repository boundary used by the scheduler to select work."""

    def list_active_targets(
        self,
        competitor_id: Any | None = None,
    ) -> list[Mapping[str, Any]]:
        """Return only active targets eligible for monitoring."""


MonitorTarget = Callable[[Any], Mapping[str, Any]]


@dataclass
class SchedulerTickResult:
    """Summary of one scheduler pass."""

    checked_at: datetime
    evaluated_target_ids: list[Any] = field(default_factory=list)
    due_target_ids: list[Any] = field(default_factory=list)
    skipped_target_ids: list[Any] = field(default_factory=list)
    succeeded_target_ids: list[Any] = field(default_factory=list)
    failed_targets: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly summary without embedding monitor payloads."""

        return {
            "checked_at": self.checked_at.isoformat(),
            "evaluated_target_ids": list(self.evaluated_target_ids),
            "due_target_ids": list(self.due_target_ids),
            "skipped_target_ids": list(self.skipped_target_ids),
            "succeeded_target_ids": list(self.succeeded_target_ids),
            "failed_targets": [dict(failure) for failure in self.failed_targets],
        }


class SchedulerService:
    """Determine due targets and delegate each one independently."""

    def __init__(
        self,
        target_repository: ActiveTargetReader,
        monitor_target: MonitorTarget,
        *,
        clock: Callable[[], datetime] = utc_now,
        log: logging.Logger | None = None,
    ) -> None:
        if not callable(monitor_target):
            raise TypeError("monitor_target must be callable")
        self.target_repository = target_repository
        self.monitor_target = monitor_target
        self.clock = clock
        self.logger = log or logger

    @classmethod
    def from_database(
        cls,
        database: Any,
        monitor_target: MonitorTarget,
        *,
        clock: Callable[[], datetime] = utc_now,
        log: logging.Logger | None = None,
    ) -> "SchedulerService":
        """Build a scheduler using the shared monitoring-target repository."""

        return cls(
            MonitoringTargetRepository.from_database(database),
            monitor_target,
            clock=clock,
            log=log,
        )

    def run_due_targets(
        self,
        *,
        now: datetime | None = None,
    ) -> SchedulerTickResult:
        """Run one pass over active targets, isolating failures per target.

        A target is due when it has never been checked or its interval has
        elapsed.  ``monitor_target`` is called once for every due target.  An
        exception or a FAILED monitoring result is recorded and logged, then
        the next target is still evaluated.
        """

        checked_at = now or self.clock()
        _require_aware_datetime(checked_at, "now")
        checked_at = _as_utc(checked_at)
        result = SchedulerTickResult(checked_at=checked_at)

        # This is intentionally the only target-selection call.  The shared
        # repository method requires active=True and discovery_status=ACTIVE.
        targets = self.target_repository.list_active_targets()
        for target in targets:
            target_id = target.get("id")
            result.evaluated_target_ids.append(target_id)
            try:
                due = _is_due(target, checked_at)
            except Exception as exc:  # noqa: BLE001 - isolate malformed rows
                self._record_failure(result, target_id, exc, "due-date evaluation")
                continue

            if not due:
                result.skipped_target_ids.append(target_id)
                continue

            result.due_target_ids.append(target_id)
            try:
                monitoring_result = self.monitor_target(target_id)
                _record_monitoring_outcome(
                    result,
                    target_id,
                    monitoring_result,
                )
            except Exception as exc:  # noqa: BLE001 - required per-target isolation
                self._record_failure(result, target_id, exc, "monitoring dispatch")

        return result

    def _record_failure(
        self,
        result: SchedulerTickResult,
        target_id: Any,
        error: Exception,
        phase: str,
    ) -> None:
        message = _exception_detail(error)
        result.failed_targets.append(
            {
                "target_id": target_id,
                "phase": phase,
                "error_message": message,
            }
        )
        self.logger.exception(
            "scheduler %s failed for monitoring target %r: %s",
            phase,
            target_id,
            message,
        )


def run_due_targets(
    *,
    target_repository: ActiveTargetReader,
    monitor_target: MonitorTarget,
    now: datetime | None = None,
    clock: Callable[[], datetime] = utc_now,
    log: logging.Logger | None = None,
) -> SchedulerTickResult:
    """Functional entry point for one deterministic scheduling tick."""

    return SchedulerService(
        target_repository,
        monitor_target,
        clock=clock,
        log=log,
    ).run_due_targets(now=now)


def run_scheduler_forever(
    scheduler: SchedulerService,
    *,
    cadence_seconds: float = DEFAULT_SCHEDULER_CADENCE_SECONDS,
    stop_event: Event | None = None,
) -> None:
    """Run immediate ticks at a fixed cadence until ``stop_event`` is set.

    The wrapper contains no target or monitoring policy.  Its only job is to
    invoke the deterministic tick and provide a lightweight process-level
    cadence; a worker/queue can replace it later without changing the tick.
    """

    if isinstance(cadence_seconds, bool) or cadence_seconds <= 0:
        raise ValueError("cadence_seconds must be positive")
    event = stop_event or Event()
    while not event.is_set():
        try:
            scheduler.run_due_targets()
        except Exception:  # noqa: BLE001 - keep the process loop alive
            scheduler.logger.exception("scheduler tick failed")
        if event.wait(cadence_seconds):
            break


def _is_due(target: Mapping[str, Any], now: datetime) -> bool:
    interval_minutes = target.get("check_interval_minutes")
    if (
        isinstance(interval_minutes, bool)
        or not isinstance(interval_minutes, int)
        or interval_minutes <= 0
    ):
        raise ValueError(
            f"check_interval_minutes must be a positive integer, got {interval_minutes!r}"
        )

    last_checked_at = target.get("last_checked_at")
    if last_checked_at is None:
        return True
    if not isinstance(last_checked_at, datetime):
        raise ValueError("last_checked_at must be a datetime")
    due_at = _as_utc(last_checked_at) + timedelta(minutes=interval_minutes)
    return due_at <= now


def _record_monitoring_outcome(
    result: SchedulerTickResult,
    target_id: Any,
    monitoring_result: Mapping[str, Any],
) -> None:
    if not isinstance(monitoring_result, Mapping):
        raise ValueError("monitor_target returned a non-mapping result")
    run = monitoring_result.get("run")
    if not isinstance(run, Mapping):
        raise ValueError("monitor_target result has no run record")
    status = run.get("status")
    if status == SUCCESS:
        result.succeeded_target_ids.append(target_id)
        return
    if status == FAILED:
        result.failed_targets.append(
            {
                "target_id": target_id,
                "phase": "monitoring result",
                "error_message": run.get("error_message")
                or "monitor_target returned FAILED without an error_message",
            }
        )
        return
    raise ValueError(f"monitor_target returned unsupported run status {status!r}")


def _require_aware_datetime(value: Any, field: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware datetime")


def _as_utc(value: datetime) -> datetime:
    # PyMongo returns BSON datetimes as naive UTC values unless a timezone-aware
    # codec option is configured. Treat those persisted values as UTC, matching
    # the website-monitoring repository's timestamp handling.
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _exception_detail(error: Exception) -> str:
    detail = str(error).strip()
    return detail or error.__class__.__name__
