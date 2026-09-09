/**
 * Empty and error placeholder. Copy is directional and never cheerful or
 * apologetic: "No pages tracked yet — run discovery to find some."
 */
export interface EmptyStateProps {
  /** Lucide icon name, 24px muted. */
  icon?: string;
  message: React.ReactNode;
  /** Usually the Button that resolves the emptiness. */
  action?: React.ReactNode;
  style?: React.CSSProperties;
}
export declare function EmptyState(props: EmptyStateProps): JSX.Element;
