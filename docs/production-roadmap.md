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

## P.2 Remove simulation from production

- [ ] P.2.1 Exclude `POST /api/monitoring-targets/<id>/simulate` from the `production` branch.
- [ ] P.2.2 Remove or exclude simulation-only code paths from the `production` branch while preserving the real monitoring and change-detection paths.

## P.3 SQS ingestion

- [ ] P.3.1 Add a standalone background worker process that long-polls the AWS SQS queue and calls the existing service layer without going through a Flask HTTP route or the internal scheduler.
- [ ] P.3.2 Implement handling for the inbound message schema: `strategy_id`, `company_domain_id`, `company_url`, and informational `host` metadata, without filtering on `host`.
- [ ] P.3.3 Implement find-or-create company/competitor logic keyed by `company_domain_id` and `company_url`, with the competitor scoped to the identified company.
- [ ] P.3.4 Make message processing idempotent for SQS at-least-once delivery by reusing the existing 1.10 duplicate-handling pattern rather than introducing a separate deduplication mechanism.
- [ ] P.3.5 Configure bounded retries and route messages that continue to fail to a Dead Letter Queue; confirm the AWS-side DLQ configuration or include it in implementation setup.
- [ ] P.3.6 Configure SQS queue URL, region, and IAM credentials through environment variables, never hardcoding or logging credentials.

## P.4 Two-case processing logic

- [ ] P.4.1 Implement the existing-competitor flow: check discovery freshness, re-run discovery only when the last run is at least 30 days old, apply automatic reconciliation, and otherwise skip directly to monitoring.
- [ ] P.4.2 Implement the new-competitor first-run flow: create the record, run discovery, auto-activate the suggested pages, and establish an initial snapshot for each newly active target without creating a change.
- [ ] P.4.3 Wire both flows into `monitor_target()` for fresh snapshots and change detection, relying on the existing hash-comparison behavior.

## P.5 Automatic tracking reconciliation

- [ ] P.5.1 Add a monthly discovery schedule for every competitor, in addition to on-demand re-discovery when an SQS message finds stale discovery data.
- [ ] P.5.2 Automatically activate newly suggested pages using the existing 1.10 activation logic, including its liveness gate.
- [ ] P.5.3 Automatically deactivate tracked pages no longer suggested by discovery using the existing 1.11 history-preserving deactivation logic.

## P.6 DynamoDB snapshot storage

- [ ] P.6.1 Run a pre-flight size check against the largest real compressed snapshot, including JD Sports' `/sale` page, and verify it stays safely below DynamoDB's 400KB per-item limit.
- [ ] P.6.2 Swap local snapshot persistence for DynamoDB behind the existing `snapshot/storage.py` abstraction.
- [ ] P.6.3 Configure DynamoDB native TTL with a 30-day expiry timestamp so expired snapshot items are removed automatically.
