# AGENTS.md — Competitive Intelligence Monitoring System

## Context
- Spec: /docs/specs.md
- Architecture (C4 + layering): /docs/architecture.md
- Roadmap: /docs/roadmap.md — check off sub-steps as completed, don't skip ahead
- API contract: /docs/api-contract.md — the frozen source of truth for Django↔Flask

---

## 1. File structure (non-negotiable)

```
project/
├── frontend/
│   └── django/           # presentation layer only
│       ├── views/
│       ├── templates/
│       └── api_client/    # the ONLY module allowed to call the Flask backend
│
├── backend/
│   └── flask/
│       ├── competitors/
│       │   ├── routes.py       # presentation
│       │   ├── service.py      # application/business logic
│       │   └── repository.py   # data access
│       ├── discovery/
│       ├── website_monitoring/
│       ├── social_monitoring/  # scaffolded, not implemented until roadmap Step 5
│       ├── snapshot/
│       ├── change_detection/
│       ├── scheduler/
│       └── database/           # shared Mongo connection + base repository
│
├── storage/
│   └── snapshots/
│
├── docs/
│   ├── specs.md
│   ├── architecture.md
│   ├── roadmap.md
│   └── api-contract.md
│
└── tests/
```

Never create new top-level folders. Never create a new module folder outside
this list without updating this file first. Amend existing files before
creating new ones.

## 2. Separate logic early — layers, not just modules

Every backend module follows the same three-layer split (see architecture.md):

```
routes.py (presentation) → service.py (business logic) → repository.py (data access)
```

Hard rules:
- `routes.py` never imports `pymongo` or touches the filesystem.
- `service.py` never imports `pymongo` directly — it calls `repository.py`.
- Only `repository.py` (and `snapshot/storage.py`) touch MongoDB or the
  filesystem.
- On the frontend: Django views never call the Flask API directly — they go
  through `frontend/django/api_client/`, which is the only module that knows
  the API contract's shapes.

If a change requires touching a layer it shouldn't, that's a signal the
change belongs in a different file, not a reason to bend the rule.

## MongoDB Atlas MCP — inspection only

A MongoDB Atlas MCP server is connected, giving direct read/query access to
the actual cluster. This is for the agent's own use while developing and
debugging — inspecting collections, checking indexes, verifying a query
before writing it into `repository.py`, confirming what a migration actually
did.

It does **not** change §2: application code (routes, services) still never
talks to MongoDB except through `repository.py` / `snapshot/storage.py`.
Querying the cluster via MCP to understand data or verify a fix is fine;
writing application logic that calls the MCP tools (or otherwise skips the
repository layer) at runtime is not — that would put a debugging tool into
the production data path.

When using the MCP to inspect data, treat it as read-only unless a task
explicitly calls for a manual data fix — flag any write/delete before
running it.

## 3. Break work down through Linear, backed by roadmap.md

`/docs/roadmap.md` is the plan; Linear is the working task tracker. Each
roadmap sub-step maps to one Linear issue.

- Before starting work, pull the relevant Linear issue via the Linear MCP —
  its description and acceptance criteria are the task definition, not a
  restatement of the roadmap line.
- Work one Linear issue at a time. Don't start a second issue before the
  current one is in review.
- Move the issue's status as work progresses (e.g. Todo → In Progress → In
  Review) via the Linear MCP rather than leaving it stale.
- When an issue is done, check off the matching sub-step in
  `/docs/roadmap.md` in the same commit — roadmap.md and Linear should never
  drift out of sync.
- If a Linear issue doesn't exist yet for a roadmap sub-step, create it
  (with the sub-step text as a starting description) before starting the
  work, rather than working untracked.
- Don't jump ahead to a later roadmap step (e.g. Step 5 social monitoring)
  while earlier steps' issues are still open, unless explicitly told to.

## 4. GitHub branching strategy

- `main` is protected — no direct commits.
- One branch per roadmap sub-step or tightly related group of sub-steps:
  `feature/<step-number>-<slug>`, e.g. `feature/2.3-competitor-endpoints`.
- One PR per branch. PR description references the roadmap sub-step(s) it
  completes.
- Rebase on `main` before opening a PR; don't merge `main` into a
  long-running feature branch repeatedly.
- Squash-merge into `main` once validated (see §5).

## 5. Validate end-to-end before merging

This project doesn't deploy to Vercel (Flask + Django, not a JS/Next.js
stack) — use whatever staging target you actually deploy to (e.g. Railway,
Render, Fly.io, or a docker-compose staging profile). The principle from the
framework still applies:

- Every PR must be exercised end-to-end in a running environment before
  merge — not just unit-tested in isolation.
- For a backend PR: hit the new/changed endpoint against a real (or seeded)
  MongoDB, not mocks only.
- For a frontend PR: click through the actual flow against a running backend
  instance, not a stubbed API client.
- For an integration PR (roadmap Step 4/5's integration pass): run the full
  flow named in the roadmap sub-step (e.g. "add competitor → discovery →
  activate target → monitoring run → change → dashboard") against staging
  before merging.
- If no staging environment exists yet, say so explicitly rather than
  merging on local-only validation — decide together whether to set one up
  now or accept the gap for this PR.

---

## Session rules
1. Orient first: read this file, `/docs/roadmap.md`'s current checkbox state,
   `/docs/api-contract.md`, and the relevant Linear issue's status before
   writing code.
2. State which Linear issue / roadmap sub-step you're working on and which
   layer(s) it touches before starting.
3. Follow the branching strategy in §4 — don't commit to `main`.
4. Validate per §5 before considering a sub-step done.
5. Move the Linear issue's status and update `/docs/roadmap.md` (plus
   `/docs/api-contract.md` if the API surface changed) as part of the same
   change, not as an afterthought.
