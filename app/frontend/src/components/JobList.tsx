import { useEffect, useState } from 'react'
import type { JobRow } from '../types'
import { fmtAgo } from '../api'

export default function JobList({
  jobs, onMarkApplied, onHide,
}: {
  jobs: JobRow[]
  onMarkApplied: (job: JobRow) => void
  onHide: (job: JobRow) => void
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

  if (!jobs.length) return <p className="empty">No jobs match the current filters.</p>
  return (
    <div className="tablewrap">
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
                  <button className="hide-btn"
                          title="hide this dead/stale link (persists across restarts)"
                          onClick={() => onHide(j)}>✕ hide</button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}