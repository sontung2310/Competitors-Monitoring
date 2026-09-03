# Design Guidelines — Frontend (Django)

Visual reference: [roboticmarketer.com](https://www.roboticmarketer.com/) —
match its color direction, corporate confidence, and dashboard/execution-tool
feel. Values below marked "placeholder" should be swapped for exact values
once you've pulled them from the reference site's inspector.

---

## Color Palette

```
--color-primary:        #E4002B   /* placeholder — bold marketing red, swap for exact hex from reference */
--color-primary-hover:  #C40025   /* ~10% darker, for hover/active states */
--color-primary-light:  #FDE8EA   /* tint for badges, subtle highlights, selected states */

--color-bg:              #FFFFFF
--color-bg-subtle:       #F7F7F8   /* section backgrounds, alternating rows */

--color-text:            #1A1A1A  /* primary text */
--color-text-muted:      #6B7280  /* secondary text, timestamps, labels */

--color-border:          #E5E7EB

--color-success:         #16A34A  /* e.g. SUCCESS monitoring run status */
--color-warning:         #D97706  /* e.g. pending review */
--color-error:           #DC2626  /* e.g. FAILED monitoring run status — distinct from --color-primary, don't reuse brand red for error state */
```

**Note:** `--color-primary` and `--color-error` must stay visually distinct
even though both are red-family — the brand red is a UI accent (buttons,
active nav, highlights), not a status color. Don't let a failed monitoring
run render in the same red as the "Get Started" button.

## Typography

Bold, confident sans-serif for headings; clean and readable for body copy —
matching the reference site's corporate-but-modern tone.

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

Headings use `--color-text`, not `--color-primary` — reserve the brand red
for interactive/accent elements, not for text color at heading scale.

## Shape & Spacing

```
--radius-sm: 6px    /* inputs, small badges */
--radius-md: 10px   /* buttons */
--radius-lg: 16px   /* cards, panels */

--spacing-unit: 8px  /* all spacing in multiples of this: 8, 16, 24, 32... */
```

Rounded corners throughout — no sharp/square edges on cards, buttons, or
inputs.

## Components

### Buttons
- Primary: `--color-primary` background, white text, `--radius-md`, bold weight
- Primary hover: `--color-primary-hover`
- Secondary: white background, `--color-primary` border + text
- Disabled: `--color-text-muted` background, no hover state

### Cards / Panels
- White background, `--color-border` 1px border, `--radius-lg`
- Subtle shadow on hover only if the card is clickable (e.g. a competitor
  card linking to detail view) — static cards stay flat

### Status badges
Use color, not just text, for monitoring run / change status:
- `SUCCESS` → `--color-success`
- `FAILED` → `--color-error`
- `RUNNING` → `--color-warning`
- Pill shape (`--radius-sm` or fully rounded), small text, colored
  background at ~15% opacity + solid-color text/icon

### Dashboard layout
- Left sidebar navigation, white background, `--color-primary` for the
  active nav item's indicator/icon (not full background fill)
- Main content area on `--color-bg-subtle` with white cards on top, for
  visual separation between page chrome and content

---

## What NOT to do
- Don't use `--color-primary` as a large background fill on content areas —
  it's an accent, not a wallpaper.
- Don't mix sharp and rounded corners across components — pick rounded
  everywhere per the direction above.
- Don't introduce a second accent color without discussing it — red + white
  + neutrals is the palette; status colors (success/warning/error) are the
  only exception.

## TODO
- [ ] Replace `--color-primary` placeholder hex with the exact value from
      roboticmarketer.com once pulled from their site's CSS/inspector
- [ ] Confirm font choice against the reference site if it's not Inter
