/* @ds-bundle: {"format":4,"namespace":"CompetitorScopeDesignSystem_312ddb","components":[{"name":"Button","sourcePath":"components/core/Button.jsx"},{"name":"Card","sourcePath":"components/core/Card.jsx"},{"name":"CardHeader","sourcePath":"components/core/Card.jsx"},{"name":"Icon","sourcePath":"components/core/Icon.jsx"},{"name":"Input","sourcePath":"components/core/Input.jsx"},{"name":"Select","sourcePath":"components/core/Select.jsx"},{"name":"CandidateRow","sourcePath":"components/data/CandidateRow.jsx"},{"name":"SimulateButton","sourcePath":"components/data/CandidateRow.jsx"},{"name":"ChangeRow","sourcePath":"components/data/ChangeRow.jsx"},{"name":"CompetitorCard","sourcePath":"components/data/CompetitorCard.jsx"},{"name":"StatTile","sourcePath":"components/data/StatTile.jsx"},{"name":"ChangeTypeBadge","sourcePath":"components/feedback/ChangeTypeBadge.jsx"},{"name":"PriceDelta","sourcePath":"components/feedback/ChangeTypeBadge.jsx"},{"name":"EmptyState","sourcePath":"components/feedback/EmptyState.jsx"},{"name":"PageTypeLabel","sourcePath":"components/feedback/PageTypeLabel.jsx"},{"name":"ClassificationTag","sourcePath":"components/feedback/PageTypeLabel.jsx"},{"name":"SimulatedBadge","sourcePath":"components/feedback/SimulatedBadge.jsx"},{"name":"StatusBadge","sourcePath":"components/feedback/StatusBadge.jsx"},{"name":"RunStatusBadge","sourcePath":"components/feedback/StatusBadge.jsx"},{"name":"DiscoveryStatusBadge","sourcePath":"components/feedback/StatusBadge.jsx"},{"name":"SegmentedSwitcher","sourcePath":"components/navigation/SegmentedSwitcher.jsx"},{"name":"TextTabs","sourcePath":"components/navigation/SegmentedSwitcher.jsx"},{"name":"Sidebar","sourcePath":"components/navigation/Sidebar.jsx"},{"name":"TopBar","sourcePath":"components/navigation/TopBar.jsx"}],"sourceHashes":{"components/core/Button.jsx":"89f7f1622319","components/core/Card.jsx":"5e973f6f47c2","components/core/Icon.jsx":"45e77d2d13a1","components/core/Input.jsx":"0fb425c28b75","components/core/Select.jsx":"04f536d0fcb2","components/data/CandidateRow.jsx":"eca5b15a3d41","components/data/ChangeRow.jsx":"95a2bc7ec154","components/data/CompetitorCard.jsx":"e7aa8fc2cb74","components/data/StatTile.jsx":"19b33fb6a944","components/feedback/ChangeTypeBadge.jsx":"dab7b7d2f728","components/feedback/EmptyState.jsx":"0b1bf5990d6c","components/feedback/PageTypeLabel.jsx":"a0f386207c33","components/feedback/SimulatedBadge.jsx":"2dbfbccb31b2","components/feedback/StatusBadge.jsx":"ae60dc614c38","components/navigation/SegmentedSwitcher.jsx":"93ab577d9389","components/navigation/Sidebar.jsx":"9c8886a7806f","components/navigation/TopBar.jsx":"675fac6f5e55","ui_kits/dashboard/app.kit.jsx":"fd08cc7d6c86","ui_kits/dashboard/changes-screen.kit.jsx":"5a56bb20e6c1","ui_kits/dashboard/competitor-screen.kit.jsx":"007d96e64aaf","ui_kits/dashboard/dashboard-screen.kit.jsx":"51161a1147ee","ui_kits/dashboard/data.js":"8583f4d33054","ui_kits/dashboard/shell.kit.jsx":"40dbaed3c3f7","ui_kits/dashboard/simulate-result.kit.jsx":"85580a0d118e"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.CompetitorScopeDesignSystem_312ddb = window.CompetitorScopeDesignSystem_312ddb || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/core/Card.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** White surface, 1px border, 16px radius. Flat unless clickable. */
function Card({
  clickable = false,
  padding,
  children,
  style,
  ...rest
}) {
  const [hover, setHover] = React.useState(false);
  return /*#__PURE__*/React.createElement("div", _extends({
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
    style: {
      background: 'var(--surface-card)',
      border: 'var(--border-width) solid var(--border-card)',
      borderRadius: 'var(--radius-lg)',
      padding: padding ?? 'var(--card-padding)',
      boxShadow: clickable && hover ? 'var(--shadow-hover)' : 'var(--shadow-none)',
      transition: 'var(--transition-surface)',
      cursor: clickable ? 'pointer' : undefined,
      ...style
    }
  }, rest), children);
}

/** Optional header strip for a Card: title left, actions right. */
function CardHeader({
  title,
  meta,
  actions,
  style
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'flex-start',
      justifyContent: 'space-between',
      gap: 'var(--space-2)',
      marginBottom: 'var(--space-2)',
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      font: 'var(--type-h3)',
      color: 'var(--text-heading)'
    }
  }, title), meta && /*#__PURE__*/React.createElement("div", {
    style: {
      font: 'var(--type-meta)',
      color: 'var(--text-meta)',
      marginTop: 2
    }
  }, meta)), actions && /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 'var(--space-1)'
    }
  }, actions));
}
Object.assign(__ds_scope, { Card, CardHeader });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Card.jsx", error: String((e && e.message) || e) }); }

// components/core/Icon.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const CDN = 'https://cdn.jsdelivr.net/npm/lucide-static@0.544.0/icons/';

/* Fetched-once cache of raw Lucide SVG markup, keyed by icon name. */
const CACHE = new Map();
const PENDING = new Map();
function load(name) {
  if (CACHE.has(name)) return null;
  if (!PENDING.has(name)) {
    PENDING.set(name, fetch(CDN + name + '.svg').then(r => r.ok ? r.text() : '').then(txt => {
      // Keep only the inner geometry; the wrapper <svg> is rendered by React
      // so size and color stay under the component's control.
      const inner = txt.replace(/^[\s\S]*?<svg[^>]*>/, '').replace(/<\/svg>[\s\S]*$/, '');
      CACHE.set(name, inner);
      return inner;
    }).catch(() => {
      CACHE.set(name, '');
      return '';
    }));
  }
  return PENDING.get(name);
}

/**
 * Lucide (2px stroke, rounded caps) is a documented SUBSTITUTION — the source
 * repo ships no icon font, sprite, or SVG set. See readme.md > ICONOGRAPHY.
 *
 * The glyph is rendered as a real inline <svg> with stroke="currentColor", so
 * it inherits text color and composites correctly everywhere (a CSS
 * mask-image pointing at a cross-origin URL does not).
 */
function Icon({
  name,
  size = 16,
  color = 'currentColor',
  strokeWidth = 2,
  style,
  ...rest
}) {
  const [markup, setMarkup] = React.useState(() => CACHE.get(name) ?? null);
  React.useEffect(() => {
    const cached = CACHE.get(name);
    if (cached !== undefined) {
      setMarkup(cached);
      return;
    }
    setMarkup(null);
    let alive = true;
    const p = load(name);
    if (p) p.then(inner => {
      if (alive) setMarkup(inner);
    });
    return () => {
      alive = false;
    };
  }, [name]);
  return /*#__PURE__*/React.createElement("svg", _extends({
    "data-icon": name,
    viewBox: "0 0 24 24",
    width: size,
    height: size,
    fill: "none",
    stroke: color,
    strokeWidth: strokeWidth,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": "true",
    focusable: "false",
    style: {
      display: 'inline-block',
      flex: '0 0 auto',
      verticalAlign: 'middle',
      overflow: 'visible',
      ...style
    },
    dangerouslySetInnerHTML: {
      __html: markup || ''
    }
  }, rest));
}
Object.assign(__ds_scope, { Icon });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Icon.jsx", error: String((e && e.message) || e) }); }

