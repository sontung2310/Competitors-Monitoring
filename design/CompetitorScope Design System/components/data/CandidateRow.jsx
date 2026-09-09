import React from 'react';
import { Button } from '../core/Button.jsx';
import { PageTypeLabel } from '../feedback/PageTypeLabel.jsx';
import { DiscoveryStatusBadge } from '../feedback/StatusBadge.jsx';

/**
 * A discovery candidate / monitoring target row. DISCARDED rows are
 * de-emphasized rather than hidden — the source keeps them queryable on
 * purpose, in case a rule or LLM call misclassified something wanted.
 */
export function CandidateRow({ url, pageType, method, status, interval, actions, style }) {
  const discarded = status === 'DISCARDED';
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--space-2)',
        padding: 'var(--space-2) var(--space-3)',
        borderBottom: '1px solid var(--border-card)',
        opacity: discarded ? 0.55 : 1,
        ...style,
      }}
    >
      <div style={{ minWidth: 0, flex: '1 1 auto' }}>
        <div
          style={{
            font: 'var(--type-body)',
            fontWeight: 'var(--font-weight-medium)',
            color: 'var(--text-body)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {url}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginTop: 3 }}>
          <PageTypeLabel type={pageType} method={method} />
          {interval && <span style={{ font: 'var(--type-meta)', color: 'var(--text-meta)' }}>every {interval}</span>}
        </div>
      </div>
      <DiscoveryStatusBadge status={status} />
      <div style={{ display: 'flex', gap: 'var(--space-1)', flex: '0 0 auto' }}>{actions}</div>
    </div>
  );
}

/** The demo centerpiece. Loading is mandatory — the LLM call takes seconds. */
export function SimulateButton({ loading, onClick, size = 'sm', ...rest }) {
  return (
    <Button variant="primary" size={size} loading={loading} onClick={onClick} {...rest}>
      {!loading && <span aria-hidden="true">🎭</span>}
      {loading ? 'Simulating…' : 'Simulate a Change'}
    </Button>
  );
}
