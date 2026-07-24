import type {
  JobsResponse, Stats, CurrentTask, TaskRun, DailyStat, Filters, SSEEvent,
} from './types'

const base = '' // same origin in prod; Vite proxy in dev

async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(base + path)
  if (!r.ok) throw new Error(`${path} -> ${r.status}`)
  return r.json() as Promise<T>
}

async function postJSON<T>(path: string): Promise<T> {
  const r = await fetch(base + path, { method: 'POST' })
  const body = await r.json().catch(() => ({}))
  if (!r.ok) {
    const err = new Error(`${path} -> ${r.status}`) as Error & { status: number; detail?: string }
    err.status = r.status
    err.detail = body.detail
    throw err
  }
  return body as T
}

export const api = {
  health: () => getJSON<{ ok: boolean; jobs: number }>('/api/health'),
  stats: () => getJSON<Stats>('/api/stats'),
  daily: (days = 14) => getJSON<DailyStat[]>(`/api/daily?days=${days}`),
  ats: () => getJSON<string[]>('/api/ats'),
  jobs: (f: Partial<Filters>, limit = 300, offset = 0) => {
    const q = new URLSearchParams()
    q.set('limit', String(limit))
    q.set('offset', String(offset))
    if (f.q) q.set('q', f.q)
    if (f.ats) q.set('ats', f.ats)
    if (f.matched) q.set('matched', 'true')
    if (f.applied) q.set('applied', f.applied)
    if (f.recent) q.set('recent', f.recent)
    if (f.sort) q.set('sort', f.sort)
    if (f.closed && f.closed !== 'exclude') q.set('closed', f.closed)
    return getJSON<JobsResponse>(`/api/jobs?${q.toString()}`)
  },
  taskCurrent: () => getJSON<CurrentTask>('/api/tasks/current'),
  taskHistory: () => getJSON<TaskRun[]>('/api/tasks/history'),
  forceReload: () => postJSON<{ accepted: boolean; started_at: number }>('/api/tasks/force-reload'),
  rescan: () => postJSON<{ accepted: boolean; started_at: number; note: string }>('/api/tasks/rescan-companies'),
  markApplied: (id: number) => postJSON<{ ok: boolean; inserted: boolean }>(`/api/jobs/${id}/mark-applied`),
  hide: (id: number) => postJSON<{ ok: boolean; hidden: boolean }>(`/api/jobs/${id}/hide`),
}

export function subscribe(onEvent: (e: SSEEvent) => void): () => void {
  const es = new EventSource(base + '/api/events')
  es.onmessage = (msg) => {
    try {
      onEvent(JSON.parse(msg.data))
    } catch {}
  }
  return () => es.close()
}

export function fmtAgo(ts?: number | null): string {
  if (!ts) return ''
  const s = Math.floor(Date.now() / 1000 - ts)
  if (s < 0) return 'now'
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

export function fmtTime(ts?: number | null): string {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString([], {
    hour: '2-digit', minute: '2-digit', month: 'short', day: 'numeric',
  })
}