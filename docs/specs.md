# Competitive Intelligence Monitoring System

## PoC Product & Technical Specification

---

# 1. Project Overview

The goal of this project is to monitor competitors' public websites and social-media accounts and notify users when meaningful updates or changes occur.

Examples of changes:

- New blog/article
- New product/item
- New campaign
- New promotion
- New award or company announcement
- New social-media post
- Price or sale changes
- Other meaningful updates on a competitor's website

The system should answer:

> **What has changed on my competitors' side since the last monitoring cycle?**

The PoC prioritizes:

- Simple and maintainable architecture
- Low operating cost
- Reliable change detection
- Efficient snapshot storage and comparison
- Simple but usable frontend/backend integration
- Architecture that can later support multiple companies/users

---

# 2. Target User

## PoC

One company is one user.

The user can:

- Add competitors
- Remove competitors
- Update competitor information
- Add/remove competitor website links
- Add/remove competitor social-media accounts
- Add/remove Layer 2 monitoring targets

## Future

The architecture must support multiple users:

```text
User / Company A
    ├── Competitor A
    ├── Competitor B
    └── Competitor C

User / Company B
    ├── Competitor X
    └── Competitor Y
```

The database should therefore include `user_id` / `company_id` relationships from the beginning, even though the PoC only contains one user.

---

# 3. Monitoring Concept

The system uses two website monitoring layers.

```text
Layer 1
Competitor website / domain
        │
        │ discover important pages
        ▼
Layer 2
Specific website pages
        │
        ▼
Actual monitoring + snapshot comparison
```

The two layers have different purposes.

---

# 4. Layer 1 — Competitor Website / Domain

## Definition

**Layer 1 represents the competitor as a whole website/domain.**

The user provides only the competitor's main website:

```text
https://competitor.com
```

Layer 1 is **not the actual monitoring target for detailed change detection**.

Its main purpose is:

> **Discover potentially important pages inside the competitor's website that could become Layer 2 monitoring targets.**

## Example

User adds:

```text
Competitor: Example Company
Website: https://example.com
```

The system explores the website and may discover:

```text
https://example.com/pricing
https://example.com/blog
https://example.com/products
https://example.com/news
https://example.com/careers
```

These discovered pages become Layer 2 candidates.

## Layer 1 discovery sources

The system uses site-owned sources so discovery remains deterministic and
focused on primary Layer 2 sections:

### 1. `robots.txt`

Check:

```text
https://example.com/robots.txt
```

This may contain Sitemap declarations and crawling rules.

### 2. Sitemap

Check common locations such as:

```text
/sitemap.xml
/sitemap_index.xml
```

and sitemap URLs referenced from `robots.txt`.

### 3. Internal links

Fetch the homepage and follow relevant internal links.

Example:

```text
Homepage
   ↓
Products
Pricing
Blog
News
About
```

## Layer 1 output

Layer 1 produces a list of candidate pages:

```text
Competitor: Example Company

Discovered Pages
────────────────────────────
/pricing
/blog
/products
/news
/careers
```

Each candidate can have a page type:

```text
/pricing    → PRICING
/blog       → BLOG
/products   → PRODUCTS
/news       → NEWS
/careers    → CAREERS
```

## Candidate normalization and classification

Raw discovered URLs go through two stages before becoming candidates a user can
review. Both stages exist to keep LLM usage — and cost — to the minimum needed.

### Stage 1 — Rule-based normalization (free, always runs)

Strip dynamic trailing segments (numeric IDs, UUIDs, hashes, timestamp-like
slugs) so that URLs collapse to a stable path:

```text
example.com/pages/dasdasdasd12323  →  example.com/pages
```

This collapse is **page-type aware**, not blanket "strip the last segment":

- Index-style paths (`/blog`, `/news`, `/press`) collapse individual post URLs
  into the parent path — the index page is the actual Layer 2 target; new
  posts are detected by content changes on that index, not tracked one URL
  each.
- Item-style paths where each slug is a distinct, independently meaningful
  page (e.g. `/products/<slug>` where each slug is a different product) are
  **not** collapsed — each is a real candidate on its own, since price/content
  changes on one product must not be conflated with another.

