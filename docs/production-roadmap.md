# Production Roadmap — Conversion Tracker

Reference: `docs/production-plan.md`

This tracker covers the backend-only production-conversion work described in the
production plan. Every item starts unchecked; implementation should proceed as
separate, focused tasks on the `production` branch.

---

## P.0 Branch & infrastructure setup

- [x] P.0.1 Create the `production` branch from the current `main` branch.
- [x] P.0.2 Enable GitHub branch protection on both `main` and `production` (require PRs and prohibit direct pushes).

## P.1 Page-type schema consolidation

- [x] P.1.1 Update the rule-based classifier patterns to recognize and suggest only `BLOG`, `NEWS`, `PRICING`, `PRODUCTS`, `SERVICES`, and `PRESS`; collapse all other page types into `OTHER` and discard them.
- [x] P.1.2 Update the LLM fallback classifier prompt and instructions to use the same six-type schema and `OTHER` discard behavior.
- [x] P.1.3 Confirm the `change_type` mapping: `BLOG` → `NEW_BLOG`, `PRICING` → `PRICE_CHANGE`, `PRODUCTS` → existing `ProductListingProcessor` events, and `NEWS`/`SERVICES`/`PRESS` → generic `PAGE_UPDATE`.
- [x] P.1.4 Add the already-fetched page meta description to the production classifier input and prompt context.
- [x] P.1.5 Use bounded, configurable (`DISCOVERY_CLASSIFIER_BATCH_SIZE`) classifier batches with per-batch failure isolation and deterministic `OTHER`/discarded fallback.
- [x] P.1.6 Add one holistic, per-competitor second-pass audit over the full SUGGESTED list: discard only flagged redundant suggestions, persist informational missing-category flags, and degrade gracefully when the audit call fails.

## P.2 Remove simulation from production

- [x] P.2.1 Exclude `POST /api/monitoring-targets/<id>/simulate` from the `production` branch.
- [x] P.2.2 Remove or exclude simulation-only code paths from the `production` branch while preserving the real monitoring and change-detection paths.

## P.3 SQS ingestion

- [x] P.3.1 Add a standalone background worker process that long-polls the AWS SQS queue and calls the existing service layer without going through a Flask HTTP route or the internal scheduler.
- [x] P.3.2 Implement handling for the inbound message schema: `strategy_id`, `company_domain_id`, `company_url`, and informational `host` metadata, without filtering on `host`.
- [x] P.3.3 Implement find-or-create company/competitor logic keyed by `company_domain_id` and `company_url`, with the competitor scoped to the identified company.
- [x] P.3.4 Make message processing idempotent for SQS at-least-once delivery by reusing the existing 1.10 duplicate-handling pattern rather than introducing a separate deduplication mechanism.
- [x] P.3.5 Configure bounded retries and route messages that continue to fail to a Dead Letter Queue; confirm the AWS-side DLQ configuration or include it in implementation setup.
- [x] P.3.6 Configure SQS queue URL, region, and IAM credentials through environment variables, never hardcoding or logging credentials.

### P.3 handler/worker evidence (TON-42, 2026-09-11)

- `sqs_handler.py` validates and normalizes the four-field message schema, handles existing/new competitors through the service layer, and keeps both paths discovery/reconciliation-only.
- `sqs_worker.py` uses a 20-second long poll and deletes only successfully processed messages; malformed and failed messages remain for the AWS retry/DLQ policy.
- Real AWS verification confirmed `ap-southeast-2`, a 900-second visibility timeout, a configured DLQ with `maxReceiveCount=10`, valid-message acknowledgement, identical duplicate-handler state, and malformed-message redelivery after no acknowledgement. Temporary test Mongo rows and queue messages were cleaned up.

## P.3 follow-up: multi-competitor schema and Primary-strategy resolution (TON-44)

- [ ] P.3.7 Replace the inbound schema with `{company_domain_id, competitor_lst, host}`; drop `strategy_id`.
- [ ] P.3.8 Resolve competitors automatically when `competitor_lst` is empty, via the external RM `account_company` → `strategy_strategy` Primary-strategy lookup, host-routed (`dev` → `rm_dev_testing`, `prod` → `rm_pre_release`, default `dev`); skip quietly when no domain match, no Primary strategy, or zero usable URLs are found.
- [ ] P.3.9 Fan out a multi-competitor resolution into one child SQS message per competitor URL instead of processing them inline, to stay within the 900-second visibility timeout; process single-URL resolutions inline through the existing P.4 flow unchanged.

## P.4 Two-case processing logic

- [x] P.4.1 Implement the existing-competitor flow: check discovery freshness, re-run discovery only when the last run is at least 30 days old, apply automatic reconciliation, and otherwise skip directly to monitoring.
- [x] P.4.2 Implement the new-competitor first-run flow: create the record, run discovery, auto-activate the suggested pages, and establish an initial snapshot for each newly active target without creating a change.
- [x] P.4.3 Wire both flows into `monitor_target()` for fresh snapshots and change detection, relying on the existing hash-comparison behavior.

### P.3/P.4 prerequisite implementation (TON-41)

- [x] Add a `discovery_runs` repository query for the latest successful run per competitor; freshness continues to come from the existing run lifecycle rather than a second timestamp field.
- [x] Add the service-layer automatic discovery reconciliation entry point: run discovery, activate newly suggested targets, and history-aware deactivate targets no longer suggested.
- [x] Keep reconciliation itself snapshot-free. A first-run or stale SQS message hands newly active targets to the scheduler so discovery stays inside the 900-second visibility timeout. A fresh message does not: it skips discovery and reconciliation, then snapshots currently tracked pages inside the message. See the 2026-09-17 correction in `docs/production-plan.md`. A real Lyfe Marketing reconciliation completed in 41.17 seconds against the 900-second queue timeout and changed target state without creating snapshots or monitoring runs.

