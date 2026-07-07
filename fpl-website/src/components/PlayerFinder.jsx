import { useEffect, useMemo, useState } from 'react'
import { playersAPI } from '../api/fplApi'

const POSITIONS = ['ALL', 'GK', 'DEF', 'MID', 'FWD']
const SORTS = [
  { key: 'total_points', label: 'Points' },
  { key: 'form', label: 'Form' },
  { key: 'price', label: 'Price' },
  { key: 'xG_per_90', label: 'xG/90' },
  { key: 'xA_per_90', label: 'xA/90' },
  { key: 'ownership', label: 'Ownership' },
]

/**
 * PlayerFinder — left column search / filter / sortable player list.
 * Clicking "+" fires onAdd(player) so parent can stage a transfer.
 */
function PlayerFinder({ squadPlayerIds = [], onAdd, selectedOutId = null }) {
  const [position, setPosition] = useState('ALL')
  const [team, setTeam] = useState('ALL')
  const [query, setQuery] = useState('')
  const [maxPrice, setMaxPrice] = useState(15)
  const [sort, setSort] = useState('total_points')
  const [players, setPlayers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    playersAPI.getAll({ limit: 1000 })
      .then(data => {
        if (cancelled) return
        const list = Array.isArray(data) ? data : (data?.players || [])
        setPlayers(list)
      })
      .catch(err => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false))
    return () => { cancelled = true }
  }, [])

  // Build unique team list for dropdown
  const teams = useMemo(() => {
    const map = new Map()
    players.forEach(p => {
      if (p.team && !map.has(p.team)) {
        map.set(p.team, p.team_name || p.team)
      }
    })
    return Array.from(map.entries())
      .map(([code, name]) => ({ code, name }))
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [players])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return players
      .filter(p => {
        if (position !== 'ALL') {
          const pos = normalizePos(p.position)
          if (pos !== position) return false
        }
        if (team !== 'ALL' && p.team !== team) return false
        if (p.price > maxPrice) return false
        if (q) {
          const name = (p.web_name || p.name || '').toLowerCase()
          if (!name.includes(q)) return false
        }
        return true
      })
      .sort((a, b) => numeric(b[sort]) - numeric(a[sort]))
  }, [players, position, team, query, maxPrice, sort])

  const grouped = useMemo(() => {
    if (position !== 'ALL') return [[position, filtered]]
    const groups = { GK: [], DEF: [], MID: [], FWD: [] }
    filtered.forEach(p => {
      const pos = normalizePos(p.position)
      if (groups[pos]) groups[pos].push(p)
    })
    return Object.entries(groups).filter(([, arr]) => arr.length > 0)
  }, [filtered, position])

  return (
    <aside className="card flex flex-col" style={{ maxHeight: 'calc(100vh - 180px)' }}>
      <div className="px-4 py-3 border-b" style={{ borderColor: 'var(--border-subtle)' }}>
        <h2 className="text-[13px] uppercase tracking-wider text-muted font-semibold mb-3">Find Player</h2>

        {/* Search */}
        <div className="relative mb-3">
          <input
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search by name…"
            className="w-full px-3 py-2 pl-9 rounded-lg text-sm text-primary placeholder:text-muted focus:outline-none transition-shadow"
            style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border-subtle)' }}
            onFocus={e => e.currentTarget.style.boxShadow = '0 0 0 2px var(--accent-primary-ring)'}
            onBlur={e => e.currentTarget.style.boxShadow = 'none'}
          />
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-5.2-5.2M17 10a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
        </div>

        {/* Team dropdown */}
        <div className="mb-3">
          <label className="text-[11px] text-muted block mb-1">Team</label>
          <select
            value={team}
            onChange={e => setTeam(e.target.value)}
            className="w-full px-3 py-2 rounded-lg text-sm text-primary focus:outline-none transition-shadow appearance-none cursor-pointer"
            style={{
              background: 'var(--bg-elevated)',
              border: '1px solid var(--border-subtle)',
              backgroundImage: `url("data:image/svg+xml;charset=UTF-8,%3csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2394a3b8' stroke-width='2'%3e%3cpath d='M6 9l6 6 6-6'/%3e%3c/svg%3e")`,
              backgroundRepeat: 'no-repeat',
              backgroundPosition: 'right 10px center',
              paddingRight: '30px',
            }}
          >
            <option value="ALL">All teams</option>
            {teams.map(t => (
              <option key={t.code} value={t.code}>{t.name}</option>
            ))}
          </select>
        </div>

        {/* Position pills */}
        <div className="flex gap-1 mb-3">
          {POSITIONS.map(pos => (
            <button
              key={pos}
              onClick={() => setPosition(pos)}
              className="flex-1 py-1.5 rounded-md text-[11px] font-semibold uppercase tracking-wide transition-colors"
              style={position === pos
                ? { background: 'var(--accent-primary-soft)', color: 'var(--accent-primary)' }
                : { background: 'var(--bg-elevated)', color: 'var(--text-secondary)' }
              }
            >
              {pos}
            </button>
          ))}
        </div>

        {/* Price slider */}
        <div className="mb-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[11px] text-muted">Max price</span>
            <span className="num text-[11px] text-primary font-medium">£{maxPrice.toFixed(1)}m</span>
          </div>
          <input
            type="range"
            min="4"
            max="15"
            step="0.1"
            value={maxPrice}
            onChange={e => setMaxPrice(parseFloat(e.target.value))}
            className="w-full accent-emerald-500"
          />
        </div>

        {/* Sort */}
        <div>
          <div className="text-[11px] text-muted mb-1">Sort by</div>
          <div className="flex gap-1 flex-wrap">
            {SORTS.map(s => (
              <button
                key={s.key}
                onClick={() => setSort(s.key)}
                className="px-2 py-1 rounded text-[11px] font-medium transition-colors"
                style={sort === s.key
                  ? { background: 'var(--accent-primary-soft)', color: 'var(--accent-primary)' }
                  : { color: 'var(--text-secondary)' }
                }
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Results count */}
      <div className="px-4 py-2 text-[11px] text-muted border-b" style={{ borderColor: 'var(--border-subtle)' }}>
        {loading ? 'Loading…' : error ? <span className="text-red-400">{error}</span> : `${filtered.length} player${filtered.length === 1 ? '' : 's'}`}
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {grouped.map(([pos, list]) => (
          <div key={pos}>
            <div className="sticky top-0 z-10 px-4 py-1.5 text-[10px] uppercase tracking-wider font-semibold text-muted" style={{ background: 'var(--bg-card)', borderBottom: '1px solid var(--border-subtle)' }}>
              {POSITION_LABELS[pos] || pos}
            </div>
            {list.map(p => (
              <PlayerRow
                key={p.id}
                player={p}
                alreadyInSquad={squadPlayerIds.includes(p.id)}
                onAdd={() => onAdd?.(p)}
                selectedOutId={selectedOutId}
                sortKey={sort}
              />
            ))}
          </div>
        ))}
      </div>

      {selectedOutId && (
        <div className="px-4 py-2 text-[11px] border-t" style={{ borderColor: 'var(--border-subtle)', background: 'var(--accent-primary-soft)', color: 'var(--accent-primary)' }}>
          Pick a replacement to complete the swap →
        </div>
      )}
    </aside>
  )
}

