import { useEffect, useState } from 'react'
import type { SweepInfo } from '../types'
import { fmtAgo } from '../api'

// Discovery-sweep progress with ETA; resets when the cursor wraps and the
// next full-rotation sweep starts.
export default function SweepBar({ sweep, notice }: { sweep?: SweepInfo; notice?: string }) {
  const [, setTick] = useState(0)  // re-render every 5s so ETA / "ago" stay live
  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 5000)
    return () => clearInterval(id)
  }, [])

  if (!sweep || !sweep.sweep_total) {
    return (
      <div className="sweep-bar">
        <div className="sweep-meta muted">Discovery sweep · preparing…</div>
      </div>
    )
  }

  const total = sweep.sweep_total
  const covered = Math.min(sweep.sweep_covered, total)
  const pct = total ? Math.min(100, Math.round((covered / total) * 100)) : 0
  const done = pct >= 100

  // ETA from the sweep's own rate (covered / elapsed since sweep_started_at).
  const elapsed = sweep.sweep_started_at ? (Date.now() / 1000 - sweep.sweep_started_at) : 0
  let eta = ''
  if (sweep.sweep_started_at && covered > 0 && elapsed > 5 && !done) {
    const remaining = Math.max(0, total - covered)
    const etaSec = remaining / (covered / elapsed)
    eta = ` · ~${fmtDur(etaSec)} left`
  } else if (!sweep.sweep_started_at) {
    eta = ' · estimating…'
  }

  return (
    <div className="sweep-bar">
      <div className="sweep-track" title={`${covered.toLocaleString()} / ${total.toLocaleString()} companies`}>
        <div className="sweep-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="sweep-meta">
        <span className="sweep-label">
          {done
            ? `Sweep #${sweep.sweep_id} complete — starting #${sweep.sweep_id + 1}`
            : `Discovery sweep #${sweep.sweep_id}`}
        </span>
        <span className="muted">
          {' '}· {covered.toLocaleString()}/{total.toLocaleString()} ({pct}%)
          {sweep.sweep_started_at ? ` · started ${fmtAgo(sweep.sweep_started_at)}` : ''}
          {eta}
          {sweep.sweep_jobs_new > 0 && ` · +${sweep.sweep_jobs_new} new`}
        </span>
      </div>
      {notice && <div className="sweep-notice">{notice}</div>}
    </div>
  )
}

function fmtDur(sec: number): string {
  if (!isFinite(sec) || sec <= 0) return '—'
  if (sec < 60) return `${Math.round(sec)}s`
  const m = Math.round(sec / 60)
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  const mm = m % 60
  return mm ? `${h}h ${mm}m` : `${h}h`
}