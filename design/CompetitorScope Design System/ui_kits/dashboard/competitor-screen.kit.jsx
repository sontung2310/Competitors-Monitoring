const { CandidateRow, SimulateButton, SegmentedSwitcher, Button, Input, EmptyState, Card } = window.CompetitorScopeDesignSystem_312ddb;

/** Screen 2 — competitor detail / discovery review, plus the manual-add liveness gate. */
function CompetitorScreen({ companyId, targets, onActivate, onDiscard, onSimulate, simulatingId, discovering, onAddManual }) {
  const [tab, setTab] = React.useState('SUGGESTED');
  const [adding, setAdding] = React.useState(false);
  const [url, setUrl] = React.useState('');
  const [err, setErr] = React.useState('');

  const counts = {
    SUGGESTED: targets.filter((t) => t.discovery_status === 'SUGGESTED').length,
    ACTIVE: targets.filter((t) => t.discovery_status === 'ACTIVE').length,
    DISCARDED: targets.filter((t) => t.discovery_status === 'DISCARDED').length,
  };
  const rows = targets.filter((t) => t.discovery_status === tab);

  function submit() {
    // Mirrors the API's liveness gate: the real validation message is shown verbatim.
    if (!/^https?:\/\/\S+\.\S+/.test(url)) { setErr('this page doesn’t appear to exist'); return; }
    setErr(''); setUrl(''); setAdding(false); onAddManual(url);
  }

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
        <SegmentedSwitcher
          value={tab}
          onChange={setTab}
          options={[
            { value: 'SUGGESTED', label: 'Suggested', icon: 'radar', count: counts.SUGGESTED },
            { value: 'ACTIVE', label: 'Active', icon: 'crosshair', count: counts.ACTIVE },
            { value: 'DISCARDED', label: 'Discarded', icon: 'archive', count: counts.DISCARDED },
          ]}
        />
        <Button variant="secondary" size="sm" icon="plus" onClick={() => setAdding((v) => !v)}>Add manually</Button>
      </div>

      {adding && (
        <Card>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 'var(--space-2)' }}>
            <Input
              style={{ flex: 1 }}
              label="Page URL"
              icon="link"
              placeholder="https://lyfemarketing.com/pricing"
              value={url}
              error={err}
              hint="The URL is liveness-checked before it is saved."
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submit()}
            />
            <Button onClick={submit} style={{ marginBottom: err ? 22 : 0 }}>Add</Button>
          </div>
        </Card>
      )}

      <window.Panel
        title={tab === 'ACTIVE' ? 'Tracked pages' : tab === 'SUGGESTED' ? 'Discovered candidates' : 'Discarded candidates'}
        right={<Button variant="secondary" size="sm" icon="refresh-cw" loading={discovering}>{discovering ? 'Running discovery…' : 'Run Discovery'}</Button>}
      >
        {rows.length === 0 ? (
          <EmptyState
            icon="radar"
            message={tab === 'ACTIVE' ? 'No pages tracked yet — activate a suggested candidate to start monitoring.' : 'No candidates here — run discovery to find some.'}
          />
        ) : (
          rows.map((t, i) => (
            <CandidateRow
              key={t.id}
              url={t.url}
              pageType={t.page_type}
              method={t.classification_method}
              status={t.discovery_status}
              interval={t.interval}
              style={i === rows.length - 1 ? { borderBottom: 0 } : undefined}
              actions={
                t.discovery_status === 'SUGGESTED' ? (
                  <>
                    <Button size="sm" onClick={() => onActivate(t.id)}>Activate</Button>
                    <Button size="sm" variant="quiet" onClick={() => onDiscard(t.id)}>Discard</Button>
                  </>
                ) : t.discovery_status === 'ACTIVE' ? (
                  <SimulateButton loading={simulatingId === t.id} onClick={() => onSimulate(t)} />
                ) : (
                  <Button size="sm" variant="quiet" onClick={() => onActivate(t.id)}>Restore</Button>
                )
              }
            />
          ))
        )}
      </window.Panel>
    </>
  );
}

Object.assign(window, { CompetitorScreen });
