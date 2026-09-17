# Production Plan — Architecture Differences from Dev

## Purpose
This documents how the production version diverges from the current dev/PoC version on `main`,
following supervisor feedback after a demo. Production is not a trimmed-down copy of dev — several
things dev has, production deliberately does not, and one core workflow (target selection) is
fully automated in production where dev has a human review step. This doc is the shared reference
for that divergence; implementation happens via separate, focused tasks after this is confirmed
accurate.

**Scope of this round: backend only.** Everything in this doc, and the implementation work that
follows from it, is backend-only for now. The frontend is explicitly excluded — not being built,
not being planned in detail here. It's a separate, later piece of work.

## Branch strategy
- `main` stays the ongoing dev branch — keeps everything currently built (simulation, all 21
  page types, manual candidate review UI, etc.) and remains where new features land first.
- `production` is a new branch, created off current `main`, then diverges via its own dedicated
  changes (subtractive and behavioral) described below.
- A feature graduates from dev to production deliberately (cherry-pick or controlled merge) once
  it's ready — production never silently drifts from or picks up unfinished dev work.
- Both branches should have GitHub branch protection enabled (require PRs, no direct pushes).

## 1. Page-type schema: 21 types → 6 + a discard bucket
Production only classifies and suggests these page types: `BLOG`, `NEWS`, `PRICING`, `PRODUCTS`,
`SERVICES`, `PRESS`. Everything else that dev currently has a dedicated type for (`CAREERS`,
`TEAM`, `CEO`, `ABOUT`, `CASE_STUDIES`, `SUCCESS_STORIES`, `TESTIMONIALS`, `REVIEWS`,
`INDUSTRIES`, `CONTACT`, `WORK`, `RESULTS`, `PORTFOLIO`, `PACKAGES`) collapses into `OTHER` and is
discarded, same mechanism as today, smaller target list.

Both the rule-based classifier's patterns and the LLM fallback classifier's prompt need updating
to only recognize/suggest the 6 core types.

`change_type` mapping stays mostly as-is: `BLOG`→`NEW_BLOG`, `PRICING`→`PRICE_CHANGE`, `PRODUCTS`→
handled by the existing `ProductListingProcessor` (`NEW_PRODUCT`/`PRODUCT_REMOVED`/`PRICE_CHANGE`).
`NEWS`, `SERVICES`, `PRESS` fall back to generic `PAGE_UPDATE` — confirmed acceptable for now, not
building dedicated types for these yet.

## 2. Simulation feature: dev-only, does not exist in production
The `POST /api/monitoring-targets/<id>/simulate` endpoint and the "Simulate a Change" UI button are
excluded entirely from the `production` branch. This was built as a genuinely separable add-on (its
own endpoint, its own frontend button, its own wrapper function on top of the real detection
logic), so removing it should be a clean subtraction, not a tangled refactor.

## 3. Production ingestion: AWS SQS instead of manual form submission
In production, new competitors are not added by a person filling in a form in the UI. An external
system publishes messages to an AWS SQS queue; our backend consumes them, processes them, and
writes the result to the database. Whatever reads the database afterward (a frontend, or anything
else) does so independently — this ingestion path has no synchronous response to any caller.

**Message schema** (revised, TON-44):
```
company_domain_id: marketingeye.com.au     # the CLIENT's own domain — the tenant identifier
competitor_lst: [<competitor url>, ...]    # explicit competitors to track; null/empty means
                                            # "resolve automatically" (see below)
host: dev                                  # selects which external RM database the automatic
                                            # resolution below reads from: dev -> rm_dev_testing,
                                            # prod -> rm_pre_release. Defaults to "dev" when
                                            # omitted. (Supersedes the earlier "informational
                                            # only, not a routing filter" note.)
```

`strategy_id` is removed from the schema — it was validated on receipt but never persisted
anywhere in our own collections, so dropping it required no data migration.

**Competitor resolution**: when `competitor_lst` is non-empty (after dropping any malformed
entries — the valid entries in the same list are still processed), it is used directly as the
tracked-competitor list. When it is empty or null, the competitors are resolved automatically from
the external RM platform's own MongoDB collections, replicating this reference lookup exactly (no
`strategy_status` filtering — selection is purely on `strategy_priority`):

