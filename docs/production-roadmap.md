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

## P.4 Two-case processing logic

- [ ] P.4.1 Implement the existing-competitor flow: check discovery freshness, re-run discovery only when the last run is at least 30 days old, apply automatic reconciliation, and otherwise skip directly to monitoring.
- [ ] P.4.2 Implement the new-competitor first-run flow: create the record, run discovery, auto-activate the suggested pages, and establish an initial snapshot for each newly active target without creating a change.
- [ ] P.4.3 Wire both flows into `monitor_target()` for fresh snapshots and change detection, relying on the existing hash-comparison behavior.

### P.3/P.4 prerequisite implementation (TON-41)

- [x] Add a `discovery_runs` repository query for the latest successful run per competitor; freshness continues to come from the existing run lifecycle rather than a second timestamp field.
- [x] Add the service-layer automatic discovery reconciliation entry point: run discovery, activate newly suggested targets, and history-aware deactivate targets no longer suggested.
- [x] Keep reconciliation deliberately snapshot-free. The SQS-triggered flow will hand newly active targets to the existing per-target scheduler on its next cycle, removing active-target snapshotting from the SQS visibility-timeout window. A real Lyfe Marketing run completed in 41.17 seconds against the 900-second queue timeout and changed target state without creating snapshots or monitoring runs.

## P.5 Automatic tracking reconciliation

- [ ] P.5.1 Add a monthly discovery schedule for every competitor, in addition to on-demand re-discovery when an SQS message finds stale discovery data.
- [ ] P.5.2 Automatically activate newly suggested pages using the existing 1.10 activation logic, including its liveness gate.
- [ ] P.5.3 Automatically deactivate tracked pages no longer suggested by discovery using the existing 1.11 history-preserving deactivation logic.

## P.6 DynamoDB snapshot storage

- [ ] P.6.1 Run a pre-flight size check against the largest real compressed snapshot, including JD Sports' `/sale` page, and verify it stays safely below DynamoDB's 400KB per-item limit.
- [ ] P.6.2 Swap local snapshot persistence for DynamoDB behind the existing `snapshot/storage.py` abstraction.
- [ ] P.6.3 Configure DynamoDB native TTL with a 30-day expiry timestamp so expired snapshot items are removed automatically.