// components/core/Button.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
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
  whiteSpace: 'nowrap'
};
const sizes = {
  sm: {
    padding: '6px 12px',
    fontSize: 'var(--font-size-small)',
    borderRadius: 'var(--radius-sm)'
  },
  md: {}
};
function Button({
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
      color: 'var(--text-on-brand)'
    },
    secondary: {
      background: 'var(--color-bg)',
      color: isDisabled ? 'var(--color-text-muted)' : 'var(--color-primary)',
      borderColor: isDisabled ? 'var(--color-border)' : 'var(--color-primary)'
    },
    quiet: {
      background: 'transparent',
      color: 'var(--color-text-muted)',
      borderColor: 'var(--color-border)'
    }
  };
  const [hover, setHover] = React.useState(false);
  const hoverStyle = !isDisabled && hover ? variant === 'primary' ? {
    background: 'var(--color-primary-hover)'
  } : variant === 'secondary' ? {
    background: 'var(--color-primary-light)'
  } : {
    background: 'var(--color-bg-subtle)',
    color: 'var(--color-text)'
  } : null;
  return /*#__PURE__*/React.createElement("button", _extends({
    type: "button",
    disabled: isDisabled,
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
    style: {
      ...base,
      ...sizes[size],
      ...variants[variant],
      ...hoverStyle,
      cursor: isDisabled ? 'default' : 'pointer',
      width: fullWidth ? '100%' : undefined,
      ...style
    }
  }, rest), loading && /*#__PURE__*/React.createElement(Spinner, null), !loading && icon && /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: icon,
    size: size === 'sm' ? 14 : 16
  }), children, !loading && iconAfter && /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: iconAfter,
    size: size === 'sm' ? 14 : 16
  }));
}
function Spinner() {
  return /*#__PURE__*/React.createElement("span", {
    style: {
      width: 14,
      height: 14,
      borderRadius: '50%',
      border: '2px solid currentColor',
      borderTopColor: 'transparent',
      opacity: 0.8,
      animation: 'cs-spin 700ms linear infinite'
    }
  });
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Button.jsx", error: String((e && e.message) || e) }); }

// components/core/Input.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function Input({
  label,
  hint,
  error,
  icon,
  id,
  style,
  ...rest
}) {
  const [focus, setFocus] = React.useState(false);
  const inputId = id || React.useId();
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 6,
      ...style
    }
  }, label && /*#__PURE__*/React.createElement("label", {
    htmlFor: inputId,
    style: {
      font: 'var(--type-label)',
      color: 'var(--text-body)'
    }
  }, label), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--space-1)',
      background: 'var(--color-bg)',
      border: `1px solid ${error ? 'var(--color-error)' : focus ? 'var(--border-focus)' : 'var(--border-input)'}`,
      borderRadius: 'var(--radius-sm)',
      padding: '9px 12px',
      transition: 'var(--transition-control)'
    }
  }, icon && /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: icon,
    size: 16,
    color: "var(--color-text-muted)"
  }), /*#__PURE__*/React.createElement("input", _extends({
    id: inputId,
    onFocus: () => setFocus(true),
    onBlur: () => setFocus(false),
    style: {
      font: 'var(--type-body)',
      color: 'var(--text-body)',
      border: 0,
      outline: 'none',
      background: 'transparent',
      width: '100%',
      minWidth: 0
    }
  }, rest))), (error || hint) && /*#__PURE__*/React.createElement("div", {
    style: {
      font: 'var(--type-meta)',
      color: error ? 'var(--color-error)' : 'var(--text-meta)'
    }
  }, error || hint));
}
Object.assign(__ds_scope, { Input });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Input.jsx", error: String((e && e.message) || e) }); }

// components/core/Select.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** Standard dropdown. Reads as an account/workspace switcher, not a tab set. */
function Select({
  label,
  value,
  options = [],
  onChange,
  size = 'md',
  style,
  ...rest
}) {
  const [hover, setHover] = React.useState(false);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 6,
      ...style
    }
  }, label && /*#__PURE__*/React.createElement("label", {
    style: {
      font: 'var(--type-label)',
      color: 'var(--text-body)'
    }
  }, label), /*#__PURE__*/React.createElement("div", {
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
    style: {
      position: 'relative',
      display: 'flex',
      alignItems: 'center',
      background: hover ? 'var(--color-bg-subtle)' : 'var(--color-bg)',
      border: '1px solid var(--border-input)',
      borderRadius: 'var(--radius-sm)',
      padding: size === 'sm' ? '6px 12px' : '9px 12px',
      transition: 'var(--transition-control)'
    }
  }, /*#__PURE__*/React.createElement("select", _extends({
    value: value,
    onChange: e => onChange && onChange(e.target.value),
    style: {
      appearance: 'none',
      border: 0,
      outline: 'none',
      background: 'transparent',
      font: 'var(--type-body)',
      fontWeight: 'var(--font-weight-medium)',
      color: 'var(--text-body)',
      width: '100%',
      paddingRight: 22,
      cursor: 'pointer'
    }
  }, rest), options.map(o => {
    const val = typeof o === 'string' ? o : o.value;
    const lab = typeof o === 'string' ? o : o.label;
    return /*#__PURE__*/React.createElement("option", {
      key: val,
      value: val
    }, lab);
  })), /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "chevron-down",
    size: 16,
    color: "var(--color-text-muted)",
    style: {
      position: 'absolute',
      right: 12,
      pointerEvents: 'none'
    }
  })));
}
Object.assign(__ds_scope, { Select });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Select.jsx", error: String((e && e.message) || e) }); }

// components/data/CompetitorCard.jsx
try { (() => {
/**
 * The one bold card-level moment on the dashboard: a company's competitor,
 * with its site, active-target count and recent-change count. Keep the rest
 * of that screen quiet around it.
 */
function CompetitorCard({
  name,
  website,
  activeTargets,
  recentChanges,
  onOpen,
  style
}) {
  return /*#__PURE__*/React.createElement(__ds_scope.Card, {
    clickable: true,
    onClick: onOpen,
    padding: "var(--space-3)",
    style: style
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--space-2)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      width: 44,
      height: 44,
      borderRadius: 'var(--radius-pill)',
      background: 'var(--color-primary-light)',
      color: 'var(--color-primary)',
      font: 'var(--type-h3)',
      flex: '0 0 auto'
    }
  }, String(name || '?').charAt(0)), /*#__PURE__*/React.createElement("div", {
    style: {
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      font: 'var(--type-h3)',
      color: 'var(--text-heading)'
    }
  }, name), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 5,
      font: 'var(--type-meta)',
      color: 'var(--text-meta)',
      marginTop: 2
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "external-link",
    size: 12
  }), website)), /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "chevron-right",
    size: 18,
    color: "var(--color-text-muted)",
    style: {
      marginLeft: 'auto'
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 'var(--space-4)',
      marginTop: 'var(--space-3)',
      paddingTop: 'var(--space-2)',
      borderTop: '1px solid var(--border-card)'
    }
  }, /*#__PURE__*/React.createElement(Metric, {
    label: "Active pages",
    value: activeTargets
  }), /*#__PURE__*/React.createElement(Metric, {
    label: "Recent changes",
    value: recentChanges
  })));
}
function Metric({
  label,
  value
}) {
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      font: 'var(--type-h2)',
      color: 'var(--text-heading)',
      fontVariantNumeric: 'tabular-nums'
    }
  }, value), /*#__PURE__*/React.createElement("div", {
    style: {
      font: 'var(--type-meta)',
      color: 'var(--text-meta)',
      letterSpacing: 'var(--label-letter-spacing)',
      textTransform: 'var(--label-transform)',
      fontWeight: 'var(--font-weight-semibold)'
    }
  }, label));
}
Object.assign(__ds_scope, { CompetitorCard });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/data/CompetitorCard.jsx", error: String((e && e.message) || e) }); }

