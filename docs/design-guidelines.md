# Design Guidelines — Frontend (Django)

Visual reference: [roboticmarketer.com](https://www.roboticmarketer.com/) —
match its color direction, corporate confidence, and dashboard/execution-tool
feel. A real screenshot of the reference app's dashboard has been reviewed
(see change log at bottom) — values below marked "visual estimate" are read
from that screenshot, not sampled with a color picker; confirm exact hex
values against the live site's inspector before final implementation.

This file covers brand system (Part 1) and how it applies to this specific
product's actual screens and data, per docs/PoC_story.md (Part 2). Read both
— Part 1 alone is not sufficient to build the PoC UI correctly.

---

# Part 1 — Brand System

## Color Palette

```
--color-primary:        #E4362A   /* visual estimate — warm fire-engine red, NOT magenta-leaning; verify against inspector */
--color-primary-hover:  #C42E22   /* ~10% darker, for hover/active states */
--color-primary-light:  #FDE8E5   /* tint for badges, subtle highlights, selected states */

--color-secondary:       #2FBF8F  /* visual estimate — mint/teal green, confirmed present in reference (donut chart, favorable-trend indicators) */
--color-secondary-light: #E3F7EF  /* tint for secondary badges/highlights */

--color-bg:              #FFFFFF
--color-bg-subtle:       #F7F7F8   /* section backgrounds, alternating rows */

--color-text:            #1A1A1A  /* primary text */
--color-text-muted:      #6B7280  /* secondary text, timestamps, labels */

--color-border:          #E5E7EB

--color-success:         #16A34A  /* e.g. SUCCESS monitoring run status */
--color-warning:         #D97706  /* e.g. pending review — also reused for the SIMULATED marker, see Part 2 */
--color-error:           #DC2626  /* e.g. FAILED monitoring run status — distinct from --color-primary, don't reuse brand red for error state */
```

**`--color-primary` vs `--color-error`**: stay visually distinct even though
both are red-family — brand red is a UI accent (buttons, active nav,
highlights), not a status color. Don't let a failed monitoring run render in
the same red as a primary button.

**`--color-secondary`**: confirmed present in the reference, used
specifically where a trend is *favorable* (one metric's down-arrow renders
green because lower is actually good for that metric, while other declining
metrics render red). Use it the same way here — for positive/added/favorable
states, paired against `--color-primary`/`--color-error` for negative/
removed/unfavorable ones. See Part 2 for exactly how this maps to this
product's data.

## Typography

```
--font-family: 'Inter', -apple-system, 'Segoe UI', Roboto, sans-serif;

--font-size-h1: 32px / weight 700
--font-size-h2: 24px / weight 700
--font-size-h3: 18px / weight 600
--font-size-body: 15px / weight 400
--font-size-small: 13px / weight 400   /* timestamps, meta info */

--line-height-heading: 1.2
--line-height-body: 1.5
```

Headings use `--color-text`, not `--color-primary`. The reference's typeface
reads as a standard modern grotesque sans consistent with Inter — keep Inter
as the working assumption, worth final confirmation against the live site.

## Shape & Spacing

```
--radius-sm: 6px    /* inputs, small badges */
--radius-md: 10px   /* buttons */
--radius-lg: 16px   /* cards, panels */

--spacing-unit: 8px  /* all spacing in multiples of this: 8, 16, 24, 32... */
```

Rounded corners throughout — confirmed strongly present in the reference:
stat tiles, chart panels, switchers, and icon badges are all rounded.

## Generic components

**Buttons** — Primary: `--color-primary` bg, white text, `--radius-md`, bold.
Hover: `--color-primary-hover`. Secondary: white bg, `--color-primary`
border+text. Disabled: `--color-text-muted` bg, no hover.

**Cards / Panels** — white bg, `--color-border` 1px border, `--radius-lg`.
Shadow on hover only if clickable; static cards stay flat.

**Stat tiles** — metric label (small, muted, uppercase), large bold value,
small circular icon badge top-right (colored per favorable/unfavorable, not
decorative), trend indicator below (arrow + %, colored by favorability not
just direction).

**Segmented tab switcher** — one rounded-pill container, plain text+icon
items inside, only the active item gets a highlighted sub-pill. Use for any
multi-option switcher in this app.

**Simple text-tab pairs** — color + underline for the active state, for a
lightweight two-option toggle within a panel.

**Status badges** — pill shape, small text, colored bg at ~15% opacity +
solid-color text/icon. `SUCCESS`→`--color-success`, `FAILED`→`--color-error`,
`RUNNING`→`--color-warning`.

**Dashboard layout** — left sidebar, white bg, `--color-primary` filled
circular badge behind the active nav item's icon. Main content on
`--color-bg-subtle` with white cards on top.

## What NOT to do
- Don't use `--color-primary` as a large background fill on content areas.
- Don't mix sharp and rounded corners.
- Don't introduce further accent colors beyond primary/secondary without
  discussing it first — see Part 2 for the one deliberate, discussed
  exception (SIMULATED marker, which reuses `--color-warning` rather than
  adding a new color).
- Don't use `--color-secondary` decoratively — it specifically means
  favorable/added/positive.

---

# Part 2 — Applied to this product (per docs/PoC_story.md)

## Page types (discovery candidates)
Plain text label, not heavily styled — these are informational, not
status-bearing: `BLOG`, `SERVICES`, `PRICING`, `PRODUCT_LISTING`, `ABOUT`,
`CAREERS`, `CONTACT`, `WORK`, `OTHER`. Pair with a small, subtle
classification-method indicator (rule-based vs. AI-classified) — a tiny icon
or muted-text tag is enough, this doesn't need its own color.

## Discovery candidate status
- `SUGGESTED` — `--color-secondary` tint badge (this is a positive, "worth
  tracking" signal) + an "Activate" button (`--color-primary`, primary
  button style).
- `DISCARDED` — `--color-text-muted`, no badge needed, visually de-emphasized
  relative to SUGGESTED rows (e.g. lower contrast, collapsed by default
  behind a toggle rather than always shown).
- `ACTIVE` (already-tracked target) — `--color-success` badge, matching the
  existing monitoring-run status vocabulary rather than inventing a new one.

## Change types (the changes feed)
Using the same favorable/unfavorable logic established in Part 1:
- `NEW_BLOG`, `NEW_PRODUCT` → `--color-secondary` badge (added/positive).
- `PRODUCT_REMOVED` → `--color-primary` or `--color-error` badge
  (removed/negative) — use `--color-error` specifically, since this is a
  genuine "something is gone" signal closer to a status alert than a brand
  accent moment.
- `PRICE_CHANGE` → **deliberately neutral**, not forced into the favorable/
  unfavorable binary. Whether a competitor's price move is "good" or "bad"
  depends on direction AND on the viewer's own business, unlike the
  reference app's own metrics — don't guess at that. Use `--color-warning`
  (attention-worthy, not good/bad) and show the actual old→new values in
  text so the person judges it themselves.
- `PAGE_UPDATE` (generic fallback) → `--color-text-muted` badge, lowest-
  emphasis of the set — it's the least specific signal.

## The SIMULATED marker — read this before implementing
This is the single most safety-critical visual element in the app. Simulated
and real changes must never be visually confusable anywhere they appear
(the simulate-button result, the changes feed, anywhere else a change
renders). This directly protects real architectural work — every simulated
record is tagged `is_simulated: true` in the API and deliberately excluded
from the real monitoring comparison logic; the UI must carry that same
seriousness visually.

- Reuses `--color-warning` (no new color introduced — see Part 1's "what not
  to do") but with a **bolder, non-standard treatment**, distinct from the
  routine 15%-opacity status pills used elsewhere: solid `--color-warning`
  background, white bold text, paired with a 🧪 icon. This should look
  different enough from an ordinary status badge that it can't be mistaken
  for one at a glance.
- Appears immediately adjacent to the change-type badge, every single time
  a simulated record is shown — never only in one place, never omittable.
- Do not use `--color-warning` this boldly anywhere else — this specific
  treatment (solid fill + icon) is reserved for this one purpose, the same
  way `--color-secondary` is reserved for favorable/added.

## Company selector
A plain dropdown (not the segmented-tab-switcher pattern — that's for
multi-option in-page switching like data sources or candidate-status
filters; the company selector is a top-level context switch and should read
as more standard/expected, like an account or workspace switcher). Two
options: "Marketing Eye" / "The Athletes Foot". Switching it should visibly
reload the whole view below — no stale data from the previous company should
remain visible mid-transition.

## Competitor summary card (dashboard)
One card per company (there's exactly one competitor per demo company) —
name, website, count of active tracked pages, count of recent changes. This
is the one bold card-level moment on the dashboard screen; keep the rest of
that screen quiet around it.

## "Simulate a Change" button
Primary button style, on each active/tracked target row. On click: a loading
state (the real call can take several seconds — a real AI generation call is
happening, don't make this feel instant), then the result renders as a
changes-feed-style row (same change-type badge + SIMULATED marker
treatment) inline or in a modal, then also appears in the real changes feed
afterward.

## Empty and error states
Direction, not mood, matching the interface's voice rather than a person's:
- Empty candidate list: "No pages tracked yet — run discovery to find some,"
  not "Nothing here!"
- Dead-URL rejection (manual add): show the actual validation message
  returned by the API (it's already specific — e.g. "this page doesn't
  appear to exist"), don't replace it with a generic "Error" state.
- Never apologize in error copy; state what happened and what to do next.

---

## TODO
- [ ] Confirm exact hex for `--color-primary` and `--color-secondary`
      against roboticmarketer.com's live inspector — values above are visual
      estimates from a screenshot, not sampled
- [ ] Confirm font choice against the reference site if it's not Inter

## Change log
- Reviewed a real screenshot of the reference app's dashboard. Corrected
  `--color-primary` estimate, added `--color-secondary` (previously absent)
  with its favorable/added semantic documented, added Stat tile and
  Segmented tab switcher patterns.
- Added Part 2: mapped this product's actual page types, discovery statuses,
  and change types onto the Part 1 color system; defined the SIMULATED
  marker treatment as a deliberate, discussed exception; added PoC-specific
  component notes (company selector, competitor card, simulate button,
  empty/error states) per docs/PoC_story.md.
