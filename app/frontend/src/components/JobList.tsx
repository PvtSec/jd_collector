import { useEffect, useState } from 'react'
import type { JobRow } from '../types'
import { fmtAgo } from '../api'

// Build the page-number list for the pager, with ellipses where gaps exist.
// e.g. page=5, pages=78 → [1, '…', 3, 4, 5, 6, 7, '…', 78]
function pageList(page: number, pages: number): (number | '…')[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1)
  const out: (number | '…')[] = []
  const first = 1, last = pages
  const lo = Math.max(2, page - 2), hi = Math.min(pages - 1, page + 2)
  out.push(first)
  if (lo > 2) out.push('…')
  for (let p = lo; p <= hi; p++) out.push(p)
  if (hi < pages - 1) out.push('…')
  out.push(last)
  return out
}

export default function JobList({
  jobs, onMarkApplied, onHide, onBuildResume,
  page, pageSize, total, count, onPageChange, onPageSizeChange,
}: {
  jobs: JobRow[]
  onMarkApplied: (job: JobRow) => void
  onHide: (job: JobRow) => void
  onBuildResume: (job: JobRow) => void
  page: number
  pageSize: number
  total: number
  count: number
  onPageChange: (p: number) => void
  onPageSizeChange: (n: number) => void
}) {
  // id of the row highlighted by clicking "Apply now"; stays highlighted until
  // the user clicks anywhere outside that row.
  const [hlId, setHlId] = useState<number | null>(null)

  useEffect(() => {
    if (hlId === null) return
    const onDown = (e: MouseEvent) => {
      // keep the highlight only if the press lands inside the highlighted row
      const tr = (e.target as HTMLElement)?.closest?.('tbody tr[data-jid]') as HTMLElement | null
      if (!tr || tr.dataset.jid !== String(hlId)) setHlId(null)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [hlId])

  const pages = Math.max(1, Math.ceil(total / pageSize))
  const offset = (page - 1) * pageSize
  const rangeStart = total === 0 ? 0 : offset + 1
  const rangeEnd = offset + count

  const pager = (
    <div className="pager">
      <span className="range">
        Showing {rangeStart.toLocaleString()}–{rangeEnd.toLocaleString()} of {total.toLocaleString()} results
      </span>
      <div className="pager-nav">
        <button disabled={page <= 1} onClick={() => onPageChange(page - 1)}>‹</button>
        {pageList(page, pages).map((p, i) =>
          p === '…'
            ? <span key={`e${i}`} className="ellipsis">…</span>
            : <button key={p} className={p === page ? 'active' : ''} onClick={() => onPageChange(p)}>{p}</button>
        )}
        <button disabled={page >= pages} onClick={() => onPageChange(page + 1)}>›</button>
      </div>
      <label className="page-size">
        <select value={pageSize} onChange={e => onPageSizeChange(Number(e.target.value))}>
          <option value={25}>25 / page</option>
          <option value={50}>50 / page</option>
          <option value={100}>100 / page</option>
        </select>
      </label>
    </div>
  )

  if (!jobs.length && total === 0) return <p className="empty">No jobs match the current filters.</p>
  return (
    <div className="tablewrap">
      {pager}
      <table>
        <thead>
          <tr>
            <th>Company</th><th>Role</th><th>Location</th>
            <th>ATS</th><th>Found</th><th></th>
          </tr>
        </thead>
        <tbody>
          {jobs.map(j => (
            <tr key={`${j.company}|${j.ats}|${j.job_id}`}
                data-jid={j.id}
                className={[
                  j.closed === 1 ? 'closed' : (j.applied ? 'applied' : (j.matched ? 'matched' : 'other')),
                  hlId === j.id ? 'highlight' : '',
                ].join(' ').trim()}>
              <td className="co">{j.company}</td>
              <td className="title">{j.title}</td>
              <td className="loc">
                {j.location || '—'}
                {j.work_type && <div className="posted">{j.work_type}</div>}
              </td>
              <td>
                <span className="ats">{j.ats}</span>
                {j.matched === 1 && <span className="match-tag">match</span>}
                {j.closed === 1 && <span className="closed-tag">closed</span>}
              </td>
              <td className="found"
                  title={j.first_seen ? new Date(j.first_seen * 1000).toLocaleString() : ''}>
                {fmtAgo(j.first_seen)}
              </td>
              <td className="actions-cell">
                <div className="actions">
                  {j.url && j.url.startsWith('http')
                    ? <a className="apply-btn" href={j.url} target="_blank"
                          rel="noopener noreferrer"
                          onClick={() => setHlId(j.id)}>Apply now ↗</a>
                    : <span className="muted">no link</span>}
                  {j.applied === 1
                    ? <span className="applied-tag">✓ applied</span>
                    : <button className="mark-btn"
                              onClick={() => onMarkApplied(j)}>Mark applied</button>}
                  <button className="resume-btn"
                          title="Build a tailored resume PDF from this job description"
                          onClick={() => onBuildResume(j)}>Build Resume</button>
                  <button className="hide-btn"
                          title="hide this dead/stale link (persists across restarts)"
                          onClick={() => onHide(j)}>✕ hide</button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {pager}
    </div>
  )
}