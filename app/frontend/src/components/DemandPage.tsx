import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { DemandResponse } from '../types'

const th = { textAlign: 'left', padding: '8px 10px', fontSize: 12, color: 'var(--muted)', borderBottom: '1px solid var(--border)', position: 'sticky', top: 0, background: 'var(--panel)' } as const
const td = { padding: '7px 10px', fontSize: 13, borderBottom: '1px solid var(--border)' } as const

export default function DemandPage({ onBack, onPickSkill }: { onBack: () => void; onPickSkill: (skill: string) => void }) {
  const [data, setData] = useState<DemandResponse | null>(null)
  const [q, setQ] = useState('')
  const [cat, setCat] = useState('')
  const [err, setErr] = useState('')

  useEffect(() => {
    let stop = false
    const load = () => api.demand(300)
      .then(d => { if (!stop) setData(d) })
      .catch(e => { if (!stop) setErr(String(e)) })
    load()
    const id = setInterval(load, 10000)
    return () => { stop = true; clearInterval(id) }
  }, [])

  const rows = data?.rows ?? []
  const cats = useMemo(() => Array.from(new Set(rows.map(r => r.category))), [rows])
  const filtered = useMemo(() => {
    const ql = q.trim().toLowerCase()
    return rows.filter(r => (!ql || r.skill.toLowerCase().includes(ql)) && (!cat || r.category === cat))
  }, [rows, q, cat])
  const top = filtered.length ? filtered[0].count : 1
  const analyzed = data?.analyzed ?? 0

  return (
    <div className="app">
      <header className="topbar" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <button className="rescan-btn" onClick={onBack}>← Jobs</button>
        <span className="muted" style={{ fontSize: 13 }}>Tool / technology demand</span>
      </header>
      <main>
        <div className="filters">
          <input type="search" placeholder="Filter skills…" value={q} onChange={e => setQ(e.target.value)} />
          <select value={cat} onChange={e => setCat(e.target.value)}>
            <option value="">All categories</option>
            {cats.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
          <span className="result-count">{analyzed.toLocaleString()} jobs analyzed · {filtered.length} skills</span>
        </div>
        {err && <div className="error">{err}</div>}
        <div className="tablewrap">
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={th}>#</th>
                <th style={th}>Skill</th>
                <th style={th}>Category</th>
                <th style={{ ...th, width: '40%' }}>Demand</th>
                <th style={{ ...th, textAlign: 'right' }}>Count</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r, i) => (
                <tr key={r.skill}>
                  <td style={td}>{i + 1}</td>
                  <td style={{ ...td, fontWeight: 600 }}>
                    <span
                      style={{ cursor: 'pointer', color: 'var(--accent)', textDecoration: 'underline' }}
                      onClick={() => onPickSkill(r.skill)}
                      title={`Show jobs demanding ${r.skill}`}
                    >
                      {r.skill}
                    </span>
                  </td>
                  <td style={td} className="muted">{r.category}</td>
                  <td style={td}>
                    <div style={{ height: 8, width: `${Math.max(3, 100 * r.count / top)}%`, background: 'var(--accent)', borderRadius: 4 }} />
                  </td>
                  <td style={{ ...td, textAlign: 'right' }}>{r.count.toLocaleString()}</td>
                </tr>
              ))}
              {!filtered.length && (
                <tr>
                  <td style={td} colSpan={5} className="muted">
                    {analyzed === 0
                      ? 'Analyzing jobs — counts appear as the scheduler scans job descriptions (fills over the first sweep).'
                      : 'No skills match the current filter.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </main>
    </div>
  )
}
