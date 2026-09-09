/**
 * Text field. Used by the "+ Add manually" candidate flow, which surfaces the
 * API's own validation message in `error` verbatim rather than a generic one.
 */
export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  /** Muted helper line under the field. */
  hint?: string;
  /** Validation message from the API, shown verbatim. Turns the border red. */
  error?: string;
  /** Lucide icon name rendered inside the field, left of the text. */
  icon?: string;
}
export declare function Input(props: InputProps): JSX.Element;
