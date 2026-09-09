const { Sidebar, TopBar, Select } = window.CompetitorScopeDesignSystem_312ddb;

/** Fixed left nav + white topbar + tinted scrolling content. Every screen uses it. */
function Shell({ view, onView, companyId, onCompany, title, breadcrumb, meta, actions, children }) {
  const D = window.CS_DATA;
  return (
    <div style={{ display: 'flex', height: '100%', background: 'var(--surface-page)', overflow: 'hidden' }}>
      <Sidebar
        active={view}
        onSelect={onView}
        items={[
          { value: 'dashboard', label: 'Dashboard', icon: 'layout-dashboard' },
          { value: 'competitor', label: 'Competitors', icon: 'users', count: 1 },
          { value: 'changes', label: 'Changes', icon: 'activity', count: D.changes[companyId].length },
          { value: 'runs', label: 'Monitoring runs', icon: 'clock' },
        ]}
        footer={
          <div style={{ borderTop: '1px solid var(--border-card)', paddingTop: 'var(--space-2)' }}>
            <Select
              label="Company"
              size="sm"
              value={companyId}
              onChange={onCompany}
              options={D.companies.map((c) => ({ value: c.id, label: c.name }))}
            />
          </div>
        }
      />
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <TopBar title={title} breadcrumb={breadcrumb} meta={meta} actions={actions} />
        <div style={{ flex: 1, overflow: 'auto', padding: 'var(--page-padding)' }}>
          <div style={{ maxWidth: 1100, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}

/** Card-shaped list with a hairline-divided body and a small header strip. */
function Panel({ title, right, children, style }) {
  return (
    <div style={{ background: 'var(--surface-card)', border: '1px solid var(--border-card)', borderRadius: 'var(--radius-lg)', overflow: 'hidden', ...style }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-2)', padding: 'var(--space-2) var(--space-3)', borderBottom: '1px solid var(--border-card)' }}>
        <div style={{ font: 'var(--type-h3)', color: 'var(--text-heading)' }}>{title}</div>
        {right}
      </div>
      {children}
    </div>
  );
}

Object.assign(window, { Shell, Panel });
