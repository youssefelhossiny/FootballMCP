import { useState, useEffect } from 'react'
import TeamFormation from '../components/TeamFormation'
import ChatInterface from '../components/ChatInterface'
import PlayerFinder from '../components/PlayerFinder'
import TopBar from '../components/TopBar'

const POSITION_TO_NUMBER = { GKP: 1, GK: 1, DEF: 2, MID: 3, FWD: 4 }
const NUMBER_TO_POSITION = { 1: 'GKP', 2: 'DEF', 3: 'MID', 4: 'FWD' }

function UserTeamPage() {
  const [teamId, setTeamId] = useState('')
  const [team, setTeam] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [savedTeamId, setSavedTeamId] = useState(null)

  // Transfer state
  const [viewMode, setViewMode] = useState('current')
  const [suggestedTransfers, setSuggestedTransfers] = useState([])
  const [theoreticalTeam, setTheoreticalTeam] = useState(null)
  const [transferNetCost, setTransferNetCost] = useState(0)
  const [freeTransfersOverride, setFreeTransfersOverride] = useState(null)

  // Manual swap state
  const [selectedOutPlayer, setSelectedOutPlayer] = useState(null)

  // Chips
  const [availableChips, setAvailableChips] = useState({
    benchboost: true, triplecaptain: true, wildcard: true, freehit: true,
  })
  const [activeChip, setActiveChip] = useState(null)

  // Chat visibility
  const [chatOpen, setChatOpen] = useState(true)

  useEffect(() => {
    const saved = localStorage.getItem('fpl_team_id')
    if (saved) {
      setTeamId(saved)
      setSavedTeamId(saved)
      fetchTeam(saved)
    }
  }, [])

  const fetchTeam = async (id) => {
    if (!id) return
    let cleanId = id.trim()
    const urlMatch = cleanId.match(/entry\/(\d+)/)
    if (urlMatch) cleanId = urlMatch[1]
    cleanId = cleanId.replace(/\D/g, '')
    if (!cleanId) { setError('Please enter a valid Team ID'); return }

    try {
      setLoading(true)
      setError(null)
      const response = await fetch(`/api/team/${cleanId}`)
      if (!response.ok) {
        if (response.status === 404) throw new Error('Team not found. Check your Team ID.')
        throw new Error('Failed to fetch team')
      }
      const data = await response.json()
      setTeam(data)
      localStorage.setItem('fpl_team_id', cleanId)
      setSavedTeamId(cleanId)
      setTeamId(cleanId)
      resetTransferState()
    } catch (err) {
      setError(err.message)
      setTeam(null)
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = (e) => { e.preventDefault(); fetchTeam(teamId) }

  const resetTransferState = () => {
    setSuggestedTransfers([])
    setTheoreticalTeam(null)
    setTransferNetCost(0)
    setSelectedOutPlayer(null)
    setViewMode('current')
  }

  // Manual swap flow: user clicks a squad player, then clicks a finder candidate
  const handleSelectOut = (player) => {
    // Toggle off if clicking the same player
    if (selectedOutPlayer?.id === player.id) {
      setSelectedOutPlayer(null)
      return
    }
    setSelectedOutPlayer(player)
  }

  const handleAddFromFinder = (candidate) => {
    if (!team) return
    if (!selectedOutPlayer) {
      // no outgoing player selected yet — ignore (finder's + button requires a selected out first)
      return
    }
    // Enforce same-position swaps
    const outPosNum = selectedOutPlayer.element_type || selectedOutPlayer.position
    const inPosStr = candidate.position === 'GK' ? 'GKP' : candidate.position
    const inPosNum = POSITION_TO_NUMBER[inPosStr]
    if (outPosNum !== inPosNum) {
      alert(`Cannot swap ${NUMBER_TO_POSITION[outPosNum]} for ${inPosStr}. Same-position swap required.`)
      return
    }

    const newTransfer = {
      out: { name: selectedOutPlayer.web_name || selectedOutPlayer.name },
      in: {
        ...candidate,
        name: candidate.web_name || candidate.name,
        web_name: candidate.web_name,
        now_cost: Math.round((candidate.price || 0) * 10),
        element_type: inPosNum,
        position: inPosNum,
        is_transfer_in: true,
      },
    }

    const nextTransfers = [...suggestedTransfers, newTransfer]
    applyTransfersLocal(nextTransfers)
    setSelectedOutPlayer(null)
  }

  // Apply transfers locally (no re-fetching player data — already have it)
  const applyTransfersLocal = (transfers) => {
    if (!team) return
    setSuggestedTransfers(transfers)

    const playerMatches = (player, searchName) => {
      if (!searchName) return false
      const s = searchName.toLowerCase().trim()
      const fn = (player.name || '').toLowerCase()
      const wn = (player.web_name || '').toLowerCase()
      if (wn === s || fn === s) return true
      if (s.length >= 3 && (wn.includes(s) || fn.includes(s))) return true
      return false
    }

    const newPlayers = team.players.map(p => ({ ...p }))
    let netCost = 0

    transfers.forEach(transfer => {
      const outIdx = newPlayers.findIndex(p => playerMatches(p, transfer.out?.name))
      if (outIdx !== -1 && transfer.in) {
        const outPlayer = newPlayers[outIdx]
        const outPrice = outPlayer.now_cost || (outPlayer.price ? outPlayer.price * 10 : 0)
        const inPrice = transfer.in.now_cost || (transfer.in.price ? transfer.in.price * 10 : 0)
        netCost += (inPrice - outPrice)

        newPlayers[outIdx] = {
          ...transfer.in,
          id: transfer.in.id || `transfer-in-${Date.now()}-${outIdx}`,
          is_bench: outPlayer.is_bench,
          bench_order: outPlayer.bench_order,
          is_transfer_in: true,
        }
      }
    })

    setTransferNetCost(netCost)

    const theoreticalPlayers = team.players.map(p => ({
      ...p,
      is_transfer_out: transfers.some(t => playerMatches(p, t.out?.name)),
    }))

    setTheoreticalTeam({
      ...team,
      players: newPlayers,
      originalPlayers: theoreticalPlayers,
    })

    setViewMode('theoretical')
  }

  // For AI-suggested transfers: fetch full player data then apply
  const applyTransfers = async (transfers) => {
    if (!team || !transfers || transfers.length === 0) return
    const enrichedTransfers = await Promise.all(
      transfers.map(async (transfer) => {
        const inName = transfer.in?.name || transfer.in
        try {
          const response = await fetch(`/api/player/${encodeURIComponent(inName)}`)
          if (response.ok) {
            const playerData = await response.json()
            return {
              ...transfer,
              in: {
                ...playerData,
                name: playerData.web_name || playerData.name || inName,
                web_name: playerData.web_name || inName,
                is_transfer_in: true,
              },
            }
          }
        } catch (err) { console.error('Failed to fetch player:', err) }
        return { ...transfer, in: { name: inName, web_name: inName, is_transfer_in: true } }
      })
    )
    applyTransfersLocal(enrichedTransfers)
  }

  const budgetInfo = calculateBudget(team, suggestedTransfers, transferNetCost, freeTransfersOverride, activeChip)

  const squadPlayerIds = team?.players?.map(p => p.id).filter(Boolean) || []

  return (
    <div className="space-y-4">
      {/* Team ID bar (compact once loaded) */}
      <TeamIdInput
        team={team}
        teamId={teamId}
        setTeamId={setTeamId}
        onSubmit={handleSubmit}
        loading={loading}
        error={error}
      />

      {team && (
        <>
          {/* Top stats strip */}
          <TopBar
            playersSelected={budgetInfo.playersSelected}
            bank={budgetInfo.bank}
            bankAfterTransfers={suggestedTransfers.length > 0 ? budgetInfo.bankAfterTransfers : null}
            teamValue={budgetInfo.teamValue}
            freeTransfers={budgetInfo.freeTransfers}
            onFreeTransfersChange={setFreeTransfersOverride}
            pointsCost={budgetInfo.pointsCost}
            pendingTransfers={suggestedTransfers.length}
            activeChip={activeChip}
            onResetChanges={resetTransferState}
            viewMode={viewMode}
            onViewModeChange={setViewMode}
            hasTheoretical={!!theoreticalTeam}
          />

          {/* Chips row */}
          <ChipsRow
            availableChips={availableChips}
            activeChip={activeChip}
            onToggleAvailable={(chip) => setAvailableChips(prev => ({ ...prev, [chip]: !prev[chip] }))}
            onActivate={setActiveChip}
            onDeactivate={() => setActiveChip(null)}
          />

          {/* 3-column cockpit */}
          <div className={`grid gap-4 ${chatOpen ? 'grid-cols-[320px_minmax(0,1fr)_360px]' : 'grid-cols-[320px_minmax(0,1fr)]'}`}>
            {/* Left: Player Finder */}
            <PlayerFinder
              squadPlayerIds={squadPlayerIds}
              onAdd={handleAddFromFinder}
              selectedOutId={selectedOutPlayer?.id}
            />

            {/* Center: Pitch + Transfer Summary */}
            <div className="space-y-4 min-w-0">
              <TeamFormation
                players={viewMode === 'current' ? team.players : (theoreticalTeam?.players || team.players)}
                showTransferIndicators={viewMode === 'theoretical'}
                selectedOutId={selectedOutPlayer?.id}
                onSelectOut={handleSelectOut}
              />

              {selectedOutPlayer && (
                <div className="card p-3 flex items-center gap-3" style={{ background: 'var(--accent-primary-soft)', borderColor: 'var(--accent-primary-ring)' }}>
                  <div className="flex-1 text-sm">
                    <span className="text-muted">Transferring out: </span>
                    <span className="text-accent font-semibold">{selectedOutPlayer.web_name || selectedOutPlayer.name}</span>
                    <span className="text-muted"> — pick a replacement from the list ←</span>
                  </div>
                  <button
                    onClick={() => setSelectedOutPlayer(null)}
                    className="text-xs text-muted hover:text-primary transition-colors"
                  >Cancel</button>
                </div>
              )}

              {suggestedTransfers.length > 0 && (
                <TransferSummary transfers={suggestedTransfers} team={team} />
              )}

              {team.injury_risks?.length > 0 && (
                <InjuryAlerts risks={team.injury_risks} />
              )}
            </div>

            {/* Right: Chat */}
            {chatOpen && (
              <div className="min-w-0">
                <div className="card flex items-center justify-between px-4 py-2 mb-2">
                  <h2 className="text-[13px] uppercase tracking-wider text-muted font-semibold">AI Assistant</h2>
                  <button
                    onClick={() => setChatOpen(false)}
                    className="text-xs text-muted hover:text-primary transition-colors"
                    title="Collapse chat"
                  >Hide</button>
                </div>
                <ChatInterface
                  teamId={savedTeamId}
                  team={theoreticalTeam || team}
                  onTransferSuggestion={applyTransfers}
                  freeTransfers={budgetInfo.freeTransfers}
                  availableChips={availableChips}
                  activeChip={activeChip}
                  suggestedTransfers={suggestedTransfers}
                />
              </div>
            )}
          </div>

          {!chatOpen && (
            <button
              onClick={() => setChatOpen(true)}
              className="fixed bottom-6 right-6 z-30 rounded-full px-4 py-3 text-sm font-semibold flex items-center gap-2 transition-all lift"
              style={{ background: 'var(--accent-primary)', color: 'white', boxShadow: '0 8px 24px rgba(16,185,129,0.4)' }}
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
              Ask AI
            </button>
          )}
        </>
      )}

      {!team && !loading && !error && (
        <EmptyState />
      )}
    </div>
  )
}

function calculateBudget(team, suggestedTransfers, transferNetCost, freeTransfersOverride, activeChip) {
  if (!team) return { playersSelected: 0, bank: 0, bankAfterTransfers: 0, teamValue: 0, freeTransfers: 1, pointsCost: 0 }
  const teamValue = team.team_value || 0
  const bank = team.bank || 0
  const freeTransfers = freeTransfersOverride !== null ? freeTransfersOverride : (team.free_transfers || 1)
  let pointsCost = 0
  if (suggestedTransfers.length > 0 && activeChip !== 'wildcard' && activeChip !== 'freehit') {
    pointsCost = Math.max(0, suggestedTransfers.length - freeTransfers) * 4
  }
  const bankAfterTransfers = (bank - transferNetCost) / 10
  return {
    playersSelected: team.players?.length || 0,
    bank: bank / 10,
    bankAfterTransfers,
    teamValue: teamValue / 10,
    freeTransfers,
    pointsCost,
  }
}

function TeamIdInput({ team, teamId, setTeamId, onSubmit, loading, error }) {
  if (team) {
    return (
      <div className="card px-5 py-3 flex items-center gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted">Manager</div>
              <div className="text-sm font-semibold text-primary truncate">{team.manager_name}</div>
            </div>
            <div className="w-px h-7" style={{ background: 'var(--border-default)' }} />
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted">Team</div>
              <div className="text-sm font-semibold text-primary truncate">{team.team_name}</div>
            </div>
            <div className="w-px h-7" style={{ background: 'var(--border-default)' }} />
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted">Total Points</div>
              <div className="num text-sm font-semibold text-primary">{team.total_points?.toLocaleString()}</div>
            </div>
            <div className="w-px h-7" style={{ background: 'var(--border-default)' }} />
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted">Overall Rank</div>
              <div className="num text-sm font-semibold text-primary">{formatRank(team.overall_rank)}</div>
            </div>
          </div>
        </div>
        <button
          onClick={() => { setTeamId(''); localStorage.removeItem('fpl_team_id'); window.location.reload() }}
          className="text-xs text-muted hover:text-primary transition-colors shrink-0"
        >Switch team</button>
      </div>
    )
  }

  return (
    <div className="card p-6">
      <h1 className="text-xl font-bold text-primary mb-1">My FPL Team</h1>
      <p className="text-secondary text-sm mb-4">
        Load your team to manage transfers, chat with the AI assistant, and benchmark against the bot.
      </p>
      <form onSubmit={onSubmit} className="flex gap-3">
        <div className="flex-1">
          <input
            type="text"
            value={teamId}
            onChange={(e) => setTeamId(e.target.value)}
            placeholder="Enter your team ID (e.g., 6408264)"
            className="w-full px-4 py-2.5 rounded-lg text-sm text-primary placeholder:text-muted focus:outline-none transition-shadow"
            style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border-default)' }}
            onFocus={e => e.currentTarget.style.boxShadow = '0 0 0 2px var(--accent-primary-ring)'}
            onBlur={e => e.currentTarget.style.boxShadow = 'none'}
          />
          <p className="text-muted text-xs mt-1.5">
            Find your Team ID at fantasy.premierleague.com/entry/<strong>TEAM_ID</strong>/event/1
            · Don't have a team? Try the demo:{' '}
            <button
              type="button"
              onClick={() => setTeamId('6408264')}
              className="text-accent font-medium hover:underline"
            >
              6408264
            </button>
          </p>
        </div>
        <button
          type="submit"
          disabled={loading || !teamId}
          className="px-5 rounded-lg text-sm font-semibold transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          style={{ background: 'var(--accent-primary)', color: 'white' }}
        >
          {loading ? 'Loading…' : 'Load Team'}
        </button>
      </form>
      {error && (
        <div className="mt-4 p-3 rounded-lg text-sm" style={{ background: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.3)', color: '#fca5a5' }}>
          {error}
        </div>
      )}
    </div>
  )
}

function ChipsRow({ availableChips, activeChip, onToggleAvailable, onActivate, onDeactivate }) {
  const chips = [
    { key: 'wildcard', label: 'Wildcard', color: '#ef4444', gradient: 'linear-gradient(135deg, #f87171, #dc2626)' },
    { key: 'freehit', label: 'Free Hit', color: '#3b82f6', gradient: 'linear-gradient(135deg, #60a5fa, #2563eb)' },
    { key: 'benchboost', label: 'Bench Boost', color: '#10b981', gradient: 'linear-gradient(135deg, #34d399, #059669)' },
    { key: 'triplecaptain', label: 'Triple Captain', color: '#a855f7', gradient: 'linear-gradient(135deg, #c084fc, #9333ea)' },
  ]
  return (
    <div className="card px-4 py-2.5 flex items-center gap-2">
      <span className="text-[11px] uppercase tracking-wider text-muted font-semibold mr-2">Chips</span>
      {chips.map(c => {
        const available = availableChips[c.key]
        const active = activeChip === c.key
        return (
          <div key={c.key} className="flex items-center gap-1">
            <button
              onClick={() => onToggleAvailable(c.key)}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-semibold transition-all"
              style={{
                background: available ? 'var(--bg-elevated)' : 'transparent',
                color: available ? 'var(--text-primary)' : 'var(--text-muted)',
                opacity: available ? 1 : 0.4,
                border: active ? `1px solid ${c.color}` : '1px solid transparent',
              }}
              title={available ? 'Mark as used' : 'Mark as available'}
            >
              <span className="w-2 h-2 rounded-full" style={{ background: available ? c.gradient : 'var(--text-muted)' }} />
              {c.label}
            </button>
            {available && (
              active ? (
                <button onClick={onDeactivate} className="text-[10px] px-1.5 py-0.5 rounded text-white" style={{ background: c.color }}>ON</button>
              ) : (
                <button onClick={() => onActivate(c.key)} className="text-[10px] px-1.5 py-0.5 rounded text-muted hover:text-primary hover:bg-white/5 transition-colors">Use</button>
              )
            )}
          </div>
        )
      })}
    </div>
  )
}

function TransferSummary({ transfers, team }) {
  return (
    <div className="card px-4 py-3">
      <div className="text-[11px] uppercase tracking-wider text-muted font-semibold mb-2">
        Pending Transfers · {transfers.length}
      </div>
      <div className="flex flex-wrap gap-2">
        {transfers.map((t, i) => {
          const outPlayer = team.players.find(p =>
            (p.web_name || '').toLowerCase().includes((t.out?.name || '').toLowerCase()) ||
            (p.name || '').toLowerCase().includes((t.out?.name || '').toLowerCase())
          )
          const outName = outPlayer?.web_name || t.out?.name || 'Unknown'
          const inName = t.in?.web_name || t.in?.name || 'Unknown'
          return (
            <div key={i} className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm" style={{ background: 'var(--bg-elevated)' }}>
              <span style={{ color: 'var(--accent-danger)' }}>{outName}</span>
              <span className="text-muted">→</span>
              <span style={{ color: 'var(--accent-primary)' }}>{inName}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function InjuryAlerts({ risks }) {
  return (
    <div className="card px-4 py-3" style={{ borderColor: 'rgba(245, 158, 11, 0.3)', background: 'rgba(245, 158, 11, 0.06)' }}>
      <div className="text-[11px] uppercase tracking-wider font-semibold mb-2" style={{ color: 'var(--accent-warn)' }}>
        Injury Alerts
      </div>
      <div className="space-y-1.5">
        {risks.map((p, i) => (
          <div key={i} className="flex items-center justify-between text-sm">
            <span className="text-primary">{p.name}</span>
            <span className="num text-xs" style={{ color: p.chance < 50 ? 'var(--accent-danger)' : 'var(--accent-warn)' }}>
              {p.chance}% chance
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="card p-12 text-center">
      <svg className="w-12 h-12 mx-auto mb-4 text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-5.2-5.2M17 10a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
      <h2 className="text-lg font-semibold text-primary mb-1">Load your team</h2>
      <p className="text-secondary text-sm max-w-md mx-auto">
        Enter your FPL Team ID above to see your squad, explore players, and get AI-powered transfer suggestions.
      </p>
    </div>
  )
}

function formatRank(rank) {
  if (!rank) return '—'
  if (rank >= 1000000) return `${(rank / 1000000).toFixed(1)}M`
  if (rank >= 1000) return `${(rank / 1000).toFixed(0)}K`
  return rank.toLocaleString()
}

export default UserTeamPage
