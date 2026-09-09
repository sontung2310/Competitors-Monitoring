# Roadmap — Competitive Intelligence Monitoring System

Reference: /docs/specs.md, /docs/architecture.md

**v1 scope:** Website Monitoring only (Layer 1 + Layer 2). Social Media Monitoring
is deferred to Step 5, after backend, frontend, and integration are working
end-to-end on website monitoring alone.

**Branch-integrity check:** Run `python scripts/check_unmerged_branches.py`
before review or when auditing `main`. It lists feature branches whose history
is not reachable from `main`, accounts for squash-merged/patch-equivalent
branches, and exits nonzero when a genuinely unmerged branch corresponds to a
checked-off roadmap item. This is process tooling, not a roadmap feature.

---

## Step 1: Website Monitoring (Layer 1 Discovery + Layer 2 Monitoring)

- [x] 1.1 Data layer: `competitors` and `monitoring_targets` collections (MongoDB) + repository module
- [x] 1.2 Layer 1 — Discovery (robots.txt, sitemaps, and shallow homepage links; search engines intentionally excluded from v1)
  - [x] robots.txt fetch/parse
  - [x] sitemap.xml / sitemap_index.xml fetch/parse
  - [x] internal link crawler from homepage
  - [x] merge + dedupe raw discovered URLs
  - [x] rule-based URL normalization (strip dynamic IDs/UUIDs/hashes; page-type aware — collapse index pages like /blog, keep distinct item pages like /products/<slug> separate)
  - [x] rule-based classification (keyword/pattern match against page_type list — free, no LLM)
  - [x] LLM classification fallback for unresolved candidates only — batched per competitor, structured JSON output, cheap model (gpt-5-nano)
  - [x] persist candidates with discovery_status (SUGGESTED/DISCARDED) and classification_method (RULE/LLM)
  - [x] 1.2b real OpenAI CandidateClassifier fallback (TON-25; the original gpt-5-nano placeholder is superseded by configurable OpenAI gpt-4o via the shared provider; provider failures retain deterministic DISCARDED fallback behavior)
- [x] 1.3 Layer 1 UX support (backend service): expose SUGGESTED candidates for review; keep DISCARDED accessible, not deleted
- [x] 1.3b Candidate CRUD service operations: activate suggested candidate, manually add/edit/remove through the normal repository layer (HTTP endpoints are wired in Step 2.3)
- [x] 1.3c Reactivate discarded candidates in the review UI and sort Suggested/Active/Discarded lists by most-recently-changed (`updated_at`) (TON-32; reactivation reuses the existing liveness-gated manual-target promotion path)
- [x] 1.4 Layer 2 — Monitoring engine
  - [x] fetch strategy: HTTP first, browser-fetch fallback for JS-heavy pages
  - [x] content normalization
  - [x] hashing + hash comparison (skip full diff when unchanged)
  - [x] full diff generation when hash differs
- [x] 1.5 Snapshot storage
  - [x] snapshot metadata (content_hash, content_size, storage_path, fetch_method, http_status)
  - [x] local file storage under storage/snapshots/<target_id>/
- [x] 1.6 Change/event creation from diff (change_type derivation)
- [x] 1.6b LLM narrative summaries for NEW_BLOG/PAGE_UPDATE changes (TON-30; summarization half only — mechanical summaries remain unchanged)
- [x] 1.6b detected URLs for changes (TON-31; deterministic product URLs, validated LLM-extracted blog URLs, clickable frontend rendering, and enrichment backfill)
- [ ] 1.6b Relevance filtering (separately deferred; not included in TON-30)
- [x] 1.7 Monitoring run tracking (RUNNING / SUCCESS / FAILED), failed run must not overwrite last valid snapshot
- [x] 1.8 Concurrency guard: prevent duplicate concurrent runs on the same target
- [x] 1.9 Scheduler: per-target interval, calls `monitor_target(target_id)` (scheduler stays decoupled from monitoring logic)
- [x] 1.10 Manual Layer 2 target creation (user-added page not from discovery)
- [x] 1.11 Delete vs. deactivate rule: hard-delete a target only if it has no snapshot/change history; otherwise set active = false to preserve foreign-key integrity on existing records
- [x] 1.12 Extract existing monitoring logic behind the `ContentProcessor` interface (pure refactor, with real-target proof that behavior and hashes are unchanged)
- [x] 1.13 Implement `ProductListingProcessor` for `PRODUCT_LISTING` pages (structured extraction, keyed diff, and `NEW_PRODUCT`/`PRODUCT_REMOVED`/`PRICE_CHANGE` events)
  - [x] WordPress comment-form/plugin volatile-noise normalization (TON-18; known false-positive change retained and documented)
  - [x] Generic exclusion of explicitly hidden HTML content from normalization (TON-20; applies to consent, utility, duplicate, and hidden-variant markup)
  - [x] Concrete Playwright browser fetcher for the 1.4 HTTP fallback gap (TON-19; HTTP remains first, browser rendering is used only for unusable responses)
  - [x] Text-blob display diff granularity for informative summaries (TON-17; hashing remains unchanged)
