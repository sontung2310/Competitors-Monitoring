/**
 * The product's only button. Primary is brand red on white text; secondary is
 * white with a red border and red label; quiet is for de-emphasized row actions.
 *
 * @startingPoint section="Core" subtitle="Primary, secondary and quiet buttons with states" viewport="700x180"
 */
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'quiet';
  size?: 'sm' | 'md';
  /** Lucide icon name rendered before the label. */
  icon?: string;
  /** Lucide icon name rendered after the label. */
  iconAfter?: string;
  /** Swaps the leading icon for a spinner and blocks interaction. Discovery and simulate calls take seconds — always use it there. */
  loading?: boolean;
  disabled?: boolean;
  fullWidth?: boolean;
  children?: React.ReactNode;
}
export declare function Button(props: ButtonProps): JSX.Element;
