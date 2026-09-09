One-line: the fixed 240px left nav on every dashboard screen.

```jsx
<Sidebar active="dashboard" onSelect={setView} items={[
  {value:'dashboard',label:'Dashboard',icon:'layout-dashboard'},
  {value:'competitors',label:'Competitors',icon:'users',count:1},
  {value:'changes',label:'Changes',icon:'activity',count:12},
]} />
```

Keep the sidebar white — the main content area is the tinted one (`--surface-page`).
