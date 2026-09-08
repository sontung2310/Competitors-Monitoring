# Task: create docs/PoC_story.md — no code, documentation only

This is a new, third kind of doc alongside the existing two: specs.md is the technical
architecture, roadmap.md is the task tracker/progress log, PoC_story.md is the demo narrative —
what a person clicking through the UI should experience, and why. Create it with exactly the
content below (light formatting adjustments to match the repo's doc style are fine; don't change
the substance).

---

# PoC Story: Competitive Intelligence Monitoring — Demo Narrative

## Purpose
This PoC demonstrates the full monitoring pipeline end-to-end through a real UI, for two
real client scenarios, without requiring a genuine competitor site change to occur first
(which could take days/weeks) — using the LLM-generated simulated-change tooling already
built in 1.14/1.15 as a live, clickable demo trigger instead of a background test script.

## The two demo companies

| Company | Website | Their one tracked competitor |
|---|---|---|
| Marketing Eye | marketingeye.com.au | Lyfe Marketing (lyfemarketing.com) |
| The Athletes Foot | theathletesfoot.com.au | JD Sports AU (jd-sports.com.au) |

Each company sees only their own competitor(s), changes, and candidates — the dropdown at the
top of the UI switches between them. This is a real, if minimal, multi-tenant scoping — not
just a filtered view within one shared dataset presented differently.

**Existing test data (Brown Bag Marketing, Elevation Marketing) is not part of either company's
view.** It stays in the database, unassigned to any company, purely for continued backend
testing and verification — it should never appear in the PoC UI's dropdown-scoped views.

## The four-screen story

**1. Company selector + Competitors dashboard**
Dropdown at the top: "Marketing Eye" / "The Athletes Foot". Selecting one loads that company's
dashboard: their one competitor as a card (name, site, count of active targets, count of recent
changes).

**2. Competitor detail / Discovery**
Click into the competitor. Shows discovered candidates (SUGGESTED/DISCARDED), each with an
Activate button for SUGGESTED ones. A "Run Discovery" action re-runs real Layer 1 discovery live.
A "+ Add manually" option demonstrates the liveness gate live — a dead URL gets rejected with a
real error message, not a mocked one.

**3. Simulate a Change — the centerpiece**
Each active target has a "🎭 Simulate a Change" button. Clicking it runs the real LLM-based
simulation (1.14/1.15's tooling) against that target and, unlike the original read-only tooling,
**persists the result** — this is a deliberate, explicit reversal of 1.14/1.15's "never write to
Atlas" rule, made specifically for this demo purpose. Every simulated record carries
`is_simulated: true`, and the UI always shows a visible "🧪 SIMULATED" badge on anything carrying
that flag — simulated and real changes are never visually or structurally ambiguous.

**4. Changes feed**
Chronological feed for the selected company's competitor(s): change type badge, real summary,
timestamp, and the SIMULATED badge where applicable.

## Demo walkthrough (the actual acceptance criteria for this PoC)
A person with no terminal access should be able to:
1. Pick "Marketing Eye" from the dropdown → see Lyfe Marketing as their one competitor.
2. Click into it → see real discovered candidates → activate one that isn't already active.
3. Click "Simulate a Change" on an active target → see a result appear, tagged SIMULATED.
4. See that same simulated change appear in the Changes feed, still tagged.
5. Switch the dropdown to "The Athletes Foot" → see JD Sports AU, entirely separate data, no
   crossover from Marketing Eye's view.
6. Repeat steps 2-4 for JD Sports AU (including at least one product-listing-specific simulated
   case — new product / price change / removed).

If all six steps work through the UI alone, the PoC demo is considered successful.

## What this requires that doesn't exist yet (for the backend task, not this doc)
- A lightweight `companies` collection (id, name, website_url) — identity/label records only, no
  fetching/monitoring logic of their own.
- A real `company_id` on each competitor (there's an existing unused `user_id` placeholder field
  on competitor records from Step 2 — formalize that into this real purpose rather than adding a
  redundant field).
- Endpoints to trigger discovery and trigger a simulation (currently only Python-callable, not
  reachable over HTTP) — Step 2 exposed CRUD and reads, not "run this process" actions.
- `is_simulated` field + persistence path for simulated changes, deliberately bypassing 1.14/1.15's
  read-only rule for this specific, clearly-tagged case only.

## Explicitly out of scope for this PoC
- Authentication / real multi-user accounts — the company dropdown is a demo convenience, not a
  security boundary.
- Whether the eventual frontend uses Django (as originally planned in roadmap Step 3) or a
  different framework — that's a separate decision, not assumed by this doc.
- Brown Bag Marketing / Elevation Marketing cleanup — they remain as unassigned backend test data,
  untouched by this work.

---

## Deliverable
- `docs/PoC_story.md` created with the content above
- No code changes