```python
def get_primary_strategy_id_from_company_domain(self, company_domain_id, host_name=None):
    primary_strategy_id = None
    mongodb_conn = MongodbConnections.get_mongodb_conn_by_host(host_name)
    account_company = mongodb_conn['account_company']
    matched_document = account_company.find_one({'company_domain': company_domain_id})
    if not matched_document:
        return
    strategy_ids = matched_document.get('strategies_associated_id')
    for strategy_id in strategy_ids:
        strategy_doc = mongodb_conn['strategy_strategy'].find_one({'id': strategy_id})
        if not strategy_doc:
            continue
        if strategy_doc.get('strategy_priority') == 'Primary':
            primary_strategy_id = strategy_id
            break
    return primary_strategy_id
```

The competitor URLs are then the non-blank, deduplicated `website` values from that strategy's
`competitors_client` array. If `account_company` has no match for the domain, no associated
strategy is `Primary`, or the `Primary` strategy resolves to zero usable URLs, the message is
skipped quietly: acknowledged/finished with no discovery work, logged for visibility. No error, no
retry.

**Multi-competitor fan-out**: a message can resolve to more than one competitor (an explicit
multi-entry `competitor_lst`, or a Primary strategy with several `competitors_client`). Discovery
alone can take close to 12 minutes for a large competitor against the queue's 900-second visibility
timeout, so running discovery for several competitors sequentially inside one message risks that
timeout. A resolved list of exactly one URL is processed inline through the flow below. A resolved
list of two or more is not processed inline at all — the handler re-publishes one child message per
URL (same schema, `competitor_lst` narrowed to that single URL) and acknowledges the original
message immediately. Each child then gets its own full visibility window through the same
single-competitor flow, with failure isolation for free: one competitor's redelivery never touches
the others. This requires `sqs:SendMessage` IAM permission on the worker in addition to the
existing receive/delete permissions.

**Architecture**: a new, standalone background worker process — not a Flask HTTP route —
continuously polls the SQS queue (long-polling via boto3's SQS client is the standard approach).
This is a new kind of caller into the existing service layer, following the same
routes→service→repository layering already established: the worker calls the same
company/competitor/discovery/reconciliation service functions already established in the
application. The SQS message flow calls `discover_and_reconcile()` only when discovery is
missing or stale. **It never calls `monitor_target()` for a `"first_run"` or `"reconciled"`
message** — both already spent the message's time budget on discovery, so calling
`monitor_target()` for every tracked page too would risk the same 900-second visibility timeout
discovery alone is already close to. Only a `"skipped_fresh"` message (which did no discovery at
all) calls `monitor_target()` inline, for each currently tracked page.

**This requires a second, standalone production process — the scheduler
(`scheduler/scheduler_runner.py`)** — deployed and run continuously alongside the SQS worker, not
instead of it. It is what actually checks a `"first_run"`/`"reconciled"` message's targets (and
every other tracked page, on its own `check_interval_minutes`) once the SQS worker has moved on.
Without it running, those targets are never checked at all. `SchedulerService` itself needed no
DynamoDB-specific code: it only calls `target_repository.list_active_targets()` with no
competitor_id (a full table Scan, already exactly the tracked set per 5.1) and reads
`id`/`check_interval_minutes`/`last_checked_at` off whatever comes back.

**Processing logic on receiving a message** — two cases. This logic runs once per resolved
competitor URL, i.e. after the resolution/fan-out step above has reduced the message to exactly one
competitor:

1. **Competitor already exists** (matched by `company_domain_id` + the resolved competitor URL):
   - Check when discovery last ran for this competitor (reuse the existing discovery-run
     timestamp tracking).
   - If discovery is stale (≥ 30 days, same threshold as the monthly cadence in section 4):
     re-run discovery, apply the auto-activate/auto-deactivate reconciliation from section 4,
     then finish the SQS message after reconciliation. Do not snapshot inside this message.
     Discovery alone can approach the 900-second visibility timeout, so the scheduler snapshots
     those targets on its next cycle.
   - If discovery is fresh (< 30 days): skip discovery and reconciliation, then still snapshot
     every currently tracked page by calling `monitor_target()` before finishing the message.
     A successful fetch always stores a snapshot. A change is created only when the new content
     hash differs from the previous snapshot. This message has no discovery work, so the snapshot
     pass is its job rather than being deferred to the scheduler.

