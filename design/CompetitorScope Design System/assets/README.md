# assets

Deliberately empty.

The mounted source (`docs/`) is a documentation-only repository: it contains no logo,
no icon font or sprite, no illustrations and no imagery. Nothing has been drawn or
reconstructed to fill the gap.

- **Logo** — none. Set the name "CompetitorScope" in Inter Semibold wherever a mark
  would go. See `guidelines/brand-wordmark.card.html`.
- **Icons** — Lucide v0.544.0 from jsDelivr CDN, fetched and inlined as real `<svg>` by
  `components/core/Icon.jsx`. A flagged substitution; see readme.md > ICONOGRAPHY. To go
  offline-safe, save the SVGs into `assets/icons/` and change the `CDN` constant in
  `Icon.jsx` to that relative path — no other change is needed.
- **Fonts** — Inter from Google Fonts CDN (`tokens/fonts.css`). No binaries supplied.

Drop real files here when the team provides them, then update `tokens/fonts.css` and
this note.
