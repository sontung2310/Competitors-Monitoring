/**
 * Tinted pill for status vocabulary. Tone carries meaning, never decoration:
 * favorable = added/positive, error = removed/failed, warning = attention-only.
 *
 * @startingPoint section="Feedback" subtitle="Status, discovery, change-type and SIMULATED badges" viewport="700x220"
 */
export interface StatusBadgeProps {
  tone?: 'success' | 'error' | 'warning' | 'favorable' | 'brand' | 'muted';
  /** Lucide icon name shown before the label at 12px. */
  icon?: string;
  children?: React.ReactNode;
  style?: React.CSSProperties;
}
export declare function StatusBadge(props: StatusBadgeProps): JSX.Element;

export interface RunStatusBadgeProps { status: 'SUCCESS' | 'FAILED' | 'RUNNING' }
export declare function RunStatusBadge(props: RunStatusBadgeProps): JSX.Element;

export interface DiscoveryStatusBadgeProps { status: 'SUGGESTED' | 'ACTIVE' | 'DISCARDED' }
/** DISCARDED renders as plain muted text with no pill — it is deliberately de-emphasized. */
export declare function DiscoveryStatusBadge(props: DiscoveryStatusBadgeProps): JSX.Element;
