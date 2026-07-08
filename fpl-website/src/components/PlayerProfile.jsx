import { useState, useEffect } from 'react'
import { playerDetailAPI } from '../api/fplApi'

/**
 * Player Profile slide-over. Ported from the Matchday "My Team.dc.html" design,
 * wired to the real GET /api/player/{name} endpoint which already returns
 * season / advanced / defensive / progressive stats, recent gameweeks and
 * upcoming fixtures.
 *
 * Props:
 *   playerName: string | null  — when set, the panel opens and fetches
 *   onClose: () => void
 *   squadPlayers: array         — current squad, to detect if this player is owned
 *   onTransferOut: (squadPlayer) => void  — start a transfer for an owned player
 *   onSubstitute: (aId, bId) => void      — bench<->XI sub
 *   canSubstitute: (aId, bId) => boolean  — legality check for sub targets
 */
function PlayerProfile({ playerName, onClose, squadPlayers = [], onTransferOut, onSubstitute, canSubstitute }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!playerName) return
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      setData(null)
      try {
        const d = await playerDetailAPI.getByName(playerName)
        if (!cancelled) setData(d)
      } catch (e) {
        if (!cancelled) setError(e.message || 'Could not load player')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [playerName])

  // Close on Escape
  useEffect(() => {
    if (!playerName) return
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [playerName, onClose])

  if (!playerName) return null

  return (
    <>
      <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 90, background: 'rgba(6,8,11,0.6)', backdropFilter: 'blur(5px)' }} />
      <aside
        style={{
          position: 'fixed', top: 0, right: 0, bottom: 0, zIndex: 95, width: '448px', maxWidth: '94vw',
          background: 'var(--ink-850)', borderLeft: '1px solid var(--border-strong)', boxShadow: 'var(--shadow-pop)',
          overflowY: 'auto', animation: 'mdSlideIn .28s var(--ease-out) both',
        }}
      >
        {loading && <PanelMessage text="Loading player…" />}
        {error && <PanelMessage text={error} onClose={onClose} />}
        {data && (
          <ProfileBody
            data={data}
            onClose={onClose}
            squadPlayers={squadPlayers}
            onTransferOut={onTransferOut}
            onSubstitute={onSubstitute}
            canSubstitute={canSubstitute}
          />
        )}
      </aside>
    </>
  )
}

function PanelMessage({ text, onClose }) {
  return (
    <div style={{ padding: '28px 24px' }}>
      {onClose && <CloseBtn onClose={onClose} />}
      <div style={{ color: 'var(--text-300)', fontSize: '14px', marginTop: '40px' }}>{text}</div>
    </div>
  )
}

function CloseBtn({ onClose }) {
  return (
    <button
      onClick={onClose}
      aria-label="Close profile"
      style={{
        position: 'absolute', top: '14px', right: '14px', width: '30px', height: '30px', borderRadius: '999px',
        border: '1px solid var(--border-default)', background: 'rgba(6,8,11,0.5)', color: 'var(--text-300)',
        fontSize: '13px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 0,
      }}
    >
      ✕
    </button>
  )
}

const POS_LABEL = { 1: 'GKP', 2: 'DEF', 3: 'MID', 4: 'FWD', GKP: 'GKP', DEF: 'DEF', MID: 'MID', FWD: 'FWD' }
const posNum = (data) => data.element_type || { GKP: 1, DEF: 2, MID: 3, FWD: 4 }[data.position] || 4

function shirtUrl(teamCode, pos) {
  const p = posNum({ element_type: pos })
  return p === 1
    ? `https://fantasy.premierleague.com/dist/img/shirts/standard/shirt_${teamCode}_1-110.png`
    : `https://fantasy.premierleague.com/dist/img/shirts/standard/shirt_${teamCode}-110.png`
}

