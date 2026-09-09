import React from 'react';
import { Icon } from './Icon.jsx';

/** Standard dropdown. Reads as an account/workspace switcher, not a tab set. */
export function Select({ label, value, options = [], onChange, size = 'md', style, ...rest }) {
  const [hover, setHover] = React.useState(false);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, ...style }}>
      {label && <label style={{ font: 'var(--type-label)', color: 'var(--text-body)' }}>{label}</label>}
      <div
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        style={{
          position: 'relative',
          display: 'flex',
          alignItems: 'center',
          background: hover ? 'var(--color-bg-subtle)' : 'var(--color-bg)',
          border: '1px solid var(--border-input)',
          borderRadius: 'var(--radius-sm)',
          padding: size === 'sm' ? '6px 12px' : '9px 12px',
          transition: 'var(--transition-control)',
        }}
      >
        <select
          value={value}
          onChange={(e) => onChange && onChange(e.target.value)}
          style={{
            appearance: 'none',
            border: 0,
            outline: 'none',
            background: 'transparent',
            font: 'var(--type-body)',
            fontWeight: 'var(--font-weight-medium)',
            color: 'var(--text-body)',
            width: '100%',
            paddingRight: 22,
            cursor: 'pointer',
          }}
          {...rest}
        >
          {options.map((o) => {
            const val = typeof o === 'string' ? o : o.value;
            const lab = typeof o === 'string' ? o : o.label;
            return <option key={val} value={val}>{lab}</option>;
          })}
        </select>
        <Icon name="chevron-down" size={16} color="var(--color-text-muted)" style={{ position: 'absolute', right: 12, pointerEvents: 'none' }} />
      </div>
    </div>
  );
}
