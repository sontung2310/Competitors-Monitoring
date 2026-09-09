import React from 'react';
import { ChangeTypeBadge } from '../feedback/ChangeTypeBadge.jsx';
import { SimulatedBadge } from '../feedback/SimulatedBadge.jsx';

/**
 * One record in the changes feed. The SIMULATED marker sits immediately after
 * the change-type badge whenever is_simulated is true — every single time.
 */
export function ChangeRow({ changeType, summary, target, detectedAt, isSimulated = false, detail, style }) {
  return (
    <div
      style={{
        display: 'flex',
        gap: 'var(--space-2)',
        padding: 'var(--space-2) var(--space-3)',
        borderBottom: '1px solid var(--border-card)',
        alignItems: 'flex-start',
        ...style,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-1)', flex: '0 0 auto', paddingTop: 2 }}>
        <ChangeTypeBadge type={changeType} />
        {isSimulated && <SimulatedBadge />}
      </div>
      <div style={{ minWidth: 0, flex: '1 1 auto' }}>
        <div style={{ font: 'var(--type-body)', color: 'var(--text-body)' }}>{summary}</div>
        {detail && <div style={{ marginTop: 4 }}>{detail}</div>}
        {target && (
          <div style={{ font: 'var(--type-meta)', color: 'var(--text-meta)', marginTop: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {target}
          </div>
        )}
      </div>
      <div style={{ font: 'var(--type-meta)', color: 'var(--text-meta)', flex: '0 0 auto', whiteSpace: 'nowrap', paddingTop: 2 }}>
        {detectedAt}
      </div>
    </div>
  );
}
