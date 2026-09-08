# CompetitorScope Design System

Design system for **CompetitorScope** — a competitive-intelligence monitoring tool for
marketing agencies and retail brands. It watches named competitors' public websites and
reports what changed: new blog posts, new or removed products, price moves, generic page
updates. Users work in a company-switchable web dashboard with a discovery/review flow
and a live "simulate a change" demo trigger.

## Product context

The system monitors in two layers:

- **Layer 1** — the competitor's domain. Not monitored directly; its job is to *discover*
  candidate pages via `robots.txt`, sitemaps and on-page links.
- **Layer 2** — specific discovered pages (`/blog`, `/pricing`, `/products`). These are the
  real monitoring targets: fetch → normalize → hash → compare → diff → change records.

Human control sits between the layers: discovery produces `SUGGESTED` candidates, and a
person activates the ones worth tracking. `DISCARDED` candidates are never deleted, only
de-emphasized, because a rule or LLM classifier can be wrong.

### Surfaces represented

There is exactly one product surface in the source material: the **PoC monitoring
dashboard** (Django frontend against a Flask API). Its four screens are:

1. Company selector + competitors dashboard
2. Competitor detail / discovery review
3. Simulate a Change (the demo centerpiece)
4. Changes feed

The two demo tenants are Marketing Eye (competitor: Lyfe Marketing) and The Athletes Foot
(competitor: JD Sports AU). `docs/architecture.html` is an internal engineering diagram,
not a product surface, and is deliberately not treated as brand.

### Sources this system was built from

Read-only local codebase mounted at `docs/` (documentation-only repo — no frontend code,
no assets, no font binaries):

| File | What it gave this system |
|---|---|
| `docs/design-guidelines.md` | **Primary source.** Full brand system: color palette, type scale, radii, spacing unit, component patterns, and Part 2's product-specific applications (badge semantics, SIMULATED marker, company selector, empty-state voice). |
| `docs/PoC_story.md` | The four-screen demo narrative, the two tenants, the simulate flow, the `is_simulated` rule. |
| `docs/api-contract.md` | Every enum, field name and error shape the UI renders. |
| `docs/specs.md` | Monitoring architecture, data model, change-type list, page-type list, the §18/§19 text wireframes for the dashboard and discovery screens. |
| `docs/roadmap.md` | Build-order context only. |
| `docs/architecture.html` | Internal diagram; not used as brand. |

