import type { JobRow } from '../types'
import { fmtAgo } from '../api'

export default function JobList({
  jobs, onMarkApplied, onHide,
}: {
  jobs: JobRow[]
  onMarkApplied: (job: JobRow) => void
  onHide: (job: JobRow) => void
}) {
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
                className={j.closed === 1 ? 'closed' : (j.applied ? 'applied' : (j.matched ? 'matched' : 'other'))}>
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
                          rel="noopener noreferrer">Apply now ↗</a>
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