- [x] 1.14 Simulated-change verification tooling for blog and product-listing scenarios, using offline LLM-generated fixtures with strict isolation from real fetch history
  - Reusable environment-configured LLM provider client is available for future consumers.
  - CandidateClassifier provider unification is completed separately in 1.2b (TON-25); this step did not wire the provider into discovery classification.
- [x] 1.15 Unified simulated-change acceptance suite: capture real content, LLM-mutate in memory, run the real processors, and verify new blog, services, product-add, price-change, and product-removal cases (TON-24; live five-case suite passed with Atlas counts unchanged). SOLD_OUT remains separately deferred under TON-23 because the JD Sports listing exposes no reliable availability signal.

## Step 2: Backend (Flask) — Website Monitoring Only

- [x] 2.1 Project skeleton per module: competitors/, discovery/, website_monitoring/, snapshot/, change_detection/, scheduler/, database/ (social_monitoring/ scaffolded but not implemented yet)
- [x] 2.2 Layering inside each module: routes (presentation) → service (business logic) → repository (data access) — see architecture.md
- [x] 2.3 REST endpoints: competitor CRUD (website URL only for now), monitoring target CRUD (add/remove/activate/deactivate), candidate review (list SUGGESTED/DISCARDED, activate, edit, discard)
- [x] 2.4 REST endpoints: changes/events read (latest updates feed)
- [x] 2.5 Wire discovery, website_monitoring, change_detection into the service layer
- [x] 2.6 MongoDB data access layer (repositories only — no direct pymongo calls outside this layer)
- [x] 2.7 Error handling: timeouts, 4xx/5xx, invalid HTML, empty responses — consistent error response shape
- [x] 2.8 API contract doc: write endpoint shapes to /docs/api-contract.md as they're finalized

## Step 3: Frontend (Django) — Website Monitoring Only

- [x] 3.1 API client layer: single module wrapping all Flask backend calls (no scattered fetch calls in views/templates)
- [x] 3.2 Main dashboard: recent updates feed (competitor, change summary, timestamp)
- [x] 3.3 Competitor management page: add/remove competitor, manage website URL (no social fields yet)
- [x] 3.4 Layer 1 UX: show SUGGESTED candidates for review (with a "show discarded" toggle), let user activate/edit/discard — every action writes through the API, not directly to the DB
- [x] 3.5 Layer 2 page list per competitor: activate/deactivate/remove
- [x] 3.6 Manual "Add Layer 2 Page" form
- [x] 3.7 Read API contract from /docs/api-contract.md rather than assuming backend shapes

### Step 3 reconciliation (Step 4 checkpoint, 2026-09-09)

All seven original Step 3 items are genuinely covered by the merged Django PoC
frontend: `monitoring/api_client/client.py` is the single Flask boundary;
dashboard, competitor management, candidate review, target management, and
manual-target templates are wired to it; and the implementation/audit used
`docs/api-contract.md` as the request/response source of truth. No Step 3 item
remains missing. The PoC scope does not add social fields, consistent with the
Step 3 requirement to defer social monitoring.

## Step 4: Backend/Frontend Integration Pass (2 agents) — Website Monitoring Only

