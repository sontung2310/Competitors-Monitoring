/**
 * Lucide glyph wrapper. Icons are masked so they take the current text color.
 */
export interface IconProps {
  /** Lucide icon name in kebab-case, e.g. "layout-dashboard", "flask-conical". */
  name: string;
  /** Square size in px. 16 inside controls and badges, 18–20 in nav. */
  size?: number;
  /** Any CSS color. Defaults to currentColor. */
  color?: string;
  style?: React.CSSProperties;
}
export declare function Icon(props: IconProps): JSX.Element;
