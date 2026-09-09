/**
 * Dashboard left nav. Active state is a filled brand-red circle behind the
 * icon — not a red label, not a red row fill.
 */
export interface SidebarItemSpec { value: string; label: string; icon: string; count?: number }
export interface SidebarProps {
  items: SidebarItemSpec[];
  active?: string;
  onSelect?: (value: string) => void;
  /** Wordmark text. No logo file exists in the source, so this is plain type. */
  brand?: string;
  /** Bottom slot — usually the company Select. */
  footer?: React.ReactNode;
  style?: React.CSSProperties;
}
export declare function Sidebar(props: SidebarProps): JSX.Element;