// components/data/StatTile.jsx
try { (() => {
/**
 * Metric label (small, muted, uppercase), large bold value, small circular
 * icon badge top-right colored by favorability, trend indicator below.
 * `favorable` is the caller's judgement, not the arrow direction — a falling
 * number can be the good one.
 */
function StatTile({
  label,
  value,
  icon,
  favorable,
  trend,
  style
}) {
  const tone = favorable === true ? 'var(--color-secondary)' : favorable === false ? 'var(--color-error)' : 'var(--color-text-muted)';
  const tint = favorable === true ? 'var(--color-secondary-light)' : favorable === false ? 'var(--badge-error-bg)' : 'var(--color-bg-subtle)';
  return /*#__PURE__*/React.createElement("div", {
    style: {
      background: 'var(--surface-card)',
      border: '1px solid var(--border-card)',
      borderRadius: 'var(--radius-lg)',
      padding: 'var(--card-padding)',
      display: 'flex',
      gap: 'var(--space-2)',
      alignItems: 'flex-start',
      justifyContent: 'space-between',
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      font: 'var(--type-meta)',
      fontWeight: 'var(--font-weight-semibold)',
      letterSpacing: 'var(--label-letter-spacing)',
      textTransform: 'var(--label-transform)',
      color: 'var(--text-meta)',
      whiteSpace: 'nowrap'
    }
  }, label), /*#__PURE__*/React.createElement("div", {
    style: {
      font: 'var(--type-h1)',
      color: 'var(--text-heading)',
      marginTop: 6,
      fontVariantNumeric: 'tabular-nums'
    }
  }, value), trend && /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 5,
      marginTop: 6,
      font: 'var(--type-meta)',
      color: tone,
      fontWeight: 'var(--font-weight-semibold)',
      whiteSpace: 'nowrap'
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: trend.direction === 'down' ? 'arrow-down' : 'arrow-up',
    size: 13
  }), trend.label)), icon && /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      width: 36,
      height: 36,
      borderRadius: 'var(--radius-pill)',
      background: tint,
      color: tone,
      flex: '0 0 auto'
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: icon,
    size: 18
  })));
}
Object.assign(__ds_scope, { StatTile });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/data/StatTile.jsx", error: String((e && e.message) || e) }); }

// components/feedback/EmptyState.jsx
try { (() => {
/** Direction, not mood. State what is missing and what action produces it. */
function EmptyState({
  icon = 'inbox',
  message,
  action,
  style
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      gap: 'var(--space-2)',
      padding: 'var(--space-6) var(--space-3)',
      textAlign: 'center',
      ...style
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: icon,
    size: 24,
    color: "var(--color-text-muted)"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      font: 'var(--type-body)',
      color: 'var(--text-meta)',
      maxWidth: 380
    }
  }, message), action);
}
Object.assign(__ds_scope, { EmptyState });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/EmptyState.jsx", error: String((e && e.message) || e) }); }

// components/feedback/PageTypeLabel.jsx
try { (() => {
/** page_type is informational, not status-bearing — plain text, no pill. */
function PageTypeLabel({
  type,
  method,
  style
}) {
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 'var(--space-1)',
      ...style
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      font: 'var(--type-meta)',
      fontWeight: 'var(--font-weight-semibold)',
      letterSpacing: 'var(--label-letter-spacing)',
      color: 'var(--text-body)'
    }
  }, type), method && /*#__PURE__*/React.createElement(ClassificationTag, {
    method: method
  }));
}
const METHOD_META = {
  RULE: {
    icon: 'ruler',
    label: 'rule'
  },
  LLM: {
    icon: 'sparkles',
    label: 'AI'
  },
  MANUAL: {
    icon: 'user',
    label: 'manual'
  }
};

/** Tiny muted indicator for classification_method. No color of its own. */
function ClassificationTag({
  method,
  style
}) {
  const m = METHOD_META[method] || METHOD_META.MANUAL;
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 4,
      font: 'var(--type-meta)',
      color: 'var(--text-meta)',
      ...style
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: m.icon,
    size: 12
  }), m.label);
}
Object.assign(__ds_scope, { PageTypeLabel, ClassificationTag });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/PageTypeLabel.jsx", error: String((e && e.message) || e) }); }

// components/feedback/SimulatedBadge.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * The most safety-critical element in the product. Solid warning fill, white
 * bold text, 🧪 emoji — deliberately unlike the 15%-tint status pills so a
 * simulated record can never be mistaken for a real one at a glance.
 * Render it on EVERY view of a record carrying is_simulated: true, immediately
 * adjacent to the change-type badge. It is never omittable.
 */
function SimulatedBadge({
  style,
  ...rest
}) {
  return /*#__PURE__*/React.createElement("span", _extends({
    title: "Generated by the simulation tool \u2014 not a real detected change",
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 5,
      background: 'var(--simulated-bg)',
      color: 'var(--simulated-fg)',
      font: 'var(--type-meta)',
      fontWeight: 'var(--font-weight-bold)',
      letterSpacing: 'var(--label-letter-spacing)',
      borderRadius: 'var(--radius-sm)',
      padding: '3px 9px',
      whiteSpace: 'nowrap',
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement("span", {
    "aria-hidden": "true"
  }, "\uD83E\uDDEA"), "SIMULATED");
}
Object.assign(__ds_scope, { SimulatedBadge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/SimulatedBadge.jsx", error: String((e && e.message) || e) }); }

// components/feedback/StatusBadge.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const TONES = {
  success: {
    fg: 'var(--color-success)',
    bg: 'var(--badge-success-bg)'
  },
  error: {
    fg: 'var(--color-error)',
    bg: 'var(--badge-error-bg)'
  },
  warning: {
    fg: 'var(--color-warning)',
    bg: 'var(--badge-warning-bg)'
  },
  favorable: {
    fg: 'var(--color-secondary)',
    bg: 'var(--color-secondary-light)'
  },
  brand: {
    fg: 'var(--color-primary)',
    bg: 'var(--color-primary-light)'
  },
  muted: {
    fg: 'var(--color-text-muted)',
    bg: 'var(--badge-muted-bg)'
  }
};

/** Pill, small text, ~15%-opacity tinted bg + solid-color label. */
function StatusBadge({
  tone = 'muted',
  icon,
  children,
  style,
  ...rest
}) {
  const t = TONES[tone] || TONES.muted;
  return /*#__PURE__*/React.createElement("span", _extends({
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 5,
      background: t.bg,
      color: t.fg,
      font: 'var(--type-meta)',
      fontWeight: 'var(--font-weight-semibold)',
      letterSpacing: 'var(--label-letter-spacing)',
      borderRadius: 'var(--radius-pill)',
      padding: '3px 10px',
      whiteSpace: 'nowrap',
      ...style
    }
  }, rest), icon && /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: icon,
    size: 12
  }), children);
}
const RUN_STATUS = {
  SUCCESS: 'success',
  FAILED: 'error',
  RUNNING: 'warning'
};
/** Monitoring-run status: SUCCESS / FAILED / RUNNING. */
function RunStatusBadge({
  status,
  ...rest
}) {
  return /*#__PURE__*/React.createElement(StatusBadge, _extends({
    tone: RUN_STATUS[status] || 'muted'
  }, rest), status);
}
const DISCOVERY_STATUS = {
  SUGGESTED: 'favorable',
  ACTIVE: 'success',
  DISCARDED: 'muted'
};
/** discovery_status of a monitoring target / candidate row. */
function DiscoveryStatusBadge({
  status,
  ...rest
}) {
  if (status === 'DISCARDED') {
    return /*#__PURE__*/React.createElement("span", _extends({
      style: {
        font: 'var(--type-meta)',
        color: 'var(--color-text-muted)',
        letterSpacing: 'var(--label-letter-spacing)'
      }
    }, rest), "DISCARDED");
  }
  return /*#__PURE__*/React.createElement(StatusBadge, _extends({
    tone: DISCOVERY_STATUS[status] || 'muted'
  }, rest), status);
}
Object.assign(__ds_scope, { StatusBadge, RunStatusBadge, DiscoveryStatusBadge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/StatusBadge.jsx", error: String((e && e.message) || e) }); }

// components/data/CandidateRow.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * A discovery candidate / monitoring target row. DISCARDED rows are
 * de-emphasized rather than hidden — the source keeps them queryable on
 * purpose, in case a rule or LLM call misclassified something wanted.
 */
function CandidateRow({
  url,
  pageType,
  method,
  status,
  interval,
  actions,
  style
}) {
  const discarded = status === 'DISCARDED';
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--space-2)',
      padding: 'var(--space-2) var(--space-3)',
      borderBottom: '1px solid var(--border-card)',
      opacity: discarded ? 0.55 : 1,
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      minWidth: 0,
      flex: '1 1 auto'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      font: 'var(--type-body)',
      fontWeight: 'var(--font-weight-medium)',
      color: 'var(--text-body)',
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap'
    }
  }, url), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--space-2)',
      marginTop: 3
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.PageTypeLabel, {
    type: pageType,
    method: method
  }), interval && /*#__PURE__*/React.createElement("span", {
    style: {
      font: 'var(--type-meta)',
      color: 'var(--text-meta)'
    }
  }, "every ", interval))), /*#__PURE__*/React.createElement(__ds_scope.DiscoveryStatusBadge, {
    status: status
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 'var(--space-1)',
      flex: '0 0 auto'
    }
  }, actions));
}