## P.5 Automatic tracking reconciliation

- [ ] P.5.1 Add a monthly discovery schedule for every competitor, in addition to on-demand re-discovery when an SQS message finds stale discovery data.
- [x] P.5.2 Automatically activate newly suggested pages using the existing 1.10 activation logic, including its liveness gate.
- [x] P.5.3 Automatically deactivate tracked pages no longer suggested by discovery using the existing 1.11 deactivation logic — deliberately **not** history-preserving against the DynamoDB backend (delete-on-deactivate; see production-plan.md 5.1) since there's no longer shared-database history to protect.

### P.5.2/P.5.3 DynamoDB-backend evidence (TON-45, 2026-09-17)

- Done only as far as P.6 required: making the *existing* `discover_and_reconcile()` activation/deactivation path (already shipped in P.3/P.4) work correctly against the DynamoDB target repository. P.5.1's monthly trigger is a separate, still-open concern — nothing about it was needed for P.6 and nothing here builds it.
- `discovery.service.activate_candidate`/`discard_candidate` now call `mark_activated()`/`mark_discarded()` instead of a raw field update; `discover_and_reconcile()`/`remove_candidate()` needed no code changes at all. Details in `docs/production-plan.md` 5.5.

## P.6 DynamoDB storage for monitoring targets and snapshots, RM MongoDB for changes (TON-45)

- [x] P.6.1 Run a pre-flight size check against the largest real compressed snapshot, including JD Sports' `/sale` page, and verify it stays safely below DynamoDB's 400KB per-item limit.
- [x] P.6.2 Configure `AWS_DYNAMODB_MONITORING_TARGETS_TABLE` / `AWS_DYNAMODB_SNAPSHOTS_TABLE` environment-based DynamoDB access, alongside the existing AWS SQS credential pattern.
- [x] P.6.3 Swap `monitoring_targets` persistence to DynamoDB: write only `SUGGESTED` rows (never `DISCARDED`), add the `competitor_id` GSI for per-competitor reconciliation lookups, use a table Scan for the scheduler's global due-for-check job, and delete a row (instead of soft-deactivating) when reconciliation stops suggesting it.
- [x] P.6.4 Swap snapshot persistence to DynamoDB behind the existing `snapshot/storage.py` abstraction, storing compressed content directly in the item and replacing local `.txt.gz` files/`storage_path` entirely.
- [x] P.6.5 Enable DynamoDB native TTL on the snapshots table with a 30-day expiry attribute so expired items are removed automatically.
- [x] P.6.6 Move `changes` persistence to a new collection (`competitors_changes`) in the external RM MongoDB database — fixed per deployment via a new `RM_HOST` env var (default `dev`), not per-message like the section 3 strategy lookup, since `ChangeService` is built once at process startup with no per-message context available; update change documents' snapshot references to the `(monitoring_target_id, captured_at)` pair instead of a single Mongo id.
- [x] P.6.7 Add a production scheduler process (`scheduler/scheduler_runner.py`) that actually runs `SchedulerService` against the DynamoDB target repository, and make `sqs_handler.py` only call `monitor_target()` inline for a `"skipped_fresh"` message — `"first_run"`/`"reconciled"` defer to this scheduler instead, closing the gap where neither the SQS handler nor anything else ever checked those targets.

### P.6 gap review fixes (TON-45, 2026-09-17)

An independent review found three real gaps between this tracker/`docs/production-plan.md` and the
shipped code, all now fixed:

1. **`sqs_handler.py` called `monitor_target()` unconditionally** for every action, including
   `"reconciled"` and `"first_run"` — reopening the exact visibility-timeout risk the 2026-09-17
   correction in `docs/production-plan.md`'s change log was written to avoid. Fixed: only
   `"skipped_fresh"` monitors inline now.
2. **Nothing ran `SchedulerService` against DynamoDB in production** — `SchedulerService.from_database()`
   still hardcoded the Mongo `MonitoringTargetRepository`, and no process called it at all. Fixed
   with P.6.7 above; `SchedulerService` itself needed zero code changes.
3. **Doc self-contradiction on `changes` routing** (section 5.3 vs 5.5) — resolution tracked
   separately as an open decision (see the P.6 follow-up discussion); not yet fixed in code.

### P.6 implementation evidence (TON-45, 2026-09-17)

Pre-flight check: the real, live JD Sports `/sale` page, fetched fresh and normalized/compressed
through the actual pipeline, came to 27,027 bytes — about 1/15th of the 400KB limit. Every new
DynamoDB/RM-Mongo repository was smoke-tested directly against the real, already-provisioned
infrastructure (not just fakes), including a real multi-item newest-first snapshot ordering check.
Full detail, including the two real bugs the live smoke tests caught (a `Decimal` type mismatch and
a `dict`-iteration bug in the generic DynamoDB update builder), is in `docs/production-plan.md`
section 5.5. `build_production_services()` and `sqs_worker.build_application_services()` were
verified to construct cleanly end-to-end against real infrastructure; the actual end-to-end pipeline
run (SQS message through to a persisted change) was deliberately deferred to right after this work,
per the agreed sequencing.
