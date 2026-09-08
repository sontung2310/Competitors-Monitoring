import React from 'react';
import { Icon } from './Icon.jsx';

export function Input({ label, hint, error, icon, id, style, ...rest }) {
  const [focus, setFocus] = React.useState(false);
  const inputId = id || React.useId();
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, ...style }}>
      {label && (
        <label htmlFor={inputId} style={{ font: 'var(--type-label)', color: 'var(--text-body)' }}>
          {label}
        </label>
      )}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-1)',
          background: 'var(--color-bg)',
          border: `1px solid ${error ? 'var(--color-error)' : focus ? 'var(--border-focus)' : 'var(--border-input)'}`,
          borderRadius: 'var(--radius-sm)',
          padding: '9px 12px',
          transition: 'var(--transition-control)',
        }}
      >
        {icon && <Icon name={icon} size={16} color="var(--color-text-muted)" />}
        <input
          id={inputId}
          onFocus={() => setFocus(true)}
          onBlur={() => setFocus(false)}
          style={{
            font: 'var(--type-body)',
            color: 'var(--text-body)',
            border: 0,
            outline: 'none',
            background: 'transparent',
            width: '100%',
            minWidth: 0,
          }}
          {...rest}
        />
      </div>
      {(error || hint) && (
        <div style={{ font: 'var(--type-meta)', color: error ? 'var(--color-error)' : 'var(--text-meta)' }}>
          {error || hint}
        </div>
      )}
    </div>
  );
}