After normalization, a liveness gate runs before Stage 2 classification for
every normalized index-type candidate. Source provenance may already require a
candidate to be `DISCARDED`, but it still passes through the same check. The
gate reuses the monitoring fetch heuristic: an HTTP 200–399 HTML response with
at least 40 visible characters is usable, and an unusable HTTP response may be
retried through the injected browser fetcher. Discovery makes up to three
liveness attempts with a short backoff. Only repeated 404/410 responses are
treated as confirmation that the normalized index is dead. Transport failures,
browser configuration failures, 403/429 anti-bot or rate-limit responses,
5xx responses, and other inconclusive failures are logged and leave the
candidate eligible for suggestion. A confirmed dead normalized index is
recorded as `DISCARDED`; no leaf URL is guessed as a substitute. This keeps
liveness validation in the final Stage 1 discovery step, before classification
and before any candidate can be offered for Layer 2 activation.

### Stage 2 — Classification (rule-first, LLM only as fallback)

1. Try keyword/pattern rules first (free): match normalized path segments and
   page title against known terms — pricing, blog, news, product, press,
   about, careers, team, CEO. A confident rule match classifies the candidate
   directly; no LLM call is made.
2. Only candidates the rules can't confidently classify go to an LLM call.
   Batch all of a competitor's unresolved candidates into a single structured
   (JSON) request rather than one call per URL. Use a low-cost model
   (e.g. `gpt-5-nano`) for this — it's a coarse relevance filter, not a task
   that needs a frontier model. See §22 Cost Strategy.
3. Output for every candidate: `page_type`, `discovery_status`
   (`SUGGESTED` or `DISCARDED`), and `classification_method` (`RULE` or
   `LLM`). Discarded candidates are **not** deleted — they stay visible at low
   priority so a wrong LLM/rule call doesn't silently hide a page the user
   would have wanted. Only `SUGGESTED` candidates need to become active
   Layer 2 targets on their own; the user still decides (§19 Layer 1 UX).

---

# 5. Layer 2 — Specific Website Page

## Definition

**Layer 2 represents a specific URL inside a competitor's website that is monitored repeatedly.**

Example:

```text
https://example.com/pricing
```

or:

```text
https://example.com/blog
```

Unlike Layer 1, Layer 2 is an **actual monitoring target**.

The system periodically:

```text
Fetch page
   ↓
Normalize content
   ↓
Compare with previous snapshot
   ↓
Detect change
   ↓
Store change
```

## Examples

### Pricing

```text
Layer 1:
https://example.com

Layer 2:
https://example.com/pricing
```

Possible detected change:

```text
Professional Plan
$99/month → $79/month
```

### Blog

```text
Layer 1:
https://example.com

Layer 2:
https://example.com/blog
```

Possible detected change:

```text
New article:
"How AI Is Changing Marketing"
```

### Product page

```text
Layer 1:
https://example.com

Layer 2:
https://example.com/products
```

Possible detected change:

```text
New product added
```

---

# 6. Relationship Between Layer 1 and Layer 2

The relationship is:

```text
One Competitor
      │
      └── Layer 1: example.com
              │
              ├── Layer 2: /pricing
              ├── Layer 2: /blog
              ├── Layer 2: /products
              └── Layer 2: /news
```

A competitor can have many Layer 2 targets.

The user can also manually add a Layer 2 page that was not discovered automatically.

Example:

```text
[+ Add monitored page]

URL:
https://example.com/special-offers
```

This is important because automatic discovery cannot guarantee that every strategically important page will be found.

---

# 7. Layer 1 vs Layer 2 — Key Principle

The system should follow:

> **Layer 1 discovers. Layer 2 monitors.**

This means the system should not attempt to treat the entire website as one large snapshot.

For example:

```text
❌ Layer 1
example.com
↓
compare entire website as one document
```

Instead:

```text
✅ Layer 1
example.com
↓
discover relevant pages
↓
/pricing
/blog
/products
/news
↓
Layer 2 monitoring
```

This provides better accuracy, lower noise, and more efficient snapshot comparison.

---

# 8. Website Monitoring

The website monitoring mechanism should follow the general approach used by changedetection.io.

The system should support:

- HTTP fetching for normal/static pages
- Browser-based fetching for JavaScript-heavy pages
- Content extraction and normalization
- Historical snapshots
- Hash-based comparison
- Full diff only when content actually changes

### Fetch strategy