/** The demo centerpiece. Loading is mandatory — the LLM call takes seconds. */
function SimulateButton({
  loading,
  onClick,
  size = 'sm',
  ...rest
}) {
  return /*#__PURE__*/React.createElement(__ds_scope.Button, _extends({
    variant: "primary",
    size: size,
    loading: loading,
    onClick: onClick
  }, rest), !loading && /*#__PURE__*/React.createElement("span", {
    "aria-hidden": "true"
  }, "\uD83C\uDFAD"), loading ? 'Simulating…' : 'Simulate a Change');
}
Object.assign(__ds_scope, { CandidateRow, SimulateButton });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/data/CandidateRow.jsx", error: String((e && e.message) || e) }); }

// components/feedback/ChangeTypeBadge.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * change_type → tone, following the favorable/unfavorable logic:
 * added is favorable, removed is an error-grade signal, PRICE_CHANGE is
 * deliberately neutral (direction is only meaningful to the viewer's own
 * business), PAGE_UPDATE is the lowest-emphasis fallback.
 */
const TONES = {
  NEW_BLOG: 'favorable',
  NEW_PRODUCT: 'favorable',
  NEW_PROMOTION: 'favorable',
  NEW_CAMPAIGN: 'favorable',
  NEW_AWARD: 'favorable',
  PRODUCT_REMOVED: 'error',
  PRICE_CHANGE: 'warning',
  PAGE_UPDATE: 'muted'
};
const ICONS = {
  NEW_BLOG: 'file-text',
  NEW_PRODUCT: 'package-plus',
  NEW_PROMOTION: 'megaphone',
  NEW_CAMPAIGN: 'megaphone',
  NEW_AWARD: 'award',
  PRODUCT_REMOVED: 'package-minus',
  PRICE_CHANGE: 'tag',
  PAGE_UPDATE: 'file-diff'
};
function ChangeTypeBadge({
  type,
  showIcon = true,
  ...rest
}) {
  return /*#__PURE__*/React.createElement(__ds_scope.StatusBadge, _extends({
    tone: TONES[type] || 'muted',
    icon: showIcon ? ICONS[type] : undefined
  }, rest), type);
}

/** old → new price, shown as text so the viewer judges the direction themselves. */
function PriceDelta({
  from,
  to,
  style
}) {
  return /*#__PURE__*/React.createElement("span", {
    style: {
      font: 'var(--type-body)',
      color: 'var(--text-body)',
      fontVariantNumeric: 'tabular-nums',
      ...style
    }
  }, from, " ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--text-meta)'
    }
  }, "\u2192"), ' ', /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 'var(--font-weight-semibold)'
    }
  }, to));
}
Object.assign(__ds_scope, { ChangeTypeBadge, PriceDelta });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/ChangeTypeBadge.jsx", error: String((e && e.message) || e) }); }

// components/data/ChangeRow.jsx
try { (() => {
/**
 * One record in the changes feed. The SIMULATED marker sits immediately after
 * the change-type badge whenever is_simulated is true — every single time.
 */
function ChangeRow({
  changeType,
  summary,
  target,
  detectedAt,
  isSimulated = false,
  detail,
  style
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 'var(--space-2)',
      padding: 'var(--space-2) var(--space-3)',
      borderBottom: '1px solid var(--border-card)',
      alignItems: 'flex-start',
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--space-1)',
      flex: '0 0 auto',
      paddingTop: 2
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.ChangeTypeBadge, {
    type: changeType
  }), isSimulated && /*#__PURE__*/React.createElement(__ds_scope.SimulatedBadge, null)), /*#__PURE__*/React.createElement("div", {
    style: {
      minWidth: 0,
      flex: '1 1 auto'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      font: 'var(--type-body)',
      color: 'var(--text-body)'
    }
  }, summary), detail && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 4
    }
  }, detail), target && /*#__PURE__*/React.createElement("div", {
    style: {
      font: 'var(--type-meta)',
      color: 'var(--text-meta)',
      marginTop: 3,
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap'
    }
  }, target)), /*#__PURE__*/React.createElement("div", {
    style: {
      font: 'var(--type-meta)',
      color: 'var(--text-meta)',
      flex: '0 0 auto',
      whiteSpace: 'nowrap',
      paddingTop: 2
    }
  }, detectedAt));
}
Object.assign(__ds_scope, { ChangeRow });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/data/ChangeRow.jsx", error: String((e && e.message) || e) }); }

// components/navigation/SegmentedSwitcher.jsx
try { (() => {
/**
 * One rounded-pill container, plain text+icon items inside; only the active
 * item gets a highlighted sub-pill. Use for any in-page multi-option switch
 * (candidate-status filters, data sources) — never for the company selector.
 */
function SegmentedSwitcher({
  options = [],
  value,
  onChange,
  size = 'md',
  style
}) {
  return /*#__PURE__*/React.createElement("div", {
    role: "tablist",
    style: {
      display: 'inline-flex',
      gap: 4,
      background: 'var(--color-bg-subtle)',
      border: '1px solid var(--border-card)',
      borderRadius: 'var(--radius-pill)',
      padding: 4,
      ...style
    }
  }, options.map(o => {
    const val = typeof o === 'string' ? o : o.value;
    const lab = typeof o === 'string' ? o : o.label;
    const icon = typeof o === 'string' ? undefined : o.icon;
    const count = typeof o === 'string' ? undefined : o.count;
    const active = val === value;
    return /*#__PURE__*/React.createElement("button", {
      key: val,
      role: "tab",
      "aria-selected": active,
      onClick: () => onChange && onChange(val),
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        border: 0,
        cursor: 'pointer',
        borderRadius: 'var(--radius-pill)',
        padding: size === 'sm' ? '5px 12px' : '7px 16px',
        font: 'var(--type-body)',
        fontSize: size === 'sm' ? 'var(--font-size-small)' : 'var(--font-size-body)',
        fontWeight: active ? 'var(--font-weight-semibold)' : 'var(--font-weight-medium)',
        background: active ? 'var(--color-bg)' : 'transparent',
        color: active ? 'var(--color-text)' : 'var(--color-text-muted)',
        boxShadow: active ? '0 1px 2px rgba(26,26,26,.06)' : 'none',
        transition: 'var(--transition-control)'
      }
    }, icon && /*#__PURE__*/React.createElement(__ds_scope.Icon, {
      name: icon,
      size: 14
    }), lab, count != null && /*#__PURE__*/React.createElement("span", {
      style: {
        font: 'var(--type-meta)',
        color: 'var(--text-meta)',
        fontVariantNumeric: 'tabular-nums'
      }
    }, count));
  }));
}

/** Lightweight two-option toggle inside a panel: color + underline on active. */
function TextTabs({
  options = [],
  value,
  onChange,
  style
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 'var(--space-3)',
      borderBottom: '1px solid var(--border-card)',
      ...style
    }
  }, options.map(o => {
    const val = typeof o === 'string' ? o : o.value;
    const lab = typeof o === 'string' ? o : o.label;
    const active = val === value;
    return /*#__PURE__*/React.createElement("button", {
      key: val,
      onClick: () => onChange && onChange(val),
      style: {
        border: 0,
        background: 'transparent',
        cursor: 'pointer',
        padding: '0 0 10px',
        marginBottom: -1,
        font: 'var(--type-body)',
        fontWeight: active ? 'var(--font-weight-semibold)' : 'var(--font-weight-medium)',
        color: active ? 'var(--color-primary)' : 'var(--color-text-muted)',
        borderBottom: `2px solid ${active ? 'var(--color-primary)' : 'transparent'}`,
        transition: 'var(--transition-control)'
      }
    }, lab);
  }));
}
Object.assign(__ds_scope, { SegmentedSwitcher, TextTabs });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/navigation/SegmentedSwitcher.jsx", error: String((e && e.message) || e) }); }

// components/navigation/Sidebar.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Left dashboard nav: white bg, brand-red filled circular badge behind the
 * active item's icon. The product ships no logo, so the wordmark slot renders
 * the brand name in plain type — see readme.md > ICONOGRAPHY.
 */
