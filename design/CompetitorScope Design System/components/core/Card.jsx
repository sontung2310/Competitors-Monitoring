import React from 'react';

/** White surface, 1px border, 16px radius. Flat unless clickable. */
export function Card({ clickable = false, padding, children, style, ...rest }) {
  const [hover, setHover] = React.useState(false);
  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        background: 'var(--surface-card)',
        border: 'var(--border-width) solid var(--border-card)',
        borderRadius: 'var(--radius-lg)',
        padding: padding ?? 'var(--card-padding)',
        boxShadow: clickable && hover ? 'var(--shadow-hover)' : 'var(--shadow-none)',
        transition: 'var(--transition-surface)',
        cursor: clickable ? 'pointer' : undefined,
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  );
}

/** Optional header strip for a Card: title left, actions right. */
export function CardHeader({ title, meta, actions, style }) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 'var(--space-2)', marginBottom: 'var(--space-2)', ...style }}>
      <div>
        <div style={{ font: 'var(--type-h3)', color: 'var(--text-heading)' }}>{title}</div>
        {meta && <div style={{ font: 'var(--type-meta)', color: 'var(--text-meta)', marginTop: 2 }}>{meta}</div>}
      </div>
      {actions && <div style={{ display: 'flex', gap: 'var(--space-1)' }}>{actions}</div>}
    </div>
  );
}
