# API Contract — Django Frontend ↔ Flask Backend

Source of truth for every request the frontend makes to the backend. Update this
file as each endpoint is finalized and freeze it before the Step 4 integration
pass.

Base URL (development): `http://localhost:5000/api`

The current PoC has no authentication boundary. The demo UI supplies a
`company_id` to scope reads and writes; requests without it retain the legacy
unscoped/compatibility behavior for backend verification scripts.

## Conventions

- All successful responses are JSON except `204 No Content` deletes.
- All error responses use exactly:

  ```json
  {"error": {"code": "not_found", "message": "competitor ... was not found"}}
  ```

- Validation errors return `400` with `code: "validation_error"`.
- Missing resources return `404` with `code: "not_found"`.
- State conflicts and duplicate resources return `409` with `code: "conflict"`.
  An in-progress monitoring claim uses the more specific `code:
  "already_running"`.
- Unexpected server failures return `500` with `code: "internal_error"` and
  do not expose a traceback.
- Timestamps are ISO 8601 UTC strings (`Z`).
- IDs are strings, including `competitor_id`, `monitoring_target_id`, and
  snapshot/change references.

## Companies

### `GET /companies`

List the two seeded PoC company identities for the selector.

- Response `200`:

  ```json
  [{"id", "name", "website_url", "created_at", "updated_at"}]
  ```

The application factory idempotently seeds `Marketing Eye`
(`marketingeye.com.au`) and `The Athletes Foot`
(`theathletesfoot.com.au`). They are labels only; companies do not have
independent monitoring logic.

## Competitors

### `GET /competitors`

List competitors. The optional `company_id` query parameter returns only
competitors explicitly assigned to that company. Unassigned competitors are
therefore excluded from a company-scoped response.

- Optional query: `company_id=`, `active=true|false`
- Response `200`:

  ```json
  [{"id", "company_id", "name", "website_url", "active", "created_at", "updated_at"}]
  ```

### `POST /competitors`

Create a competitor. Website-only competitor records are supported for now.

- Request: `{ "company_id": string?, "name": string, "website_url": string, "active": boolean? }`
- Response `201`: competitor object
- Duplicate `(company_id, website_url)` returns `409` when a company is supplied.

### `GET /competitors/<id>`

- Optional query: `company_id=`; when supplied, the competitor must belong to
  that company.
- Response `200`: competitor object
- Response `404`: standard error envelope

### `PATCH /competitors/<id>`

- Optional query: `company_id=` for scoped access.
- Request: one or more of `{ "name"?, "website_url"?, "active"?, "company_id"? }`
- Response `200`: updated competitor object

### `DELETE /competitors/<id>`

- Optional query: `company_id=` for scoped access.
- Response `204`
- Response `404` if the competitor is not in the current user scope.

## Candidates — Layer 1 review

Candidates and activated monitoring targets share the `monitoring_targets`
collection. A candidate is persisted with `active=false` until activation.

### `GET /competitors/<id>/candidates`

- Query: `company_id=`, `status=SUGGESTED|DISCARDED|ALL` (default: `SUGGESTED`)
- Response `200`:

  ```json
  [{
    "id", "competitor_id", "raw_url", "url", "page_type",
    "discovery_status", "classification_method", "active",
    "check_interval_minutes", "created_at", "updated_at"
  }]
  ```

`DISCARDED` rows remain queryable and are never hidden by deletion.

### `POST /competitors/<id>/candidates`

Add a manual candidate for later review (Step 1.3b).

- Query: `company_id=`; when supplied, the competitor must belong to that company.
- Request: `{ "url": string }`
- Response `201`: candidate with `discovery_status: "SUGGESTED"` and
  `classification_method: "MANUAL"`
- An exact existing URL is returned idempotently rather than inserted again.

### `POST /candidates/<id>/activate`

Promote a SUGGESTED candidate in place.

- Optional query: `company_id=` for scoped access.
- Response `200`: same row ID with `active: true` and
  `discovery_status: "ACTIVE"`
- DISCARDED or otherwise invalid candidate state returns `409`.

### `POST /candidates/<id>/discard`

Mark an unactivated candidate as `DISCARDED` without deleting it, so it remains
available through the discarded-candidate review view.

- Optional query: `company_id=` for scoped access.
- Response `200`: same row with `active: false` and
  `discovery_status: "DISCARDED"`
- Activated candidates return `409`.

### `PATCH /candidates/<id>`

Edit an unactivated candidate's URL.

- Optional query: `company_id=` for scoped access.
- Request: `{ "url": string }`
- Response `200`: updated candidate object
- Activated candidates return `409`.

### `DELETE /candidates/<id>`

- Optional query: `company_id=` for scoped access.
Remove a candidate through the existing history-aware service operation. This
is a destructive removal for a never-activated row (`204`); use the discard
endpoint when the review decision should preserve the row. An activated row
with history is deactivated in place and returned as `200`; its
`discovery_status` remains `ACTIVE` so history references remain valid.

## Monitoring targets

### `GET /monitoring-targets`

- Optional query: `company_id=`, `competitor_id=`. If `company_id` is supplied,
  only targets whose competitor is assigned to that company are returned.
