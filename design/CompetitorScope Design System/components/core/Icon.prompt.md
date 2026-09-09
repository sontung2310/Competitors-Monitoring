One-line: masked Lucide glyph that inherits text color — use it anywhere the UI needs an icon, since the source repo ships no icon assets of its own.

```jsx
<Icon name="layout-dashboard" size={18} />
<Icon name="trending-down" size={14} color="var(--signal-favorable)" />
```

Names are Lucide kebab-case. Common ones in this product: `layout-dashboard`, `users`, `activity`, `settings`, `search`, `plus`, `chevron-down`, `external-link`, `refresh-cw`, `trending-up`, `trending-down`, `clock`, `file-text`, `package`, `tag`.

Emoji are **not** replaced by Icon in two places the source pins verbatim: the 🧪 SIMULATED badge and the 🎭 Simulate a Change button.
