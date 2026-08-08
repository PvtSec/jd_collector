import { useEffect, useRef, useState } from 'react'
import type {
  JobRow, ResumeForm, ResumeSkill, JdResponse,
  WorkBlock, EduBlock, CertBlock, ProjectBlock, AchievementBlock,
} from '../types'
import { api } from '../api'

// ---- empty-block factories ------------------------------------------------
const emptyWork = (): WorkBlock => ({ title: '', company: '', location: '', start: '', end: '', desc: '', highlights: [''] })
const emptyEdu = (): EduBlock => ({ institution: '', degree: '', start: '', end: '' })
const emptyCert = (): CertBlock => ({ name: '', date: '', url: '', highlights: [] })
const emptyProject = (): ProjectBlock => ({ name: '', tags: '', url: '', highlights: [''] })
const emptyAchievement = (): AchievementBlock => ({ name: '', date: '', url: '', highlights: [] })

const blankForm = (job: JobRow): ResumeForm => ({
  name: '', email: '', phone: '', location: '', linkedIn: '', github: '', website: '',
  jobTitle: job.title || '', company: job.company || '',
  summary: [], skills: [],
  experience: [emptyWork()], education: [emptyEdu()],
  certifications: [], projects: [], achievements: [],
})

// extension profile (subset of autofill_extension/profile.template.json)
interface ExtProfile {
  firstName?: string; lastName?: string; email?: string
  phone?: { country?: string; countryCode?: string; number?: string }
  location?: string; linkedIn?: string; github?: string; website?: string
}