2. **Competitor does not exist yet** (first run):
   - Create the competitor record, scoped to the company identified by `company_domain_id`.
   - Run discovery, auto-activate the suggested pages (section 4's reconciliation logic, applied
     to this initial suggested set), then finish the SQS message.
   - No initial snapshot is taken synchronously. The scheduler picks up newly-active targets on
     its next cycle and calls `monitor_target()`. Since there is no previous snapshot yet, no
     change can be (or should be) detected on that first scheduled run; the next scheduler run
     can detect a real change against the baseline.

**Visibility-timeout boundary**: the queue's fixed visibility timeout is 900 seconds. Discovery
alone has been observed to take close to 12 minutes for a large competitor, and synchronously
snapshotting every active target on top of that discovery would add further variable work to the
same message. A first-run or stale message therefore ends after discovery and reconciliation, and
leaves snapshots to the scheduler. That split does not apply to a fresh message: it does no
discovery, so it must snapshot its currently tracked pages before it finishes. A real
reconciliation run completed in 41.17 seconds without snapshots, leaving a substantial margin
under the current timeout when discovery is the work being done.

**This coexists with the existing internal per-target scheduler (1.9), it does not replace it.**
The scheduler keeps running independently on each target's own `check_interval_minutes`. SQS
triggers discovery and reconciliation only when the competitor is new or discovery is stale.
A fresh existing competitor is snapshot-only inside the message. Newly-activated targets from a
first-run or stale message are picked up by the scheduler on its next cycle, which remains
responsible for their first snapshot and later change detection.
The concurrency guard already built in 1.8 (atomic duplicate-run prevention) continues to protect
scheduler monitoring runs and any other monitor attempts — no new protection is needed here.

**Idempotency requirement**: SQS has at-least-once delivery — the same message can occasionally
arrive more than once. Processing the same `company_domain_id` + `company_url` pair twice must not
create a duplicate competitor or double-trigger discovery/reconciliation beyond what the logic
above already produces. Reuse the same duplicate-handling logic already built for candidates (1.10) —
extend that pattern to inbound queue messages, don't build a second, separate deduplication
mechanism.

**Failure handling**: a message that fails to process (malformed schema, invalid domain,
discovery error) should not be silently dropped or retried forever. Standard practice: after a
bounded number of retries, route it to a Dead Letter Queue for inspection — confirm whether this
is already configured on the AWS side, or needs to be planned as part of implementation.

**Credentials**: AWS SQS access (queue URL, region, IAM credentials) follows the same pattern as
existing MongoDB/OpenAI credentials — environment-variable based, never hardcoded, never logged.
The external RM database lookup follows the same pattern: `RM_MONGODB_URI` (falls back to
`MONGODB_URI` when unset, since it may be the same cluster) plus `RM_MONGODB_DATABASE_DEV`
(default `rm_dev_testing`) and `RM_MONGODB_DATABASE_PROD` (default `rm_pre_release`) selected by
the message's `host` field.

## 4. No manual target selection — fully automatic tracking
This is the biggest behavioral difference from dev.

**What disappears**: the entire Discovery review UI (SUGGESTED/ACTIVE/DISCARDED tabs, Activate/
Discard/"Activate anyway"/manual-add buttons) does not exist in production. There is no human
review step for which pages get tracked.

**What happens instead**: discovery runs automatically once a month per competitor (in addition to
the on-demand staleness-triggered re-discovery described in section 3) — whatever the classifier
suggests (among the 6 core types) becomes the tracked set directly, with no manual activation step.

**Reconciliation policy** (confirmed): when a re-discovery run no longer suggests a page that's
currently being tracked, that page is automatically deactivated — reusing the existing 1.11
deactivate-with-history-preserved logic. Newly-suggested pages are automatically activated —
reusing the existing 1.10 activation logic (liveness gate included).

**Because there's no human safety net anymore, classification precision matters more than it did
in dev.** The mechanisms that already exist and have already caught real mistakes — the liveness
gate, the index-vs-item exclusion patterns — carry over directly and become more load-bearing, not
less. Any future classification changes for production should be held to a higher precision bar
than dev changes, given nothing catches a mistake before it goes live.

