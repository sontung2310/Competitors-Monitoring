/**
 * Dashboard metric tile.
 *
 * @startingPoint section="Data" subtitle="Metric tiles with favorability-colored trend" viewport="700x200"
 */
export interface StatTileProps {
  /** Short metric name — rendered uppercase. */
  label: string;
  value: React.ReactNode;
  /** Lucide icon name for the circular badge, top-right. */
  icon?: string;
  /** Is this metric's current state good for the viewer? Drives the color of the badge and trend, independent of arrow direction. Omit for neutral. */
  favorable?: boolean;
  trend?: { direction: 'up' | 'down'; label: string };
  style?: React.CSSProperties;
}
export declare function StatTile(props: StatTileProps): JSX.Element;
