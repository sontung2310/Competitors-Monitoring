import React from 'react';
import { Icon } from '../core/Icon.jsx';

const TONES = {
  success:   { fg: 'var(--color-success)', bg: 'var(--badge-success-bg)' },
  error:     { fg: 'var(--color-error)',   bg: 'var(--badge-error-bg)' },
  warning:   { fg: 'var(--color-warning)', bg: 'var(--badge-warning-bg)' },
  favorable: { fg: 'var(--color-secondary)', bg: 'var(--color-secondary-light)' },
  brand:     { fg: 'var(--color-primary)', bg: 'var(--color-primary-light)' },
  muted:     { fg: 'var(--color-text-muted)', bg: 'var(--badge-muted-bg)' },
};

/** Pill, small text, ~15%-opacity tinted bg + solid-color label. */
export function StatusBadge({ tone = 'muted', icon, children, style, ...rest }) {
  const t = TONES[tone] || TONES.muted;
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        background: t.bg,
        color: t.fg,
        font: 'var(--type-meta)',
        fontWeight: 'var(--font-weight-semibold)',
        letterSpacing: 'var(--label-letter-spacing)',
        borderRadius: 'var(--radius-pill)',
        padding: '3px 10px',
        whiteSpace: 'nowrap',
        ...style,
      }}
      {...rest}
    >
      {icon && <Icon name={icon} size={12} />}
      {children}
    </span>
  );
}

const RUN_STATUS = { SUCCESS: 'success', FAILED: 'error', RUNNING: 'warning' };
/** Monitoring-run status: SUCCESS / FAILED / RUNNING. */
export function RunStatusBadge({ status, ...rest }) {
  return <StatusBadge tone={RUN_STATUS[status] || 'muted'} {...rest}>{status}</StatusBadge>;
}

const DISCOVERY_STATUS = { SUGGESTED: 'favorable', ACTIVE: 'success', DISCARDED: 'muted' };
/** discovery_status of a monitoring target / candidate row. */
export function DiscoveryStatusBadge({ status, ...rest }) {
  if (status === 'DISCARDED') {
    return (
      <span style={{ font: 'var(--type-meta)', color: 'var(--color-text-muted)', letterSpacing: 'var(--label-letter-spacing)' }} {...rest}>
        DISCARDED
      </span>
    );
  }
  return <StatusBadge tone={DISCOVERY_STATUS[status] || 'muted'} {...rest}>{status}</StatusBadge>;
}
