"""Change persistence in the external RM MongoDB database (production).

Per ``docs/production-plan.md`` section 5.3, ``changes`` moves out of our own
database into a new collection in the external RM database, reusing the same
host-routed connection settings already built for the strategy lookup
(``scheduler/strategy_lookup.py``).

This subclasses the existing :class:`ChangeRepository` rather than
reimplementing it: since DynamoDB target ids are minted in Mongo ObjectId
*format* (see ``website_monitoring/dynamodb_repository.py``), every read
method that round-trips ``monitoring_target_id`` through ``to_object_id()``
(``list_for_target``, ``list``, ``get``, indexes, narrative backfill queries)
keeps working unchanged. Only ``create()`` differs: a snapshot reference is
now the DynamoDB ``{monitoring_target_id, captured_at}`` pair instead of a
single Mongo ObjectId, since a DynamoDB snapshot has no single opaque id.

Unlike the strategy lookup (resolved fresh per SQS message, since ``host`` is
a field on the inbound message), this repository is built once at process
startup — ``ChangeService``/``MonitoringRunService`` have no per-message
context, and the scheduler calls ``monitor_target()`` independently of SQS
entirely. Which RM database this deployment writes to is therefore a fixed,
environment-level choice (``RM_HOST``, default ``"dev"``), separate from the
per-message ``host`` used for strategy resolution.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Mapping, Optional

from backend.flask.database.base_repository import (
    serialize_document,
    to_object_id,
    utc_now,
)
from backend.flask.database.connection import connect_database

from .repository import ChangeRepository


class RmChangeRepository(ChangeRepository):
    """``competitors_changes`` in the external RM database."""

    collection_name = "competitors_changes"

    @classmethod
    def from_host(cls, host: str) -> "RmChangeRepository":
        """Connect using the same host-routing convention as the strategy lookup."""

        from backend.flask.scheduler.strategy_lookup import rm_mongo_settings_for_host

        settings = rm_mongo_settings_for_host(host)
        _, database = connect_database(settings)
        return cls.from_database(database)

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> "RmChangeRepository":
        """Connect using this deployment's fixed ``RM_HOST`` (default ``"dev"``)."""

        values = environ if environ is not None else os.environ
        host = values.get("RM_HOST", "dev").strip().lower() or "dev"
        return cls.from_host(host)

    def create(
        self,
        *,
        monitoring_target_id: Any,
        previous_snapshot_id: Any,
        current_snapshot_id: Any,
        detected_at: datetime,
        change_type: str,
        summary: str,
        status: str,
        now: Optional[Any] = None,
        narrative_summary: Optional[str] = None,
        detected_url: Optional[str] = None,
    ) -> dict[str, Any]:
        """Same contract as ``ChangeRepository.create``, except
        ``previous_snapshot_id``/``current_snapshot_id`` are DynamoDB
        snapshot reference mappings (``{"monitoring_target_id": ...,
        "captured_at": ...}``), not scalar ids."""

        _require_timestamp(detected_at)
        _require_text(change_type, "change_type")
        _require_text(summary, "summary")
        if narrative_summary is not None:
            _require_text(narrative_summary, "narrative_summary")
        if detected_url is not None:
            _require_text(detected_url, "detected_url")
        _require_text(status, "status")
        timestamp = now or utc_now()
        document = {
            "monitoring_target_id": to_object_id(monitoring_target_id),
            "previous_snapshot": _snapshot_reference(previous_snapshot_id),
            "current_snapshot": _snapshot_reference(current_snapshot_id),
            "detected_at": detected_at,
            "change_type": change_type,
            "summary": summary,
            "narrative_summary": narrative_summary,
            "detected_url": detected_url,
            "status": status,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        result = self.collection.insert_one(document)
        inserted_id = getattr(result, "inserted_id", None)
        if inserted_id is not None:
            document["_id"] = inserted_id
        return serialize_document(document) or {}


def _snapshot_reference(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(
            "snapshot reference must be a {monitoring_target_id, captured_at} mapping"
        )
    monitoring_target_id = value.get("monitoring_target_id")
    captured_at = value.get("captured_at")
    if not isinstance(monitoring_target_id, str) or not monitoring_target_id.strip():
        raise ValueError("snapshot reference is missing monitoring_target_id")
    if not isinstance(captured_at, str) or not captured_at.strip():
        raise ValueError("snapshot reference is missing captured_at")
    return {"monitoring_target_id": monitoring_target_id, "captured_at": captured_at}


def _require_text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


def _require_timestamp(value: Any) -> None:
    if not isinstance(value, datetime):
        raise ValueError("detected_at must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("detected_at must be timezone-aware")


__all__ = ["RmChangeRepository"]
