const { ChangeRow, PriceDelta, SegmentedSwitcher, EmptyState } = window.CompetitorScopeDesignSystem_312ddb;

/** Screen 4 — the chronological changes feed for the selected company. */
function ChangesScreen({ changes }) {
  const [scope, setScope] = React.useState('ALL');
  const rows = scope === 'ALL' ? changes : changes.filter((c) => c.is_simulated === (scope === 'SIM'));
  return (
    <>
      <SegmentedSwitcher
        value={scope}
        onChange={setScope}
        options={[
          { value: 'ALL', label: 'All changes', count: changes.length },
          { value: 'REAL', label: 'Detected', count: changes.filter((c) => !c.is_simulated).length },
          { value: 'SIM', label: 'Simulated', count: changes.filter((c) => c.is_simulated).length },
        ]}
      />
      <window.Panel title="Changes feed">
        {rows.length === 0 ? (
          <EmptyState icon="inbox" message="No changes in this view yet — monitoring runs will fill it as pages change." />
        ) : (
          rows.map((c, i) => (
            <ChangeRow
              key={c.id}
              changeType={c.change_type}
              summary={c.summary}
              target={c.target}
              detectedAt={c.detected_at}
              isSimulated={c.is_simulated}
              detail={c.from ? <PriceDelta from={c.from} to={c.to} /> : null}
              style={i === rows.length - 1 ? { borderBottom: 0 } : undefined}
            />
          ))
        )}
      </window.Panel>
    </>
  );
}

Object.assign(window, { ChangesScreen });
