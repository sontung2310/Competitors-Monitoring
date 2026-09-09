/**
 * Header row above the main content area. White, bottom-bordered, holds the
 * screen title and the screen's own actions (Run Discovery, Add manually).
 */
export interface TopBarProps {
  title: React.ReactNode;
  /** Small muted line above the title, e.g. "Competitors / Lyfe Marketing". */
  breadcrumb?: React.ReactNode;
  /** Small muted line below the title, e.g. the competitor's website. */
  meta?: React.ReactNode;
  actions?: React.ReactNode;
  style?: React.CSSProperties;
}
export declare function TopBar(props: TopBarProps): JSX.Element;
