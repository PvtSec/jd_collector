import type { Filters } from '../types'

// Filters: free-text search, ATS, matched-only, applied, time-of-listing
// (the "recently found by backend" filter maps to first_seen window), sort.
export default function FilterBar({
  filters, onChange, atsList, resultCount, totalCount,
}: {
  filters: Filters
  onChange: (patch: Partial<Filters>) => void
  atsList: string[]
  resultCount: number
  totalCount: number
}) {
  const set = (k: keyof Filters) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const v = e.target.type === 'checkbox'
      ? (e.target as HTMLInputElement).checked
      : e.target.value
    onChange({ [k]: v } as Partial<Filters>)
  }
  return (
    <div className="filters">
      <input type="search" placeholder="Search company / role / location…"
             value={filters.q} onChange={set('q')} />

      <select value={filters.ats} onChange={set('ats')}>
        <option value="">All ATS</option>
        {atsList.map(a => <option key={a} value={a}>{a}</option>)}
      </select>

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

      <span className="result-count">{resultCount} shown / {totalCount} total</span>
    </div>
  )
}