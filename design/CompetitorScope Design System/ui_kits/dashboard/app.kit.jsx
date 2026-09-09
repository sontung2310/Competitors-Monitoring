const { Button, RunStatusBadge } = window.CompetitorScopeDesignSystem_312ddb;

function App() {
  const D = window.CS_DATA;
  const [companyId, setCompanyId] = React.useState('me');
  const [view, setView] = React.useState('dashboard');
  const [targets, setTargets] = React.useState(() => JSON.parse(JSON.stringify(D.targets)));
  const [changes, setChanges] = React.useState(() => JSON.parse(JSON.stringify(D.changes)));
  const [simulatingId, setSimulatingId] = React.useState(null);
  const [result, setResult] = React.useState(null);
  const [discovering, setDiscovering] = React.useState(false);
  const [reloading, setReloading] = React.useState(false);

  const comp = D.competitors[companyId];

  // A company switch reloads the whole view below — no stale rows from the previous company.
  function switchCompany(id) {
    setReloading(true);
    setResult(null);
    setView('dashboard');
    setTimeout(() => { setCompanyId(id); setReloading(false); }, 320);
  }

  function setStatus(id, status) {
    setTargets((prev) => ({
      ...prev,
      [companyId]: prev[companyId].map((t) => (t.id === id ? { ...t, discovery_status: status, interval: status === 'ACTIVE' ? t.interval || '12 h' : t.interval } : t)),
    }));
  }

  function addManual(url) {
    setTargets((prev) => ({
      ...prev,
      [companyId]: [{ id: 'm' + Date.now(), url, page_type: 'OTHER', classification_method: 'MANUAL', discovery_status: 'SUGGESTED' }, ...prev[companyId]],
    }));
  }

  function runDiscovery() { setDiscovering(true); setTimeout(() => setDiscovering(false), 2200); }

  function simulate(target) {
    setSimulatingId(target.id);
    setTimeout(() => {
      const events = (D.simulations[target.page_type] || D.simulations.BLOG).map((e) => ({ ...e }));
      setSimulatingId(null);
      setResult({ target, events });
      setChanges((prev) => ({
        ...prev,
        [companyId]: [
          ...events.map((e, i) => ({ id: 's' + Date.now() + i, change_type: e.change_type, summary: e.summary, from: e.from, to: e.to, target: target.url.replace(/^https?:\/\//, ''), detected_at: 'just now', is_simulated: true })),
          ...prev[companyId],
        ],
      }));
    }, 1900);
  }

  const titles = {
    dashboard: { title: D.companies.find((c) => c.id === companyId).name, meta: 'Competitive monitoring overview' },
    competitor: { breadcrumb: 'Competitors', title: comp.name, meta: comp.website_url },
    changes: { title: 'Changes', meta: `Chronological feed for ${comp.name}` },
    runs: { title: 'Monitoring runs', meta: 'Latest Layer 2 fetch results' },
  };
  const t = titles[view];

  const actions =
    view === 'competitor'
      ? <Button variant="secondary" size="sm" icon="refresh-cw" loading={discovering} onClick={runDiscovery}>{discovering ? 'Running discovery…' : 'Run Discovery'}</Button>
      : view === 'dashboard'
        ? <Button size="sm" icon="users" onClick={() => setView('competitor')}>Review candidates</Button>
        : null;

  return (
    <div style={{ position: 'relative', height: '100%' }}>
      <window.Shell view={view} onView={setView} companyId={companyId} onCompany={switchCompany} {...t} actions={actions}>
        {reloading ? (
          <div style={{ font: 'var(--type-body)', color: 'var(--text-meta)', padding: 'var(--space-6)', textAlign: 'center' }}>Loading company data…</div>
        ) : view === 'dashboard' ? (
          <window.DashboardScreen companyId={companyId} onOpenCompetitor={(v) => setView(v === 'changes' ? 'changes' : 'competitor')} />
        ) : view === 'competitor' ? (
          <window.CompetitorScreen
            companyId={companyId}
            targets={targets[companyId]}
            onActivate={(id) => setStatus(id, 'ACTIVE')}
            onDiscard={(id) => setStatus(id, 'DISCARDED')}
            onSimulate={simulate}
            simulatingId={simulatingId}
            discovering={discovering}
            onAddManual={addManual}
          />
        ) : view === 'changes' ? (
          <window.ChangesScreen changes={changes[companyId]} />
        ) : (
          <window.Panel title="Monitoring runs">
            {D.runs[companyId].map((r, i, arr) => (
              <div key={r.id} style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', padding: 'var(--space-2) var(--space-3)', borderBottom: i === arr.length - 1 ? 0 : '1px solid var(--border-card)' }}>
                <div style={{ flex: 1, minWidth: 0, font: 'var(--type-body)' }}>{r.target}</div>
                <RunStatusBadge status={r.status} />
                <div style={{ font: 'var(--type-meta)', color: 'var(--text-meta)' }}>{r.at}</div>
              </div>
            ))}
          </window.Panel>
        )}
      </window.Shell>
      {result && <window.SimulateResult target={result.target} events={result.events} onClose={() => setResult(null)} />}
    </div>
  );
}

// Mounted by an inline script in index.html — this file must have NO top-level side
// effects, because the design-system compiler evaluates every .jsx in the project.
Object.assign(window, { App });
