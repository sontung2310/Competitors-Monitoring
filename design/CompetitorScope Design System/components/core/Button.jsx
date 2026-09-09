import React from 'react';
import { Icon } from './Icon.jsx';

const base = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 'var(--space-1)',
  font: 'var(--type-body)',
  fontWeight: 'var(--font-weight-bold)',
  borderRadius: 'var(--radius-md)',
  border: '1px solid transparent',
  padding: 'var(--control-padding-y) var(--control-padding-x)',
  cursor: 'pointer',
  transition: 'var(--transition-control)',
  whiteSpace: 'nowrap',
};

const sizes = {
  sm: { padding: '6px 12px', fontSize: 'var(--font-size-small)', borderRadius: 'var(--radius-sm)' },
  md: {},
};

export function Button({
  variant = 'primary',
  size = 'md',
  icon,
  iconAfter,
  loading = false,
  disabled = false,
  fullWidth = false,
  children,
  style,
  ...rest
}) {
  const isDisabled = disabled || loading;
  const variants = {
    primary: {
      background: isDisabled ? 'var(--color-text-muted)' : 'var(--color-primary)',
      color: 'var(--text-on-brand)',
    },
    secondary: {
      background: 'var(--color-bg)',
      color: isDisabled ? 'var(--color-text-muted)' : 'var(--color-primary)',
      borderColor: isDisabled ? 'var(--color-border)' : 'var(--color-primary)',
    },
    quiet: {
      background: 'transparent',
      color: 'var(--color-text-muted)',
      borderColor: 'var(--color-border)',
    },
  };
  const [hover, setHover] = React.useState(false);
  const hoverStyle =
    !isDisabled && hover
      ? variant === 'primary'
        ? { background: 'var(--color-primary-hover)' }
        : variant === 'secondary'
          ? { background: 'var(--color-primary-light)' }
          : { background: 'var(--color-bg-subtle)', color: 'var(--color-text)' }
      : null;

  return (
    <button
      type="button"
      disabled={isDisabled}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        ...base,
        ...sizes[size],
        ...variants[variant],
        ...hoverStyle,
        cursor: isDisabled ? 'default' : 'pointer',
        width: fullWidth ? '100%' : undefined,
        ...style,
      }}
      {...rest}
    >
      {loading && <Spinner />}
      {!loading && icon && <Icon name={icon} size={size === 'sm' ? 14 : 16} />}
      {children}
      {!loading && iconAfter && <Icon name={iconAfter} size={size === 'sm' ? 14 : 16} />}
    </button>
  );
}

function Spinner() {
  return (
    <span
      style={{
        width: 14,
        height: 14,
        borderRadius: '50%',
        border: '2px solid currentColor',
        borderTopColor: 'transparent',
        opacity: 0.8,
        animation: 'cs-spin 700ms linear infinite',
      }}
    />
  );
}