export default function ResumeDialog({ job, onClose }: { job: JobRow; onClose: () => void }) {
  const [form, setForm] = useState<ResumeForm>(() => blankForm(job))
  const [jd, setJd] = useState<JdResponse | null>(null)
  const [jdLoading, setJdLoading] = useState(true)
  const [jdError, setJdError] = useState('')
  const [building, setBuilding] = useState(false)
  const [buildError, setBuildError] = useState('')
  const [newSkill, setNewSkill] = useState('')
  const [newSkillCat, setNewSkillCat] = useState('')
  const [showJd, setShowJd] = useState(false)
  const [extStatus, setExtStatus] = useState<'waiting' | 'filled' | 'none'>('waiting')
  const formRef = useRef(form)
  formRef.current = form

  // --- 1) ask the autofill extension for the stored profile (postMessage bridge) ---
  useEffect(() => {
    const onMsg = (e: MessageEvent) => {
      if (e.source !== window) return
      const d = e.data
      if (!d || d.type !== 'JA_PROFILE' || !d.profile) return
      const p = d.profile as ExtProfile
      setForm(f => ({
        ...f,
        name: f.name || [p.firstName, p.lastName].filter(Boolean).join(' ') || f.name,
        email: f.email || p.email || '',
        phone: f.phone || [p.phone?.countryCode, p.phone?.number].filter(Boolean).join(' ').trim() || '',
        location: f.location || p.location || '',
        linkedIn: f.linkedIn || p.linkedIn || '',
        github: f.github || p.github || '',
        website: f.website || p.website || '',
      }))
      setExtStatus('filled')
    }
    window.addEventListener('message', onMsg)
    window.postMessage({ type: 'JA_GET_PROFILE' }, location.origin)
    const t = setTimeout(() => {
      setExtStatus(s => (s === 'waiting' ? 'none' : s))
    }, 800)
    return () => { window.removeEventListener('message', onMsg); clearTimeout(t) }
  }, [])

  // --- 2) fetch the JD + parsed skills from the backend ---
  useEffect(() => {
    let cancelled = false
    setJdLoading(true)
    api.jd(job.id).then(r => {
      if (cancelled) return
      setJd(r)
      const skills: ResumeSkill[] = (r.skills || []).map(s => ({ name: s.name, category: s.category, keep: true }))
      // Seed a single editable profile-summary line: it should read as a real resume
      // summary covering the role + the skill areas the JD calls for (not a raw skill
      // list). The user is expected to expand it to cover their experience too.
      const cats = [...new Set((r.skills || []).map(s => s.category))].slice(0, 4)
      const seedSummary = cats.length
        ? [`${r.title || job.title} with experience spanning ${cats.join(', ')}.`]
        : (r.title ? [`Targeting the ${r.title} role.`] : [])
      setForm(f => ({ ...f, skills: skills.length ? skills : f.skills, summary: f.summary.length ? f.summary : seedSummary }))
      setJdLoading(false)
    }).catch(e => {
      if (cancelled) return
      setJdError(String(e))
      setJdLoading(false)
    })
    return () => { cancelled = true }
  }, [job.id, job.title])

  // close on Escape
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => { document.removeEventListener('keydown', onKey); document.body.style.overflow = '' }
  }, [onClose])

  // --- field updaters ---
  const setField = <K extends keyof ResumeForm>(k: K, v: ResumeForm[K]) =>
    setForm(f => ({ ...f, [k]: v }))

  const updateBlock = (list: keyof ResumeForm, idx: number, patch: Record<string, unknown>) =>
    setForm(f => {
      const arr = (f[list] as unknown[]).slice() as Record<string, unknown>[]
      arr[idx] = { ...arr[idx], ...patch }
      return { ...f, [list]: arr }
    })
  const addBlock = (list: keyof ResumeForm, blk: unknown) =>
    setForm(f => ({ ...f, [list]: [...(f[list] as unknown[]), blk] }))
  const removeBlock = (list: keyof ResumeForm, idx: number) =>
    setForm(f => ({ ...f, [list]: (f[list] as unknown[]).filter((_, i) => i !== idx) }))

  const setHighlight = (list: keyof ResumeForm, idx: number, hi: number, val: string) =>
    setForm(f => {
      const arr = (f[list] as { highlights: string[] }[]).slice()
      const hl = arr[idx].highlights.slice()
      hl[hi] = val
      arr[idx] = { ...arr[idx], highlights: hl }
      return { ...f, [list]: arr }
    })
  const addHighlight = (list: keyof ResumeForm, idx: number) =>
    setForm(f => {
      const arr = (f[list] as { highlights: string[] }[]).slice()
      arr[idx] = { ...arr[idx], highlights: [...arr[idx].highlights, ''] }
      return { ...f, [list]: arr }
    })
  const removeHighlight = (list: keyof ResumeForm, idx: number, hi: number) =>
    setForm(f => {
      const arr = (f[list] as { highlights: string[] }[]).slice()
      arr[idx] = { ...arr[idx], highlights: arr[idx].highlights.filter((_, i) => i !== hi) }
      return { ...f, [list]: arr }
    })

  // --- skills tag editor ---
  const toggleSkill = (i: number) =>
    setForm(f => { const s = f.skills.slice(); s[i] = { ...s[i], keep: !s[i].keep }; return { ...f, skills: s } })
  const removeSkill = (i: number) =>
    setForm(f => ({ ...f, skills: f.skills.filter((_, j) => j !== i) }))
  const addSkill = () => {
    const nm = newSkill.trim()
    if (!nm) return
    setForm(f => f.skills.some(s => s.name.toLowerCase() === nm.toLowerCase())
      ? f
      : { ...f, skills: [...f.skills, { name: nm, category: newSkillCat.trim() || 'Custom', keep: true }] })
    setNewSkill('')
  }

  // group skills by category for display
  const skillCats: { cat: string; items: ResumeSkill[] }[] = []
  for (const s of form.skills) {
    let g = skillCats.find(c => c.cat === s.category)
    if (!g) { g = { cat: s.category, items: [] }; skillCats.push(g) }
    g.items.push(s)
  }

  // --- submit ---
  const submit = async () => {
    setBuilding(true); setBuildError('')
    try {
      const f = formRef.current
      // drop empty blocks so they don't render stray LaTeX
      const clean: ResumeForm = {
        ...f,
        summary: f.summary.filter(x => x.trim()),
        skills: f.skills,
        experience: f.experience.map(b => ({ ...b, highlights: b.highlights.filter(h => h.trim()) })).filter(b => b.title || b.company),
        education: f.education.filter(b => b.institution || b.degree),
        certifications: f.certifications.map(b => ({ ...b, highlights: b.highlights.filter(h => h.trim()) })).filter(b => b.name),
        projects: f.projects.map(b => ({ ...b, highlights: b.highlights.filter(h => h.trim()) })).filter(b => b.name),
        achievements: f.achievements.map(b => ({ ...b, highlights: b.highlights.filter(h => h.trim()) })).filter(b => b.name),
      }
      const { blob, filename } = await api.buildResume(clean)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename || `${clean.name || 'resume'}_${clean.jobTitle || 'resume'}.pdf`
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 2000)
    } catch (e: any) {
      setBuildError(e?.message || String(e))
    } finally {
      setBuilding(false)
    }
  }

  const noPdf = jd?.pdflatex === false

  return (
    <div className="rb-overlay" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="rb-modal">
        <div className="rb-head">
          <div>
            <div className="rb-title">Build Resume</div>
            <div className="rb-sub">{job.title} · {job.company}</div>
          </div>
          <button className="rb-x" onClick={onClose} title="Close">×</button>
        </div>

        <div className="rb-body">
          {noPdf && <div className="rb-warn">⚠ LaTeX (pdflatex) is not installed in this environment — PDF generation is disabled. Rebuild the image with the TeX Live layer.</div>}
          {buildError && <div className="rb-error"><b>Compile failed:</b><pre>{buildError}</pre></div>}

          {/* personal info */}
          <fieldset className="rb-fieldset">
            <legend>Personal info
              <span className="rb-extstatus" data-st={extStatus}>
                {extStatus === 'filled' ? ' · auto-filled from extension' : extStatus === 'none' ? ' · extension not detected' : ' · asking extension…'}
              </span>
            </legend>
            <div className="rb-grid2">
              <Field label="Full name" value={form.name} onChange={v => setField('name', v)} />
              <Field label="Email" value={form.email} onChange={v => setField('email', v)} />
              <Field label="Phone" value={form.phone} onChange={v => setField('phone', v)} />
              <Field label="Location" value={form.location} onChange={v => setField('location', v)} />
              <Field label="LinkedIn URL" value={form.linkedIn} onChange={v => setField('linkedIn', v)} />
              <Field label="GitHub URL" value={form.github} onChange={v => setField('github', v)} />
              <Field label="Website" value={form.website} onChange={v => setField('website', v)} />
              <Field label="Role (filename)" value={form.jobTitle} onChange={v => setField('jobTitle', v)} />
            </div>
          </fieldset>

          {/* JD + skills */}
          <fieldset className="rb-fieldset">
            <legend>Skills from the job description</legend>
            <div className="rb-jdbar">
              {jdLoading ? <span className="rb-muted">Fetching job description…</span>
                : jdError ? <span className="rb-error">JD fetch failed: {jdError}</span>
                : jd?.jd_text
                  ? <button className="rb-linkbtn" onClick={() => setShowJd(s => !s)}>{showJd ? 'Hide' : 'Show'} job description ({jd.skills.length} skills found)</button>
                  : <span className="rb-muted">No job description available — add skills manually below.</span>}
            </div>
            {showJd && jd?.jd_text && <pre className="rb-jd">{jd.jd_text.slice(0, 4000)}{jd.jd_text.length > 4000 ? '…' : ''}</pre>}

            {skillCats.length === 0 && !jdLoading && <div className="rb-muted">No skills detected. Add your own below.</div>}
            <div className="rb-skills">
              {skillCats.map(g => (
                <div key={g.cat} className="rb-skillcat">
                  <div className="rb-skillcat-name">{g.cat}</div>
                  <div className="rb-tagrow">
                    {g.items.map(s => {
                      const i = form.skills.indexOf(s)
                      return (
                        <span key={s.name} className={'rb-tag' + (s.keep ? ' on' : ' off')}>
                          <label className="rb-tagkeep"><input type="checkbox" checked={s.keep} onChange={() => toggleSkill(i)} />{s.name}</label>
                          <button className="rb-tagx" title="Remove" onClick={() => removeSkill(i)}>×</button>
                        </span>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
            <div className="rb-addskill">
              <input className="rb-input" placeholder="Add a skill…" value={newSkill} onChange={e => setNewSkill(e.target.value)}
                     onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addSkill() } }} />
              <input className="rb-input rb-cat" placeholder="category (optional)" value={newSkillCat} onChange={e => setNewSkillCat(e.target.value)} />
              <button className="rb-addbtn" onClick={addSkill}>Add</button>
            </div>
            <div className="rb-muted rb-hint">Checked tags are included in the resume · uncheck to keep-for-later or × to remove.</div>
          </fieldset>

          {/* profile summary */}
          <fieldset className="rb-fieldset">
            <legend>Profile summary</legend>
            <ListEditor items={form.summary} onChange={v => setField('summary', v)} placeholder="A summary line covering your role, experience, and key skill areas…" multiline />
          </fieldset>

          {/* work experience */}
          <fieldset className="rb-fieldset">
            <legend>Work experience</legend>
            {form.experience.map((b, i) => (
              <div className="rb-block" key={i}>
                <div className="rb-block-head">
                  <span>Experience {i + 1}</span>
                  {form.experience.length > 1 && <button className="rb-rm" onClick={() => removeBlock('experience', i)}>remove</button>}
                </div>
                <div className="rb-grid2">
                  <Field label="Title" value={b.title} onChange={v => updateBlock('experience', i, { title: v })} />
                  <Field label="Company" value={b.company} onChange={v => updateBlock('experience', i, { company: v })} />
                  <Field label="Location" value={b.location} onChange={v => updateBlock('experience', i, { location: v })} />
                  <div className="rb-grid2c">
                    <Field label="Start" value={b.start} onChange={v => updateBlock('experience', i, { start: v })} />
                    <Field label="End" value={b.end} onChange={v => updateBlock('experience', i, { end: v })} />
                  </div>
                </div>
                <Field label="One-line company description" value={b.desc} onChange={v => updateBlock('experience', i, { desc: v })} />
                <div className="rb-hllabel">Highlights</div>
                <ListEditor items={b.highlights} onChange={v => updateBlock('experience', i, { highlights: v })}
                            onItemChange={(hi, v) => setHighlight('experience', i, hi, v)}
                            onAdd={() => addHighlight('experience', i)} onRemove={(hi) => removeHighlight('experience', i, hi)} />
              </div>
            ))}
            <button className="rb-addblock" onClick={() => addBlock('experience', emptyWork())}>+ Add experience</button>
          </fieldset>

          {/* education */}
          <fieldset className="rb-fieldset">
            <legend>Education</legend>
            {form.education.map((b, i) => (
              <div className="rb-block" key={i}>
                <div className="rb-block-head">
                  <span>Education {i + 1}</span>
                  {form.education.length > 1 && <button className="rb-rm" onClick={() => removeBlock('education', i)}>remove</button>}
                </div>
                <div className="rb-grid2">
                  <Field label="Institution" value={b.institution} onChange={v => updateBlock('education', i, { institution: v })} />
                  <Field label="Degree" value={b.degree} onChange={v => updateBlock('education', i, { degree: v })} />
                  <Field label="Start" value={b.start} onChange={v => updateBlock('education', i, { start: v })} />
                  <Field label="End" value={b.end} onChange={v => updateBlock('education', i, { end: v })} />
                </div>
              </div>
            ))}
            <button className="rb-addblock" onClick={() => addBlock('education', emptyEdu())}>+ Add education</button>
          </fieldset>

          {/* certifications */}
          <fieldset className="rb-fieldset">
            <legend>Certifications</legend>
            {form.certifications.map((b, i) => (
              <div className="rb-block" key={i}>
                <div className="rb-block-head">
                  <span>Cert {i + 1}</span>
                  <button className="rb-rm" onClick={() => removeBlock('certifications', i)}>remove</button>
                </div>
                <div className="rb-grid2">
                  <Field label="Name" value={b.name} onChange={v => updateBlock('certifications', i, { name: v })} />
                  <Field label="Date" value={b.date} onChange={v => updateBlock('certifications', i, { date: v })} />
                </div>
                <Field label="URL" value={b.url} onChange={v => updateBlock('certifications', i, { url: v })} />
                <div className="rb-hllabel">Highlights</div>
                <ListEditor items={b.highlights} onChange={v => updateBlock('certifications', i, { highlights: v })}
                            onItemChange={(hi, v) => setHighlight('certifications', i, hi, v)}
                            onAdd={() => addHighlight('certifications', i)} onRemove={(hi) => removeHighlight('certifications', i, hi)} />
              </div>
            ))}
            <button className="rb-addblock" onClick={() => addBlock('certifications', emptyCert())}>+ Add certification</button>
          </fieldset>

          {/* projects */}
          <fieldset className="rb-fieldset">
            <legend>Projects</legend>
            {form.projects.map((b, i) => (
              <div className="rb-block" key={i}>
                <div className="rb-block-head">
                  <span>Project {i + 1}</span>
                  <button className="rb-rm" onClick={() => removeBlock('projects', i)}>remove</button>
                </div>
                <div className="rb-grid2">
                  <Field label="Name" value={b.name} onChange={v => updateBlock('projects', i, { name: v })} />
                  <Field label="Tags (e.g. Python | AWS)" value={b.tags} onChange={v => updateBlock('projects', i, { tags: v })} />
                </div>
                <Field label="URL" value={b.url} onChange={v => updateBlock('projects', i, { url: v })} />
                <div className="rb-hllabel">Highlights</div>
                <ListEditor items={b.highlights} onChange={v => updateBlock('projects', i, { highlights: v })}
                            onItemChange={(hi, v) => setHighlight('projects', i, hi, v)}
                            onAdd={() => addHighlight('projects', i)} onRemove={(hi) => removeHighlight('projects', i, hi)} />
              </div>
            ))}
            <button className="rb-addblock" onClick={() => addBlock('projects', emptyProject())}>+ Add project</button>
          </fieldset>

          {/* achievements */}
          <fieldset className="rb-fieldset">
            <legend>Achievements</legend>
            {form.achievements.map((b, i) => (
              <div className="rb-block" key={i}>
                <div className="rb-block-head">
                  <span>Achievement {i + 1}</span>
                  <button className="rb-rm" onClick={() => removeBlock('achievements', i)}>remove</button>
                </div>
                <div className="rb-grid2">
                  <Field label="Name" value={b.name} onChange={v => updateBlock('achievements', i, { name: v })} />
                  <Field label="Date" value={b.date} onChange={v => updateBlock('achievements', i, { date: v })} />
                </div>
                <Field label="URL" value={b.url} onChange={v => updateBlock('achievements', i, { url: v })} />
                <div className="rb-hllabel">Highlights</div>
                <ListEditor items={b.highlights} onChange={v => updateBlock('achievements', i, { highlights: v })}
                            onItemChange={(hi, v) => setHighlight('achievements', i, hi, v)}
                            onAdd={() => addHighlight('achievements', i)} onRemove={(hi) => removeHighlight('achievements', i, hi)} />
              </div>
            ))}
            <button className="rb-addblock" onClick={() => addBlock('achievements', emptyAchievement())}>+ Add achievement</button>
          </fieldset>
        </div>

        <div className="rb-foot">
          <span className="rb-muted">PDF generated in real time — nothing is stored on the server.</span>
          <div className="rb-footbtns">
            <button className="rb-cancel" onClick={onClose}>Cancel</button>
            <button className="rb-generate" disabled={building || noPdf} onClick={submit}>
              {building ? 'Compiling…' : 'Generate PDF'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ---- small reusable inputs -----------------------------------------------
function Field({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="rb-field">
      <span className="rb-label">{label}</span>
      <input className="rb-input" value={value || ''} onChange={e => onChange(e.target.value)} />
    </label>
  )
}

// ListEditor: edits a string[] of bullet/highlight items. When used standalone
// (summary) it owns the array via onChange(items); when nested in a block the
// parent passes onItemChange/onAdd/onRemove for finer control.
function ListEditor({
  items, onChange, onItemChange, onAdd, onRemove, placeholder, multiline,
}: {
  items: string[]
  onChange?: (items: string[]) => void
  onItemChange?: (idx: number, v: string) => void
  onAdd?: () => void
  onRemove?: (idx: number) => void
  placeholder?: string
  multiline?: boolean
}) {
  const set = (i: number, v: string) => {
    if (onItemChange) { onItemChange(i, v); return }
    const arr = items.slice(); arr[i] = v; onChange!(arr)
  }
  const add = () => {
    if (onAdd) { onAdd(); return }
    onChange!([...items, ''])
  }
  const remove = (i: number) => {
    if (onRemove) { onRemove(i); return }
    onChange!(items.filter((_, j) => j !== i))
  }
  return (
    <div className="rb-list">
      {items.map((it, i) => (
        <div className="rb-listrow" key={i}>
          {multiline
            ? <textarea className="rb-input rb-textarea" rows={2} value={it} placeholder={placeholder}
                        onChange={e => set(i, e.target.value)} />
            : <input className="rb-input" value={it} placeholder={placeholder}
                      onChange={e => set(i, e.target.value)} />}
          <button className="rb-listrm" onClick={() => remove(i)} title="Remove">×</button>
        </div>
      ))}
      <button className="rb-additem" onClick={add}>+ Add bullet</button>
    </div>
  )
}