**Frontend is out of scope for this round** (see scope note above) — noting only for later
reference that production's eventual frontend would only need two of dev's four screens (the
competitors dashboard and the changes feed, since discovery-review and simulate don't apply to
production), not something to build now.

## 5. Storage layer: DynamoDB for monitoring targets and snapshots, RM MongoDB for changes (TON-45)
This replaces the earlier "snapshot storage" section with the full, confirmed split of where each
piece of state lives in production. Only three things change persistence; everything else
(`companies`, `competitors`, `monitoring_runs`, `discovery_runs`) keeps living in our own MongoDB
exactly as it does today — no schema or backend change for those collections in this round.

| Data | Dev (Mongo) | Production |
| --- | --- | --- |
| Tracked pages (`monitoring_targets`) | `monitoring_targets` collection, `active`/`discovery_status` lifecycle | DynamoDB table `AWS_DYNAMODB_MONITORING_TARGETS_TABLE` (`competitors_analysis_monitoring_targets`) |
| Snapshot content + metadata | `snapshots` collection + local `.txt.gz` files | DynamoDB table `AWS_DYNAMODB_SNAPSHOTS_TABLE` (`competitors_analysys_snapshots`), content included in the item |
| Detected changes | `changes` collection, same database as everything else | A new collection (`competitors_changes`) in the external RM database, selected once per deployment via `RM_HOST` (not per message — see 5.3) |
| `companies`, `competitors`, `monitoring_runs`, `discovery_runs` | our own MongoDB | unchanged — still our own MongoDB |

### 5.1 Monitoring targets: DynamoDB, `SUGGESTED`-only, presence means tracked
Dev's `monitoring_targets` collection double-duties as both the candidate review list (SUGGESTED/
DISCARDED) and the finalized monitored set (`active`/`discovery_status=ACTIVE`). Production only
ever needs the second half of that — pages actually being watched — so the DynamoDB table is
deliberately narrower:

- Only rows with `discovery_status = "SUGGESTED"` (the label the rule-based/LLM classifier already
  produces) are written. `DISCARDED` candidates are never written to DynamoDB at all, to avoid
  paying to store rows production has no reviewer to look at.
- A row's mere presence in the table means it is currently tracked — there is no separate
  `active` boolean or `ACTIVE` status to maintain in DynamoDB the way dev tracks it in Mongo.
- **Deactivation means deletion.** When reconciliation (section 4) decides a page is no longer
  suggested, its DynamoDB row is deleted outright, not soft-deactivated with a flag. This is a
  deliberate divergence from dev's 1.11 "deactivate, don't hard-delete" rule: dev preserves
  deactivated rows because Mongo also holds the change/snapshot history that references them in
  the same database, but production's history (see 5.3) no longer lives in the same store, so
  there is nothing left referencing a production `monitoring_targets` row once it stops being
  tracked.

**Key schema** (already provisioned, confirmed via `describe-table`): partition key `_id` (string)
only, no secondary indexes, TTL disabled (not needed here — unlike snapshots, a tracked target
doesn't expire on a timer, it's removed by reconciliation). This only supports point lookups by id,
which isn't enough on its own:

- **Discovery reconciliation** needs "every target currently tracked for competitor X," to compare
  against a fresh discovery run. This needs a new **Global Secondary Index keyed by `competitor_id`**
  — the one addition to the table's indexing.
- **The scheduler** needs "every tracked target, across every competitor, due for a check." Since
  every row in the table is already tracked (nothing else is ever written here), this is served by
  a plain **table Scan** — there's no `active`/`discovery_status` filter left to apply, only the
  same due-by-`last_checked_at` check the scheduler already does in Python today. At the data
  volumes this system operates at, a Scan is simple and cheap; it can be revisited if the tracked
  set grows large enough for that to change.

**Field mapping**:

