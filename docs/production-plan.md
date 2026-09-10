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

**Message schema**:
```
strategy_id: 1              # fixed for now, forward-looking extensibility field
company_domain_id: marketingeye.com.au   # the CLIENT's own domain — the tenant identifier
company_url: <competitor's website>       # the competitor to add and start tracking
host: dev                                  # informational metadata only, not a routing filter —
                                            # real production messages will say "prod", the
                                            # consumer does not need to filter by this field
```

**Architecture**: a new, standalone background worker process — not a Flask HTTP route —
continuously polls the SQS queue (long-polling via boto3's SQS client is the standard approach).
This is a new kind of caller into the existing service layer, following the same
routes→service→repository layering already established: the worker calls the same
company/competitor/discovery/monitoring service functions the HTTP API and scheduler already use,
it just doesn't go through an HTTP route or the internal scheduler to reach them.

**Processing logic on receiving a message** — two cases:

1. **Competitor already exists** (matched by `company_domain_id` + `company_url`):
   - Check when discovery last ran for this competitor (reuse the existing discovery-run
     timestamp tracking).
   - If discovery is stale (≥ 30 days, same threshold as the monthly cadence in section 4):
     re-run discovery, apply the auto-activate/auto-deactivate reconciliation from section 4,
     then proceed to the next step.
   - If discovery is fresh (< 30 days): skip straight to the next step.
   - Take a fresh snapshot of every currently-active (tracked) page for this competitor — reuse
     `monitor_target()` as-is, which already handles "compare against the previous snapshot, save
     a change record if different" with no new logic needed.

2. **Competitor does not exist yet** (first run):
   - Create the competitor record, scoped to the company identified by `company_domain_id`.
   - Run discovery, auto-activate the suggested pages (section 4's reconciliation logic, applied
     to this initial suggested set).
   - Take an initial snapshot for each newly-active target via `monitor_target()`. Since there's no
     previous snapshot yet, no change can be (or should be) detected on this first run — this
     falls out naturally from the existing hash-comparison logic, no special-casing needed. The
     *next* snapshot (from a later SQS message, or the internal scheduler — see below) is what can
     detect a real change against this baseline.

**This coexists with the existing internal per-target scheduler (1.9), it does not replace it.**
The scheduler keeps running independently on each target's own `check_interval_minutes`; SQS
messages trigger additional, on-demand checks on top of that regular cadence. Because both
mechanisms can occasionally land on the same target around the same time, this relies on the
concurrency guard already built in 1.8 (atomic duplicate-run prevention) — no new protection is
needed here, this is exactly the situation that guard exists for.

**Idempotency requirement**: SQS has at-least-once delivery — the same message can occasionally
arrive more than once. Processing the same `company_domain_id` + `company_url` pair twice must not
create a duplicate competitor or double-trigger discovery/snapshotting beyond what the logic above
already produces. Reuse the same duplicate-handling logic already built for candidates (1.10) —
extend that pattern to inbound queue messages, don't build a second, separate deduplication
mechanism.

**Failure handling**: a message that fails to process (malformed schema, invalid domain,
discovery error) should not be silently dropped or retried forever. Standard practice: after a
bounded number of retries, route it to a Dead Letter Queue for inspection — confirm whether this
is already configured on the AWS side, or needs to be planned as part of implementation.

**Credentials**: AWS SQS access (queue URL, region, IAM credentials) follows the same pattern as
existing MongoDB/OpenAI credentials — environment-variable based, never hardcoded, never logged.

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

## 5. Snapshot storage: DynamoDB with 30-day TTL
Production snapshot content moves from local `.txt.gz` files to DynamoDB, using DynamoDB's native
TTL feature (an expiry timestamp attribute; AWS auto-deletes after it passes, no custom cleanup
job needed). Confirmed: plain DynamoDB, not a DynamoDB+S3 hybrid — accepting the 400KB per-item
limit for now.

**Pre-flight check needed before implementation**: verify the largest real compressed snapshot
(JD Sports' `/sale` page is the largest known example) stays safely under 400KB. Cheap to check now,
expensive to discover as a production incident later.

The existing snapshot storage abstraction (`snapshot/storage.py`) was built with a pluggable
backend in mind from the start (spec always anticipated moving off local storage) — swapping the
backend should be a contained change against that existing interface, not a rewrite.

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

---

## Deliverable
- `docs/production-plan.md` created with the content above
- No code changes