```text
Layer 2 URL
     │
     ▼
HTTP fetch
     │
     ├── usable response → continue
     │
     └── JS-required / unusable
                 │
                 ▼
           Browser fetch
```

Browser automation should not be the default for every page because it is more expensive and slower.

---

# 9. Social Media Monitoring

Social media is treated separately from website monitoring because each platform exposes content differently.

The PoC supports:

- LinkedIn
- Instagram
- TikTok

OpenCLI is used as the collection mechanism.

Each platform has its own adapter:

```text
Social Monitoring
      │
      ├── LinkedIn Adapter
      ├── Instagram Adapter
      └── TikTok Adapter
```

The adapters should produce a common normalized result.

Example:

```json
{
    "platform": "instagram",
    "account": "competitor_a",
    "post_id": "123456",
    "post_url": "...",
    "published_at": "...",
    "text": "...",
    "content_hash": "..."
}
```

For social monitoring, the system should identify new/updated posts using platform-level identifiers and normalized content rather than treating raw HTML as the primary historical record.

---

# 10. Competitor Input

The frontend/API should accept information conceptually equivalent to:

```python
{
    "competitor_a": {
        "website": "https://competitor-a.com",
        "social": {
            "linkedin": "https://linkedin.com/company/competitor-a",
            "instagram": "https://instagram.com/competitor-a",
            "tiktok": "https://tiktok.com/@competitor-a"
        }
    }
}
```

This is an API/UI representation only.

The database should use normalized tables.

---

# 11. Database Structure

Recommended PoC database: **MongoDB**.

## Users / Companies

```text
users
-----
id
name
created_at
```

## Competitors

```text
competitors
-----------
id
user_id
name
website_url
active
created_at
updated_at
```

## Social Accounts

```text
social_accounts
---------------
id
competitor_id
platform
profile_url
active
created_at
```

## Monitoring Targets

A monitoring target represents a Layer 2 page.

```text
monitoring_targets
------------------
id
competitor_id
raw_url                  # URL as originally discovered, before normalization
url                       # normalized URL — this is what gets monitored
page_type
discovery_source          # ROBOTS | SITEMAP | LINKS | MANUAL
discovery_status          # SUGGESTED | DISCARDED | ACTIVE
classification_method     # RULE | LLM | MANUAL
active
check_interval_minutes
last_checked_at
last_changed_at
created_at
updated_at
```

`discovery_status` and `active` are deliberately separate: a candidate can be
`SUGGESTED` while `active = false` (awaiting review), become `ACTIVE` once the
user approves it, or be user-added directly as `ACTIVE`/`MANUAL` with no
review step. Deleting a target the user never activated (no snapshot/change
history yet) can hard-delete the row. Removing a target that already has
monitoring history should deactivate (`active = false`) instead of
hard-deleting, so existing `snapshots`/`changes` records keep a valid
foreign key.

Examples:

```text
competitor_id = 1
url = https://competitor.com/pricing
page_type = PRICING
```

or:

```text
competitor_id = 1
url = https://competitor.com/blog
page_type = BLOG
```

---

# 12. Snapshot Storage

Every successful Layer 2 monitoring run can create a snapshot.

```text
snapshots
---------
id
monitoring_target_id
captured_at
content_hash
content_size
storage_path
fetch_method
http_status
```

The actual snapshot content should be stored separately from the metadata.

For the PoC:

```text
storage/
└── snapshots/
    └── <monitoring_target_id>/
        ├── <timestamp-1>.txt.gz
        ├── <timestamp-2>.txt.gz
        └── <timestamp-3>.txt.gz
```

This is similar in principle to changedetection.io's approach of maintaining snapshot history associated with a monitoring watch.

For later scaling, the same files can be moved from local storage to object storage such as S3.

---

# 13. Efficient Comparison

The monitoring system should not perform an expensive full diff on every check.

Use:

```text
Fetch
  ↓
Normalize
  ↓
Hash
  ↓
Compare hashes
  │
  ├── Same
  │     ↓
  │   No change
  │
  └── Different
        ↓
      Full diff
        ↓
     Create change
```

Example:

```text
Previous hash:
ABC123

Current hash:
ABC123

→ No change
```

If:

```text
Previous hash:
ABC123

Current hash:
XYZ987

→ Content changed
→ Load previous + current snapshots
→ Generate diff
→ Create change record
```

