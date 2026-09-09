import React from 'react';
import { Icon } from '../core/Icon.jsx';

/** page_type is informational, not status-bearing — plain text, no pill. */
export function PageTypeLabel({ type, method, style }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-1)', ...style }}>
      <span
        style={{
          font: 'var(--type-meta)',
          fontWeight: 'var(--font-weight-semibold)',
          letterSpacing: 'var(--label-letter-spacing)',
          color: 'var(--text-body)',
        }}
      >
        {type}
      </span>
      {method && <ClassificationTag method={method} />}
    </span>
  );
}

const METHOD_META = {
  RULE: { icon: 'ruler', label: 'rule' },
  LLM: { icon: 'sparkles', label: 'AI' },
  MANUAL: { icon: 'user', label: 'manual' },
};

/** Tiny muted indicator for classification_method. No color of its own. */
export function ClassificationTag({ method, style }) {
  const m = METHOD_META[method] || METHOD_META.MANUAL;
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        font: 'var(--type-meta)',
        color: 'var(--text-meta)',
        ...style,
      }}
    >
      <Icon name={m.icon} size={12} />
      {m.label}
    </span>
  );
}