- [x] 4.1 Freeze /docs/api-contract.md as the shared source of truth before starting this step
- [x] 4.2 Backend agent: verify every endpoint matches the frozen contract exactly
- [x] 4.3 Frontend agent: verify every API client call matches the frozen contract exactly
- [x] 4.4 End-to-end pass: add competitor → Layer 1 discovery → activate Layer 2 target → monitoring run → change detected → dashboard shows it
- [x] 4.5 Fix contract mismatches found during integration (update api-contract.md, not just the code)
- [x] 4.6 Reliability check: failed monitoring run doesn't break dashboard, doesn't overwrite last snapshot

### Step 4 integration-pass evidence (TON-29, 2026-09-09)

- 4.1 is frozen in `docs/api-contract.md`, with an explicit no-silent-drift
  checkpoint note.
- 4.2/4.3 found no method/path/request/status mismatches. The only finding was
  a response-documentation gap: older real change rows can omit
  `is_simulated`; the contract now records that omission as false.
- 4.4 was exercised as one continuous live PoC walkthrough for Marketing Eye →
  Lyfe Marketing and The Athletes Foot → JD Sports AU, including the JD
  `PRODUCT_LISTING` price simulation and company-scope switch.
- 4.5 required a contract documentation correction only; no runtime code fix
  was required.
- 4.6 used an injected fetch failure on Lyfe's real `/blog` target. The run was
  persisted as `FAILED`, no snapshot or change was created, and the prior real
  snapshot remained byte-for-byte unchanged. The dashboard and changes feed
  rendered normally; the UI does not currently surface failed monitoring runs,
  which remains a known PoC limitation.

## PoC-specific backend slice (TON-27)

- [x] Companies collection and idempotent demo seeding; migrate legacy
  competitor `user_id` into `company_id`, assign Lyfe Marketing and JD Sports
  AU, and leave Brown Bag Marketing/Elevation Marketing unassigned.
- [x] Company-scoped competitor, candidate, monitoring-target, and change
  endpoints; synchronous discovery and tagged simulation trigger endpoints.
- [x] Persistence-enabled simulation wrapper that preserves the original
  zero-write simulation helpers and excludes `is_simulated=true` snapshots from
  genuine monitor comparisons.
- [x] Discovery item-type exclusion follow-up: individual
  `/product/<slug>/<sku>` leaves are excluded without affecting aggregate
  product-listing targets; JD Sports bug-artifact cleanup was scoped to the
  exact discarded rows.

**v1 PoC complete at this point** — website-only monitoring, working end-to-end.

## PoC-specific frontend slice (TON-28)

- [x] Django frontend with a single Flask API client, company-scoped dashboard,
  discovery review, live simulation result, and changes feed screens; validated
  with real API data, loading/error states, and browser screenshots.
- [x] Timeout-safe discovery polling uses a persisted `RUNNING` → `SUCCESS` /
  `FAILED` lifecycle rather than inferring completion from candidate-row count;
  the JD Sports discovery timing limitation is documented in `PoC_story.md`.

---

## Step 5: Social Media Monitoring (LinkedIn, Instagram, TikTok)

- [ ] 5.1 Data layer: `social_accounts` collection + repository module
- [ ] 5.2 OpenCLI collection setup (shared across adapters)
- [ ] 5.3 LinkedIn adapter → normalized post schema
- [ ] 5.4 Instagram adapter → normalized post schema
- [ ] 5.5 TikTok adapter → normalized post schema
- [ ] 5.6 Common normalized post model (platform, account, post_id, post_url, published_at, text, content_hash)
- [ ] 5.7 New/updated post detection via platform-level post_id + content_hash (not raw HTML)
- [ ] 5.8 Change/event creation for new posts (NEW_POST type)
- [ ] 5.9 Adapter-level failure isolation: one platform/account failure must not block others
- [ ] 5.10 Backend: social_monitoring/ routes + service + repository (same three-layer pattern as Step 2)
- [ ] 5.11 Backend: social account CRUD endpoints; update /docs/api-contract.md
- [ ] 5.12 Frontend: social account fields on competitor management page
- [ ] 5.13 Frontend: dashboard shows social changes alongside website changes
- [ ] 5.14 Integration pass: add social account → adapter run → new post detected → dashboard shows it
- [ ] 5.15 Reliability check: one social adapter failure doesn't stop website monitoring or other adapters
