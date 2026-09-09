One-line: the metric tile row at the top of a dashboard — label, big number, favorability-colored icon badge and trend.

```jsx
<StatTile label="Active targets" value={3} icon="crosshair" />
<StatTile label="Changes this week" value={12} icon="activity" favorable trend={{direction:'up',label:'+4 vs last week'}} />
```

Set `favorable` from meaning, not direction. The icon badge is semantic, never decorative.
