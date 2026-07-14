import type { CurrentTask, DailyStat, TaskRun } from '../types'
import { fmtAgo } from '../api'

// Top-right status: shows whether the backend is running a task, the last run,
// and a per-day discovery rollup. Includes the force-reload button (disabled
// while a task is running) per the spec, plus a manual rescan button.
export default function StatusBar({
  task, daily, lastRun, onForceRun, onRescan, runMsg,
}: {
  task: CurrentTask | null
  daily: DailyStat[]
  lastRun?: TaskRun | null
  onForceRun: () => void
  onRescan: () => void
  runMsg: string
}) {
  const running = task?.running ?? false

  return (
    <div className="statusbar">
      <div className="status-pill" data-state={running ? 'running' : 'idle'}>
        <span className="dot" />
        {running ? `Running: ${task?.kind ?? 'task'}` : 'Idle'}
      </div>

      <div className="status-detail">
        {running
          ? <span className="muted">
              started {fmtAgo(task?.started_at)} · {task?.progress ?? ''}
              {task?.companies_total ? ` · ${task.companies_done ?? 0}/${task.companies_total}` : ''}
              {task?.jobs_new ? ` · +${task.jobs_new} new` : ''}
            </span>
          : lastRun
            ? <span className="muted">
                last run {fmtAgo(lastRun.ended_at)} · +{lastRun.jobs_new ?? 0} new ·{' '}
                {lastRun.status}
              </span>
            : <span className="muted">no runs yet · ticks every 5 min</span>}
      </div>

      <div className="status-runs" title="discovery per day (last 14 days)">
        {daily.length
          ? daily.slice(0, 7).map(r => (
              <span key={r.date} className="day-chip">
                <b>{r.date.slice(5)}</b> +{r.jobs_new || 0}
              </span>
            ))
          : <span className="muted">no daily history yet</span>}
      </div>

      <button
        className="force-btn"
        onClick={onForceRun}
        disabled={running}
        title={running ? 'a task is already running' : 'force a discovery task now'}
      >
        ⟳ Force reload
      </button>

      <button
        className="rescan-btn"
        onClick={onRescan}
        disabled={running}
        title={running ? 'a task is already running'
          : 'slow: re-runs discover_slugs + discover_topstartups + consolidate'}
      >
        ⟳ Rescan companies
      </button>

      {runMsg && <div className="run-msg">{runMsg}</div>}
    </div>
  )
}