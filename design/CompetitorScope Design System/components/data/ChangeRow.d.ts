/**
 * Changes-feed row: type badge, SIMULATED marker where applicable, the real
 * summary text, the target URL and a relative timestamp.
 *
 * @startingPoint section="Data" subtitle="Changes-feed rows, real and simulated" viewport="700x240"
 */
export interface ChangeRowProps {
  changeType: string;
  /** The summary string from the change record — shown as-is, not rewritten. */
  summary: React.ReactNode;
  /** The monitored URL this change belongs to. */
  target?: string;
  /** Pre-formatted relative time, e.g. "2 hours ago". */
  detectedAt?: string;
  /** From the record's is_simulated flag. Never hardcode false to hide the badge. */
  isSimulated?: boolean;
  /** Extra node under the summary — usually a PriceDelta for PRICE_CHANGE. */
  detail?: React.ReactNode;
  style?: React.CSSProperties;
}
export declare function ChangeRow(props: ChangeRowProps): JSX.Element;
