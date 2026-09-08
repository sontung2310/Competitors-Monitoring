const { ChangeRow, PriceDelta, Button, Icon } = window.CompetitorScopeDesignSystem_312ddb;

/** Screen 3 — the simulate result, rendered as changes-feed rows in a modal. */
function SimulateResult({ target, events, onClose }) {
  return (
    <div
      onClick={onClose}
      style={{ position: 'absolute', inset: 0, background: 'rgba(26,26,26,.35)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 'var(--space-4)', animation: 'cs-fade-in 180ms var(--ease-standard)' }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ background: 'var(--surface-card)', border: '1px solid var(--border-card)', borderRadius: 'var(--radius-lg)', boxShadow: 'var(--shadow-overlay)', width: 'min(680px,100%)', overflow: 'hidden' }}
      >
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 'var(--space-2)', padding: 'var(--space-3)', borderBottom: '1px solid var(--border-card)' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ font: 'var(--type-h3)', color: 'var(--text-heading)' }}>Simulation complete</div>
            <div style={{ font: 'var(--type-meta)', color: 'var(--text-meta)', marginTop: 3 }}>
              {events.length} change {events.length === 1 ? 'record' : 'records'} written for {target.url}
            </div>
          </div>
          <button onClick={onClose} style={{ border: 0, background: 'transparent', cursor: 'pointer', color: 'var(--color-text-muted)', padding: 4 }} aria-label="Close">
            <Icon name="x" size={18} />
          </button>
        </div>
        {events.map((e, i) => (
          <ChangeRow
            key={i}
            changeType={e.change_type}
            summary={e.summary}
            target={target.url.replace(/^https?:\/\//, '')}
            detectedAt="just now"
            isSimulated
            detail={e.from ? <PriceDelta from={e.from} to={e.to} /> : null}
            style={i === events.length - 1 ? { borderBottom: 0 } : undefined}
          />
        ))}
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', padding: 'var(--space-2) var(--space-3)', borderTop: '1px solid var(--border-card)', background: 'var(--color-bg-subtle)' }}>
          <div style={{ font: 'var(--type-meta)', color: 'var(--text-meta)', flex: 1 }}>
            Simulated records are excluded from the real monitoring baseline.
          </div>
          <Button size="sm" variant="secondary" onClick={onClose}>Done</Button>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { SimulateResult });
