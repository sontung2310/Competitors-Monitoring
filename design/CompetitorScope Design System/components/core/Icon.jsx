import React from 'react';

const CDN = 'https://cdn.jsdelivr.net/npm/lucide-static@0.544.0/icons/';

/* Fetched-once cache of raw Lucide SVG markup, keyed by icon name. */
const CACHE = new Map();
const PENDING = new Map();

function load(name) {
  if (CACHE.has(name)) return null;
  if (!PENDING.has(name)) {
    PENDING.set(
      name,
      fetch(CDN + name + '.svg')
        .then((r) => (r.ok ? r.text() : ''))
        .then((txt) => {
          // Keep only the inner geometry; the wrapper <svg> is rendered by React
          // so size and color stay under the component's control.
          const inner = txt.replace(/^[\s\S]*?<svg[^>]*>/, '').replace(/<\/svg>[\s\S]*$/, '');
          CACHE.set(name, inner);
          return inner;
        })
        .catch(() => {
          CACHE.set(name, '');
          return '';
        }),
    );
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
export function Icon({ name, size = 16, color = 'currentColor', strokeWidth = 2, style, ...rest }) {
  const [markup, setMarkup] = React.useState(() => CACHE.get(name) ?? null);

  React.useEffect(() => {
    const cached = CACHE.get(name);
    if (cached !== undefined) { setMarkup(cached); return; }
    setMarkup(null);
    let alive = true;
    const p = load(name);
    if (p) p.then((inner) => { if (alive) setMarkup(inner); });
    return () => { alive = false; };
  }, [name]);

  return (
    <svg
      data-icon={name}
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke={color}
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      style={{ display: 'inline-block', flex: '0 0 auto', verticalAlign: 'middle', overflow: 'visible', ...style }}
      dangerouslySetInnerHTML={{ __html: markup || '' }}
      {...rest}
    />
  );
}