- Response `200`:

  ```json
  [{
    "id", "competitor_id", "raw_url", "url", "page_type",
    "discovery_source", "discovery_status", "classification_method",
    "active", "check_interval_minutes", "last_checked_at",
    "last_changed_at", "created_at", "updated_at"
  }]
  ```

### `GET /monitoring-targets/<id>`

- Optional query: `company_id=` for scoped access.
- Response `200`: monitoring-target object
- Response `404`: standard error envelope

### `POST /monitoring-targets`

Create a user-selected Layer 2 target directly through the Step 1.10 service.
The liveness gate runs before persistence; page type is optional and is
rule-detected with `OTHER` as the fallback. The shared page-type interval
defaults are applied automatically.

- Request: `{ "company_id": string?, "competitor_id": string, "url": string, "page_type": string? }`
- Response `201`: active monitoring-target object with
  `discovery_status: "ACTIVE"` and `classification_method: "MANUAL"`
- Existing ACTIVE URL is returned unchanged; existing SUGGESTED/DISCARDED URL
  is liveness-checked and promoted in place.

### `PATCH /monitoring-targets/<id>`

- Optional query: `company_id=` for scoped access.
- Request: one or both of `{ "active"?: boolean, "check_interval_minutes"?: integer }`
- Response `200`: updated target object
- `active=true` also moves a review row to `discovery_status: "ACTIVE"` so
  the repository invariant cannot be violated.

### `DELETE /monitoring-targets/<id>`

- Optional query: `company_id=` for scoped access.
Apply the history-based Step 1.11 rule through the service layer.

- Response `204` after hard-delete or deactivation
- Response `404` if the target does not exist

## Changes / events

### `GET /changes`

Read the newest change feed. It never creates or mutates records.

- Optional query: `company_id=`, `competitor_id=`, `target_id=`, `since=<ISO 8601 UTC>`,
  `limit=1..100` (default `50`)
- Response `200`:

  ```json
  [{
    "id", "monitoring_target_id", "change_type", "summary",
    "detected_at", "status", "is_simulated"
  }]
  ```

### `GET /changes/<id>`

- Optional query: `company_id=` for scoped access.
- Response `200`: full change record, including
  `previous_snapshot_id`, `current_snapshot_id`, and `is_simulated`.
- Response `404`: standard error envelope

## Deferred API areas

- Social account endpoints remain deferred to Step 5.
- Monitoring-run and scheduler control endpoints are not exposed in Step 2;
  Step 1 services remain callable internally until a later API requirement.
  The PoC discovery-run status endpoint below is an exception used only to
  observe the long-running discovery trigger.

## PoC trigger actions

### `POST /competitors/<id>/discover`

Run the real Layer 1 discovery flow for the competitor and persist its normal
candidate results. Optional queries: `company_id=` for scoped access and
`run_id=` for a caller-supplied discovery lifecycle identifier. When `run_id`
is supplied, the backend persists `RUNNING` before source collection and
transitions that record to `SUCCESS` or `FAILED` when the synchronous work
finishes.

- Response `200`:

  ```json
  {"competitor_id", "candidates": [...], "summary": {"website_url",
  "raw_count", "normalized_count", "suggested_count", "discarded_count",
  "source_breakdown"}}
  ```

This remains synchronous inside Flask and can take several seconds—or up to
approximately 12 minutes for JD Sports AU—because it makes real HTTP crawl
requests and may call the LLM classifier. The frontend request may time out
while Flask continues running; when a `run_id` was supplied, poll the status
endpoint below rather than inferring completion from candidate-row counts.

### `GET /discovery-runs/<run_id>`

Read the persisted status of an HTTP-triggered discovery run. Optional query:
`company_id=`; when supplied, the run's competitor must belong to that
company.

- Response `200`:

  ```json
  {
    "id", "run_id", "competitor_id", "company_id",
    "status": "RUNNING|SUCCESS|FAILED",
    "started_at", "finished_at", "candidate_count",
    "summary", "error_message", "created_at", "updated_at"
  }
  ```

- Response `404`: standard error envelope

`SUCCESS` is authoritative even when `candidate_count` is unchanged from the
previous discovery run. `FAILED` exposes the backend's error message for the
frontend error state.

### `POST /monitoring-targets/<id>/simulate`

Run the persistence-enabled PoC simulation for an active target. Optional
`company_id` may be supplied as a query parameter or in the JSON body.

- Request: `{ "mutation_type": string?, "company_id": string? }`
- `mutation_type` is only used for `PRODUCT_LISTING` targets and may be
  `NEW_PRODUCT`, `PRODUCT_REMOVED`, or `PRICE_CHANGE`. When omitted, the
  product-listing simulation generates all three events.
- Response `200`:

  ```json
  {"monitoring_target_id", "page_type", "is_simulated": true,
  "previous_snapshot", "snapshot", "change", "changes"}
  ```

The endpoint calls the original read-only simulation helper first, then
persists a new snapshot and one or more change records with
`is_simulated: true`. It does not update the target's real monitoring
baseline. The next genuine `monitor_target` comparison explicitly excludes
simulated snapshots and uses the newest non-simulated snapshot.
