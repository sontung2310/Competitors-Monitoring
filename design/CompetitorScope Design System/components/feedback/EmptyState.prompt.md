One-line: centered placeholder for an empty list or a failed read — one directional sentence plus the action that fixes it.

```jsx
<EmptyState icon="radar" message="No pages tracked yet — run discovery to find some."
  action={<Button icon="refresh-cw">Run Discovery</Button>} />
```

No "Nothing here!", no "Oops", no apology. For API errors, pass the API's own message through.
