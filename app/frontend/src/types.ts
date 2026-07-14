// Shapes mirroring the backend JSON responses (see app/backend/src/app.py).

export interface JobRow {
  id: number
  company: string
  ats: string
  job_id: string
  title: string
  location: string
  work_type: string
  url: string
  posted_at: string
  first_seen: number
  last_seen: number
  last_check: number
  matched: number  // 0 | 1
  applied: number  // 0 | 1
}

export interface JobsResponse {
  items: JobRow[]
  total: number
  count: number
  limit: number
  offset: number
}

export interface Stats {
  total: number
  matched: number
  applied: number
  last_24h: number
  matched_24h: number
  by_ats: Record<string, number>
  last_run: TaskRun | null
  applied_ledger: Record<string, number>
  companies_total?: number
  companies_automatable?: number
}

export interface TaskRun {
  id: number
  kind: string
  started_at: number
  ended_at: number | null
  status: string  // running | success | failed
  companies_total: number | null
  companies_done: number | null
  jobs_seen: number | null
  jobs_new: number | null
  jobs_matched: number | null
  error: string | null
}

export interface CurrentTask {
  running: boolean
  kind?: string
  started_at?: number
  run_id?: number
  companies_total?: number
  companies_done?: number
  jobs_seen?: number
  jobs_new?: number
  jobs_matched?: number
  progress?: string
}

export interface DailyStat {
  date: string
  runs: number
  jobs_new: number
  jobs_matched: number
  companies_enumerated: number
}

export interface SSEEvent {
  type: 'hello' | 'task_started' | 'task_progress' | 'task_completed' | 'task_failed'
  [k: string]: unknown
}

export interface Filters {
  q: string
  ats: string
  matched: boolean
  applied: '' | 'true' | 'false'
  recent: string  // '' | '24h' | '7d' | '30d' | 'all'
  sort: 'recent' | 'company' | 'matched'
}