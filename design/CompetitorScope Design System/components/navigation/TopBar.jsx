import React from 'react';

/** Page header strip: title + optional breadcrumb on the left, actions right. */
export function TopBar({ title, breadcrumb, meta, actions, style }) {
  return (
    <header
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 'var(--space-3)',
        padding: 'var(--space-3) var(--page-padding)',
        background: 'var(--color-bg)',
        borderBottom: '1px solid var(--border-card)',
        ...style,
      }}
    >
      <div style={{ minWidth: 0 }}>
        {breadcrumb && (
          <div style={{ font: 'var(--type-meta)', color: 'var(--text-meta)', marginBottom: 4 }}>{breadcrumb}</div>
        )}
        <h1 style={{ font: 'var(--type-h2)', color: 'var(--text-heading)', margin: 0 }}>{title}</h1>
        {meta && <div style={{ font: 'var(--type-meta)', color: 'var(--text-meta)', marginTop: 4 }}>{meta}</div>}
      </div>
      {actions && <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-1)' }}>{actions}</div>}
    </header>
  );
}