This makes frequent monitoring much cheaper.

---

# 14. Changes / Events

Detected changes should be stored separately from snapshots.

```text
changes
-------
id
monitoring_target_id
previous_snapshot_id
current_snapshot_id
detected_at
change_type
summary
status
```

Examples:

```text
PRICE_CHANGE
NEW_BLOG
NEW_PRODUCT
NEW_PROMOTION
NEW_CAMPAIGN
NEW_AWARD
PAGE_UPDATE
```

The PoC can initially derive `change_type` from the monitored page type and simple rules.

---

# 15. Monitoring Runs

Every attempt should have a monitoring-run record.

```text
monitoring_runs
---------------
id
monitoring_target_id
started_at
finished_at
status
error_message
```

Possible statuses:

```text
RUNNING
SUCCESS
FAILED
```

A failed request must **not** become a new valid snapshot.

Example:

```text
Previous valid snapshot
        ↓
HTTP 500
        ↓
Monitoring run = FAILED
        ↓
Previous snapshot remains unchanged
```

This prevents false change detection.

---

# 16. Scheduling

Each monitoring target has its own interval.

Example:

```text
Pricing page       → every 6 hours
Blog               → every 3 hours
LinkedIn           → every 2 hours
Instagram          → every 2 hours
TikTok             → every 2 hours
```

The monitoring function should be safe to execute repeatedly.

The system must prevent the same target from being processed concurrently.

Conceptually:

```text
Target A
    │
    ├── RUNNING → skip another run
    │
    └── not running → execute
```

For the PoC, a lightweight scheduler is sufficient.

The monitoring logic itself should be independent from the scheduler:

```python
monitor_target(target_id)
```

This makes it possible to introduce workers/queues later without rewriting the monitoring engine.

---

# 17. Backend Structure

Recommended structure:

```text
project/
│
├── frontend/
│   └── Django
│
├── backend/
│   └── Flask
│       ├── competitors/
│       ├── discovery/
│       ├── website_monitoring/
│       ├── social_monitoring/
│       ├── snapshot/
│       ├── change_detection/
│       ├── scheduler/
│       └── database/
│
├── storage/
│   └── snapshots/
│
└── tests/
```

Core backend operations:

```python
discover_website(competitor_id)

discover_layer2_pages(competitor_id)

monitor_website(target_id)

monitor_social_account(account_id)

create_snapshot(target_id, content)

compare_snapshots(previous, current)

create_change(target_id, diff)
```

---

# 18. Frontend

The frontend uses Django and communicates with the Flask backend.

## Main Dashboard

The primary screen should show recent competitive updates:

```text
Competitive Monitor

Recent Updates
────────────────────────────────────

Competitor A
Price changed: $99 → $79
2 hours ago

Competitor B
New blog: "AI Marketing Trends"
5 hours ago

Competitor C
New TikTok post
Yesterday
```

## Competitor Management

```text
Competitor A

Website
https://competitor-a.com

Social Accounts
✓ LinkedIn
✓ Instagram
✓ TikTok

Layer 2 Pages
✓ Pricing
✓ Blog
✓ Products
○ News

[+ Add Layer 2 Page]
[Remove Competitor]
```

The user should be able to activate/deactivate/remove Layer 2 pages.

---

# 19. Layer 1 UX

After adding a competitor, the system can show discovered pages:

```text
Competitor A
https://competitor-a.com

Discovered Pages

✓ /pricing       PRICING
✓ /blog          BLOG
✓ /products      PRODUCTS
○ /careers       CAREERS
○ /about         ABOUT
```

The user can decide which discovered pages become active Layer 2 monitoring targets.

This gives the system:

> **Automatic discovery + human control**

rather than automatically monitoring every discovered URL.

`SUGGESTED` candidates (see §4 Candidate normalization and classification)
are what populates this list by default; `DISCARDED` candidates remain
accessible (e.g. a "show discarded" toggle) rather than disappearing, in case
a rule or LLM call misclassified a page the user actually wants.

Every action in this UI — activating a suggested candidate, adding a link
manually, editing a URL, or removing one — writes through the normal API
(Django → Flask → repository), the same as any other CRUD flow in this
system. There is no separate direct-DB path for this screen.

---

