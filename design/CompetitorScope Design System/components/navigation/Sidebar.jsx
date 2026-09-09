import React from 'react';
import { Icon } from '../core/Icon.jsx';

/**
 * Left dashboard nav: white bg, brand-red filled circular badge behind the
 * active item's icon. The product ships no logo, so the wordmark slot renders
 * the brand name in plain type — see readme.md > ICONOGRAPHY.
 */
export function Sidebar({ items = [], active, onSelect, brand = 'CompetitorScope', footer, style }) {
  return (
    <nav
      style={{
        width: 'var(--sidebar-width)',
        flex: '0 0 var(--sidebar-width)',
        background: 'var(--surface-nav)',
        borderRight: '1px solid var(--border-card)',
        padding: 'var(--space-3) var(--space-2)',
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-4)',
        ...style,
      }}
    >
      <div style={{ font: 'var(--type-h3)', color: 'var(--text-heading)', padding: '0 var(--space-1)', letterSpacing: '-.01em' }}>
        {brand}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {items.map((it) => (
          <SidebarItem key={it.value} {...it} active={it.value === active} onSelect={onSelect} />
        ))}
      </div>
      <div style={{ marginTop: 'auto' }}>{footer}</div>
    </nav>
  );
}

function SidebarItem({ value, label, icon, count, active, onSelect }) {
  const [hover, setHover] = React.useState(false);
  return (
    <button
      onClick={() => onSelect && onSelect(value)}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--space-1)',
        width: '100%',
        border: 0,
        cursor: 'pointer',
        background: hover && !active ? 'var(--color-bg-subtle)' : 'transparent',
        borderRadius: 'var(--radius-md)',
        padding: '8px',
        font: 'var(--type-body)',
        fontWeight: active ? 'var(--font-weight-semibold)' : 'var(--font-weight-medium)',
        color: active ? 'var(--color-text)' : 'var(--color-text-muted)',
        transition: 'var(--transition-control)',
        textAlign: 'left',
      }}
    >
      <span
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 28,
          height: 28,
          borderRadius: 'var(--radius-pill)',
          background: active ? 'var(--color-primary)' : 'transparent',
          color: active ? 'var(--text-on-brand)' : 'var(--color-text-muted)',
          transition: 'var(--transition-control)',
        }}
      >
        <Icon name={icon} size={16} />
      </span>
      {label}
      {count != null && (
        <span style={{ marginLeft: 'auto', font: 'var(--type-meta)', color: 'var(--text-meta)', fontVariantNumeric: 'tabular-nums' }}>{count}</span>
      )}
    </button>
  );
}
