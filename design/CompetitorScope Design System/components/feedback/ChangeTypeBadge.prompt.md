One-line: the change_type badge for a changes-feed row, with the favorable/neutral/unfavorable mapping baked in.

```jsx
<ChangeTypeBadge type="PRICE_CHANGE" />
<PriceDelta from="$129.95" to="$99.95" />
```

Do not override the tone. `PRICE_CHANGE` stays neutral even when the direction looks obviously good or bad.
