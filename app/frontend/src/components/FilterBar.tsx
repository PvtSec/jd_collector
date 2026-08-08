import type { Filters } from '../types'

// Filters: free-text search, ATS (checkbox "avoid some"), matched-only, applied,
// time-of-listing (the "recently found by backend" filter maps to first_seen
// window), sort. The ATS control is a checkbox dropdown: every ATS is checked
// (included) by default; unchecking one AVOIDS (excludes) it. `filters.ats`
// holds the EXCLUDED set ([] = all, no filter).
export default function FilterBar({
  filters, onChange, atsList, byAts, totalCount,
}: {
  filters: Filters
  onChange: (patch: Partial<Filters>) => void
  atsList: string[]
  byAts: Record<string, number>
  totalCount: number
}) {
  const set = (k: keyof Filters) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const v = e.target.type === 'checkbox'
      ? (e.target as HTMLInputElement).checked
      : e.target.value
    onChange({ [k]: v } as Partial<Filters>)
  }

  const excluded = filters.ats || []
  const isAvoided = (a: string) => excluded.includes(a)
  const toggle = (a: string) =>
    onChange({ ats: isAvoided(a) ? excluded.filter(x => x !== a) : [...excluded, a] })
  const avoidAll = () => onChange({ ats: [...atsList] })  // exclude everything = none
  const avoidNone = () => onChange({ ats: [] })          // exclude nothing  = all
  const includedCount = atsList.length - excluded.length

  // show the busiest ATS first so the avoidable heavy ones are at the top
  const sorted = [...atsList].sort((a, b) => (byAts[b] || 0) - (byAts[a] || 0)
    || a.localeCompare(b))
  const headerLabel = excluded.length === 0
    ? 'ATS: all'
    : `ATS: ${includedCount}/${atsList.length} (−${excluded.length} avoided)`

  return (
    <div className="filters">
      {filters.skill && (
        <span
          onClick={() => onChange({ skill: '' })}
          title="Clear skill filter"
          style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 6,
            background: '#1f6feb33', color: 'var(--accent)', border: '1px solid var(--accent)',
            borderRadius: 6, padding: '4px 10px', fontSize: 12 }}
        >
          {filters.skill} ✕
        </span>
      )}
      <input type="search" placeholder="Search company / role / location…"
             value={filters.q} onChange={set('q')} />

      <details className="ats-dropdown">
        <summary>{headerLabel}</summary>
        <div className="ats-panel">
          <div className="ats-actions">
            <button type="button" onClick={avoidNone}>All</button>
            <button type="button" onClick={avoidAll}>None</button>
          </div>
          {sorted.length === 0 && <div className="muted" style={{ padding: 6 }}>no ATS yet</div>}
          {sorted.map(a => (
            <label key={a} className="ats-row" title={isAvoided(a) ? `${a} avoided` : a}>
              <input type="checkbox" checked={!isAvoided(a)} onChange={() => toggle(a)} />
              <span className="ats-name">{a}</span>
              <span className="ats-count">{(byAts[a] || 0).toLocaleString()}</span>
            </label>
          ))}
        </div>
      </details>

      <select value={filters.recent} onChange={set('recent')}>
        <option value="">Any time</option>
        <option value="1h">Last hour</option>
        <option value="24h">Last 24 h</option>
        <option value="7d">Last 7 days</option>
        <option value="30d">Last 30 days</option>
      </select>

      <select value={filters.sort} onChange={set('sort')}>
        <option value="recent">Sort: recently found</option>
        <option value="company">Sort: company</option>
        <option value="matched">Sort: matched first</option>
      </select>

      <select value={filters.applied} onChange={set('applied')}>
        <option value="">Any apply state</option>
        <option value="false">Not applied</option>
        <option value="true">Applied</option>
      </select>

      <select value={filters.closed} onChange={set('closed')}>
        <option value="exclude">Open only</option>
        <option value="only">Closed</option>
        <option value="any">Open + closed</option>
      </select>

      <label className="chk">
        <input type="checkbox" checked={filters.matched} onChange={set('matched')} />
        Matched only
      </label>

      <span className="result-count">
        {totalCount.toLocaleString()} results{filters.q ? ` for “${filters.q}”` : ''}
      </span>
    </div>
  )
}