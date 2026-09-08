/**
 * Row in the candidate / tracked-pages list on the competitor detail screen.
 *
 * @startingPoint section="Data" subtitle="Candidate rows with activate, discard and simulate actions" viewport="700x240"
 */
export interface CandidateRowProps {
  /** Normalized URL — the one that gets monitored. */
  url: string;
  pageType: string;
  method?: 'RULE' | 'LLM' | 'MANUAL';
  status: 'SUGGESTED' | 'ACTIVE' | 'DISCARDED';
  /** Human-readable check interval, e.g. "6 h" — from check_interval_minutes. */
  interval?: string;
  /** Right-aligned buttons: Activate on SUGGESTED, SimulateButton on ACTIVE. */
  actions?: React.ReactNode;
  style?: React.CSSProperties;
}
export declare function CandidateRow(props: CandidateRowProps): JSX.Element;

export interface SimulateButtonProps {
  loading?: boolean;
  onClick?: () => void;
  size?: 'sm' | 'md';
}
/** Primary button with the 🎭 emoji the source pins verbatim. */
export declare function SimulateButton(props: SimulateButtonProps): JSX.Element;
