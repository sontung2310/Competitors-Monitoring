# Roadmap — Competitive Intelligence Monitoring System

Reference: /docs/specs.md, /docs/architecture.md

**v1 scope:** Website Monitoring only (Layer 1 + Layer 2). Social Media Monitoring
is deferred to Step 5, after backend, frontend, and integration are working
end-to-end on website monitoring alone.

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
- [x] 1.3 Layer 1 UX support (backend service): expose SUGGESTED candidates for review; keep DISCARDED accessible, not deleted
- [x] 1.3b Candidate CRUD service operations: activate suggested candidate, manually add/edit/remove through the normal repository layer (HTTP endpoints are wired in Step 2.3)
- [x] 1.4 Layer 2 — Monitoring engine
  - [x] fetch strategy: HTTP first, browser-fetch fallback for JS-heavy pages
  - [x] content normalization
  - [x] hashing + hash comparison (skip full diff when unchanged)
  - [x] full diff generation when hash differs
- [x] 1.5 Snapshot storage
  - [x] snapshot metadata (content_hash, content_size, storage_path, fetch_method, http_status)
  - [x] local file storage under storage/snapshots/<target_id>/
- [x] 1.6 Change/event creation from diff (change_type derivation)
- [x] 1.7 Monitoring run tracking (RUNNING / SUCCESS / FAILED), failed run must not overwrite last valid snapshot
- [x] 1.8 Concurrency guard: prevent duplicate concurrent runs on the same target
- [x] 1.9 Scheduler: per-target interval, calls `monitor_target(target_id)` (scheduler stays decoupled from monitoring logic)
- [x] 1.10 Manual Layer 2 target creation (user-added page not from discovery)
- [ ] 1.11 Delete vs. deactivate rule: hard-delete a target only if it has no snapshot/change history; otherwise set active = false to preserve foreign-key integrity on existing records

## Step 2: Backend (Flask) — Website Monitoring Only

- [ ] 2.1 Project skeleton per module: competitors/, discovery/, website_monitoring/, snapshot/, change_detection/, scheduler/, database/ (social_monitoring/ scaffolded but not implemented yet)
- [ ] 2.2 Layering inside each module: routes (presentation) → service (business logic) → repository (data access) — see architecture.md
- [ ] 2.3 REST endpoints: competitor CRUD (website URL only for now), monitoring target CRUD (add/remove/activate/deactivate), candidate review (list SUGGESTED/DISCARDED, activate, edit, discard)
- [ ] 2.4 REST endpoints: changes/events read (latest updates feed)
- [ ] 2.5 Wire discovery, website_monitoring, change_detection into the service layer
- [ ] 2.6 MongoDB data access layer (repositories only — no direct pymongo calls outside this layer)
- [ ] 2.7 Error handling: timeouts, 4xx/5xx, invalid HTML, empty responses — consistent error response shape
- [ ] 2.8 API contract doc: write endpoint shapes to /docs/api-contract.md as they're finalized

## Step 3: Frontend (Django) — Website Monitoring Only

- [ ] 3.1 API client layer: single module wrapping all Flask backend calls (no scattered fetch calls in views/templates)
- [ ] 3.2 Main dashboard: recent updates feed (competitor, change summary, timestamp)
- [ ] 3.3 Competitor management page: add/remove competitor, manage website URL (no social fields yet)
- [ ] 3.4 Layer 1 UX: show SUGGESTED candidates for review (with a "show discarded" toggle), let user activate/edit/discard — every action writes through the API, not directly to the DB
- [ ] 3.5 Layer 2 page list per competitor: activate/deactivate/remove
- [ ] 3.6 Manual "Add Layer 2 Page" form
- [ ] 3.7 Read API contract from /docs/api-contract.md rather than assuming backend shapes

## Step 4: Backend/Frontend Integration Pass (2 agents) — Website Monitoring Only

- [ ] 4.1 Freeze /docs/api-contract.md as the shared source of truth before starting this step
- [ ] 4.2 Backend agent: verify every endpoint matches the frozen contract exactly
- [ ] 4.3 Frontend agent: verify every API client call matches the frozen contract exactly
- [ ] 4.4 End-to-end pass: add competitor → Layer 1 discovery → activate Layer 2 target → monitoring run → change detected → dashboard shows it
- [ ] 4.5 Fix contract mismatches found during integration (update api-contract.md, not just the code)
- [ ] 4.6 Reliability check: failed monitoring run doesn't break dashboard, doesn't overwrite last snapshot

**v1 PoC complete at this point** — website-only monitoring, working end-to-end.

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