| Field (Mongo today) | Type today | After migration | Notes |
| --- | --- | --- | --- |
| `_id` | ObjectId, Mongo-generated | `_id` (String) | DynamoDB doesn't auto-generate ids; minted ourselves before every `PutItem`, in Mongo ObjectId *format*, just stringified, so nothing downstream has to care the id "looks different." |
| `competitor_id` | ObjectId | `competitor_id` (String) | Same value, stringified — the competitor itself is unaffected and still lives in Mongo. |
| `raw_url`, `url`, `page_type`, `discovery_source`, `classification_method`, `check_interval_minutes`, `last_checked_at`, `last_changed_at` | as today | unchanged, same meaning | Timestamps become ISO-8601 strings (DynamoDB has no native datetime type). |
| `discovery_status` | `SUGGESTED`/`ACTIVE`/`DISCARDED` | always `"SUGGESTED"` | `DISCARDED` rows are never written. Every row that exists is tracked, so this value never varies — kept only as a label of how it got here (classifier output), not a lifecycle. |
| `active` | boolean | **dropped** | With "row exists = tracked," this flag would always be `true` for any row you could find — redundant, so it isn't stored. |
| `created_at`, `updated_at` | datetime | ISO-8601 strings | Same meaning. |

How the operations change: "activate a newly-suggested page" (reconciliation) becomes a `PutItem`
for a row that didn't exist before; "deactivate a page no longer suggested" becomes a `DeleteItem`,
not a flag flip; "list targets for competitor X" becomes a `Query` against the new GSI instead of a
Mongo filter; "list everything due for a check" becomes a `Scan` followed by the same Python
due-time check that already runs today.

### 5.2 Snapshots: DynamoDB, content included in the item, 30-day TTL
**Key schema** (already provisioned): partition key `monitoring_target_id`, sort key `captured_at`
(string) — this already matches the exact access pattern dev uses today (`list_for_target`, newest
first), so no new index is needed here.

Snapshot **content itself** (not just metadata) moves into the DynamoDB item as the compressed
bytes, replacing local `.txt.gz` files and the `storage_path` pointer entirely — confirmed plain
DynamoDB, not a DynamoDB+S3 hybrid, accepting the 400KB-per-item limit.