const POSITION_LABELS = {
  GK: 'Goalkeepers',
  DEF: 'Defenders',
  MID: 'Midfielders',
  FWD: 'Forwards',
}

function PlayerRow({ player, alreadyInSquad, onAdd, selectedOutId, sortKey }) {
  const primaryStat = formatStat(player[sortKey], sortKey)

  return (
    <div
      className="flex items-center gap-3 px-4 py-2 border-b transition-colors hover:bg-white/[0.03]"
      style={{ borderColor: 'var(--border-subtle)' }}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-[13px] font-medium text-primary truncate">{player.web_name || player.name}</span>
          {player.status && player.status !== 'a' && (
            <StatusDot status={player.status} />
          )}
        </div>
        <div className="flex items-center gap-2 text-[11px] text-muted">
          <span>{player.team_name || player.team}</span>
          <span>·</span>
          <span>{player.position}</span>
        </div>
      </div>
      <div className="text-right shrink-0">
        <div className="num text-[12px] font-semibold text-primary">£{Number(player.price || 0).toFixed(1)}m</div>
        <div className="num text-[10px] text-muted">{primaryStat}</div>
      </div>
      <button
        onClick={onAdd}
        disabled={alreadyInSquad}
        className="w-7 h-7 rounded-full flex items-center justify-center text-sm font-bold transition-all shrink-0 disabled:opacity-30 disabled:cursor-not-allowed"
        style={alreadyInSquad
          ? { background: 'var(--bg-elevated)', color: 'var(--text-muted)' }
          : selectedOutId
            ? { background: 'var(--accent-primary)', color: 'white' }
            : { background: 'var(--bg-elevated)', color: 'var(--accent-primary)' }
        }
        title={alreadyInSquad ? 'Already in squad' : selectedOutId ? 'Swap into squad' : 'Add to squad'}
      >
        {alreadyInSquad ? '✓' : '+'}
      </button>
    </div>
  )
}

function StatusDot({ status }) {
  const color =
    status === 'i' || status === 'u' ? 'var(--accent-danger)' :
    status === 'd' ? 'var(--accent-warn)' :
    status === 's' ? 'var(--accent-warn)' :
    'var(--text-muted)'
  return <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ background: color }} />
}

function normalizePos(pos) {
  if (pos === 'GKP') return 'GK'
  return pos
}

function numeric(v) {
  const n = typeof v === 'string' ? parseFloat(v) : v
  return Number.isFinite(n) ? n : 0
}

function formatStat(v, key) {
  const n = numeric(v)
  if (key === 'total_points') return `${Math.round(n)} pts`
  if (key === 'price') return ''
  if (key === 'ownership') return `${n.toFixed(1)}%`
  if (key === 'form') return `${n.toFixed(1)} form`
  return n.toFixed(2)
}

export default PlayerFinder
