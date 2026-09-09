import React from 'react';
import { StatusBadge } from './StatusBadge.jsx';

/**
 * change_type → tone, following the favorable/unfavorable logic:
 * added is favorable, removed is an error-grade signal, PRICE_CHANGE is
 * deliberately neutral (direction is only meaningful to the viewer's own
 * business), PAGE_UPDATE is the lowest-emphasis fallback.
 */
const TONES = {
  NEW_BLOG: 'favorable',
  NEW_PRODUCT: 'favorable',
  NEW_PROMOTION: 'favorable',
  NEW_CAMPAIGN: 'favorable',
  NEW_AWARD: 'favorable',
  PRODUCT_REMOVED: 'error',
  PRICE_CHANGE: 'warning',
  PAGE_UPDATE: 'muted',
};

const ICONS = {
  NEW_BLOG: 'file-text',
  NEW_PRODUCT: 'package-plus',
  NEW_PROMOTION: 'megaphone',
  NEW_CAMPAIGN: 'megaphone',
  NEW_AWARD: 'award',
  PRODUCT_REMOVED: 'package-minus',
  PRICE_CHANGE: 'tag',
  PAGE_UPDATE: 'file-diff',
};

export function ChangeTypeBadge({ type, showIcon = true, ...rest }) {
  return (
    <StatusBadge tone={TONES[type] || 'muted'} icon={showIcon ? ICONS[type] : undefined} {...rest}>
      {type}
    </StatusBadge>
  );
}

/** old → new price, shown as text so the viewer judges the direction themselves. */
export function PriceDelta({ from, to, style }) {
  return (
    <span style={{ font: 'var(--type-body)', color: 'var(--text-body)', fontVariantNumeric: 'tabular-nums', ...style }}>
      {from} <span style={{ color: 'var(--text-meta)' }}>→</span>{' '}
      <span style={{ fontWeight: 'var(--font-weight-semibold)' }}>{to}</span>
    </span>
  );
}
