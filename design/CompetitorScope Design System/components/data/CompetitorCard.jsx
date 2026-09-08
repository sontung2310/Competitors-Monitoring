import React from 'react';
import { Card } from '../core/Card.jsx';
import { Icon } from '../core/Icon.jsx';

/**
 * The one bold card-level moment on the dashboard: a company's competitor,
 * with its site, active-target count and recent-change count. Keep the rest
 * of that screen quiet around it.
 */
export function CompetitorCard({ name, website, activeTargets, recentChanges, onOpen, style }) {
  return (
    <Card clickable onClick={onOpen} padding="var(--space-3)" style={style}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 44,
            height: 44,
            borderRadius: 'var(--radius-pill)',
            background: 'var(--color-primary-light)',
            color: 'var(--color-primary)',
            font: 'var(--type-h3)',
            flex: '0 0 auto',
          }}
        >
          {String(name || '?').charAt(0)}
        </span>
        <div style={{ minWidth: 0 }}>
          <div style={{ font: 'var(--type-h3)', color: 'var(--text-heading)' }}>{name}</div>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 5, font: 'var(--type-meta)', color: 'var(--text-meta)', marginTop: 2 }}>
            <Icon name="external-link" size={12} />
            {website}
          </div>
        </div>
        <Icon name="chevron-right" size={18} color="var(--color-text-muted)" style={{ marginLeft: 'auto' }} />
      </div>
      <div style={{ display: 'flex', gap: 'var(--space-4)', marginTop: 'var(--space-3)', paddingTop: 'var(--space-2)', borderTop: '1px solid var(--border-card)' }}>
        <Metric label="Active pages" value={activeTargets} />
        <Metric label="Recent changes" value={recentChanges} />
      </div>
    </Card>
  );
}

function Metric({ label, value }) {
  return (
    <div>
      <div style={{ font: 'var(--type-h2)', color: 'var(--text-heading)', fontVariantNumeric: 'tabular-nums' }}>{value}</div>
      <div
        style={{
          font: 'var(--type-meta)',
          color: 'var(--text-meta)',
          letterSpacing: 'var(--label-letter-spacing)',
          textTransform: 'var(--label-transform)',
          fontWeight: 'var(--font-weight-semibold)',
        }}
      >
        {label}
      </div>
    </div>
  );
}