`docs/design-guidelines.md` names [roboticmarketer.com](https://www.roboticmarketer.com/)
as its visual reference and marks both brand hexes as **visual estimates from a
screenshot, not sampled** — with an open TODO to confirm them against the live inspector.
Those estimates are what this system encodes. See "Open questions" below.

---

## CONTENT FUNDAMENTALS

**Voice: an instrument reporting, not a person talking.** The product's job is to answer
one question — *what has changed on my competitors' side since the last monitoring cycle?*
— so copy states facts and next actions and stops.

- **Person.** Second person only where an action is being asked of the reader
  ("run discovery to find some"). Never first person; the system never says "I" or "we",
  and never speaks for the user's business.
- **Casing.** Sentence case for headings, labels and buttons ("Add manually", "Run
  Discovery", "Tracked pages"). **API enums stay verbatim and uppercase** — `NEW_BLOG`,
  `PRODUCT_LISTING`, `SUGGESTED`, `SUCCESS`. The UI speaks the API's vocabulary rather
  than prettifying it; a designer inventing "New blog post" breaks the mapping between
  what the screen says and what the record holds.
- **Empty states: direction, not mood.** Say what is absent and what produces it.
  ✅ "No pages tracked yet — run discovery to find some."
  ❌ "Nothing here!" / "Looks a bit empty in here 👀"
- **Errors: never apologize.** State what happened and what to do next. When the API
  returns a specific message, show it verbatim — the manual-add liveness gate already
  answers with "this page doesn't appear to exist", which is more useful than any generic
  "Error" state a designer would substitute.
- **Numbers over adjectives.** A price change renders `$219.99 → $179.99`, not "price
  dropped significantly". Whether a competitor's move is good or bad depends on the
  viewer's own business; the product refuses to guess.
- **Summaries are quoted, not rewritten.** A change record's `summary` string comes from
  the pipeline and renders as-is.
- **Emoji: two, both load-bearing, both pinned by the source.** 🧪 on the SIMULATED badge
  and 🎭 on the "Simulate a Change" button. No decorative emoji anywhere else — no emoji
  in headings, empty states, or error copy.
- **Vibe.** Corporate confidence. An execution tool a marketing manager keeps open in a
  tab, not a consumer app. Dense, quiet, factual; the interface earns attention by being
  accurate, not by being lively.

Sample copy in the product's register:

> Recent updates · New post: "7 B2B Content Trends for 2026" · 2 hours ago
> No pages tracked yet — run discovery to find some.
> Running discovery — this makes real requests and can take a few seconds.
> Generated by the simulation tool — not a real detected change.

---

## VISUAL FOUNDATIONS

**Colors.** A three-part palette and nothing more. Brand red `#E4362A` (warm fire-engine,
deliberately *not* magenta-leaning) is a UI accent — buttons, active nav, highlights,
selected states — never a large background fill on content. Mint `#2FBF8F` is reserved for
*favorable / added / positive* and is never decorative. Status colors (`#16A34A` success,
`#D97706` warning, `#DC2626` error) stay visually distinct from brand red: a failed
monitoring run must not render in the same red as a primary button. No fourth accent may
be introduced without discussion — the one deliberate exception in the source reuses
`--color-warning` for the SIMULATED marker rather than adding a color.

**Favorability, not direction.** The reference app colors a falling metric green when
lower is better. This system inherits that: `favorable` is a judgement the caller passes
in, independent of whether the arrow points up or down. `PRICE_CHANGE` is deliberately
excluded from the binary and renders amber — attention-worthy, not good or bad.

**Type.** Inter (400/500/600/700) at five sizes: 32/24/18/15/13. Nothing between, nothing
above. Headings are ink `#1A1A1A`, never brand red. Line-height 1.2 on headings, 1.5 on
body. Uppercase 13px semibold with 0.06em tracking for metric labels; tabular figures for
every number so counts and prices don't jitter between renders.

**Spacing.** One 8px unit, multiples only — 8/16/24/32/40/48/64. No half-steps. Cards take
24px padding, sit 16px apart, on a 32px page gutter. The sidebar is a fixed 240px.

**Backgrounds.** Flat color only. No imagery, no illustration, no gradients, no textures,
no patterns. The dashboard is a two-tone system: white sidebar and white cards floating on
the `#F7F7F8` content ground. There are no photographs, hero images or brand illustrations
anywhere in the source, and none have been invented — so there is no imagery color vibe to
describe. If real imagery is later supplied, it should stay cool and neutral to keep the
red accent as the only warm note on screen.

**Corners.** Rounded throughout, at three steps: 6px inputs and small badges, 10px
buttons, 16px cards and panels, full pill for status badges, segmented switchers and the
circular icon badges. Sharp and rounded corners are never mixed in the same view.

**Cards.** White fill, 1px `#E5E7EB` border, 16px radius, **flat**. A card takes a shadow
only if it is clickable, and only on hover. Static panels stay borderless-of-shadow
forever. There is no border-left accent-color card pattern in this system.

**Shadows.** Two, both functional: `0 4px 16px rgba(26,26,26,.08)` for a hovered clickable
card, `0 12px 32px rgba(26,26,26,.14)` for overlays (dropdown menus, the simulate modal).
No inner shadows. No shadow on buttons or badges.

**Borders.** A single 1px `#E5E7EB` hairline does all the structural work — card edges,
row dividers, the sidebar rule, the topbar underline, input outlines. Focused inputs swap
the hairline to brand red; invalid ones to error red. Active text tabs use a 2px brand-red
underline. No double borders, no dividers heavier than 1px.

**Hover states.** Primary buttons darken to `#C42E22`. Secondary buttons fill with the
brand tint `#FDE8E5`. Quiet buttons and sidebar rows fill with `#F7F7F8` and their label
darkens from muted to ink. Clickable cards gain the hover shadow. Nothing changes opacity
on hover and nothing moves.

**Press states.** Color only — the pressed state is the hover color held. Nothing shrinks,
scales, or lifts. Disabled primary buttons go muted-grey filled with no hover at all.

**Animation.** Restrained and functional. 120ms color/background transitions on controls,
180ms shadow on card hover, both on `cubic-bezier(.4,0,.2,1)`. A spinner rotation for
in-flight discovery and simulate calls — those hit real HTTP crawls and a real LLM
generation, take several seconds, and must never feel instant. No fades on page content,
no bounces, no slide-ins, no staggered reveals, no scroll-driven motion.

**Transparency and blur.** Transparency appears in exactly one place: status-badge
backgrounds at ~15% opacity over white. There is no glass, no backdrop blur, no scrim
gradient, no protection gradient — badges sit on solid surfaces, so a solid tint suffices.
Overlays use a plain dark scrim, not blur.

**Layout rules.** Fixed 240px left sidebar, white, full height, with the company selector
pinned at its foot. A white `TopBar` with a 1px underline holds the screen title and that
screen's own actions. Main content scrolls on the tinted ground, max content width around
1100px, single column of stacked cards or a 3-up stat-tile grid. Rows inside a card are
divided by hairlines, not gaps. Nothing is sticky except the sidebar and topbar.

**The one bold moment per screen.** The source is explicit that the dashboard's competitor
card is the single bold card-level element and the rest of that screen should stay quiet
around it. Apply the same discipline elsewhere: one primary button, one bold card, one
focal number per view.

---

## ICONOGRAPHY

**⚠️ Substitution flagged.** The mounted `docs/` repo is documentation-only: it contains
**no icon font, no SVG sprite, no PNG icons and no logo files**. `docs/design-guidelines.md`
describes icons functionally ("small circular icon badge top-right", "plain text+icon
items") without naming a set.

- **Substituted set: [Lucide](https://lucide.dev) v0.544.0, loaded from jsDelivr CDN.**
  Chosen because it is a 24×24, 2px-stroke, rounded-cap outline set — the closest common
  match to the reference app's light outline icons — and because it needs no binaries.
  `components/core/Icon.jsx` fetches each glyph's SVG once, caches it, and renders it as a
  real inline `<svg>` with `stroke="currentColor"` — so icons inherit text color and
  composite correctly. (An earlier CSS `mask-image` approach pointing at the same CDN URL
  did not paint; don't reintroduce it.) Nothing is committed to `assets/` — if the team
  prefers offline-safe icons, drop the SVGs into `assets/icons/` and point `CDN` in
  `Icon.jsx` at that relative path.
- **Style rules.** Outline only, never filled. 12px inside badges, 14px in small buttons,
  16px in controls and rows, 18px in nav and icon badges, 24px in empty states. Icons take
  the surrounding text color, except inside a stat tile's circular badge where they carry
  the favorability color. Icons are decorative in the accessibility sense — every one is
  paired with a text label, none carries meaning alone.
- **Circular icon badges.** 28px in the sidebar (brand-red fill behind the active item's
  icon), 36px in stat tiles (favorability tint behind a favorability-colored glyph). These
  are semantic, per the source: "colored per favorable/unfavorable, not decorative".
- **Emoji.** Used deliberately, in two places only, both pinned verbatim by the source
  documents: **🧪** on the SIMULATED badge and **🎭** on the "Simulate a Change" button.
  These are not substitutions and should not be swapped for icons. No other emoji.
- **Unicode as icon.** One case: the arrow in a price delta (`$219.99 → $179.99`) is a
  literal → in muted ink, not an icon.
- **Logo.** None supplied. Wherever a mark would go — sidebar header, thumbnail, slide
  corner — the name **CompetitorScope** is set in Inter Semibold with -0.02em tracking. No
  mark has been drawn, reconstructed or approximated. See `guidelines/brand-wordmark.card.html`.

Common glyphs in this product: `layout-dashboard`, `users`, `activity`, `settings`,
`crosshair`, `radar`, `refresh-cw`, `plus`, `link`, `external-link`, `chevron-down`,
`chevron-right`, `file-text`, `file-diff`, `package-plus`, `package-minus`, `tag`,
`megaphone`, `award`, `clock`, `alert-triangle`, `arrow-up`, `arrow-down`, `ruler`,
`sparkles`, `user`, `inbox`.

---

## Index

Root manifest:

| Path | What it is |
|---|---|
| `readme.md` | This file — product context, content fundamentals, visual foundations, iconography, index. |
| `SKILL.md` | Agent-Skills front matter so this folder works as a Claude Code skill. |
| `styles.css` | The only stylesheet consumers link. `@import` lines only. |
| `thumbnail.html` | Homepage tile for this design system. |
| `tokens/` | `fonts.css`, `colors.css`, `typography.css`, `spacing.css`, `shape.css`, `motion.css`, `keyframes.css`. |
| `guidelines/` | 15 foundation specimen cards (Colors, Type, Spacing, Brand). |
| `components/` | Reusable primitives, grouped by concern. |
| `ui_kits/` | Full-screen product recreations. |
| `assets/` | Empty by design — the source supplies no logo, imagery or icon files. |

### Components

Grouped by concern. Each directory holds `<Name>.jsx`, `<Name>.d.ts`,
`<Name>.prompt.md` and one `@dsCard` HTML.

**`components/core/`** — Icon, Button, Card (+ CardHeader), Input, Select

**`components/feedback/`** — StatusBadge (+ RunStatusBadge, DiscoveryStatusBadge),
SimulatedBadge, ChangeTypeBadge (+ PriceDelta), PageTypeLabel (+ ClassificationTag),
EmptyState

**`components/navigation/`** — Sidebar, TopBar, SegmentedSwitcher (+ TextTabs)

**`components/data/`** — StatTile, CompetitorCard, CandidateRow (+ SimulateButton),
ChangeRow

Full list, alphabetically: `Button`, `CandidateRow`, `Card`, `CardHeader`,
`ChangeRow`, `ChangeTypeBadge`, `ClassificationTag`, `CompetitorCard`,
`DiscoveryStatusBadge`, `EmptyState`, `Icon`, `Input`, `PageTypeLabel`, `PriceDelta`,
`RunStatusBadge`, `SegmentedSwitcher`, `Select`, `Sidebar`, `SimulateButton`,
`SimulatedBadge`, `StatTile`, `StatusBadge`, `TextTabs`, `TopBar`.

### Component inventory provenance

Every family above has a counterpart in `docs/design-guidelines.md` or the API contract:
Buttons, Cards/Panels, Stat tiles, Segmented tab switcher, Simple text-tab pairs, Status
badges, Dashboard layout (sidebar), page-type labels, discovery-status badges,
change-type badges, the SIMULATED marker, the company selector, the competitor summary
card, the Simulate a Change button, and empty/error states.

**Intentional additions** (not in the source, added because the source's own patterns
cannot be built without them):

- **`Icon`** — a glyph wrapper. The source describes icons but ships none; every
  icon-bearing pattern it defines needs a single place where the substituted set and its
  sizing live.
- **`TopBar`** — the source's §18/§19 text wireframes show a screen title with actions
  beside it on every screen, but never name the container.
- **`Input`** — required by the "+ Add manually" flow and its verbatim-API-error rule; the
  source specifies the error behavior and the 6px input radius but no field component.
- **`PriceDelta`** — the source mandates showing "the actual old→new values in text"; this
  is that instruction as a component.

No Toast, Avatar, Tooltip, Dialog, Accordion or other standard-set primitive has been
added, because the source defines none.

### UI kits

| Path | Product surface |
|---|---|
| `ui_kits/dashboard/` | The PoC monitoring dashboard — company selector, competitors dashboard, competitor detail/discovery, simulate flow, changes feed. |

---

## Open questions for the team

1. **Confirm the brand hexes.** `--color-primary` (`#E4362A`) and `--color-secondary`
   (`#2FBF8F`) are the source doc's own visual estimates from a screenshot, carried
   forward unchanged. Its TODO asks for inspector-sampled values.
2. **Confirm the typeface.** Inter is the source's stated working assumption, also pending
   confirmation against the reference site. No font binaries were provided, so Inter is
   loaded from Google Fonts — send self-hosted files if the team has them.
3. **Send a logo**, or confirm the wordmark-in-type treatment is the intended identity.
4. **Confirm the icon set.** Lucide is a substitution. If the real product uses a
   different set, name it and this system will swap.
5. **No imagery of any kind** exists in the sources — no photography, illustration or
   background art. If the brand has any, it belongs here.
