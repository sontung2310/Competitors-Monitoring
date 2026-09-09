One-line: the standard dropdown — reach for it on top-level context switches (company selector), never for in-page option filtering.

```jsx
<Select label="Company" value={companyId} options={companies.map(c => ({value: c.id, label: c.name}))} onChange={setCompanyId} />
```

Switching a company selector must visibly reload the whole view below it — no stale rows from the previous company may remain on screen mid-transition.
