/**
 * White panel on the subtle page ground. Static cards stay flat; only
 * clickable cards take a shadow, and only on hover.
 */
export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  clickable?: boolean;
  /** Override --card-padding. */
  padding?: string | number;
  children?: React.ReactNode;
}
export declare function Card(props: CardProps): JSX.Element;

export interface CardHeaderProps {
  title: React.ReactNode;
  /** Small muted line under the title — url, timestamp, count. */
  meta?: React.ReactNode;
  actions?: React.ReactNode;
  style?: React.CSSProperties;
}
export declare function CardHeader(props: CardHeaderProps): JSX.Element;
