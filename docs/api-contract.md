# API Contract — Django Frontend ↔ Flask Backend

Source of truth for every request the frontend makes to the backend. Update this
file as each endpoint is finalized and freeze it before the Step 4 integration
pass.

Base URL (development): `http://localhost:5000/api`

The current PoC is single-user. No authentication header is required; the Flask
app scopes competitor CRUD to `APP_USER_ID` (default: `default-user`).

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

## Competitors

### `GET /competitors`

List competitors belonging to the current PoC user.

- Optional query: `active=true|false`
- Response `200`:

  ```json
  [{"id", "name", "website_url", "active", "created_at", "updated_at"}]
  ```

### `POST /competitors`

Create a competitor. Website-only competitor records are supported for now.

- Request: `{ "name": string, "website_url": string, "active": boolean? }`
- Response `201`: competitor object
- Duplicate `(APP_USER_ID, website_url)` returns `409`.

### `GET /competitors/<id>`

- Response `200`: competitor object
- Response `404`: standard error envelope

### `PATCH /competitors/<id>`

- Request: one or more of `{ "name"?, "website_url"?, "active"? }`
- Response `200`: updated competitor object

### `DELETE /competitors/<id>`

- Response `204`
- Response `404` if the competitor is not in the current user scope.

## Candidates — Layer 1 review

Candidates and activated monitoring targets share the `monitoring_targets`
collection. A candidate is persisted with `active=false` until activation.

### `GET /competitors/<id>/candidates`

- Query: `status=SUGGESTED|DISCARDED|ALL` (default: `SUGGESTED`)
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

- Request: `{ "url": string }`
- Response `201`: candidate with `discovery_status: "SUGGESTED"` and
  `classification_method: "MANUAL"`
- An exact existing URL is returned idempotently rather than inserted again.

### `POST /candidates/<id>/activate`

Promote a SUGGESTED candidate in place.

- Response `200`: same row ID with `active: true` and
  `discovery_status: "ACTIVE"`
- DISCARDED or otherwise invalid candidate state returns `409`.

### `POST /candidates/<id>/discard`

Mark an unactivated candidate as `DISCARDED` without deleting it, so it remains
available through the discarded-candidate review view.

- Response `200`: same row with `active: false` and
  `discovery_status: "DISCARDED"`
- Activated candidates return `409`.

### `PATCH /candidates/<id>`

Edit an unactivated candidate's URL.

- Request: `{ "url": string }`
- Response `200`: updated candidate object
- Activated candidates return `409`.

### `DELETE /candidates/<id>`

Remove a candidate through the existing history-aware service operation. This
is a destructive removal for a never-activated row (`204`); use the discard
endpoint when the review decision should preserve the row. An activated row
with history is deactivated in place and returned as `200`; its
`discovery_status` remains `ACTIVE` so history references remain valid.

## Monitoring targets

### `GET /monitoring-targets`

- Optional query: `competitor_id=`
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

- Response `200`: monitoring-target object
- Response `404`: standard error envelope

### `POST /monitoring-targets`

Create a user-selected Layer 2 target directly through the Step 1.10 service.
The liveness gate runs before persistence; page type is optional and is
rule-detected with `OTHER` as the fallback. The shared page-type interval
defaults are applied automatically.

- Request: `{ "competitor_id": string, "url": string, "page_type": string? }`
- Response `201`: active monitoring-target object with
  `discovery_status: "ACTIVE"` and `classification_method: "MANUAL"`
- Existing ACTIVE URL is returned unchanged; existing SUGGESTED/DISCARDED URL
  is liveness-checked and promoted in place.

### `PATCH /monitoring-targets/<id>`

- Request: one or both of `{ "active"?: boolean, "check_interval_minutes"?: integer }`
- Response `200`: updated target object
- `active=true` also moves a review row to `discovery_status: "ACTIVE"` so
  the repository invariant cannot be violated.

### `DELETE /monitoring-targets/<id>`

Apply the history-based Step 1.11 rule through the service layer.

- Response `204` after hard-delete or deactivation
- Response `404` if the target does not exist

## Changes / events

### `GET /changes`

Read the newest change feed. It never creates or mutates records.

- Optional query: `competitor_id=`, `target_id=`, `since=<ISO 8601 UTC>`,
  `limit=1..100` (default `50`)
- Response `200`:

  ```json
  [{
    "id", "monitoring_target_id", "change_type", "summary",
    "detected_at", "status"
  }]
  ```

### `GET /changes/<id>`

- Response `200`: full change record, including
  `previous_snapshot_id` and `current_snapshot_id`
- Response `404`: standard error envelope

## Deferred API areas

- Social account endpoints remain deferred to Step 5.
- Monitoring-run and scheduler control endpoints are not exposed in Step 2;
  Step 1 services remain callable internally until a later API requirement.
