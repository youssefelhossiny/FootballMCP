import { useState, useEffect, useMemo } from 'react'
import { DEMO_TEAM_ID } from '../lib/demo'

/**
 * Season analytics for the user's own team.
 *
 * Three questions, in the order a manager actually asks them:
 *   1. How did I do this gameweek?      -> vs my own average AND the global average
 *   2. How am I trending?               -> points + rank across every gameweek so far
 *   3. How do I compare to real people? -> mini-league standings
 *
 * The global average matters more than the raw score: a 60 is strong in a
 * low-scoring week and weak in a high-scoring one, so every comparison here is
 * relative rather than absolute.
 */
/**
 * `teamId` prop: when supplied (embedded in My Team) the section uses it and
 * skips its own ID prompt, so the page has ONE place to enter a team id rather
 * than two that can disagree.
 */
export function AnalyticsSection({ teamId: teamIdProp }) {
  const [teamId, setTeamId] = useState(teamIdProp || localStorage.getItem('fpl_team_id') || DEMO_TEAM_ID)
  const [inputId, setInputId] = useState('')
  const [data, setData] = useState(null)
  const [leagueId, setLeagueId] = useState(null)
  const [league, setLeague] = useState(null)
  const [loading, setLoading] = useState(false)
  const [leagueLoading, setLeagueLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (teamIdProp && teamIdProp !== teamId) setTeamId(teamIdProp)
  }, [teamIdProp])

  useEffect(() => {
    if (teamId) loadAnalytics(teamId)
  }, [teamId])

  useEffect(() => {
    if (teamId && leagueId) loadLeague(teamId, leagueId)
  }, [teamId, leagueId])

  async function loadAnalytics(id) {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`/api/analytics/${id}`)
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `Could not load team ${id}`)
      }
      const json = await res.json()
      setData(json)
      // Default to the first non-global league — the private ones are the
      // leagues people actually care about placing in.
      const priv = json.leagues?.find((l) => l.id > 1000) || json.leagues?.[0]
      if (priv) setLeagueId(priv.id)
    } catch (e) {
      setError(e.message)
      setData(null)
    } finally {
      setLoading(false)
    }
  }

  async function loadLeague(id, lid) {
    setLeagueLoading(true)
    try {
      const res = await fetch(`/api/analytics/${id}/league/${lid}`)
      setLeague(res.ok ? await res.json() : null)
    } catch {
      setLeague(null)
    } finally {
      setLeagueLoading(false)
    }
  }

  function submitId(e) {
    e.preventDefault()
    const clean = inputId.trim().replace(/\D/g, '')
    if (!clean) return
    localStorage.setItem('fpl_team_id', clean)
    setTeamId(clean)
  }

  if (!teamId) {
    return (
      <div className="card p-12 text-center max-w-lg mx-auto mt-12">
        <div className="text-lg font-semibold text-primary mb-1">Season analytics</div>
        <p className="text-sm text-secondary mb-6">
          Enter your FPL team ID to see your gameweek history, form trend and league standing.
        </p>
        <form onSubmit={submitId} className="flex gap-2 justify-center">
          <input
            value={inputId}
            onChange={(e) => setInputId(e.target.value)}
            placeholder={`e.g. ${DEMO_TEAM_ID}`}
            className="px-3 py-2 rounded-md text-sm outline-none"
            style={{
              background: 'var(--bg-elevated)',
              border: '1px solid var(--border-default)',
              color: 'var(--text-primary, #fff)',
              width: 200,
            }}
          />
          <button type="submit" className="px-4 py-2 rounded-md text-sm font-medium"
            style={{ background: 'var(--accent-primary)', color: '#04140c' }}>
            Load
          </button>
        </form>
        <p className="text-[11px] text-muted mt-4">
          Find it in your FPL URL: fantasy.premierleague.com/entry/<b>ID</b>/event/1
        </p>
      </div>
    )
  }

  if (loading) return <Centered>Loading your season…</Centered>

  if (error) {
    return (
      <div className="card p-8 text-center max-w-lg mx-auto mt-12"
        style={{ borderColor: 'var(--accent-danger)' }}>
        <div className="text-sm mb-4" style={{ color: 'var(--accent-danger)' }}>{error}</div>
        <button onClick={() => { localStorage.removeItem('fpl_team_id'); setTeamId('') }}
          className="px-4 py-2 rounded-md text-sm font-medium"
          style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border-default)' }}>
          Use a different team ID
        </button>
      </div>
    )
  }

  if (!data) return null

  const { summary, gameweeks, leagues, past_seasons: pastSeasons } = data
  const latest = gameweeks[gameweeks.length - 1]

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-semibold text-primary">{summary.team_name}</h1>
          <div className="text-xs text-muted">
            {summary.manager} · {summary.gameweeks_played} gameweeks played
          </div>
        </div>
        <button
          onClick={() => { localStorage.removeItem('fpl_team_id'); setTeamId('') }}
          className="text-xs text-muted hover:text-primary transition-colors">
          change team
        </button>
      </div>

      {/* This gameweek — the headline question */}
      {latest && <LatestGameweek gw={latest} avgOwn={summary.average_score} />}

      {/* Season totals */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
        <Stat label="Total points" value={summary.total_points} />
        <Stat label="Overall rank" value={fmtRank(summary.overall_rank)} />
        <Stat label="Avg / GW" value={summary.average_score} />
        <Stat label="Best GW" value={summary.best_gw ? `${summary.best_gw.points}` : '—'}
          sub={summary.best_gw ? `GW${summary.best_gw.gameweek}` : null} />
        <Stat label="Worst GW" value={summary.worst_gw ? `${summary.worst_gw.points}` : '—'}
          sub={summary.worst_gw ? `GW${summary.worst_gw.gameweek}` : null} />
        <Stat label="Beat average" value={`${summary.beat_average_count}/${summary.gameweeks_played}`} />
        <Stat label="Squad value" value={`£${summary.squad_value}m`}
          sub={`£${summary.bank}m banked`} />
      </div>

      <WorldStanding summary={summary} gameweeks={gameweeks} />

      <PointsChart gameweeks={gameweeks} />

      <div className="grid lg:grid-cols-2 gap-5">
        <PercentileChart gameweeks={gameweeks} />
        <CeilingChart gameweeks={gameweeks} />
      </div>

      {pastSeasons?.length > 0 && <PastSeasons seasons={pastSeasons} summary={summary} />}

      <WorldContext gameweeks={gameweeks} />

      <div className="grid lg:grid-cols-2 gap-5">
        <RankChart gameweeks={gameweeks} rankChange={summary.rank_change} />
        <GameweekTable gameweeks={gameweeks} />
      </div>

      {/* Costs people forget to track */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Points left on bench" value={summary.total_bench_points}
          tone={summary.total_bench_points > 20 ? 'warn' : null}
          sub="wasted if you'd started them" />
        <Stat label="Transfer hits taken" value={`-${summary.total_transfer_cost}`}
          tone={summary.total_transfer_cost > 0 ? 'warn' : null} />
        <Stat label="Chips used" value={summary.chips_used.length}
          sub={summary.chips_used.map((c) => `${c.name} GW${c.gameweek}`).join(', ') || 'none yet'} />
        <Stat label="Rank movement" value={fmtDelta(summary.rank_change)}
          tone={summary.rank_change > 0 ? 'good' : summary.rank_change < 0 ? 'bad' : null}
          sub="since GW1" />
      </div>

      <LeagueSection
        leagues={leagues}
        leagueId={leagueId}
        setLeagueId={setLeagueId}
        league={league}
        loading={leagueLoading}
      />
    </div>
  )
}

