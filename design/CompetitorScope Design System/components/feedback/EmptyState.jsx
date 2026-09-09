import React from 'react';
import { Icon } from '../core/Icon.jsx';

/** Direction, not mood. State what is missing and what action produces it. */
export function EmptyState({ icon = 'inbox', message, action, style }) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 'var(--space-2)',
        padding: 'var(--space-6) var(--space-3)',
        textAlign: 'center',
        ...style,
      }}
    >
      <Icon name={icon} size={24} color="var(--color-text-muted)" />
      <div style={{ font: 'var(--type-body)', color: 'var(--text-meta)', maxWidth: 380 }}>{message}</div>
      {action}
    </div>
  );
}
