import { useEffect, useState, useCallback } from 'react'
import { api, subscribe, fmtAgo } from './api'
import type { Stats, CurrentTask, DailyStat, JobRow, Filters, SSEEvent } from './types'
import StatusBar from './components/StatusBar'
import StatsBar from './components/StatsBar'
import FilterBar from './components/FilterBar'
import JobList from './components/JobList'

export default function App() {
  const [task, setTask] = useState<CurrentTask | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [daily, setDaily] = useState<DailyStat[]>([])
  const [atsList, setAtsList] = useState<string[]>([])
  const [jobs, setJobs] = useState<JobRow[]>([])
  const [jobsCount, setJobsCount] = useState(0)
  const [jobsTotal, setJobsTotal] = useState(0)
  const [filters, setFilters] = useState<Filters>({
    q: '', ats: '', matched: true, applied: '', recent: '', sort: 'recent',
  })
  const [error, setError] = useState('')
  const [runMsg, setRunMsg] = useState('')
  const [tick, setTick] = useState(0)  // bump to refetch jobs after a task completes

  // initial load: status + stats + daily + ats
  const refreshAll = useCallback(async () => {
    try {
      const [t, s, d, a] = await Promise.all([
        api.taskCurrent(), api.stats(), api.daily(14), api.ats(),
      ])
      setTask(t); setStats(s); setDaily(d); setAtsList(a)
    } catch (e) {
      setError(String(e))
    }
  }, [])

  useEffect(() => {
    refreshAll()
    // SSE drives live status updates; fall back to polling every 10s if SSE drops
    const unsub = subscribe((e: SSEEvent) => {
      if (e.type === 'hello') return
      api.taskCurrent().then(setTask).catch(() => {})
      if (e.type === 'task_completed' || e.type === 'task_failed') {
        api.stats().then(setStats).catch(() => {})
        api.daily(14).then(setDaily).catch(() => {})
        setTick(n => n + 1)  // refetch jobs
      }
    })
    const poll = setInterval(refreshAll, 10000)
    return () => { unsub(); clearInterval(poll) }
  }, [refreshAll])

  // reload jobs whenever filters change or a task finishes
  useEffect(() => {
    let cancelled = false
    api.jobs(filters)
      .then(d => {
        if (!cancelled) {
          setJobs(d.items); setJobsCount(d.count); setJobsTotal(d.total)
        }
      })
      .catch(e => !cancelled && setError(String(e)))
    return () => { cancelled = true }
  }, [filters, tick])

  const forceRun = useCallback(async () => {
    setRunMsg(''); setError('')
    try {
      await api.forceReload()
      setRunMsg('Task started — discovering jobs…')
      api.taskCurrent().then(setTask).catch(() => {})
    } catch (e: any) {
      if (e.status === 409) setRunMsg('A task is already running — button disabled.')
      else setRunMsg('Failed: ' + (e.detail || String(e)))
    }
  }, [])

  const rescan = useCallback(async () => {
    setRunMsg(''); setError('')
    try {
      const r = await api.rescan()
      setRunMsg(r.note)
      api.taskCurrent().then(setTask).catch(() => {})
    } catch (e: any) {
      if (e.status === 409) setRunMsg('A task is already running — button disabled.')
      else setRunMsg('Failed: ' + (e.detail || String(e)))
    }
  }, [])

  const onMarkApplied = useCallback((job: JobRow) => {
    api.markApplied(job.id).then(() => {
      setJobs(prev => prev.map(j => j.id === job.id ? { ...j, applied: 1 } : j))
      setStats(prev => prev ? { ...prev, applied: prev.applied + 1 } : prev)
    }).catch(e => setError(String(e)))
  }, [])

  const onHide = useCallback((job: JobRow) => {
    api.hide(job.id).then(() => {
      setJobs(prev => prev.filter(j => j.id !== job.id))
      setJobsTotal(n => Math.max(0, n - 1))
    }).catch(e => setError(String(e)))
  }, [])

  const onFilter = (patch: Partial<Filters>) => setFilters(f => ({ ...f, ...patch }))

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <h1>Job Auto</h1>
          <span className="tag">discovery dashboard</span>
        </div>
        <StatusBar task={task} daily={daily} onForceRun={forceRun} onRescan={rescan}
                   runMsg={runMsg} lastRun={stats?.last_run} />
      </header>

      <main>
        <StatsBar stats={stats} />
        <FilterBar filters={filters} onChange={onFilter} atsList={atsList}
                   resultCount={jobsCount} totalCount={jobsTotal} />
        {error && <div className="error">{error}</div>}
        <JobList jobs={jobs} onMarkApplied={onMarkApplied} onHide={onHide} />
      </main>

      <footer>
        Backend tick every {stats?.last_run ? '' : '5'} min · last run {fmtAgo(stats?.last_run?.ended_at)} ·
        {' '}{jobsTotal} jobs tracked
      </footer>
    </div>
  )
}