# 20. Reliability Requirements

The system should handle:

- Connection timeout
- HTTP 4xx/5xx
- Browser failure
- Invalid HTML
- Empty responses
- Website structure changes
- Social adapter failure
- Temporary external-service failure

Requirements:

1. A failed fetch must not overwrite the last successful snapshot.
2. One failed competitor must not stop other competitors from being monitored.
3. Monitoring runs must have explicit success/failure states.
4. Re-running a failed target must be safe.
5. Duplicate concurrent runs must be prevented.

---

# 21. Scalability Requirements

The PoC may initially contain:

```text
1 user
10 competitors
~5 Layer 2 targets per competitor
```

The database and code should nevertheless support:

```text
Many users
    ↓
Many competitors
    ↓
Many monitoring targets
    ↓
Many snapshots
    ↓
Many changes
```

The monitoring functions should be as stateless as practical so that monitoring can later be moved from:

```text
Single process
```

to:

```text
Scheduler
    ↓
Queue
    ↓
Multiple workers
```

without changing the business logic.

---

# 22. Cost Strategy

The PoC should prioritize low operating cost.

Use:

```text
Django
Flask
MongoDB
Local/object snapshot storage
HTTP client
Browser automation only when required
OpenCLI for social collection
```

Avoid adding expensive infrastructure unless the PoC demonstrates the need.

Do not run an LLM on every monitoring cycle.

Layer 1 candidate classification (§4) follows the same principle: rule-based
matching handles classification first, and only unresolved candidates go to
an LLM, batched per competitor, using a low-cost model (e.g. `gpt-5-nano`)
rather than a frontier model.

AI can be introduced later for:

- Semantic change classification
- Change summarization
- Importance scoring
- Business-impact analysis

The deterministic monitoring layer should first determine whether something actually changed.

---

# 23. PoC Scope

## Must Have

- One user/company
- Competitor CRUD
- Website URL
- LinkedIn URL
- Instagram URL
- TikTok URL
- Layer 1 website discovery
- Layer 2 page monitoring
- Automatic snapshot creation
- Efficient snapshot comparison
- Change records
- Social post detection
- Scheduled monitoring
- Frontend dashboard
- Latest-change display
- Error handling

## Out of Scope

- Layer 3 element-level monitoring
- Advanced AI analysis
- Automated strategic recommendations
- Complex multi-tenant authentication
- Kubernetes
- Distributed queues
- Multiple notification integrations
- Large-scale crawling infrastructure

---

# 24. End-to-End PoC Flow

```text
User adds competitor
        │
        ▼
https://competitor.com
        │
        ▼
Layer 1: Website Discovery
        │
        ├── robots.txt
        ├── sitemap
        ├── internal links
        │
        ▼
Candidate Layer 2 Pages
        │
        ├── /pricing
        ├── /blog
        ├── /products
        └── /news
        │
        ▼
User selects / system activates targets
        │
        ▼
Layer 2 Monitoring
        │
        ├── Fetch
        ├── Normalize
        ├── Hash
        └── Compare
        │
        ▼
Change detected?
      │
      ├── NO → finish
      │
      └── YES
            │
            ▼
        Save snapshots
            │
            ▼
        Create change
            │
            ▼
        Frontend displays update
```

Social monitoring follows a separate platform-specific flow:

```text
Social Account
      │
      ▼
Platform Adapter
      │
      ├── LinkedIn
      ├── Instagram
      └── TikTok
      │
      ▼
Normalize posts
      │
      ▼
Compare post IDs/content
      │
      ▼
New / Updated Post
      │
      ▼
Save to DB
      │
      ▼
Frontend
```

---

# 25. Main Design Principle

The PoC should optimize for **useful competitive signals**, not maximum crawling coverage.

The fundamental model is:

```text
Competitor
    │
    ▼
Layer 1: Discover
    │
    ▼
Layer 2: Monitor
    │
    ▼
Snapshot
    │
    ▼
Compare
    │
    ▼
Change / Event
    │
    ▼
Database
    │
    ▼
Frontend / Notification
```

Layer 1 should be **broad and exploratory**.

Layer 2 should be **specific and reliable**.

This provides a practical balance between:

```text
Automation
     ↕
AccuracyCould you help me to desgin
```

without requiring the user to manually configure every page of every competitor.
