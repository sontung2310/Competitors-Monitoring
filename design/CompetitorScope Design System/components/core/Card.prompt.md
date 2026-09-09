One-line: the container for everything on a dashboard — white, bordered, 16px radius, flat.

```jsx
<Card clickable onClick={open}>
  <CardHeader title="Lyfe Marketing" meta="lyfemarketing.com" actions={<Button size="sm" variant="quiet">View</Button>} />
  …
</Card>
```

Never fill a card with brand red. Don't mix radii — a card is always `--radius-lg`.
