# UI kit — CompetitorScope monitoring dashboard

A click-through recreation of the PoC's four-screen demo narrative
(`docs/PoC_story.md`), built from the design system's own components. All data is fake
but shaped like the real API responses in `docs/api-contract.md`.

Open `index.html`.

## Screens

| File | Screen |
|---|---|
| `shell.kit.jsx` | Sidebar + topbar + tinted content frame, plus the `Panel` list container. Used by every screen. |
| `dashboard-screen.kit.jsx` | **1.** Stat tiles, the one bold competitor card, recent updates, latest monitoring runs. |
| `competitor-screen.kit.jsx` | **2.** Discovery review — suggested / active / discarded via the segmented switcher, Activate and Discard actions, Run Discovery with its loading state, and the "+ Add manually" liveness gate. |
| `simulate-result.kit.jsx` | **3.** The simulate result modal — changes-feed rows carrying the 🧪 SIMULATED marker. |
| `changes-screen.kit.jsx` | **4.** The chronological changes feed, filterable by detected vs simulated. |
| `app.kit.jsx` | State, company switching, and the fake async for discovery and simulation. |
| `data.js` | Seeded fake data for both demo tenants. |

## What is interactive

- Switch company in the sidebar footer — the whole view reloads through a visible
  loading state, so no rows from the previous company remain on screen.
- Activate or discard a suggested candidate; discarded ones move to the Discarded tab at
  reduced contrast rather than disappearing.
- Add a URL manually — anything that isn't a plausible URL is rejected with the API's own
  message, "this page doesn't appear to exist".
- Run Discovery shows a ~2s spinner (the real call makes HTTP crawls and may call the LLM
  classifier).
- 🎭 Simulate a Change on any active target runs a ~2s fake LLM call, opens the result
  modal, and pushes the same records into the changes feed — still tagged. A
  `PRODUCT_LISTING` target generates all three product events, as the API does.

## Deliberate omissions

The source defines no authentication, no settings screen, no social-account UI (deferred
to a later step) and no charts. Those are left out rather than invented. The
"Monitoring runs" view is a thin list because the API exposes no monitoring-run endpoints
in this step — it renders what `docs/specs.md` §20 describes and nothing more.

## Why the `.kit.jsx` suffix

These screens are lowercase-`.kit.jsx` on purpose. The design-system compiler treats any
PascalCase `.jsx` as a component and evaluates it inside `_ds_bundle.js`; that would run
this kit's `ReactDOM.createRoot` call on every card page in the Design System tab. The
suffix keeps the kit out of the bundle. Keep it if you add screens here.
