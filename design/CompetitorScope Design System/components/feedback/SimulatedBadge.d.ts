/**
 * Solid-fill marker for any record with `is_simulated: true`. Takes no props —
 * the treatment is fixed on purpose so it cannot be softened, recolored, or
 * shrunk into looking like an ordinary status pill.
 */
export interface SimulatedBadgeProps { style?: React.CSSProperties }
export declare function SimulatedBadge(props: SimulatedBadgeProps): JSX.Element;
