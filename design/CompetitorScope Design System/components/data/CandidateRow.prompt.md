One-line: one candidate or tracked page, with its type, classification method, status and row actions.

```jsx
<CandidateRow url="https://lyfemarketing.com/blog" pageType="BLOG" method="RULE" status="SUGGESTED"
  actions={<><Button size="sm">Activate</Button><Button size="sm" variant="quiet">Discard</Button></>} />

<CandidateRow url="https://lyfemarketing.com/blog" pageType="BLOG" status="ACTIVE" interval="6 h"
  actions={<SimulateButton loading={busy} onClick={simulate} />} />
```

Discarded rows stay in the list at reduced contrast, usually behind a "show discarded" switch.
