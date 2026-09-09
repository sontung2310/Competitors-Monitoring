/**
 * Page-type label for a candidate or target row. Deliberately unstyled type,
 * not a colored pill — page types are informational, not status-bearing.
 */
export type PageType =
  | 'BLOG' | 'SERVICES' | 'PRICING' | 'PRODUCT_LISTING' | 'ABOUT'
  | 'CAREERS' | 'CONTACT' | 'WORK' | 'OTHER';
export interface PageTypeLabelProps {
  type: PageType;
  /** classification_method — renders the tiny rule/AI/manual indicator alongside. */
  method?: 'RULE' | 'LLM' | 'MANUAL';
  style?: React.CSSProperties;
}
export declare function PageTypeLabel(props: PageTypeLabelProps): JSX.Element;

export interface ClassificationTagProps { method: 'RULE' | 'LLM' | 'MANUAL'; style?: React.CSSProperties }
export declare function ClassificationTag(props: ClassificationTagProps): JSX.Element;
