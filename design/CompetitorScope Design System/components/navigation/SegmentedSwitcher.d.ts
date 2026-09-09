/**
 * Pill-container switcher for in-page multi-option state. Confirmed present in
 * the visual reference; the active item is the only one with a sub-pill.
 *
 * @startingPoint section="Navigation" subtitle="Segmented pill switcher and underline text tabs" viewport="700x160"
 */
export interface SegmentedOption { value: string; label: string; icon?: string; count?: number }
export interface SegmentedSwitcherProps {
  options: Array<SegmentedOption | string>;
  value?: string;
  onChange?: (value: string) => void;
  size?: 'sm' | 'md';
  style?: React.CSSProperties;
}
export declare function SegmentedSwitcher(props: SegmentedSwitcherProps): JSX.Element;

export interface TextTabsProps {
  options: Array<{ value: string; label: string } | string>;
  value?: string;
  onChange?: (value: string) => void;
  style?: React.CSSProperties;
}
/** Two-option in-panel toggle: brand color + 2px underline marks the active tab. */
export declare function TextTabs(props: TextTabsProps): JSX.Element;