/* ---------- This gameweek ---------- */

function LatestGameweek({ gw, avgOwn }) {
  const vsAvg = gw.vs_average
  const vsOwn = +(gw.points - avgOwn).toFixed(1)
  return (
    <div className="card p-5">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-wider text-muted mb-1">
            Gameweek {gw.gameweek}{gw.chip ? ` · ${gw.chip}` : ''}
          </div>
          <div className="flex items-baseline gap-3">
            <span className="text-4xl font-semibold text-primary" style={{ fontFamily: 'var(--font-num)' }}>
              {gw.points}
            </span>
            <span className="text-sm text-secondary">points</span>
          </div>
        </div>
        <div className="flex gap-6 flex-wrap">
          <Delta label="vs global average" value={vsAvg} suffix={` (avg ${gw.average})`} />
          <Delta label="vs your average" value={vsOwn} suffix={` (avg ${avgOwn})`} />
          <div>
            <div className="text-[11px] uppercase tracking-wider text-muted mb-1">GW rank</div>
            <div className="text-lg font-medium text-primary" style={{ fontFamily: 'var(--font-num)' }}>
              {fmtRank(gw.gw_rank)}
            </div>
          </div>
          {gw.bench_points > 0 && (
            <div>
              <div className="text-[11px] uppercase tracking-wider text-muted mb-1">On bench</div>
              <div className="text-lg font-medium" style={{
                fontFamily: 'var(--font-num)',
                color: gw.bench_points >= 10 ? 'var(--accent-warn)' : 'var(--text-secondary)',
              }}>
                {gw.bench_points}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Delta({ label, value, suffix }) {
  const good = value > 0
  const color = value === 0 ? 'var(--text-secondary)' : good ? 'var(--accent-primary)' : 'var(--accent-danger)'
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-muted mb-1">{label}</div>
      <div className="text-lg font-medium" style={{ fontFamily: 'var(--font-num)', color }}>
        {value > 0 ? '+' : ''}{value}
        <span className="text-[11px] text-muted ml-1">{suffix}</span>
      </div>
    </div>
  )
}

/* ---------- World standing ---------- */

function WorldStanding({ summary, gameweeks }) {
  const pct = summary.world_percentile
  const best = summary.best_percentile_gw
  // Percentile is 1 = best, so a LOW number is good.
  const pctiles = gameweeks.map((g) => g.percentile).filter((v) => v != null)
  const avgPctile = pctiles.length
    ? Math.round(pctiles.reduce((a, b) => a + b, 0) / pctiles.length)
    : null

  return (
    <div className="card p-5">
      <SectionTitle
        title="Where you stand in the world"
        hint={`Out of ${summary.total_managers?.toLocaleString() ?? '—'} managers playing.`}
      />
      <div className="mt-4 grid md:grid-cols-4 gap-4 items-center">
        <div className="md:col-span-2">
          {/* A single bar is the clearest way to read "where am I" — position
              along the whole population, not an abstract rank number. */}
          <div className="relative h-8 rounded-md overflow-hidden"
            style={{ background: 'linear-gradient(90deg, var(--accent-primary) 0%, var(--accent-warn) 55%, var(--accent-danger) 100%)', opacity: 0.35 }}>
            {pct != null && (
              <div className="absolute top-0 bottom-0" style={{ left: `${Math.min(pct, 99.5)}%`, width: 3, background: '#fff' }} />
            )}
          </div>
          <div className="flex justify-between text-[10px] text-muted mt-1">
            <span>top 1%</span><span>median</span><span>bottom</span>
          </div>
          {pct != null && (
            <div className="text-sm mt-2" style={{ color: 'var(--accent-primary)' }}>
              You are in the <b>top {pct}%</b> — rank {summary.overall_rank?.toLocaleString()}
            </div>
          )}
        </div>
        <Stat label="Avg GW percentile" value={avgPctile != null ? `top ${avgPctile}%` : '—'}
          sub="1 = best week in the world" />
        <Stat label="Best week" value={best ? `top ${best.percentile}%` : '—'}
          sub={best ? `GW${best.gameweek} · ${best.points} pts` : null}
          tone="good" />
      </div>
    </div>
  )
}

/* ---------- Percentile trend ---------- */

function PercentileChart({ gameweeks }) {
  const pts = gameweeks.filter((g) => g.percentile != null)
  if (!pts.length) return null
  const W = 100, H = 100
  // Percentile 1 = best, so invert: a HIGH line means a good week.
  const coords = pts.map((g, i) => [
    pts.length === 1 ? 0 : (i / (pts.length - 1)) * W,
    (g.percentile / 100) * H,
  ])
  const path = coords.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')

  return (
    <div className="card p-5">
      <SectionTitle title="Weekly world percentile"
        hint="Your rank among all managers that week. Higher on the chart = better." />
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: 140 }} className="mt-3">
        {/* median reference */}
        <line x1="0" y1={H / 2} x2={W} y2={H / 2} stroke="var(--border-strong)" strokeDasharray="2,2" strokeWidth="0.5" />
        <path d={`${path} L${W},${H} L0,${H} Z`} fill="var(--accent-primary)" opacity="0.12" />
        <path d={path} fill="none" stroke="var(--accent-primary)" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
        {coords.map(([x, y], i) => (
          <circle key={i} cx={x} cy={y} r="1.6" fill="var(--accent-primary)" vectorEffect="non-scaling-stroke" />
        ))}
      </svg>
      <div className="flex justify-between text-[10px] text-muted mt-1">
        {pts.map((g) => <span key={g.gameweek}>GW{g.gameweek}<br />top {g.percentile}%</span>)}
      </div>
    </div>
  )
}

/* ---------- Ceiling: how close to a perfect week ---------- */

function CeilingChart({ gameweeks }) {
  const rows = gameweeks.filter((g) => g.pct_of_best != null)
  if (!rows.length) return null
  return (
    <div className="card p-5">
      <SectionTitle title="How close to the best score in the world"
        hint="Your points as a share of that week's highest-scoring manager." />
      <div className="space-y-2.5 mt-4">
        {rows.map((g) => (
          <div key={g.gameweek} className="flex items-center gap-3">
            <span className="text-[11px] text-muted w-10">GW{g.gameweek}</span>
            <div className="flex-1 h-5 rounded" style={{ background: 'var(--bg-elevated)' }}>
              <div className="h-full rounded flex items-center justify-end pr-1.5"
                style={{
                  width: `${g.pct_of_best}%`,
                  background: g.pct_of_best >= 60 ? 'var(--accent-primary)'
                    : g.pct_of_best >= 40 ? 'var(--accent-warn)' : 'var(--accent-danger)',
                  opacity: 0.8,
                }}>
                <span className="text-[10px] font-medium" style={{ color: '#04140c' }}>{g.pct_of_best}%</span>
              </div>
            </div>
            <span className="text-[11px] text-muted w-24 text-right">
              {g.points} / {g.highest}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ---------- Season-over-season ---------- */

function PastSeasons({ seasons, summary }) {
  // Include this season so the comparison is like-for-like on the chart.
  const rows = [...seasons, {
    season: 'this season',
    total_points: summary.total_points,
    rank: summary.overall_rank,
    rank_percentage: summary.world_percentile != null ? String(Math.round(summary.world_percentile)) : null,
    current: true,
  }]
  const maxPts = Math.max(...rows.map((r) => r.total_points || 0), 1)

  return (
    <div className="card p-5">
      <SectionTitle title="Season by season"
        hint="Your own history — the comparison that says whether this year is actually going well." />
      <div className="space-y-3 mt-4">
        {rows.map((r) => {
          const pctNum = r.rank_percentage != null ? Number(r.rank_percentage) : null
          return (
            <div key={r.season} className="flex items-center gap-3">
              <span className="text-xs w-24" style={{ color: r.current ? 'var(--accent-primary)' : 'var(--text-secondary)' }}>
                {r.season}
              </span>
              <div className="flex-1 h-6 rounded" style={{ background: 'var(--bg-elevated)' }}>
                <div className="h-full rounded" style={{
                  width: `${(r.total_points / maxPts) * 100}%`,
                  background: r.current ? 'var(--accent-primary)' : 'var(--border-strong)',
                  opacity: r.current ? 0.85 : 0.6,
                }} />
              </div>
              <span className="text-xs w-16 text-right" style={{ fontFamily: 'var(--font-num)' }}>
                {r.total_points?.toLocaleString()}
              </span>
              <span className="text-[11px] w-28 text-right text-muted">
                {r.rank ? `#${r.rank.toLocaleString()}` : '—'}
                {pctNum != null && (
                  <span style={{ color: pctNum <= 10 ? 'var(--accent-primary)' : 'var(--text-muted)' }}>
                    {' '}· top {pctNum}%
                  </span>
                )}
              </span>
            </div>
          )
        })}
      </div>
      <div className="text-[11px] text-muted mt-3">
        Note: this season is {rows[rows.length - 1].total_points} points so far, so the bar is
        partial — compare the rank percentage rather than the total.
      </div>
    </div>
  )
}

/* ---------- What the rest of the world did ---------- */

function WorldContext({ gameweeks }) {
  const rows = gameweeks.filter((g) => g.most_captained || Object.keys(g.chip_plays || {}).length)
  if (!rows.length) return null
  const CHIP = { bboost: 'Bench Boost', freehit: 'Free Hit', wildcard: 'Wildcard', '3xc': 'Triple Captain' }
  return (
    <div className="card p-5">
      <SectionTitle title="What everyone else did"
        hint="The crowd's captain and chip usage each week — useful for judging differentials." />
      <div className="overflow-x-auto mt-3">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[11px] uppercase tracking-wider text-muted">
              <Th>GW</Th><Th>Most captained</Th><Th right>World avg</Th><Th right>Top score</Th><Th>Chips played</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((g) => (
              <tr key={g.gameweek} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                <Td>{g.gameweek}</Td>
                <Td bold>{g.most_captained || '—'}</Td>
                <Td right muted>{g.average}</Td>
                <Td right muted>{g.highest}</Td>
                <Td muted>
                  {Object.entries(g.chip_plays || {})
                    .sort((a, b) => b[1] - a[1])
                    .slice(0, 2)
                    .map(([k, v]) => `${CHIP[k] || k} ${(v / 1000).toFixed(0)}k`)
                    .join(' · ') || '—'}
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/* ---------- Charts (inline SVG — no chart library needed) ---------- */

function PointsChart({ gameweeks }) {
  const { bars, max } = useMemo(() => {
    const max = Math.max(...gameweeks.flatMap((g) => [g.points, g.average]), 1)
    return { bars: gameweeks, max }
  }, [gameweeks])

  return (
    <div className="card p-5">
      <SectionTitle
        title="Points per gameweek"
        hint="Your score against the global average — the bar is you, the line is everyone."
      />
      <div className="flex items-end gap-2 mt-4" style={{ height: 180 }}>
        {bars.map((g) => {
          const h = (g.points / max) * 100
          const avgH = (g.average / max) * 100
          const beat = g.points >= g.average
          return (
            <div key={g.gameweek} className="flex-1 flex flex-col items-center justify-end relative"
              style={{ height: '100%' }} title={`GW${g.gameweek}: ${g.points} pts (avg ${g.average})`}>
              {/* average marker */}
              <div className="absolute w-full" style={{
                bottom: `${avgH}%`,
                borderTop: '1px dashed var(--border-strong)',
                opacity: 0.7,
              }} />
              <div className="w-full rounded-t transition-all" style={{
                height: `${h}%`,
                minHeight: 3,
                background: beat ? 'var(--accent-primary)' : 'var(--accent-danger)',
                opacity: beat ? 0.85 : 0.6,
              }} />
              <div className="text-[10px] text-muted mt-1.5">{g.gameweek}</div>
            </div>
          )
        })}
      </div>
      <div className="flex gap-4 mt-3 text-[11px] text-muted">
        <Legend color="var(--accent-primary)" label="beat the average" />
        <Legend color="var(--accent-danger)" label="below average" />
        <span className="flex items-center gap-1.5">
          <span style={{ width: 14, borderTop: '1px dashed var(--border-strong)' }} /> global average
        </span>
      </div>
    </div>
  )
}

function RankChart({ gameweeks, rankChange }) {
  const pts = gameweeks.filter((g) => g.overall_rank)
  if (pts.length < 2) {
    return (
      <div className="card p-5">
        <SectionTitle title="Overall rank" hint="Needs at least two gameweeks." />
      </div>
    )
  }
  const ranks = pts.map((g) => g.overall_rank)
  const min = Math.min(...ranks)
  const max = Math.max(...ranks)
  const span = max - min || 1
  const W = 100
  const H = 100
  // Rank is inverted: rank 1 is the TOP of the chart, so a rising line = improving.
  const coords = pts.map((g, i) => {
    const x = (i / (pts.length - 1)) * W
    const y = ((g.overall_rank - min) / span) * H
    return [x, y]
  })
  const path = coords.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const improving = rankChange > 0

  return (
    <div className="card p-5">
      <SectionTitle
        title="Overall rank"
        hint={`${improving ? 'Climbing' : rankChange < 0 ? 'Falling' : 'Flat'} — higher on the chart is better.`}
      />
      <div className="mt-3">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: 150 }}>
          <path d={`${path} L${W},${H} L0,${H} Z`}
            fill={improving ? 'var(--accent-primary)' : 'var(--accent-danger)'} opacity="0.12" />
          <path d={path} fill="none"
            stroke={improving ? 'var(--accent-primary)' : 'var(--accent-danger)'}
            strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
        </svg>
        <div className="flex justify-between text-[10px] text-muted mt-1">
          <span>GW{pts[0].event || pts[0].gameweek} · {fmtRank(pts[0].overall_rank)}</span>
          <span>GW{pts[pts.length - 1].gameweek} · {fmtRank(pts[pts.length - 1].overall_rank)}</span>
        </div>
      </div>
    </div>
  )
}

/* ---------- Tables ---------- */

function GameweekTable({ gameweeks }) {
  return (
    <div className="card p-5">
      <SectionTitle title="Gameweek by gameweek" />
      <div className="overflow-x-auto mt-3">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[11px] uppercase tracking-wider text-muted">
              <Th>GW</Th><Th right>Pts</Th><Th right>Avg</Th><Th right>+/−</Th>
              <Th right>Bench</Th><Th right>Rank</Th>
            </tr>
          </thead>
          <tbody>
            {[...gameweeks].reverse().map((g) => (
              <tr key={g.gameweek} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                <Td>
                  {g.gameweek}
                  {g.chip && <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded"
                    style={{ background: 'var(--accent-primary-soft)', color: 'var(--accent-primary)' }}>
                    {g.chip}
                  </span>}
                </Td>
                <Td right bold>{g.points}</Td>
                <Td right muted>{g.average}</Td>
                <Td right>
                  <span style={{ color: g.vs_average >= 0 ? 'var(--accent-primary)' : 'var(--accent-danger)' }}>
                    {g.vs_average > 0 ? '+' : ''}{g.vs_average}
                  </span>
                </Td>
                <Td right muted={g.bench_points < 10}>
                  <span style={g.bench_points >= 10 ? { color: 'var(--accent-warn)' } : {}}>
                    {g.bench_points}
                  </span>
                </Td>
                <Td right muted>{fmtRank(g.overall_rank)}</Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function LeagueSection({ leagues, leagueId, setLeagueId, league, loading }) {
  if (!leagues?.length) return null
  return (
    <div className="card p-5">
      <SectionTitle title="Mini-leagues" hint="How you compare to people you actually play against." />

      <div className="flex gap-2 flex-wrap mt-3 mb-4">
        {leagues.map((l) => (
          <button key={l.id} onClick={() => setLeagueId(l.id)}
            className="px-3 py-1.5 rounded-md text-xs font-medium transition-colors"
            style={leagueId === l.id
              ? { background: 'var(--accent-primary-soft)', color: 'var(--accent-primary)' }
              : { background: 'var(--bg-elevated)', color: 'var(--text-secondary)' }}>
            {l.name}
            <span className="ml-1.5 text-muted">#{fmtRank(l.rank)}</span>
            {l.movement !== 0 && (
              <span className="ml-1" style={{
                color: l.movement > 0 ? 'var(--accent-primary)' : 'var(--accent-danger)',
              }}>
                {l.movement > 0 ? '▲' : '▼'}{Math.abs(l.movement)}
              </span>
            )}
          </button>
        ))}
      </div>

      {loading && <div className="text-sm text-muted py-4">Loading league…</div>}

      {!loading && league?.stats && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">
            <Stat label="Your rank" value={`#${fmtRank(league.stats.my_rank)}`} />
            <Stat label="Percentile" value={league.stats.percentile != null ? `top ${100 - league.stats.percentile}%` : '—'} />
            <Stat label="Behind leader" value={league.stats.points_behind_leader ?? '—'} sub="points" />
            <Stat label="vs top 50 avg" value={fmtDelta(league.stats.vs_top50_average)}
              tone={league.stats.vs_top50_average > 0 ? 'good' : 'bad'}
              sub="league-wide avg isn't published" />
            <Stat label="Top 50 avg" value={league.stats.top50_average} sub={`${league.stats.members_shown} shown`} />
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[11px] uppercase tracking-wider text-muted">
                  <Th>#</Th><Th>Team</Th><Th>Manager</Th><Th right>GW</Th><Th right>Total</Th>
                </tr>
              </thead>
              <tbody>
                {league.standings.map((e) => (
                  <tr key={e.entry}
                    style={{
                      borderTop: '1px solid var(--border-subtle)',
                      background: e.is_me ? 'var(--accent-primary-soft)' : 'transparent',
                    }}>
                    <Td>{e.rank}</Td>
                    <Td bold={e.is_me}>{e.entry_name}</Td>
                    <Td muted>{e.player_name}</Td>
                    <Td right muted>{e.event_total}</Td>
                    <Td right bold>{e.total}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}

/* ---------- Small shared bits ---------- */

function Stat({ label, value, sub, tone }) {
  const color = tone === 'good' ? 'var(--accent-primary)'
    : tone === 'bad' ? 'var(--accent-danger)'
    : tone === 'warn' ? 'var(--accent-warn)'
    : 'var(--text-primary, #fff)'
  return (
    <div className="card px-4 py-3">
      <div className="text-[10px] uppercase tracking-wider text-muted mb-1">{label}</div>
      <div className="text-lg font-semibold" style={{ fontFamily: 'var(--font-num)', color }}>{value}</div>
      {sub && <div className="text-[10px] text-muted mt-0.5">{sub}</div>}
    </div>
  )
}

function SectionTitle({ title, hint }) {
  return (
    <div>
      <div className="text-sm font-semibold text-primary">{title}</div>
      {hint && <div className="text-[11px] text-muted mt-0.5">{hint}</div>}
    </div>
  )
}

function Legend({ color, label }) {
  return (
    <span className="flex items-center gap-1.5">
      <span style={{ width: 10, height: 10, borderRadius: 2, background: color }} />
      {label}
    </span>
  )
}

const Th = ({ children, right }) => (
  <th className={`pb-2 font-medium ${right ? 'text-right' : 'text-left'}`}>{children}</th>
)
const Td = ({ children, right, bold, muted }) => (
  <td className={`py-2 ${right ? 'text-right' : 'text-left'} ${bold ? 'font-semibold' : ''}`}
    style={{
      color: muted ? 'var(--text-muted, #8b96a8)' : 'var(--text-primary, #fff)',
      fontFamily: right ? 'var(--font-num)' : undefined,
    }}>
    {children}
  </td>
)

const Centered = ({ children }) => (
  <div className="text-center py-16 text-sm text-secondary">{children}</div>
)

function fmtRank(n) {
  if (n == null) return '—'
  return n.toLocaleString()
}

function fmtDelta(n) {
  if (!n) return '0'
  return n > 0 ? `+${n.toLocaleString()}` : n.toLocaleString()
}

function MyAnalyticsPage() {
  return <AnalyticsSection />
}

export default MyAnalyticsPage
