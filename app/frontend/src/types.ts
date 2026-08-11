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
  closed: number   // 0 | 1 (absent from board for >= grace misses)
  closed_at: number | null
}

export interface JobsResponse {
  items: JobRow[]
  total: number
  count: number
  limit: number
  offset: number
}

export interface DemandRow {
  skill: string
  category: string
  count: number
}

export interface DemandResponse {
  analyzed: number
  rows: DemandRow[]
}

export interface Stats {
  total: number
  matched: number
  applied: number
  closed: number
  last_24h: number
  matched_24h: number
  by_ats: Record<string, number>
  last_run: TaskRun | null
  applied_ledger: Record<string, number>
  companies_total?: number
  companies_automatable?: number
  dead_boards?: number
  sweep?: SweepInfo
}

export interface SweepInfo {
  cursor: number
  sweep_id: number
  sweep_started_at: number
  sweep_total: number
  sweep_covered: number
  sweep_jobs_new: number
  sweep_jobs_matched: number
  pct: number
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
  type: 'hello' | 'task_started' | 'task_progress' | 'task_completed' | 'task_failed' | 'sweep_completed'
  [k: string]: unknown
}

export interface Filters {
  q: string
  ats: string[]   // selected ATS (kept). [] = all (no filter). uncheck = exclude.
  matched: boolean
  applied: '' | 'true' | 'false'
  recent: string  // '' | '24h' | '7d' | '30d' | 'all'
  sort: 'recent' | 'company' | 'matched'
  closed: 'exclude' | 'only' | 'any'  // open-only (default) | closed | all
  skill: string   // demand skill filter ('' = none)
  // per-column free-text filters ('' = none). AND together with q.
  company: string
  title: string
  location: string
  ats_q: string   // text filter on ats (independent of the `ats` exclude checkboxes)
}

// ---- Resume builder -----------------------------------------------------

export interface ResumeSkill {
  name: string
  category: string
  keep: boolean
}

export interface WorkBlock {
  title: string
  company: string
  location: string
  start: string
  end: string
  desc: string
  highlights: string[]
}

export interface EduBlock {
  institution: string
  degree: string
  start: string
  end: string
}

export interface CertBlock {
  name: string
  date: string
  url: string
  highlights: string[]
}

export interface ProjectBlock {
  name: string
  tags: string
  url: string
  highlights: string[]
}

export interface AchievementBlock {
  name: string
  date: string
  url: string
  highlights: string[]
}

export interface ResumeForm {
  name: string
  email: string
  phone: string
  location: string
  linkedIn: string
  github: string
  website: string
  jobTitle: string
  company: string
  summary: string[]
  skills: ResumeSkill[]
  experience: WorkBlock[]
  education: EduBlock[]
  certifications: CertBlock[]
  projects: ProjectBlock[]
  achievements: AchievementBlock[]
}

export interface JdResponse {
  title: string
  company: string
  jd_text: string
  skills: { name: string; category: string }[]
  jd_error: string | null
  pdflatex: boolean
}