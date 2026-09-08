/**
 * Badge for a change record's `change_type`. Tone is derived from the type,
 * not chosen by the caller, so the favorable/unfavorable mapping stays
 * consistent everywhere the changes feed renders.
 */
export type ChangeType =
  | 'NEW_BLOG' | 'NEW_PRODUCT' | 'NEW_PROMOTION' | 'NEW_CAMPAIGN' | 'NEW_AWARD'
  | 'PRODUCT_REMOVED' | 'PRICE_CHANGE' | 'PAGE_UPDATE';
export interface ChangeTypeBadgeProps { type: ChangeType; showIcon?: boolean; style?: React.CSSProperties }
export declare function ChangeTypeBadge(props: ChangeTypeBadgeProps): JSX.Element;

export interface PriceDeltaProps {
  /** Previous price, pre-formatted with its currency symbol. */
  from: string;
  /** New price, pre-formatted. */
  to: string;
  style?: React.CSSProperties;
}
/** Always show the real old→new values next to a PRICE_CHANGE — never an up/down verdict. */
export declare function PriceDelta(props: PriceDeltaProps): JSX.Element;
