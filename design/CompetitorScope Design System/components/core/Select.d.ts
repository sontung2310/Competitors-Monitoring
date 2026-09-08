/**
 * Plain dropdown. The company selector uses this deliberately — a top-level
 * context switch should read as standard and expected, unlike the segmented
 * switcher which is for in-page multi-option filtering.
 */
export interface SelectOption { value: string; label: string }
export interface SelectProps {
  label?: string;
  value?: string;
  options?: Array<SelectOption | string>;
  onChange?: (value: string) => void;
  size?: 'sm' | 'md';
  style?: React.CSSProperties;
}
export declare function Select(props: SelectProps): JSX.Element;
