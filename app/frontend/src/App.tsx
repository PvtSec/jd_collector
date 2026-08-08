import { useEffect, useState, useCallback } from 'react'
import { api, subscribe, fmtAgo } from './api'
import type { Stats, CurrentTask, DailyStat, JobRow, Filters, SSEEvent } from './types'
import StatusBar from './components/StatusBar'
import StatsBar from './components/StatsBar'
import FilterBar from './components/FilterBar'
import SweepBar from './components/SweepBar'
import JobList from './components/JobList'
import ResumeDialog from './components/ResumeDialog'
import DemandPage from './components/DemandPage'

export default function App() {
  const [task, setTask] = useState<CurrentTask | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [daily, setDaily] = useState<DailyStat[]>([])
  const [atsList, setAtsList] = useState<string[]>([])
  const [jobs, setJobs] = useState<JobRow[]>([])
  const [jobsCount, setJobsCount] = useState(0)
  const [jobsTotal, setJobsTotal] = useState(0)
  const [filters, setFilters] = useState<Filters>({
    q: '', ats: [], matched: true, applied: '', recent: '', sort: 'recent', closed: 'exclude', skill: '',
  })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [error, setError] = useState('')
  const [runMsg, setRunMsg] = useState('')
  const [sweepNotice, setSweepNotice] = useState('')
  const [tick, setTick] = useState(0)  // bump to refetch jobs after a task completes
  const [resumeJob, setResumeJob] = useState<JobRow | null>(null)
  const [view, setView] = useState<'jobs' | 'demand'>(() => window.location.pathname === '/demand' ? 'demand' : 'jobs')

  useEffect(() => {
    const onPop = () => setView(window.location.pathname === '/demand' ? 'demand' : 'jobs')
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  const go = (v: 'jobs' | 'demand') => {
    window.history.pushState({}, '', v === 'demand' ? '/demand' : '/')
    setView(v)
  }
  // debounced free-text search so typing doesn't fire a query per keystroke
  const [debouncedQ, setDebouncedQ] = useState(filters.q)
  useEffect(() => {
    const id = setTimeout(() => setDebouncedQ(filters.q), 300)
    return () => clearTimeout(id)
  }, [filters.q])

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
      if (e.type === 'sweep_completed') {
        // a full discovery sweep finished; the backend immediately starts the
        // next one. Surface it + refresh the sweep bar (stats carries the new cursor).
        const id = (e.sweep_id as number) ?? 0
        const jn = (e.jobs_new as number) ?? 0
        const next = (e.new_sweep_id as number) ?? id + 1
        setSweepNotice(`Sweep #${id} complete (+${jn} new) — starting #${next}`)
        api.stats().then(setStats).catch(() => {})
        window.clearTimeout((window as any).__sweepNoticeT)
        ;(window as any).__sweepNoticeT = window.setTimeout(() => setSweepNotice(''), 15000)
      }
      if (e.type === 'task_completed' || e.type === 'task_failed') {
        api.stats().then(setStats).catch(() => {})
        api.daily(14).then(setDaily).catch(() => {})
        setTick(n => n + 1)
      }
    })
    const poll = setInterval(refreshAll, 10000)
    return () => { unsub(); clearInterval(poll) }
  }, [refreshAll])

  // auto-refresh the jobs table every 15s so newly-discovered jobs appear
  // without a manual reload (the table also refetches on task_completed).
  useEffect(() => {
    const id = setInterval(() => setTick(n => n + 1), 15000)
    return () => clearInterval(id)
  }, [])

  // reload jobs when the non-q filters / page / page-size change, the debounced
  // search settles, a task finishes, or the 15s auto-refresh bumps `tick`.
  // `filters.q` is intentionally NOT a dep — it's applied via debouncedQ so
  // typing doesn't fire a query per keystroke.
  const { matched, ats, applied, recent, sort, closed, skill } = filters
  useEffect(() => {
    let cancelled = false
    const offset = (page - 1) * pageSize
    api.jobs({ q: debouncedQ, matched, ats, applied, recent, sort, closed, skill }, pageSize, offset)
      .then(d => {
        if (cancelled) return
        setJobs(d.items); setJobsCount(d.count); setJobsTotal(d.total)
        if (d.items.length === 0 && d.total > 0 && page > 1) {
          setPage(Math.max(1, Math.ceil(d.total / pageSize)))
        }
      })
      .catch(e => !cancelled && setError(String(e)))
    return () => { cancelled = true }
  }, [debouncedQ, matched, ats, applied, recent, sort, closed, skill, tick, page, pageSize])

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

  const onBuildResume = useCallback((job: JobRow) => setResumeJob(job), [])

  const onFilter = (patch: Partial<Filters>) => {
    setFilters(f => ({ ...f, ...patch }))
    setPage(1)
  }
  const onPickSkill = (skill: string) => {
    setFilters(f => ({ ...f, skill, matched: false }))
    setPage(1)
    go('jobs')
  }
  const onPageChange = (p: number) => setPage(p)
  const onPageSizeChange = (n: number) => { setPageSize(n); setPage(1) }

  if (view === 'demand') return <DemandPage onBack={() => go('jobs')} onPickSkill={onPickSkill} />

  return (
    <div className="app">
      <header className="topbar">
        <StatusBar task={task} daily={daily} onForceRun={forceRun} onRescan={rescan}
                   runMsg={runMsg} lastRun={stats?.last_run}
                   trailing={
                     <button className="rescan-btn" onClick={() => go('demand')} title="Tool / technology demand">
                       Top Demands
                     </button>
                   } />
      </header>

      <main>
        <SweepBar sweep={stats?.sweep} notice={sweepNotice} />
        <StatsBar stats={stats} />
        <FilterBar filters={filters} onChange={onFilter} atsList={atsList}
                   byAts={stats?.by_ats ?? {}} totalCount={jobsTotal} />
        {error && <div className="error">{error}</div>}
        <JobList jobs={jobs} onMarkApplied={onMarkApplied} onHide={onHide}
                 onBuildResume={onBuildResume}
                 page={page} pageSize={pageSize} total={jobsTotal} count={jobsCount}
                 onPageChange={onPageChange} onPageSizeChange={onPageSizeChange} />
      </main>

      {resumeJob && <ResumeDialog job={resumeJob} onClose={() => setResumeJob(null)} />}

      <footer>
        Backend tick every {stats?.last_run ? '' : '5'} min · last run {fmtAgo(stats?.last_run?.ended_at)} ·
        {' '}{jobsTotal} jobs tracked
      </footer>
    </div>
  )
}