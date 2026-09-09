import React from 'react';
import { Icon } from '../core/Icon.jsx';

/**
 * Metric label (small, muted, uppercase), large bold value, small circular
 * icon badge top-right colored by favorability, trend indicator below.
 * `favorable` is the caller's judgement, not the arrow direction — a falling
 * number can be the good one.
 */
export function StatTile({ label, value, icon, favorable, trend, style }) {
  const tone =
    favorable === true ? 'var(--color-secondary)' : favorable === false ? 'var(--color-error)' : 'var(--color-text-muted)';
  const tint =
    favorable === true ? 'var(--color-secondary-light)' : favorable === false ? 'var(--badge-error-bg)' : 'var(--color-bg-subtle)';
  return (
    <div
      style={{
        background: 'var(--surface-card)',
        border: '1px solid var(--border-card)',
        borderRadius: 'var(--radius-lg)',
        padding: 'var(--card-padding)',
        display: 'flex',
        gap: 'var(--space-2)',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        ...style,
      }}
    >
      <div>
        <div
          style={{
            font: 'var(--type-meta)',
            fontWeight: 'var(--font-weight-semibold)',
            letterSpacing: 'var(--label-letter-spacing)',
            textTransform: 'var(--label-transform)',
            color: 'var(--text-meta)',
            whiteSpace: 'nowrap',
          }}
        >
          {label}
        </div>
        <div style={{ font: 'var(--type-h1)', color: 'var(--text-heading)', marginTop: 6, fontVariantNumeric: 'tabular-nums' }}>
          {value}
        </div>
        {trend && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 6, font: 'var(--type-meta)', color: tone, fontWeight: 'var(--font-weight-semibold)', whiteSpace: 'nowrap' }}>
            <Icon name={trend.direction === 'down' ? 'arrow-down' : 'arrow-up'} size={13} />
            {trend.label}
          </div>
        )}
      </div>
      {icon && (
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 36,
            height: 36,
            borderRadius: 'var(--radius-pill)',
            background: tint,
            color: tone,
            flex: '0 0 auto',
          }}
        >
          <Icon name={icon} size={18} />
        </span>
      )}
    </div>
  );
}
