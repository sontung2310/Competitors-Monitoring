"""MongoDB persistence for long-running Layer 1 discovery runs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

from backend.flask.database.base_repository import (
    BaseMongoRepository,
    serialize_document,
    to_object_id,
    utc_now,
)


class DiscoveryRunRepository(BaseMongoRepository):
    """Persistence operations for the ``discovery_runs`` collection."""

    collection_name = "discovery_runs"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    _STATUSES = frozenset({RUNNING, SUCCESS, FAILED})

    def ensure_indexes(self) -> None:
        self.collection.create_index(
            [("run_id", 1)],
            unique=True,
            name="uq_discovery_runs_run_id",
        )
        self.collection.create_index(
            [("competitor_id", 1), ("started_at", -1)],
            name="ix_discovery_runs_competitor_started_at",
        )

    def start(
        self,
        run_id: str,
        *,
        competitor_id: Any,
        company_id: Any = None,
        started_at: Optional[datetime] = None,
    ) -> dict[str, Any]:
        _require_text(run_id, "run_id")
        timestamp = started_at or utc_now()
        document = {
            "run_id": run_id,
            "competitor_id": to_object_id(competitor_id),
            "company_id": to_object_id(company_id) if company_id is not None else None,
            "status": self.RUNNING,
            "started_at": timestamp,
            "finished_at": None,
            "candidate_count": None,
            "summary": None,
            "error_message": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        result = self.collection.insert_one(document)
        inserted_id = getattr(result, "inserted_id", None)
        if inserted_id is not None:
            document["_id"] = inserted_id
        return serialize_document(document) or {}

    def get(self, run_id: str) -> Optional[dict[str, Any]]:
        _require_text(run_id, "run_id")
        return serialize_document(self.collection.find_one({"run_id": run_id}))

    def find_latest_successful(
        self,
        competitor_id: Any,
        *,
        company_id: Any = None,
    ) -> Optional[dict[str, Any]]:
        """Return the most recently finished successful run for a competitor.

        Discovery freshness is derived from the existing discovery-run
        lifecycle records.  No timestamp is copied onto the competitor, so
        failed and in-progress runs cannot accidentally make a competitor
        appear fresh.
        """

        query: dict[str, Any] = {
            "competitor_id": to_object_id(competitor_id),
            "status": self.SUCCESS,
        }
        if company_id is not None:
            query["company_id"] = to_object_id(company_id)
        runs = self._find_sorted(
            query,
            [("finished_at", -1), ("started_at", -1)],
        )
        return runs[0] if runs else None

    def succeed(
        self,
        run_id: str,
        *,
        candidate_count: int,
        summary: Mapping[str, Any] | None = None,
        finished_at: Optional[datetime] = None,
    ) -> Optional[dict[str, Any]]:
        return self._finish(
            run_id,
            status=self.SUCCESS,
            candidate_count=candidate_count,
            summary=summary,
            finished_at=finished_at,
        )

    def fail(
        self,
        run_id: str,
        error_message: str,
        *,
        finished_at: Optional[datetime] = None,
    ) -> Optional[dict[str, Any]]:
        _require_text(error_message, "error_message")
        timestamp = finished_at or utc_now()
        result = self.collection.update_one(
            {"run_id": run_id, "status": self.RUNNING},
            {
                "$set": {
                    "status": self.FAILED,
                    "finished_at": timestamp,
                    "error_message": error_message,
                    "updated_at": utc_now(),
                }
            },
        )
        if not self._matched(result):
            return self.get(run_id)
        return self.get(run_id)

    def _finish(
        self,
        run_id: str,
        *,
        status: str,
        candidate_count: int,
        summary: Mapping[str, Any] | None,
        finished_at: Optional[datetime],
    ) -> Optional[dict[str, Any]]:
        _require_text(run_id, "run_id")
        if status not in {self.SUCCESS, self.FAILED}:
            raise ValueError("discovery run must finish SUCCESS or FAILED")
        if isinstance(candidate_count, bool) or not isinstance(candidate_count, int):
            raise ValueError("candidate_count must be an integer")
        timestamp = finished_at or utc_now()
        result = self.collection.update_one(
            {"run_id": run_id, "status": self.RUNNING},
            {
                "$set": {
                    "status": status,
                    "finished_at": timestamp,
                    "candidate_count": candidate_count,
                    "summary": dict(summary) if summary is not None else None,
                    "error_message": None,
                    "updated_at": utc_now(),
                }
            },
        )
        if not self._matched(result):
            return self.get(run_id)
        return self.get(run_id)


def _require_text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
