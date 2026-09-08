const { StatTile, CompetitorCard, ChangeRow, PriceDelta, RunStatusBadge, Button } = window.CompetitorScopeDesignSystem_312ddb;

/** Screen 1 — company selector result: stat tiles, the one bold competitor card, recent feed. */
function DashboardScreen({ companyId, onOpenCompetitor }) {
  const D = window.CS_DATA;
  const comp = D.competitors[companyId];
  const targets = D.targets[companyId];
  const changes = D.changes[companyId];
  const active = targets.filter((t) => t.discovery_status === 'ACTIVE');
  const failed = D.runs[companyId].filter((r) => r.status === 'FAILED').length;

  return (
    <>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 'var(--card-gap)' }}>
        <StatTile label="Active pages" value={active.length} icon="crosshair" />
        <StatTile label="Changes / 7d" value={changes.length} icon="activity" favorable trend={{ direction: 'up', label: '+2 vs last week' }} />
        <StatTile label="Failed runs" value={failed} icon="alert-triangle" favorable={failed === 0} trend={failed ? { direction: 'up', label: '+1 today' } : undefined} />
      </div>

      <CompetitorCard
        name={comp.name}
        website={comp.website_url}
        activeTargets={active.length}
        recentChanges={changes.length}
        onOpen={onOpenCompetitor}
      />

      <window.Panel
        title="Recent updates"
        right={<Button variant="quiet" size="sm" iconAfter="chevron-right" onClick={() => onOpenCompetitor('changes')}>View all</Button>}
      >
        {changes.slice(0, 3).map((c, i) => (
          <ChangeRow
            key={c.id}
            changeType={c.change_type}
            summary={c.summary}
            target={c.target}
            detectedAt={c.detected_at}
            isSimulated={c.is_simulated}
            detail={c.from ? <PriceDelta from={c.from} to={c.to} /> : null}
            style={i === 2 ? { borderBottom: 0 } : undefined}
          />
        ))}
      </window.Panel>

      <window.Panel title="Latest monitoring runs">
        {D.runs[companyId].map((r, i, arr) => (
          <div key={r.id} style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', padding: 'var(--space-2) var(--space-3)', borderBottom: i === arr.length - 1 ? 0 : '1px solid var(--border-card)' }}>
            <div style={{ flex: 1, minWidth: 0, font: 'var(--type-body)', color: 'var(--text-body)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.target}</div>
            <RunStatusBadge status={r.status} />
            <div style={{ font: 'var(--type-meta)', color: 'var(--text-meta)', whiteSpace: 'nowrap' }}>{r.at}</div>
          </div>
        ))}
      </window.Panel>
    </>
  );
}

Object.assign(window, { DashboardScreen });
