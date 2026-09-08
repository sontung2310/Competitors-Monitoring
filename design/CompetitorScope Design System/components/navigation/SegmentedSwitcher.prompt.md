One-line: the in-page option switcher — candidate-status filters, feed scopes, anything with 2–4 mutually exclusive views.

```jsx
<SegmentedSwitcher value={tab} onChange={setTab}
  options={[{value:'SUGGESTED',label:'Suggested',count:6},{value:'ACTIVE',label:'Active',count:3},{value:'DISCARDED',label:'Discarded',count:11}]} />

<TextTabs value={pane} onChange={setPane} options={[{value:'changes',label:'Changes'},{value:'targets',label:'Tracked pages'}]} />
```

Not for the company selector — that is a `Select`, on purpose.
