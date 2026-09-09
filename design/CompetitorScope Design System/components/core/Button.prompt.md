One-line: the product's button — primary for the one committing action in a view, secondary for alternatives, quiet for row-level utilities.

```jsx
<Button variant="primary" onClick={activate}>Activate</Button>
<Button variant="secondary" icon="refresh-cw" loading={running}>Run Discovery</Button>
<Button variant="quiet" size="sm">Discard</Button>
```

Disabled renders muted-grey filled with no hover (source rule). `loading` is required on Run Discovery and Simulate a Change — both hit real network/LLM calls that take several seconds.