function Sidebar({
  items = [],
  active,
  onSelect,
  brand = 'CompetitorScope',
  footer,
  style
}) {
  return /*#__PURE__*/React.createElement("nav", {
    style: {
      width: 'var(--sidebar-width)',
      flex: '0 0 var(--sidebar-width)',
      background: 'var(--surface-nav)',
      borderRight: '1px solid var(--border-card)',
      padding: 'var(--space-3) var(--space-2)',
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--space-4)',
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      font: 'var(--type-h3)',
      color: 'var(--text-heading)',
      padding: '0 var(--space-1)',
      letterSpacing: '-.01em'
    }
  }, brand), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 2
    }
  }, items.map(it => /*#__PURE__*/React.createElement(SidebarItem, _extends({
    key: it.value
  }, it, {
    active: it.value === active,
    onSelect: onSelect
  })))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 'auto'
    }
  }, footer));
}
function SidebarItem({
  value,
  label,
  icon,
  count,
  active,
  onSelect
}) {
  const [hover, setHover] = React.useState(false);
  return /*#__PURE__*/React.createElement("button", {
    onClick: () => onSelect && onSelect(value),
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--space-1)',
      width: '100%',
      border: 0,
      cursor: 'pointer',
      background: hover && !active ? 'var(--color-bg-subtle)' : 'transparent',
      borderRadius: 'var(--radius-md)',
      padding: '8px',
      font: 'var(--type-body)',
      fontWeight: active ? 'var(--font-weight-semibold)' : 'var(--font-weight-medium)',
      color: active ? 'var(--color-text)' : 'var(--color-text-muted)',
      transition: 'var(--transition-control)',
      textAlign: 'left'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      width: 28,
      height: 28,
      borderRadius: 'var(--radius-pill)',
      background: active ? 'var(--color-primary)' : 'transparent',
      color: active ? 'var(--text-on-brand)' : 'var(--color-text-muted)',
      transition: 'var(--transition-control)'
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: icon,
    size: 16
  })), label, count != null && /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: 'auto',
      font: 'var(--type-meta)',
      color: 'var(--text-meta)',
      fontVariantNumeric: 'tabular-nums'
    }
  }, count));
}
Object.assign(__ds_scope, { Sidebar });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/navigation/Sidebar.jsx", error: String((e && e.message) || e) }); }

// components/navigation/TopBar.jsx
try { (() => {
/** Page header strip: title + optional breadcrumb on the left, actions right. */
function TopBar({
  title,
  breadcrumb,
  meta,
  actions,
  style
}) {
  return /*#__PURE__*/React.createElement("header", {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 'var(--space-3)',
      padding: 'var(--space-3) var(--page-padding)',
      background: 'var(--color-bg)',
      borderBottom: '1px solid var(--border-card)',
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      minWidth: 0
    }
  }, breadcrumb && /*#__PURE__*/React.createElement("div", {
    style: {
      font: 'var(--type-meta)',
      color: 'var(--text-meta)',
      marginBottom: 4
    }
  }, breadcrumb), /*#__PURE__*/React.createElement("h1", {
    style: {
      font: 'var(--type-h2)',
      color: 'var(--text-heading)',
      margin: 0
    }
  }, title), meta && /*#__PURE__*/React.createElement("div", {
    style: {
      font: 'var(--type-meta)',
      color: 'var(--text-meta)',
      marginTop: 4
    }
  }, meta)), actions && /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--space-1)'
    }
  }, actions));
}
Object.assign(__ds_scope, { TopBar });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/navigation/TopBar.jsx", error: String((e && e.message) || e) }); }

// ui_kits/dashboard/app.kit.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const {
  Button,
  RunStatusBadge
} = window.CompetitorScopeDesignSystem_312ddb;
function App() {
  const D = window.CS_DATA;
  const [companyId, setCompanyId] = React.useState('me');
  const [view, setView] = React.useState('dashboard');
  const [targets, setTargets] = React.useState(() => JSON.parse(JSON.stringify(D.targets)));
  const [changes, setChanges] = React.useState(() => JSON.parse(JSON.stringify(D.changes)));
  const [simulatingId, setSimulatingId] = React.useState(null);
  const [result, setResult] = React.useState(null);
  const [discovering, setDiscovering] = React.useState(false);
  const [reloading, setReloading] = React.useState(false);
  const comp = D.competitors[companyId];

  // A company switch reloads the whole view below — no stale rows from the previous company.
  function switchCompany(id) {
    setReloading(true);
    setResult(null);
    setView('dashboard');
    setTimeout(() => {
      setCompanyId(id);
      setReloading(false);
    }, 320);
  }
  function setStatus(id, status) {
    setTargets(prev => ({
      ...prev,
      [companyId]: prev[companyId].map(t => t.id === id ? {
        ...t,
        discovery_status: status,
        interval: status === 'ACTIVE' ? t.interval || '12 h' : t.interval
      } : t)
    }));
  }
  function addManual(url) {
    setTargets(prev => ({
      ...prev,
      [companyId]: [{
        id: 'm' + Date.now(),
        url,
        page_type: 'OTHER',
        classification_method: 'MANUAL',
        discovery_status: 'SUGGESTED'
      }, ...prev[companyId]]
    }));
  }
  function runDiscovery() {
    setDiscovering(true);
    setTimeout(() => setDiscovering(false), 2200);
  }
  function simulate(target) {
    setSimulatingId(target.id);
    setTimeout(() => {
      const events = (D.simulations[target.page_type] || D.simulations.BLOG).map(e => ({
        ...e
      }));
      setSimulatingId(null);
      setResult({
        target,
        events
      });
      setChanges(prev => ({
        ...prev,
        [companyId]: [...events.map((e, i) => ({
          id: 's' + Date.now() + i,
          change_type: e.change_type,
          summary: e.summary,
          from: e.from,
          to: e.to,
          target: target.url.replace(/^https?:\/\//, ''),
          detected_at: 'just now',
          is_simulated: true
        })), ...prev[companyId]]
      }));
    }, 1900);
  }
  const titles = {
    dashboard: {
      title: D.companies.find(c => c.id === companyId).name,
      meta: 'Competitive monitoring overview'
    },
    competitor: {
      breadcrumb: 'Competitors',
      title: comp.name,
      meta: comp.website_url
    },
    changes: {
      title: 'Changes',
      meta: `Chronological feed for ${comp.name}`
    },
    runs: {
      title: 'Monitoring runs',
      meta: 'Latest Layer 2 fetch results'
    }
  };
  const t = titles[view];
  const actions = view === 'competitor' ? /*#__PURE__*/React.createElement(Button, {
    variant: "secondary",
    size: "sm",
    icon: "refresh-cw",
    loading: discovering,
    onClick: runDiscovery
  }, discovering ? 'Running discovery…' : 'Run Discovery') : view === 'dashboard' ? /*#__PURE__*/React.createElement(Button, {
    size: "sm",
    icon: "users",
    onClick: () => setView('competitor')
  }, "Review candidates") : null;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      height: '100%'
    }
  }, /*#__PURE__*/React.createElement(window.Shell, _extends({
    view: view,
    onView: setView,
    companyId: companyId,
    onCompany: switchCompany
  }, t, {
    actions: actions
  }), reloading ? /*#__PURE__*/React.createElement("div", {
    style: {
      font: 'var(--type-body)',
      color: 'var(--text-meta)',
      padding: 'var(--space-6)',
      textAlign: 'center'
    }
  }, "Loading company data\u2026") : view === 'dashboard' ? /*#__PURE__*/React.createElement(window.DashboardScreen, {
    companyId: companyId,
    onOpenCompetitor: v => setView(v === 'changes' ? 'changes' : 'competitor')
  }) : view === 'competitor' ? /*#__PURE__*/React.createElement(window.CompetitorScreen, {
    companyId: companyId,
    targets: targets[companyId],
    onActivate: id => setStatus(id, 'ACTIVE'),
    onDiscard: id => setStatus(id, 'DISCARDED'),
    onSimulate: simulate,
    simulatingId: simulatingId,
    discovering: discovering,
    onAddManual: addManual
  }) : view === 'changes' ? /*#__PURE__*/React.createElement(window.ChangesScreen, {
    changes: changes[companyId]
  }) : /*#__PURE__*/React.createElement(window.Panel, {
    title: "Monitoring runs"
  }, D.runs[companyId].map((r, i, arr) => /*#__PURE__*/React.createElement("div", {
    key: r.id,
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--space-2)',
      padding: 'var(--space-2) var(--space-3)',
      borderBottom: i === arr.length - 1 ? 0 : '1px solid var(--border-card)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0,
      font: 'var(--type-body)'
    }
  }, r.target), /*#__PURE__*/React.createElement(RunStatusBadge, {
    status: r.status
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      font: 'var(--type-meta)',
      color: 'var(--text-meta)'
    }
  }, r.at))))), result && /*#__PURE__*/React.createElement(window.SimulateResult, {
    target: result.target,
    events: result.events,
    onClose: () => setResult(null)
  }));
}

