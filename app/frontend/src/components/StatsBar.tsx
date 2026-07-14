import type { Stats } from '../types'

export default function StatsBar({ stats }: { stats: Stats | null }) {
  if (!stats) return <div className="stats" />
  const tiles: [string, number | string][] = [
    ['Total jobs', stats.total],
    ['Matched', stats.matched],
    ['Applied', stats.applied],
    ['Found 24h', stats.last_24h],
    ['Matched 24h', stats.matched_24h],
    ['Companies', stats.companies_total ?? '—'],
    ['Automatable', stats.companies_automatable ?? '—'],
  ]
  return (
    <div className="stats">
      {tiles.map(([k, v]) => (
        <div className="stat" key={k}>
          <div className="n">{v ?? '—'}</div>
          <div className="l">{k}</div>
        </div>
      ))}
    </div>
  )
}