**Pre-flight check needed before implementation**: verify the largest real compressed snapshot
(JD Sports' `/sale` page is the largest known example) stays safely under 400KB. Cheap to check now,
expensive to discover as a production incident later.

**TTL**: the table's TTL is currently disabled and needs to be turned on as part of implementation,
using an epoch-seconds expiry attribute (proposed name: `expires_at`) computed as
`captured_at + 30 days`. AWS then auto-deletes expired items with no custom cleanup job needed.

The existing snapshot storage abstraction (`snapshot/storage.py`) was built with a pluggable
backend in mind from the start (spec always anticipated moving off local storage) — swapping the
backend should be a contained change against that existing interface, not a rewrite.

**Field mapping**:

| Field (Mongo today) | Type today | After migration | Notes |
| --- | --- | --- | --- |
| `_id` | ObjectId | **dropped entirely** | Nothing ever needs to look up a snapshot by one flat id — every caller already has both `monitoring_target_id` and `captured_at` in hand. The table's real key replaces it. |
| `monitoring_target_id` | ObjectId | `monitoring_target_id` (String) — partition key | Now a DynamoDB target id, stringified. |
| `captured_at` | datetime | `captured_at` (String, ISO-8601) — sort key | Already provisioned this way; gives a native `Query` for "this target's history, newest first," no separate index needed. |
| `content_hash`, `content_size`, `fetch_method`, `http_status` | as today | unchanged | |
| `storage_path` (pointer to a local `.txt.gz` file) | string | **replaced by `content`** (Binary — the actual gzip bytes) | The real substance of the move: content lives *in* the item now, not on disk. |
| `created_at` / `updated_at` | both stored | just `created_at` kept | Snapshots are never modified after creation, so the two were always identical — one is redundant. |
| *(new)* | — | `expires_at` (Number, epoch seconds) | The TTL attribute described above. |
| `is_simulated` | legacy/optional | **dropped** | Production never creates simulated snapshots (section 2), so this never applies. |

How the operations change: `create()` becomes one `PutItem` carrying metadata and content together;
fetching one snapshot becomes `GetItem(monitoring_target_id, captured_at)` instead of a bare-id
lookup; `list_for_target()` becomes a `Query` on the table's own primary key
(`ScanIndexForward=False` for newest-first) — functionally identical to today's Mongo sort, just
native to the table instead of a secondary index.

### 5.3 Changes: a new collection in the external RM MongoDB database
The `changes` collection is the one piece of history that still needs a durable, queryable store
(it's the actual client-facing result), but it no longer lives alongside `monitoring_targets`/
`snapshots` since those moved to DynamoDB. It moves to a **new collection in the external RM
database** (`competitors_changes`).

**Routing is fixed per deployment, not per message** (confirmed, TON-45 gap review — this
deliberately diverges from the strategy lookup's per-message `host` routing in section 3): a new
`RM_HOST` environment variable (default `"dev"`) selects `rm_dev_testing` or `rm_pre_release`
once, when the worker process starts, via the same `rm_mongo_settings_for_host()` connection
helper the strategy lookup already uses. This is not a simplification made for convenience — after
the P.6 gap-review fix, most monitoring (and therefore most change creation) happens via the
scheduler's own tick, not inline inside an SQS message, and the scheduler has no per-message `host`
to route by at all; only a per-deployment setting can cover both the SQS-triggered path and the
scheduler-triggered path consistently. A real deployment has a dev worker pointed at a dev queue
and a prod worker pointed at a prod queue, so this matches how the two would actually be run, and
each worker only ever needs to know its own `RM_HOST` once.

**Reference shape**: dev's `changes` documents reference `monitoring_target_id`,
`previous_snapshot_id`, and `current_snapshot_id` as single Mongo ObjectIds. DynamoDB's snapshot
table has no single opaque id — a snapshot is identified by the pair `(monitoring_target_id,
captured_at)` — so a production change document's snapshot references become that same pair
(e.g. `{"monitoring_target_id": ..., "captured_at": ...}`) instead of one flat id string. This lets
anything holding a change record fetch the real snapshot directly from DynamoDB with a plain
`GetItem`, with no extra index required.

This move is far less disruptive than 5.1/5.2 — it's still MongoDB, just a different database, so
every existing query capability (the `$in` filter, the `since` range filter, the narrative-backfill
query, the index) keeps working unchanged. Only two fields actually change shape:

| Field | Today | After migration |
| --- | --- | --- |
| `monitoring_target_id` | ObjectId | plain string (the DynamoDB target id) |
| `previous_snapshot_id` / `current_snapshot_id` | single ObjectId each | replaced by `previous_snapshot` / `current_snapshot`, each an embedded `{"monitoring_target_id": ..., "captured_at": ...}` pair |
| `detected_at`, `change_type`, `summary`, `narrative_summary`, `detected_url`, `status`, `created_at`, `updated_at` | as today | unchanged |
| `is_simulated` | legacy/optional | dropped (production never simulates, same reasoning as 5.2) |

### 5.4 The one near-ripple in a collection that isn't moving: `monitoring_runs`
`monitoring_runs` (the concurrency guard that prevents two monitoring checks running on the same
target at once) stays in our own MongoDB, unchanged as a collection. Its repository
(`MonitoringRunRepository`) forces `monitoring_target_id` through `to_object_id()` on every
read/write and in one of its unique indexes, which would break once that field holds a DynamoDB
target id instead of a genuine Mongo ObjectId — **except** DynamoDB target ids are deliberately
minted in valid Mongo ObjectId *format* (`str(ObjectId())`, see 5.1's field mapping), purely so this
kind of cross-reference keeps round-tripping through `to_object_id()`/`serialize_document()`
unchanged. No code change was needed here after all; this is called out explicitly so the reason
isn't a coincidence someone has to rediscover later. `companies`, `competitors`, and
`discovery_runs` were checked for the same issue and none of them store a `monitoring_target_id`
reference at all, so they're genuinely untouched.

### 5.5 Implementation evidence (TON-45, 2026-09-17)

Implemented on `feature/p6-dynamodb-storage` (off `feature/p3-multi-competitor-fanout`, which holds
the unmerged TON-44 work this depends on for the RM Mongo connection helper).

- **New modules**: `database/dynamodb_connection.py` (env config + boto3 client/resource
  construction), `website_monitoring/dynamodb_repository.py` (`DynamoDBMonitoringTargetRepository`),
  `snapshot/dynamodb_service.py` (`DynamoDBSnapshotService`, content + metadata in one item),
  `change_detection/rm_repository.py` (`RmChangeRepository`, subclasses the existing
  `ChangeRepository` — only `create()` differs), `scheduler/production_services.py`
  (`build_production_services()`, the full production wiring).
- **Necessary-for-P.6 slice of P.5** (not the monthly schedule, P.5.1, which remains open):
  `discovery.service.activate_candidate`/`discard_candidate` now call new
  `mark_activated()`/`mark_discarded()` repository methods instead of a raw `update()` with
  `active`/`discovery_status` fields — the Mongo repository's versions are thin, behavior-preserving
  wrappers around today's exact update calls; the DynamoDB repository's versions implement the real
  presence-based/delete-on-discard semantics. `discover_and_reconcile()` and `remove_candidate()`
  needed no changes at all: `_is_activated()` naturally evaluates `False` for every DynamoDB target
  (no `active` field, `discovery_status` never `"ACTIVE"`), which happens to route `remove_candidate`
  straight to its existing hard-delete branch — exactly the confirmed "deactivate means delete" rule,
  for a different reason than why it was originally written that way.
- **Two small injectable hooks**, both defaulting to today's exact behavior (zero change for
  dev/Mongo): `MonitoringRunService.active_target_check` (replaces the hardcoded
  `active=True and discovery_status="ACTIVE"` check, which would reject every DynamoDB target
  otherwise) and `ChangeService.snapshot_reference_extractor` (replaces the hardcoded single-id
  extraction, since a DynamoDB snapshot has no single id — only the `{monitoring_target_id,
  captured_at}` pair).
- **`RM_HOST`** (new env var, default `"dev"`): which RM database the *changes* repository writes to
  is a fixed, per-deployment choice resolved once at process startup, not a per-message one — unlike
  the strategy lookup's `host` field, `ChangeService`/`MonitoringRunService` are built once per
  process and the scheduler calls `monitor_target()` independently of SQS entirely, so there is no
  per-message context available to route by at that point.
- **Real-infrastructure verification**: every new piece was smoke-tested directly against the real,
  already-provisioned DynamoDB tables and the real `rm_dev_testing` database (not just fakes) —
  create/get/GSI-query/scan/update/delete on both DynamoDB tables, TTL attribute computation,
  newest-first snapshot ordering, and create/get/list/delete on the RM Mongo changes collection.
  This caught two real bugs a mocked unit test would have missed: DynamoDB's resource API returns
  `Decimal` for every Number attribute (needed explicit `int()` conversion back), and a
  `dict`-iteration bug in the generic `update_item` builder (`enumerate(values)` iterates a dict's
  *keys*, not its values). `build_production_services()` and `sqs_worker.build_application_services()`
  were also verified to construct cleanly against real infrastructure.
- **Not done in this round**: the actual end-to-end pipeline (SQS message → discovery/reconciliation
  → scheduler → snapshot → change) has not been exercised live as one continuous flow against the
  new storage — that was deliberately deferred to right after this work, per the agreed sequencing.
  `live_sqs_verification.py`/`live_p4_verification.py` were left untouched and still exercise the
  Mongo-only graph via `create_app(...)`, not the new DynamoDB/RM-Mongo graph.

## Explicit assumptions to confirm
- "Candidate pages" in section 3's processing logic means currently-tracked/active pages for that
  competitor, not raw undecided SUGGESTED/DISCARDED candidates — snapshotting only applies to
  pages actually being monitored.
- Production starts from a fresh, empty database — this is an architecture/branch change, not a
  data migration task. None of the existing dev/PoC data (Brown Bag, Elevation, JD test artifacts,
  Marketing Eye/The Athletes Foot demo data) needs to move into production.
- The "company" concept (client-scoping, e.g. Marketing Eye / The Athletes Foot) is assumed to
  carry forward as production's real multi-tenant foundation, keyed by domain per section 3 —
  but real authentication/access control for production is NOT addressed by this feedback and
  remains a separate, open question.

## Explicitly out of scope for this doc
- The frontend, entirely — this round is backend-only (see scope note in Purpose)
- Production hosting/infrastructure setup (AWS account, IAM, deployment pipeline/CI) beyond the
  SQS consumer itself
- Authentication and real multi-tenant access control
- Billing
- Whether a manual "force re-discovery now" trigger should also exist alongside the monthly
  schedule for admin/ops use — reasonable to include, not mandated by this doc

## Change log
- 2026-09-11 — Updated section 3 to reflect the decoupled SQS flow: discovery/reconciliation
  finishes the message, while the existing scheduler owns snapshots. This avoids consuming the
  900-second visibility-timeout margin with variable snapshot work; a real reconciliation run
  completed in 41.17 seconds without snapshots. Superseded for the fresh path by the 2026-09-17
  correction below: a message whose discovery is under 30 days still snapshots inside SQS.
- 2026-09-17 — Corrected section 3. An existing competitor whose last successful discovery is
  under 30 days skips discovery and reconciliation, but the SQS message must call
  `monitor_target()` and snapshot every currently tracked page. First-run and stale messages
  still leave snapshots to the scheduler, because discovery already consumes the
  visibility-timeout margin.
- 2026-09-17 (TON-44) — Replaced the `{strategy_id, company_domain_id, company_url, host}` schema
  with `{company_domain_id, competitor_lst, host}`. Added automatic competitor resolution via the
  external RM platform's `account_company`/`strategy_strategy` collections (Primary-strategy
  lookup) when `competitor_lst` is empty, host-routed to `rm_dev_testing`/`rm_pre_release`. Added
  fan-out to one competitor per message when resolution yields more than one URL, to keep every
  message's discovery work inside the 900-second visibility timeout.
- 2026-09-17 (TON-45) — Rewrote section 5: `monitoring_targets` and `snapshots` move to two
  already-provisioned DynamoDB tables (`AWS_DYNAMODB_MONITORING_TARGETS_TABLE`,
  `AWS_DYNAMODB_SNAPSHOTS_TABLE`); `changes` moves to a new collection in the external RM MongoDB
  database instead of our own; `companies`/`competitors`/`monitoring_runs`/`discovery_runs` are
  unaffected. Confirmed: DynamoDB `monitoring_targets` only ever stores `SUGGESTED` rows (no
  `DISCARDED` rows, ever), presence in the table means tracked, and "deactivate" now means deleting
  the row rather than flipping a flag.
- 2026-09-17 (TON-45) — Added a field-by-field mapping table to each of 5.1/5.2/5.3 (old Mongo
  field → new DynamoDB/RM-Mongo field, with the reasoning for each drop/rename), and a new 5.4
  documenting that `monitoring_runs` needs a code change (relaxing its `to_object_id()` calls on
  `monitoring_target_id`) even though the collection itself doesn't move; `companies`, `competitors`,
  and `discovery_runs` were checked and confirmed to have no such reference.
- 2026-09-17 (TON-45 gap review) — Fixed three real gaps between this doc and the shipped code,
  caught by an independent review: (1) `sqs_handler.py` was still calling `monitor_target()`
  unconditionally for every action, including `"reconciled"` and `"first_run"` — contradicting the
  2026-09-17 correction above and reopening the exact visibility-timeout risk that correction
  existed to avoid; fixed by only calling it for `"skipped_fresh"`. (2) `SchedulerService` was
  never wired to run against DynamoDB at all in production — the doc assumed a scheduler was
  catching first-run/stale-rediscovery targets that, in practice, nothing was checking; fixed with
  `scheduler/scheduler_runner.py`, a new production process. `SchedulerService` itself needed no
  changes — its Mongo-specific behavior was in `MonitoringTargetRepository`'s query, not in
  `SchedulerService`. (3) `docs/production-plan.md` 5.3/the summary table still described `changes`
  as host-routed like the strategy lookup, contradicting 5.5's `RM_HOST` (fixed-per-deployment)
  description.
- 2026-09-17 (TON-45 gap review, resolved) — Gap 4 resolved: `RM_HOST` fixed-per-deployment is the
  confirmed design (Option A of three considered), not just an implementation shortcut — after the
  gap-review fix above, most change creation happens via the scheduler's own tick, which has no
  per-message `host` at all, so only a per-deployment setting can route both the SQS-triggered and
  scheduler-triggered paths consistently. Section 5.3 and the summary table above were corrected to
  match; no code change was needed since `RM_HOST` was already implemented this way.

---

## Deliverable
- `docs/production-plan.md` created with the content above
- No code changes
