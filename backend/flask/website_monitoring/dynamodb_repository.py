"""DynamoDB-backed ``monitoring_targets`` storage for production.

Implements the same public method shapes as
:class:`backend.flask.website_monitoring.repository.MonitoringTargetRepository`
so ``DiscoveryService``, ``MonitoringRunService``, and the scheduler can use
either repository interchangeably without any change to their own code. The
data model is deliberately narrower than Mongo's three-state
SUGGESTED/ACTIVE/DISCARDED lifecycle, per ``docs/production-plan.md`` section
5.1:

- Only rows classified ``SUGGESTED`` are ever written. ``DISCARDED``
  candidates are never persisted here at all.
- A row's mere presence in the table means it is currently tracked; there is
  no separate ``active`` flag to maintain.
- "Deactivating" a target means deleting its row (see ``mark_discarded``),
  not flipping a flag.

Two lifecycle-transition methods, ``mark_activated`` and ``mark_discarded``,
exist specifically so ``discovery/service.py``'s ``activate_candidate`` and
``discard_candidate`` can call something semantically explicit instead of a
generic field update that would otherwise try to write the forbidden
``active``/``discovery_status="ACTIVE"``/``"DISCARDED"`` values. The generic
``update()`` method deliberately rejects those two fields to keep that
contract explicit rather than silently swallowing them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from bson import ObjectId

from backend.flask.database.base_repository import utc_now
from backend.flask.database.dynamodb_connection import (
    DynamoDBSettings,
    create_dynamodb_resource,
)

from .intervals import default_check_interval_minutes


_ORDINARY_UPDATE_FIELDS = {
    "raw_url",
    "url",
    "page_type",
    "discovery_source",
    "classification_method",
    "check_interval_minutes",
    "last_checked_at",
    "last_changed_at",
}


class DynamoDBMonitoringTargetRepository:
    """Persistence operations for the production monitoring-targets table."""

    GSI_NAME = "gsi_competitor_id"

    def __init__(self, table: Any) -> None:
        self.table = table

    @classmethod
    def from_settings(
        cls,
        settings: Optional[DynamoDBSettings] = None,
    ) -> "DynamoDBMonitoringTargetRepository":
        resolved = settings or DynamoDBSettings.from_env()
        resource = create_dynamodb_resource(resolved)
        return cls(resource.Table(resolved.monitoring_targets_table))

    def ensure_indexes(self) -> None:
        """No-op: the table and its GSI are provisioned by infrastructure setup."""

    def create(
        self,
        *,
        competitor_id: Any,
        url: str,
        page_type: str,
        check_interval_minutes: int,
        raw_url: Optional[str] = None,
        discovery_source: str = "MANUAL",
        discovery_status: str = "SUGGESTED",
        classification_method: str = "MANUAL",
        active: Optional[bool] = None,
        last_checked_at: Optional[Any] = None,
        last_changed_at: Optional[Any] = None,
        now: Optional[Any] = None,
    ) -> dict[str, Any]:
        """Insert a tracked target. ``active`` is accepted for interface
        parity with the Mongo repository and ignored: writing a row here
        already means it's tracked."""

        _require_text(url, "url")
        _require_text(page_type, "page_type")
        _require_positive_interval(check_interval_minutes)
        timestamp = now or utc_now()
        item = {
            "_id": str(ObjectId()),
            "competitor_id": str(competitor_id),
            "raw_url": raw_url or url,
            "url": url,
            "page_type": page_type,
            "discovery_source": discovery_source,
            "discovery_status": "SUGGESTED",
            "classification_method": classification_method,
            "check_interval_minutes": int(check_interval_minutes),
            "last_checked_at": _iso(last_checked_at),
            "last_changed_at": _iso(last_changed_at),
            "created_at": _iso(timestamp),
            "updated_at": _iso(timestamp),
        }
        self.table.put_item(Item=item)
        return _to_dict(item)

    def get(
        self,
        target_id: Any,
        *,
        competitor_id: Optional[Any] = None,
    ) -> Optional[dict[str, Any]]:
        response = self.table.get_item(Key={"_id": str(target_id)})
        item = response.get("Item")
        if item is None:
            return None
        target = _to_dict(item)
        if competitor_id is not None and target["competitor_id"] != str(competitor_id):
            return None
        return target

    def list_for_competitor(
        self,
        competitor_id: Any,
        *,
        active: Optional[bool] = None,
        discovery_status: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Every row is already tracked and SUGGESTED, so a filter asking for
        anything else (an explicit ``active=False`` or a non-SUGGESTED status)
        can only ever match nothing."""

        if active is False:
            return []
        if discovery_status is not None and discovery_status != "SUGGESTED":
            return []
        from boto3.dynamodb.conditions import Key

        items: list[dict[str, Any]] = []
        query_kwargs: dict[str, Any] = {
            "IndexName": self.GSI_NAME,
            "KeyConditionExpression": Key("competitor_id").eq(str(competitor_id)),
        }
        while True:
            response = self.table.query(**query_kwargs)
            items.extend(response.get("Items", []))
            if "LastEvaluatedKey" not in response:
                break
            query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        rows = [_to_dict(item) for item in items]
        rows.sort(key=lambda row: row.get("created_at") or "", reverse=True)
        return rows

    def list_active_targets(
        self,
        competitor_id: Optional[Any] = None,
    ) -> list[dict[str, Any]]:
        """Scoped to a competitor, this queries the GSI. Unscoped (the
        scheduler's global "what's due for a check" job), this Scans the
        whole table, which is already exactly the tracked set — there is no
        ``active``/``discovery_status`` filter left to apply."""

        if competitor_id is not None:
            return self.list_for_competitor(competitor_id)
        items: list[dict[str, Any]] = []
        scan_kwargs: dict[str, Any] = {}
        while True:
            response = self.table.scan(**scan_kwargs)
            items.extend(response.get("Items", []))
            if "LastEvaluatedKey" not in response:
                break
            scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        rows = [_to_dict(item) for item in items]
        rows.sort(key=lambda row: row.get("created_at") or "", reverse=True)
        return rows

    def find_by_url(
        self,
        competitor_id: Any,
        url: str,
    ) -> Optional[dict[str, Any]]:
        _require_text(url, "url")
        for target in self.list_for_competitor(competitor_id):
            if target["url"] == url:
                return target
        return None

    def upsert_discovered_candidate(
        self,
        *,
        competitor_id: Any,
        raw_url: str,
        url: str,
        page_type: str,
        discovery_source: str,
        discovery_status: str,
        classification_method: str,
        now: Optional[Any] = None,
    ) -> dict[str, Any]:
        """Persist a discovered candidate; never persist a DISCARDED verdict.

        A URL reclassified DISCARDED on a later run is not deleted here —
        that's the job of ``discover_and_reconcile``'s separate deactivation
        pass, which compares the final suggested-URL set against what's
        currently tracked. This only returns an in-memory placeholder so
        callers that read fields off the result (without expecting it to have
        been persisted) keep working.
        """

        _require_text(raw_url, "raw_url")
        _require_text(url, "url")
        _require_text(page_type, "page_type")
        _require_text(discovery_source, "discovery_source")
        _require_text(discovery_status, "discovery_status")
        _require_text(classification_method, "classification_method")

        if discovery_status == "DISCARDED":
            existing = self.find_by_url(competitor_id, url)
            return {
                "id": existing["id"] if existing else None,
                "competitor_id": str(competitor_id),
                "raw_url": raw_url,
                "url": url,
                "page_type": page_type,
                "discovery_source": discovery_source,
                "discovery_status": "DISCARDED",
                "classification_method": classification_method,
                "active": False,
            }

        existing = self.find_by_url(competitor_id, url)
        if existing is not None:
            updated = self.update(
                existing["id"],
                {
                    "raw_url": raw_url,
                    "discovery_source": discovery_source,
                    "page_type": page_type,
                    "classification_method": classification_method,
                },
                competitor_id=competitor_id,
            )
            return updated or existing

        return self.create(
            competitor_id=competitor_id,
            raw_url=raw_url,
            url=url,
            page_type=page_type,
            discovery_source=discovery_source,
            discovery_status="SUGGESTED",
            classification_method=classification_method,
            check_interval_minutes=default_check_interval_minutes(page_type),
            now=now,
        )

    def discard_discovered_candidates_by_url_patterns(
        self,
        competitor_id: Any,
        *,
        url_patterns: tuple[str, ...],
    ) -> int:
        """No-op: there is no unactivated-candidate limbo state to repair.

        Dev's Mongo version retroactively discards previously-suggested,
        never-activated rows that now match a newly learned exclusion
        pattern. In the presence-based DynamoDB model, a page matching such a
        pattern simply stops being reclassified SUGGESTED on the next
        discovery run and is removed by the normal reconciliation
        deactivation pass instead.
        """

        return 0

    def update(
        self,
        target_id: Any,
        updates: Optional[Mapping[str, Any]] = None,
        *,
        competitor_id: Optional[Any] = None,
        **fields: Any,
    ) -> Optional[dict[str, Any]]:
        """Update ordinary metadata fields. ``active``/``discovery_status``
        are rejected here — callers must use ``mark_activated``/
        ``mark_discarded`` instead, so a lifecycle transition is never
        silently swallowed as a plain field write."""

        values = dict(updates or {})
        values.update(fields)
        if not values:
            raise ValueError("at least one monitoring-target field is required")
        if "active" in values or "discovery_status" in values:
            raise ValueError(
                "use mark_activated()/mark_discarded() for lifecycle transitions, "
                "not update()"
            )
        unknown = set(values) - _ORDINARY_UPDATE_FIELDS
        if unknown:
            raise ValueError(f"unsupported monitoring-target fields: {sorted(unknown)}")
        if "url" in values:
            _require_text(values["url"], "url")
        if "raw_url" in values:
            _require_text(values["raw_url"], "raw_url")
        if "page_type" in values:
            _require_text(values["page_type"], "page_type")
        if "check_interval_minutes" in values:
            _require_positive_interval(values["check_interval_minutes"])

        current = self.get(target_id, competitor_id=competitor_id)
        if current is None:
            return None
        for field in ("last_checked_at", "last_changed_at"):
            if field in values and values[field] is not None:
                values[field] = _iso(values[field])
        values["updated_at"] = _iso(utc_now())
        return self._update_fields(target_id, values)

    def delete(
        self,
        target_id: Any,
        *,
        competitor_id: Optional[Any] = None,
    ) -> bool:
        if competitor_id is not None:
            existing = self.get(target_id, competitor_id=competitor_id)
            if existing is None:
                return False
        else:
            existing = self.get(target_id)
            if existing is None:
                return False
        self.table.delete_item(Key={"_id": str(target_id)})
        return True

    def mark_activated(
        self,
        target_id: Any,
        *,
        competitor_id: Optional[Any] = None,
        check_interval_minutes: Optional[int] = None,
    ) -> Optional[dict[str, Any]]:
        """A row's presence already means it's tracked, so this only ever
        needs to backfill a missing/invalid check interval, never a status
        flip."""

        target = self.get(target_id, competitor_id=competitor_id)
        if target is None:
            return None
        if (
            check_interval_minutes is not None
            and check_interval_minutes != target.get("check_interval_minutes")
        ):
            return self._update_fields(
                target_id,
                {
                    "check_interval_minutes": int(check_interval_minutes),
                    "updated_at": _iso(utc_now()),
                },
            )
        return target

    def mark_discarded(
        self,
        target_id: Any,
        *,
        competitor_id: Optional[Any] = None,
    ) -> Optional[dict[str, Any]]:
        """Discarding means deleting the row; the returned dict reflects the
        outcome for callers that only read fields off the result."""

        target = self.get(target_id, competitor_id=competitor_id)
        if target is None:
            return None
        self.table.delete_item(Key={"_id": str(target_id)})
        return {**target, "active": False, "discovery_status": "DISCARDED"}

    def _update_fields(
        self,
        target_id: Any,
        values: Mapping[str, Any],
    ) -> dict[str, Any]:
        keys = list(values.keys())
        expression_names = {f"#f{i}": key for i, key in enumerate(keys)}
        expression_values = {f":v{i}": values[key] for i, key in enumerate(keys)}
        update_expression = "SET " + ", ".join(
            f"#f{i} = :v{i}" for i in range(len(keys))
        )
        self.table.update_item(
            Key={"_id": str(target_id)},
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expression_names,
            ExpressionAttributeValues=expression_values,
        )
        return self.get(target_id)


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat()
    raise TypeError(f"unsupported timestamp value: {value!r}")


def _to_dict(item: Mapping[str, Any]) -> dict[str, Any]:
    from decimal import Decimal

    result = dict(item)
    result["id"] = result.pop("_id")
    if isinstance(result.get("check_interval_minutes"), Decimal):
        result["check_interval_minutes"] = int(result["check_interval_minutes"])
    return result


def _require_text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


def _require_positive_interval(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("check_interval_minutes must be a positive integer")


__all__ = ["DynamoDBMonitoringTargetRepository"]
