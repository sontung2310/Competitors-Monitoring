# API Contract — Django Frontend ↔ Flask Backend

Source of truth for every request the frontend makes to the backend. Update this
file as each endpoint is finalized (roadmap Step 2). Freeze it before Step 4
(integration pass) — after that, changes here require updating both agents'
code in the same commit.

Base URL (dev): `http://localhost:5000/api`

---

## Competitors

### `GET /competitors`
List all competitors for the current user.
- Response `200`: `[{ id, name, website_url, active, created_at }]`

### `POST /competitors`
- Request: `{ name, website_url }`
- Response `201`: `{ id, name, website_url, active, created_at }`

### `GET /competitors/<id>`
- Response `200`: `{ id, name, website_url, active, created_at, updated_at }`
- Response `404`: `{ error: "not_found" }`

### `PATCH /competitors/<id>`
- Request: `{ name?, website_url?, active? }`
- Response `200`: updated competitor object

### `DELETE /competitors/<id>`
- Response `204`

---

## Candidates (Layer 1 discovery review)

### `GET /competitors/<id>/candidates`
- Query: `?status=SUGGESTED|DISCARDED` (default: `SUGGESTED`)
- Response `200`: `[{ id, raw_url, url, page_type, discovery_status, classification_method }]`

### `POST /competitors/<id>/candidates`
Manual add.
- Request: `{ url, page_type? }`
- Response `201`: candidate object, `discovery_status: "MANUAL"`

### `PATCH /candidates/<id>`
Activate, edit, or discard.
- Request: `{ discovery_status?, url?, page_type? }`
- Response `200`: updated candidate object

### `DELETE /candidates/<id>`
Only for candidates with no monitoring history (see specs.md monitoring_targets note).
- Response `204`

---

## Monitoring Targets

### `GET /monitoring-targets`
- Query: `?competitor_id=`
- Response `200`: `[{ id, competitor_id, url, page_type, active, check_interval_minutes, last_checked_at, last_changed_at }]`

### `POST /monitoring-targets`
- Request: `{ competitor_id, url, page_type, check_interval_minutes }`
- Response `201`: monitoring target object

### `PATCH /monitoring-targets/<id>`
- Request: `{ active?, check_interval_minutes? }`
- Response `200`: updated object

### `DELETE /monitoring-targets/<id>`
Deactivates instead of deleting if snapshot/change history exists (see specs.md).
- Response `204`

---

## Changes / Events

### `GET /changes`
Latest updates feed for the dashboard.
- Query: `?competitor_id=&since=&limit=`
- Response `200`: `[{ id, monitoring_target_id, change_type, summary, detected_at, status }]`

### `GET /changes/<id>`
- Response `200`: full change record including `previous_snapshot_id`, `current_snapshot_id`

---

## Conventions

- All error responses: `{ error: "<code>", message: "<human readable>" }`
- Timestamps: ISO 8601 UTC
- Pagination (once needed): `?page=&page_size=`, response wraps in `{ items, total, page }`

## TODO (fill in as Step 2 progresses)
- [ ] Social account endpoints (Step 5)
- [ ] Auth/session shape (currently single-user PoC, no auth header required)