// Mounted by an inline script in index.html — this file must have NO top-level side
// effects, because the design-system compiler evaluates every .jsx in the project.
Object.assign(window, {
  App
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/dashboard/app.kit.jsx", error: String((e && e.message) || e) }); }

// ui_kits/dashboard/changes-screen.kit.jsx
try { (() => {
const {
  ChangeRow,
  PriceDelta,
  SegmentedSwitcher,
  EmptyState
} = window.CompetitorScopeDesignSystem_312ddb;

/** Screen 4 — the chronological changes feed for the selected company. */
function ChangesScreen({
  changes
}) {
  const [scope, setScope] = React.useState('ALL');
  const rows = scope === 'ALL' ? changes : changes.filter(c => c.is_simulated === (scope === 'SIM'));
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(SegmentedSwitcher, {
    value: scope,
    onChange: setScope,
    options: [{
      value: 'ALL',
      label: 'All changes',
      count: changes.length
    }, {
      value: 'REAL',
      label: 'Detected',
      count: changes.filter(c => !c.is_simulated).length
    }, {
      value: 'SIM',
      label: 'Simulated',
      count: changes.filter(c => c.is_simulated).length
    }]
  }), /*#__PURE__*/React.createElement(window.Panel, {
    title: "Changes feed"
  }, rows.length === 0 ? /*#__PURE__*/React.createElement(EmptyState, {
    icon: "inbox",
    message: "No changes in this view yet \u2014 monitoring runs will fill it as pages change."
  }) : rows.map((c, i) => /*#__PURE__*/React.createElement(ChangeRow, {
    key: c.id,
    changeType: c.change_type,
    summary: c.summary,
    target: c.target,
    detectedAt: c.detected_at,
    isSimulated: c.is_simulated,
    detail: c.from ? /*#__PURE__*/React.createElement(PriceDelta, {
      from: c.from,
      to: c.to
    }) : null,
    style: i === rows.length - 1 ? {
      borderBottom: 0
    } : undefined
  }))));
}
Object.assign(window, {
  ChangesScreen
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/dashboard/changes-screen.kit.jsx", error: String((e && e.message) || e) }); }

// ui_kits/dashboard/competitor-screen.kit.jsx
try { (() => {
const {
  CandidateRow,
  SimulateButton,
  SegmentedSwitcher,
  Button,
  Input,
  EmptyState,
  Card
} = window.CompetitorScopeDesignSystem_312ddb;

/** Screen 2 — competitor detail / discovery review, plus the manual-add liveness gate. */
function CompetitorScreen({
  companyId,
  targets,
  onActivate,
  onDiscard,
  onSimulate,
  simulatingId,
  discovering,
  onAddManual
}) {
  const [tab, setTab] = React.useState('SUGGESTED');
  const [adding, setAdding] = React.useState(false);
  const [url, setUrl] = React.useState('');
  const [err, setErr] = React.useState('');
  const counts = {
    SUGGESTED: targets.filter(t => t.discovery_status === 'SUGGESTED').length,
    ACTIVE: targets.filter(t => t.discovery_status === 'ACTIVE').length,
    DISCARDED: targets.filter(t => t.discovery_status === 'DISCARDED').length
  };
  const rows = targets.filter(t => t.discovery_status === tab);
  function submit() {
    // Mirrors the API's liveness gate: the real validation message is shown verbatim.
    if (!/^https?:\/\/\S+\.\S+/.test(url)) {
      setErr('this page doesn’t appear to exist');
      return;
    }
    setErr('');
    setUrl('');
    setAdding(false);
    onAddManual(url);
  }
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 'var(--space-2)',
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement(SegmentedSwitcher, {
    value: tab,
    onChange: setTab,
    options: [{
      value: 'SUGGESTED',
      label: 'Suggested',
      icon: 'radar',
      count: counts.SUGGESTED
    }, {
      value: 'ACTIVE',
      label: 'Active',
      icon: 'crosshair',
      count: counts.ACTIVE
    }, {
      value: 'DISCARDED',
      label: 'Discarded',
      icon: 'archive',
      count: counts.DISCARDED
    }]
  }), /*#__PURE__*/React.createElement(Button, {
    variant: "secondary",
    size: "sm",
    icon: "plus",
    onClick: () => setAdding(v => !v)
  }, "Add manually")), adding && /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'flex-end',
      gap: 'var(--space-2)'
    }
  }, /*#__PURE__*/React.createElement(Input, {
    style: {
      flex: 1
    },
    label: "Page URL",
    icon: "link",
    placeholder: "https://lyfemarketing.com/pricing",
    value: url,
    error: err,
    hint: "The URL is liveness-checked before it is saved.",
    onChange: e => setUrl(e.target.value),
    onKeyDown: e => e.key === 'Enter' && submit()
  }), /*#__PURE__*/React.createElement(Button, {
    onClick: submit,
    style: {
      marginBottom: err ? 22 : 0
    }
  }, "Add"))), /*#__PURE__*/React.createElement(window.Panel, {
    title: tab === 'ACTIVE' ? 'Tracked pages' : tab === 'SUGGESTED' ? 'Discovered candidates' : 'Discarded candidates',
    right: /*#__PURE__*/React.createElement(Button, {
      variant: "secondary",
      size: "sm",
      icon: "refresh-cw",
      loading: discovering
    }, discovering ? 'Running discovery…' : 'Run Discovery')
  }, rows.length === 0 ? /*#__PURE__*/React.createElement(EmptyState, {
    icon: "radar",
    message: tab === 'ACTIVE' ? 'No pages tracked yet — activate a suggested candidate to start monitoring.' : 'No candidates here — run discovery to find some.'
  }) : rows.map((t, i) => /*#__PURE__*/React.createElement(CandidateRow, {
    key: t.id,
    url: t.url,
    pageType: t.page_type,
    method: t.classification_method,
    status: t.discovery_status,
    interval: t.interval,
    style: i === rows.length - 1 ? {
      borderBottom: 0
    } : undefined,
    actions: t.discovery_status === 'SUGGESTED' ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      onClick: () => onActivate(t.id)
    }, "Activate"), /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      variant: "quiet",
      onClick: () => onDiscard(t.id)
    }, "Discard")) : t.discovery_status === 'ACTIVE' ? /*#__PURE__*/React.createElement(SimulateButton, {
      loading: simulatingId === t.id,
      onClick: () => onSimulate(t)
    }) : /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      variant: "quiet",
      onClick: () => onActivate(t.id)
    }, "Restore")
  }))));
}
Object.assign(window, {
  CompetitorScreen
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/dashboard/competitor-screen.kit.jsx", error: String((e && e.message) || e) }); }

// ui_kits/dashboard/dashboard-screen.kit.jsx
try { (() => {
const {
  StatTile,
  CompetitorCard,
  ChangeRow,
  PriceDelta,
  RunStatusBadge,
  Button
} = window.CompetitorScopeDesignSystem_312ddb;

/** Screen 1 — company selector result: stat tiles, the one bold competitor card, recent feed. */
function DashboardScreen({
  companyId,
  onOpenCompetitor
}) {
  const D = window.CS_DATA;
  const comp = D.competitors[companyId];
  const targets = D.targets[companyId];
  const changes = D.changes[companyId];
  const active = targets.filter(t => t.discovery_status === 'ACTIVE');
  const failed = D.runs[companyId].filter(r => r.status === 'FAILED').length;
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))',
      gap: 'var(--card-gap)'
    }
  }, /*#__PURE__*/React.createElement(StatTile, {
    label: "Active pages",
    value: active.length,
    icon: "crosshair"
  }), /*#__PURE__*/React.createElement(StatTile, {
    label: "Changes / 7d",
    value: changes.length,
    icon: "activity",
    favorable: true,
    trend: {
      direction: 'up',
      label: '+2 vs last week'
    }
  }), /*#__PURE__*/React.createElement(StatTile, {
    label: "Failed runs",
    value: failed,
    icon: "alert-triangle",
    favorable: failed === 0,
    trend: failed ? {
      direction: 'up',
      label: '+1 today'
    } : undefined
  })), /*#__PURE__*/React.createElement(CompetitorCard, {
    name: comp.name,
    website: comp.website_url,
    activeTargets: active.length,
    recentChanges: changes.length,
    onOpen: onOpenCompetitor
  }), /*#__PURE__*/React.createElement(window.Panel, {
    title: "Recent updates",
    right: /*#__PURE__*/React.createElement(Button, {
      variant: "quiet",
      size: "sm",
      iconAfter: "chevron-right",
      onClick: () => onOpenCompetitor('changes')
    }, "View all")
  }, changes.slice(0, 3).map((c, i) => /*#__PURE__*/React.createElement(ChangeRow, {
    key: c.id,
    changeType: c.change_type,
    summary: c.summary,
    target: c.target,
    detectedAt: c.detected_at,
    isSimulated: c.is_simulated,
    detail: c.from ? /*#__PURE__*/React.createElement(PriceDelta, {
      from: c.from,
      to: c.to
    }) : null,
    style: i === 2 ? {
      borderBottom: 0
    } : undefined
  }))), /*#__PURE__*/React.createElement(window.Panel, {
    title: "Latest monitoring runs"
  }, D.runs[companyId].map((r, i, arr) => /*#__PURE__*/React.createElement("div", {
    key: r.id,
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--space-2)',
      padding: 'var(--space-2) var(--space-3)',
      borderBottom: i === arr.length - 1 ? 0 : '1px solid var(--border-card)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0,
      font: 'var(--type-body)',
      color: 'var(--text-body)',
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap'
    }
  }, r.target), /*#__PURE__*/React.createElement(RunStatusBadge, {
    status: r.status
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      font: 'var(--type-meta)',
      color: 'var(--text-meta)',
      whiteSpace: 'nowrap'
    }
  }, r.at)))));
}
Object.assign(window, {
  DashboardScreen
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/dashboard/dashboard-screen.kit.jsx", error: String((e && e.message) || e) }); }

// ui_kits/dashboard/data.js
try { (() => {
// Fake data shaped exactly like the API contract's response objects.
window.CS_DATA = {
  companies: [{
    id: 'me',
    name: 'Marketing Eye',
    website_url: 'marketingeye.com.au'
  }, {
    id: 'taf',
    name: 'The Athletes Foot',
    website_url: 'theathletesfoot.com.au'
  }],
  competitors: {
    me: {
      id: 'c1',
      company_id: 'me',
      name: 'Lyfe Marketing',
      website_url: 'lyfemarketing.com'
    },
    taf: {
      id: 'c2',
      company_id: 'taf',
      name: 'JD Sports AU',
      website_url: 'jd-sports.com.au'
    }
  },
  targets: {
    me: [{
      id: 't1',
      url: 'https://lyfemarketing.com/blog',
      page_type: 'BLOG',
      classification_method: 'RULE',
      discovery_status: 'ACTIVE',
      interval: '6 h'
    }, {
      id: 't2',
      url: 'https://lyfemarketing.com/pricing',
      page_type: 'PRICING',
      classification_method: 'RULE',
      discovery_status: 'ACTIVE',
      interval: '12 h'
    }, {
      id: 't3',
      url: 'https://lyfemarketing.com/services',
      page_type: 'SERVICES',
      classification_method: 'LLM',
      discovery_status: 'ACTIVE',
      interval: '24 h'
    }, {
      id: 't4',
      url: 'https://lyfemarketing.com/case-studies',
      page_type: 'WORK',
      classification_method: 'LLM',
      discovery_status: 'SUGGESTED'
    }, {
      id: 't5',
      url: 'https://lyfemarketing.com/about',
      page_type: 'ABOUT',
      classification_method: 'RULE',
      discovery_status: 'SUGGESTED'
    }, {
      id: 't6',
      url: 'https://lyfemarketing.com/contact',
      page_type: 'CONTACT',
      classification_method: 'RULE',
      discovery_status: 'DISCARDED'
    }, {
      id: 't7',
      url: 'https://lyfemarketing.com/privacy-policy',
      page_type: 'OTHER',
      classification_method: 'RULE',
      discovery_status: 'DISCARDED'
    }],
    taf: [{
      id: 't8',
      url: 'https://jd-sports.com.au/mens-shoes',
      page_type: 'PRODUCT_LISTING',
      classification_method: 'LLM',
      discovery_status: 'ACTIVE',
      interval: '6 h'
    }, {
      id: 't9',
      url: 'https://jd-sports.com.au/blog',
      page_type: 'BLOG',
      classification_method: 'RULE',
      discovery_status: 'ACTIVE',
      interval: '6 h'
    }, {
      id: 't10',
      url: 'https://jd-sports.com.au/sale',
      page_type: 'PRODUCT_LISTING',
      classification_method: 'LLM',
      discovery_status: 'SUGGESTED'
    }, {
      id: 't11',
      url: 'https://jd-sports.com.au/careers',
      page_type: 'CAREERS',
      classification_method: 'RULE',
      discovery_status: 'DISCARDED'
    }]
  },
  changes: {
    me: [{
      id: 'x1',
      change_type: 'NEW_BLOG',
      summary: 'New post: “7 B2B Content Trends Agencies Will Sell in 2026”',
      target: 'lyfemarketing.com/blog',
      detected_at: '2 hours ago',
      is_simulated: false
    }, {
      id: 'x2',
      change_type: 'PAGE_UPDATE',
      summary: 'Services page copy changed in 3 sections',
      target: 'lyfemarketing.com/services',
      detected_at: '9 hours ago',
      is_simulated: false
    }, {
      id: 'x3',
      change_type: 'PRICE_CHANGE',
      summary: 'Social Media Management retainer price changed',
      from: '$1,500/mo',
      to: '$1,750/mo',
      target: 'lyfemarketing.com/pricing',
      detected_at: 'Yesterday',
      is_simulated: false
    }, {
      id: 'x4',
      change_type: 'NEW_BLOG',
      summary: 'New post: “How Much Should You Spend on PPC?”',
      target: 'lyfemarketing.com/blog',
      detected_at: '3 days ago',
      is_simulated: false
    }],
    taf: [{
      id: 'x5',
      change_type: 'NEW_PRODUCT',
      summary: 'Added: Nike Air Max Dn8 (Men\'s)',
      target: 'jd-sports.com.au/mens-shoes',
      detected_at: '40 minutes ago',
      is_simulated: false
    }, {
      id: 'x6',
      change_type: 'PRICE_CHANGE',
      summary: 'Nike Pegasus 41 price changed',
      from: '$219.99',
      to: '$179.99',
      target: 'jd-sports.com.au/mens-shoes',
      detected_at: '5 hours ago',
      is_simulated: false
    }, {
      id: 'x7',
      change_type: 'PRODUCT_REMOVED',
      summary: 'Removed: adidas Samba OG (Core Black)',
      target: 'jd-sports.com.au/mens-shoes',
      detected_at: 'Yesterday',
      is_simulated: false
    }, {
      id: 'x8',
      change_type: 'NEW_BLOG',
      summary: 'New post: “Best Running Shoes for Winter Training”',
      target: 'jd-sports.com.au/blog',
      detected_at: '2 days ago',
      is_simulated: false
    }]
  },
  runs: {
    me: [{
      id: 'r1',
      target: 'lyfemarketing.com/blog',
      status: 'SUCCESS',
      at: '18 min ago'
    }, {
      id: 'r2',
      target: 'lyfemarketing.com/pricing',
      status: 'SUCCESS',
      at: '52 min ago'
    }, {
      id: 'r3',
      target: 'lyfemarketing.com/services',
      status: 'FAILED',
      at: '1 hour ago'
    }],
    taf: [{
      id: 'r4',
      target: 'jd-sports.com.au/mens-shoes',
      status: 'RUNNING',
      at: 'now'
    }, {
      id: 'r5',
      target: 'jd-sports.com.au/blog',
      status: 'SUCCESS',
      at: '35 min ago'
    }]
  },
  // What POST /monitoring-targets/<id>/simulate returns, per page type.
  simulations: {
    BLOG: [{
      change_type: 'NEW_BLOG',
      summary: 'New post: “The Agency Retainer Is Dead. Here’s What Replaced It.”'
    }],
    PRICING: [{
      change_type: 'PRICE_CHANGE',
      summary: 'SEO starter package price changed',
      from: '$800/mo',
      to: '$950/mo'
    }],
    SERVICES: [{
      change_type: 'PAGE_UPDATE',
      summary: 'Services page added a new “AI Content Ops” offering'
    }],
    PRODUCT_LISTING: [{
      change_type: 'NEW_PRODUCT',
      summary: 'Added: ASICS Gel-Kayano 32 (Men’s)'
    }, {
      change_type: 'PRICE_CHANGE',
      summary: 'New Balance 9060 price changed',
      from: '$239.99',
      to: '$199.99'
    }, {
      change_type: 'PRODUCT_REMOVED',
      summary: 'Removed: Puma Speedcat OG'
    }]
  }
};
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/dashboard/data.js", error: String((e && e.message) || e) }); }

// ui_kits/dashboard/shell.kit.jsx
try { (() => {
const {
  Sidebar,
  TopBar,
  Select
} = window.CompetitorScopeDesignSystem_312ddb;

/** Fixed left nav + white topbar + tinted scrolling content. Every screen uses it. */
function Shell({
  view,
  onView,
  companyId,
  onCompany,
  title,
  breadcrumb,
  meta,
  actions,
  children
}) {
  const D = window.CS_DATA;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      height: '100%',
      background: 'var(--surface-page)',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement(Sidebar, {
    active: view,
    onSelect: onView,
    items: [{
      value: 'dashboard',
      label: 'Dashboard',
      icon: 'layout-dashboard'
    }, {
      value: 'competitor',
      label: 'Competitors',
      icon: 'users',
      count: 1
    }, {
      value: 'changes',
      label: 'Changes',
      icon: 'activity',
      count: D.changes[companyId].length
    }, {
      value: 'runs',
      label: 'Monitoring runs',
      icon: 'clock'
    }],
    footer: /*#__PURE__*/React.createElement("div", {
      style: {
        borderTop: '1px solid var(--border-card)',
        paddingTop: 'var(--space-2)'
      }
    }, /*#__PURE__*/React.createElement(Select, {
      label: "Company",
      size: "sm",
      value: companyId,
      onChange: onCompany,
      options: D.companies.map(c => ({
        value: c.id,
        label: c.name
      }))
    }))
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0,
      display: 'flex',
      flexDirection: 'column'
    }
  }, /*#__PURE__*/React.createElement(TopBar, {
    title: title,
    breadcrumb: breadcrumb,
    meta: meta,
    actions: actions
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflow: 'auto',
      padding: 'var(--page-padding)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 1100,
      margin: '0 auto',
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--space-2)'
    }
  }, children))));
}

/** Card-shaped list with a hairline-divided body and a small header strip. */
function Panel({
  title,
  right,
  children,
  style
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      background: 'var(--surface-card)',
      border: '1px solid var(--border-card)',
      borderRadius: 'var(--radius-lg)',
      overflow: 'hidden',
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 'var(--space-2)',
      padding: 'var(--space-2) var(--space-3)',
      borderBottom: '1px solid var(--border-card)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      font: 'var(--type-h3)',
      color: 'var(--text-heading)'
    }
  }, title), right), children);
}
Object.assign(window, {
  Shell,
  Panel
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/dashboard/shell.kit.jsx", error: String((e && e.message) || e) }); }

// ui_kits/dashboard/simulate-result.kit.jsx
try { (() => {
const {
  ChangeRow,
  PriceDelta,
  Button,
  Icon
} = window.CompetitorScopeDesignSystem_312ddb;

/** Screen 3 — the simulate result, rendered as changes-feed rows in a modal. */
function SimulateResult({
  target,
  events,
  onClose
}) {
  return /*#__PURE__*/React.createElement("div", {
    onClick: onClose,
    style: {
      position: 'absolute',
      inset: 0,
      background: 'rgba(26,26,26,.35)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: 'var(--space-4)',
      animation: 'cs-fade-in 180ms var(--ease-standard)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    onClick: e => e.stopPropagation(),
    style: {
      background: 'var(--surface-card)',
      border: '1px solid var(--border-card)',
      borderRadius: 'var(--radius-lg)',
      boxShadow: 'var(--shadow-overlay)',
      width: 'min(680px,100%)',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'flex-start',
      gap: 'var(--space-2)',
      padding: 'var(--space-3)',
      borderBottom: '1px solid var(--border-card)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      font: 'var(--type-h3)',
      color: 'var(--text-heading)'
    }
  }, "Simulation complete"), /*#__PURE__*/React.createElement("div", {
    style: {
      font: 'var(--type-meta)',
      color: 'var(--text-meta)',
      marginTop: 3
    }
  }, events.length, " change ", events.length === 1 ? 'record' : 'records', " written for ", target.url)), /*#__PURE__*/React.createElement("button", {
    onClick: onClose,
    style: {
      border: 0,
      background: 'transparent',
      cursor: 'pointer',
      color: 'var(--color-text-muted)',
      padding: 4
    },
    "aria-label": "Close"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "x",
    size: 18
  }))), events.map((e, i) => /*#__PURE__*/React.createElement(ChangeRow, {
    key: i,
    changeType: e.change_type,
    summary: e.summary,
    target: target.url.replace(/^https?:\/\//, ''),
    detectedAt: "just now",
    isSimulated: true,
    detail: e.from ? /*#__PURE__*/React.createElement(PriceDelta, {
      from: e.from,
      to: e.to
    }) : null,
    style: i === events.length - 1 ? {
      borderBottom: 0
    } : undefined
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--space-2)',
      padding: 'var(--space-2) var(--space-3)',
      borderTop: '1px solid var(--border-card)',
      background: 'var(--color-bg-subtle)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      font: 'var(--type-meta)',
      color: 'var(--text-meta)',
      flex: 1
    }
  }, "Simulated records are excluded from the real monitoring baseline."), /*#__PURE__*/React.createElement(Button, {
    size: "sm",
    variant: "secondary",
    onClick: onClose
  }, "Done"))));
}
Object.assign(window, {
  SimulateResult
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/dashboard/simulate-result.kit.jsx", error: String((e && e.message) || e) }); }

__ds_ns.Button = __ds_scope.Button;

__ds_ns.Card = __ds_scope.Card;

__ds_ns.CardHeader = __ds_scope.CardHeader;

__ds_ns.Icon = __ds_scope.Icon;

__ds_ns.Input = __ds_scope.Input;

__ds_ns.Select = __ds_scope.Select;

__ds_ns.CandidateRow = __ds_scope.CandidateRow;

__ds_ns.SimulateButton = __ds_scope.SimulateButton;

__ds_ns.ChangeRow = __ds_scope.ChangeRow;

__ds_ns.CompetitorCard = __ds_scope.CompetitorCard;

__ds_ns.StatTile = __ds_scope.StatTile;

__ds_ns.ChangeTypeBadge = __ds_scope.ChangeTypeBadge;

__ds_ns.PriceDelta = __ds_scope.PriceDelta;

__ds_ns.EmptyState = __ds_scope.EmptyState;

__ds_ns.PageTypeLabel = __ds_scope.PageTypeLabel;

__ds_ns.ClassificationTag = __ds_scope.ClassificationTag;

__ds_ns.SimulatedBadge = __ds_scope.SimulatedBadge;

__ds_ns.StatusBadge = __ds_scope.StatusBadge;

__ds_ns.RunStatusBadge = __ds_scope.RunStatusBadge;

__ds_ns.DiscoveryStatusBadge = __ds_scope.DiscoveryStatusBadge;

__ds_ns.SegmentedSwitcher = __ds_scope.SegmentedSwitcher;

__ds_ns.TextTabs = __ds_scope.TextTabs;

__ds_ns.Sidebar = __ds_scope.Sidebar;

__ds_ns.TopBar = __ds_scope.TopBar;

})();
