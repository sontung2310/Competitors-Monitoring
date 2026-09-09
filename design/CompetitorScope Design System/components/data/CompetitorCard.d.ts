/**
 * One tracked competitor, as it appears on the company dashboard.
 *
 * @startingPoint section="Data" subtitle="Competitor summary card for the dashboard" viewport="700x220"
 */
export interface CompetitorCardProps {
  name: string;
  /** Bare host, no scheme — "lyfemarketing.com". */
  website: string;
  /** Count of monitoring targets with active=true. */
  activeTargets: number;
  /** Count of change records in the recent window. */
  recentChanges: number;
  onOpen?: () => void;
  style?: React.CSSProperties;
}
export declare function CompetitorCard(props: CompetitorCardProps): JSX.Element;
