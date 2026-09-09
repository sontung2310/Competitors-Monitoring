One-line: a single detected change in the chronological feed.

```jsx
<ChangeRow changeType="NEW_BLOG" summary="New post: “7 B2B Content Trends for 2026”"
  target="lyfemarketing.com/blog" detectedAt="2 hours ago" />

<ChangeRow changeType="PRICE_CHANGE" summary="Nike Pegasus 41 price changed"
  detail={<PriceDelta from="$219.99" to="$179.99" />} detectedAt="just now" isSimulated />
```

Pass `isSimulated` straight from the record. Show the record's own summary text; don't paraphrase it.
