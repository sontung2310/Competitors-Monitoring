One-line: renders 🧪 SIMULATED — required on every appearance of a change or snapshot whose `is_simulated` flag is true, in the simulate result, in the changes feed, everywhere.

```jsx
<ChangeTypeBadge type="NEW_BLOG" />
{change.is_simulated && <SimulatedBadge />}
```

Do not restyle it, do not gate it behind a filter or a toggle, and do not use solid `--color-warning` anywhere else in the product.