function ProfileBody({ data, onClose, squadPlayers = [], onTransferOut, onSubstitute, canSubstitute }) {
  const pos = posNum(data)
  const status = data.status || 'a'
  const chance = data.chance_of_playing

  // Is this player currently in the user's squad? Match by name (the endpoint
  // returns web_name/name; squad players carry the same fields).
  const nameKey = (data.web_name || data.name || '').toLowerCase()
  const squadPlayer = squadPlayers.find(
    (p) => (p.web_name || '').toLowerCase() === nameKey || (p.name || '').toLowerCase() === nameKey
  )
  // Bench players eligible to swap with this squad player (legal formation only)
  const subTargets = squadPlayer
    ? squadPlayers.filter(
        (p) => p.id !== squadPlayer.id && (!canSubstitute || canSubstitute(squadPlayer.id, p.id))
      )
    : []

  const posBg = { 1: 'var(--gold-soft)', 2: 'var(--info-soft)', 3: 'var(--accent-soft)', 4: 'var(--danger-soft)' }[pos]
  const posFg = { 1: 'var(--gold-400)', 2: 'var(--azure-400)', 3: 'var(--pitch-400)', 4: 'var(--flare-400)' }[pos]
  const statusLabel = status === 'a' ? 'Available' : status === 'd' ? 'Doubt' + (chance != null ? ` ${chance}%` : '') : status === 'i' ? 'Injured' : 'Suspended'
  const statusBg = status === 'a' ? 'var(--accent-soft)' : status === 'd' ? 'var(--gold-soft)' : 'var(--danger-soft)'
  const statusFg = status === 'a' ? 'var(--pitch-400)' : status === 'd' ? 'var(--gold-400)' : 'var(--flare-400)'

  const s = data.season_stats || {}
  const adv = data.advanced_stats || {}
  const def = data.defensive_stats || {}
  const prog = data.progressive_stats || {}

  const season = [
    { label: 'Points', value: s.total_points ?? 0 },
    { label: 'Form', value: s.form ?? '0' },
    { label: 'Pts / game', value: s.points_per_game ?? '0' },
    { label: 'Goals', value: s.goals ?? 0 },
    { label: 'Assists', value: s.assists ?? 0 },
    { label: 'Minutes', value: s.minutes ?? 0 },
  ]

  // Last-5 form bars from recent_gameweeks (endpoint returns newest first)
  const recent = [...(data.recent_gameweeks || [])].reverse() // -> oldest..newest (newest right)
  const maxPts = Math.max(6, ...recent.map((g) => g.points || 0))
  const bars = recent.map((g) => {
    const pts = g.points || 0
    const color = pts >= 6 ? 'var(--pitch-500)' : pts >= 3 ? 'var(--azure-500)' : 'var(--ink-650)'
    return { gw: 'GW' + g.gameweek, pts, h: `${Math.max(6, (pts / maxPts) * 100)}%`, color, fg: pts >= 6 ? 'var(--pitch-400)' : 'var(--text-300)' }
  })

  const fixtures = (data.upcoming_fixtures || []).slice(0, 5).map((f) => {
    const d = f.difficulty || 3
    const map = {
      1: { bg: 'rgba(16,185,129,0.22)', border: 'rgba(16,185,129,0.4)', fg: 'var(--pitch-300)' },
      2: { bg: 'var(--accent-soft)', border: 'rgba(16,185,129,0.25)', fg: 'var(--pitch-400)' },
      3: { bg: 'var(--surface-3)', border: 'var(--border-subtle)', fg: 'var(--text-200)' },
      4: { bg: 'var(--gold-soft)', border: 'rgba(245,158,11,0.3)', fg: 'var(--gold-400)' },
      5: { bg: 'var(--danger-soft)', border: 'rgba(239,68,68,0.35)', fg: 'var(--flare-400)' },
    }[d]
    return { gw: f.gameweek, ha: f.is_home ? 'H' : 'A', diff: d, ...map }
  })

  const num = (v, dp = 2) => (typeof v === 'number' ? v.toFixed(dp) : v ?? '—')
  const attack = {
    title: 'Attack · expected goals', accent: 'var(--pitch-500)',
    stats: [
      { label: 'xG / 90', value: num(adv.xG_per_90), hero: pos >= 3 },
      { label: 'xA / 90', value: num(adv.xA_per_90), hero: pos >= 3 },
      { label: 'xG total', value: num(adv.xG, 1) },
      { label: 'npxG / 90', value: num(adv.npxG_per_90) },
      { label: 'Shots', value: adv.shots ?? 0 },
      { label: 'xG over-perf', value: num(adv.xG_overperformance, 1) },
    ],
  }
  const creation = {
    title: 'Creation · progression', accent: 'var(--azure-500)',
    stats: [
      { label: 'SCA / 90', value: num(prog.sca_per_90) },
      { label: 'GCA / 90', value: num(prog.gca_per_90) },
      { label: 'Key passes', value: adv.key_passes ?? 0 },
      { label: 'Prog passes / 90', value: num(prog.progressive_passes_per_90, 1) },
      { label: 'Prog carries / 90', value: num(prog.progressive_carries_per_90, 1) },
      { label: 'xG chain / 90', value: num(adv.xGChain_per_90) },
    ],
  }
  const defence = {
    title: 'Defence · contribution', accent: 'var(--gold-500)',
    stats: [
      { label: 'DC / 90', value: num(def.def_contributions_per_90, 1), hero: pos === 2 },
      { label: 'Tackles', value: def.tackles ?? 0 },
      { label: 'Tackle %', value: (def.tackle_pct ?? 0) + '%' },
      { label: 'Interceptions', value: def.interceptions ?? 0 },
      { label: 'Blocks', value: def.blocks ?? 0 },
      { label: 'Clearances', value: def.clearances ?? 0 },
    ],
  }
  const groups = pos === 2 ? [defence, attack, creation] : pos === 1 ? [defence, creation] : [attack, creation, defence]

  return (
    <>
      {/* Hero */}
      <div style={{ position: 'relative', padding: '24px 24px 20px', background: 'radial-gradient(120% 90% at 50% -20%, rgba(16,185,129,0.14) 0%, rgba(16,185,129,0) 60%), var(--ink-800)', borderBottom: '1px solid var(--border-subtle)' }}>
        <CloseBtn onClose={onClose} />
        <div style={{ display: 'flex', gap: '18px', alignItems: 'center' }}>
          <span
            role="img"
            aria-label={data.team_name}
            style={{ display: 'block', width: '84px', height: '84px', flexShrink: 0, backgroundImage: `url('${shirtUrl(data.team_code, pos)}')`, backgroundSize: 'contain', backgroundRepeat: 'no-repeat', backgroundPosition: 'center', filter: 'drop-shadow(0 10px 18px rgba(0,0,0,0.6))' }}
          />
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '3px' }}>
              <span style={{ padding: '2px 9px', borderRadius: '999px', background: posBg, color: posFg, fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: '10px', letterSpacing: '0.08em' }}>{POS_LABEL[pos]}</span>
              <span style={{ fontSize: '12px', color: 'var(--text-300)' }}>{data.team_name}</span>
            </div>
            <h2 style={{ margin: '0 0 7px', fontFamily: 'var(--font-display)', fontWeight: 900, fontSize: '27px', letterSpacing: '-0.02em', textTransform: 'uppercase', color: 'var(--text-100)', lineHeight: 1.02 }}>{data.web_name || data.name}</h2>
            <div style={{ display: 'flex', alignItems: 'center', gap: '7px', flexWrap: 'wrap' }}>
              <span className="tnum" style={{ padding: '3px 10px', borderRadius: '999px', background: 'var(--accent-soft)', color: 'var(--pitch-400)', fontWeight: 800, fontSize: '12px' }}>£{Number(data.price).toFixed(1)}m</span>
              <span className="tnum" style={{ padding: '3px 10px', borderRadius: '999px', background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border-subtle)', color: 'var(--text-300)', fontSize: '11px', fontWeight: 600 }}>{data.ownership}% owned</span>
              <span style={{ padding: '3px 10px', borderRadius: '999px', background: statusBg, color: statusFg, fontSize: '11px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.03em' }}>{statusLabel}</span>
            </div>
          </div>
        </div>
        {data.news && (
          <div style={{ marginTop: '14px', padding: '9px 13px', borderRadius: '10px', background: 'var(--gold-soft)', border: '1px solid rgba(245,158,11,0.3)', fontSize: '12px', lineHeight: 1.45, color: 'var(--gold-400)' }}>{data.news}</div>
        )}
      </div>

      {/* Squad actions — only for players in your team */}
      {squadPlayer && (onTransferOut || onSubstitute) && (
        <SquadActions
          squadPlayer={squadPlayer}
          subTargets={subTargets}
          onTransferOut={onTransferOut}
          onSubstitute={onSubstitute}
        />
      )}

      <div style={{ padding: '20px 24px 32px', display: 'flex', flexDirection: 'column', gap: '22px' }}>
        {/* Season summary */}
        <div>
          <SectionLabel>Season</SectionLabel>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px' }}>
            {season.map((st) => (
              <div key={st.label} style={{ background: 'var(--surface-2)', border: '1px solid var(--border-subtle)', borderRadius: '12px', padding: '9px 12px' }}>
                <div style={{ fontSize: '10px', letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text-400)' }}>{st.label}</div>
                <div className="tnum" style={{ fontWeight: 800, fontSize: '17px', color: 'var(--text-100)', marginTop: '1px' }}>{st.value}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Last-5 form */}
        {bars.length > 0 && (
          <div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px', marginBottom: '9px' }}>
              <SectionLabel inline>Last {bars.length} gameweeks</SectionLabel>
              <span className="tnum" style={{ fontSize: '11px', color: 'var(--text-500)' }}>newest right</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: '10px', height: '96px', padding: '0 4px' }}>
              {bars.map((b, i) => (
                <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'flex-end', height: '100%', gap: '4px' }}>
                  <span className="tnum" style={{ fontWeight: 800, fontSize: '12px', color: b.fg }}>{b.pts}</span>
                  <div style={{ width: '100%', maxWidth: '34px', height: b.h, minHeight: '3px', borderRadius: '6px 6px 3px 3px', background: b.color }} />
                  <span className="tnum" style={{ fontSize: '9px', letterSpacing: '0.06em', color: 'var(--text-500)' }}>{b.gw}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Fixtures */}
        {fixtures.length > 0 && (
          <div>
            <SectionLabel>Next {fixtures.length} fixtures</SectionLabel>
            <div style={{ display: 'flex', gap: '7px' }}>
              {fixtures.map((f, i) => (
                <div key={i} style={{ flex: 1, textAlign: 'center', padding: '8px 2px 7px', borderRadius: '10px', background: f.bg, border: `1px solid ${f.border}` }}>
                  <div style={{ fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: '12px', color: f.fg }}>{f.diff}</div>
                  <div className="tnum" style={{ fontSize: '9px', letterSpacing: '0.05em', color: 'var(--text-400)', marginTop: '2px' }}>GW{f.gw} {f.ha}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Position-aware stat groups */}
        {groups.map((g) => (
          <div key={g.title}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '9px' }}>
              <span style={{ width: '3px', height: '12px', borderRadius: '2px', background: g.accent }} />
              <SectionLabel inline>{g.title}</SectionLabel>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 14px' }}>
              {g.stats.map((st) => (
                <div key={st.label} style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: '8px', padding: '6px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                  <span style={{ fontSize: '12px', color: 'var(--text-300)' }}>{st.label}</span>
                  <span className="tnum" style={{ fontWeight: 800, fontSize: st.hero ? '15px' : '13px', color: st.hero ? 'var(--pitch-400)' : 'var(--text-100)' }}>{st.value}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </>
  )
}

function SectionLabel({ children, inline }) {
  return (
    <div style={{ fontSize: '11px', letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--text-400)', fontWeight: 700, marginBottom: inline ? 0 : '9px' }}>
      {children}
    </div>
  )
}

function SquadActions({ squadPlayer, subTargets, onTransferOut, onSubstitute }) {
  const isBench = !!squadPlayer.is_bench
  // Sub direction: a benched player subs into the XI; a starter subs out to bench.
  const subVerb = isBench ? 'Sub into XI with' : 'Sub out for'

  return (
    <div style={{ padding: '14px 24px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', flexDirection: 'column', gap: '10px', background: 'var(--ink-800)' }}>
      <div style={{ display: 'flex', gap: '8px' }}>
        {onTransferOut && (
          <button
            onClick={() => onTransferOut(squadPlayer)}
            style={{
              flex: 1, padding: '10px 14px', borderRadius: '10px', border: '1px solid rgba(239,68,68,0.35)',
              background: 'var(--danger-soft)', color: 'var(--flare-400)', fontWeight: 700, fontSize: '13px',
              cursor: 'pointer', fontFamily: 'var(--font-display)', textTransform: 'uppercase', letterSpacing: '0.03em',
            }}
          >
            Transfer out
          </button>
        )}
      </div>

      {onSubstitute && subTargets.length > 0 && (
        <div>
          <SectionLabel>{subVerb}</SectionLabel>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            {subTargets.map((t) => (
              <button
                key={t.id}
                onClick={() => onSubstitute(squadPlayer.id, t.id)}
                style={{
                  padding: '6px 11px', borderRadius: '999px', border: '1px solid var(--border-default)',
                  background: 'var(--surface-2)', color: 'var(--text-200)', fontSize: '12px', fontWeight: 600, cursor: 'pointer',
                }}
              >
                {t.web_name || t.name}{t.is_bench ? '' : ' (XI)'}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default PlayerProfile
