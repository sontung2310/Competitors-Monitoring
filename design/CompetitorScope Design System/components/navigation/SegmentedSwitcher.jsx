import React from 'react';
import { Icon } from '../core/Icon.jsx';

/**
 * One rounded-pill container, plain text+icon items inside; only the active
 * item gets a highlighted sub-pill. Use for any in-page multi-option switch
 * (candidate-status filters, data sources) — never for the company selector.
 */
export function SegmentedSwitcher({ options = [], value, onChange, size = 'md', style }) {
  return (
    <div
      role="tablist"
      style={{
        display: 'inline-flex',
        gap: 4,
        background: 'var(--color-bg-subtle)',
        border: '1px solid var(--border-card)',
        borderRadius: 'var(--radius-pill)',
        padding: 4,
        ...style,
      }}
    >
      {options.map((o) => {
        const val = typeof o === 'string' ? o : o.value;
        const lab = typeof o === 'string' ? o : o.label;
        const icon = typeof o === 'string' ? undefined : o.icon;
        const count = typeof o === 'string' ? undefined : o.count;
        const active = val === value;
        return (
          <button
            key={val}
            role="tab"
            aria-selected={active}
            onClick={() => onChange && onChange(val)}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              border: 0,
              cursor: 'pointer',
              borderRadius: 'var(--radius-pill)',
              padding: size === 'sm' ? '5px 12px' : '7px 16px',
              font: 'var(--type-body)',
              fontSize: size === 'sm' ? 'var(--font-size-small)' : 'var(--font-size-body)',
              fontWeight: active ? 'var(--font-weight-semibold)' : 'var(--font-weight-medium)',
              background: active ? 'var(--color-bg)' : 'transparent',
              color: active ? 'var(--color-text)' : 'var(--color-text-muted)',
              boxShadow: active ? '0 1px 2px rgba(26,26,26,.06)' : 'none',
              transition: 'var(--transition-control)',
            }}
          >
            {icon && <Icon name={icon} size={14} />}
            {lab}
            {count != null && (
              <span style={{ font: 'var(--type-meta)', color: 'var(--text-meta)', fontVariantNumeric: 'tabular-nums' }}>{count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/** Lightweight two-option toggle inside a panel: color + underline on active. */
export function TextTabs({ options = [], value, onChange, style }) {
  return (
    <div style={{ display: 'flex', gap: 'var(--space-3)', borderBottom: '1px solid var(--border-card)', ...style }}>
      {options.map((o) => {
        const val = typeof o === 'string' ? o : o.value;
        const lab = typeof o === 'string' ? o : o.label;
        const active = val === value;
        return (
          <button
            key={val}
            onClick={() => onChange && onChange(val)}
            style={{
              border: 0,
              background: 'transparent',
              cursor: 'pointer',
              padding: '0 0 10px',
              marginBottom: -1,
              font: 'var(--type-body)',
              fontWeight: active ? 'var(--font-weight-semibold)' : 'var(--font-weight-medium)',
              color: active ? 'var(--color-primary)' : 'var(--color-text-muted)',
              borderBottom: `2px solid ${active ? 'var(--color-primary)' : 'transparent'}`,
              transition: 'var(--transition-control)',
            }}
          >
            {lab}
          </button>
        );
      })}
    </div>
  );
}
