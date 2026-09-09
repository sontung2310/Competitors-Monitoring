One-line: single-line text field, 6px radius, red focus border — used for URL entry in the manual-add flow.

```jsx
<Input label="Page URL" placeholder="https://competitor.com/pricing" icon="link"
  error={apiError /* "this page doesn't appear to exist" — pass the API message through */} />
```

Never replace an API validation message with "Error". Never apologize in the copy.
