import { useState, useEffect } from 'react'
import TeamFormation from '../components/TeamFormation'
import ChatInterface from '../components/ChatInterface'
import SquadTable from '../components/SquadTable'

function UserTeamPage() {
  const [teamId, setTeamId] = useState('')
  const [team, setTeam] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [savedTeamId, setSavedTeamId] = useState(null)

  // Transfer view state
  const [viewMode, setViewMode] = useState('current') // 'current' or 'theoretical'
  const [suggestedTransfers, setSuggestedTransfers] = useState([]) // { out: player, in: player }
  const [theoreticalTeam, setTheoreticalTeam] = useState(null)
  const [transferNetCost, setTransferNetCost] = useState(0) // Net cost of transfers in tenths
  const [freeTransfersOverride, setFreeTransfersOverride] = useState(null) // User override for free transfers

  // Chips state - which are available and which is being used
  const [availableChips, setAvailableChips] = useState({
    benchboost: true,
    triplecaptain: true,
    wildcard: true,
    freehit: true
  })
  const [activeChip, setActiveChip] = useState(null) // The chip being used THIS week

  // Load saved team ID from localStorage on mount
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

    // Extract team ID from URL if full URL is pasted
    let cleanId = id.trim()
    const urlMatch = cleanId.match(/entry\/(\d+)/)
    if (urlMatch) {
      cleanId = urlMatch[1]
    }
    // Remove any non-numeric characters
    cleanId = cleanId.replace(/\D/g, '')

    if (!cleanId) {
      setError('Please enter a valid Team ID')
      return
    }

    try {
      setLoading(true)
      setError(null)
      const response = await fetch(`/api/team/${cleanId}`)
      if (!response.ok) {
        if (response.status === 404) {
          throw new Error('Team not found. Check your Team ID.')
        }
        throw new Error('Failed to fetch team')
      }
      const data = await response.json()
      setTeam(data)
      localStorage.setItem('fpl_team_id', cleanId)
      setSavedTeamId(cleanId)
      setTeamId(cleanId)
    } catch (err) {
      setError(err.message)
      setTeam(null)
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    fetchTeam(teamId)
  }

  // Apply suggested transfers to create theoretical team
  const applyTransfers = async (transfers) => {
    if (!team || !transfers || transfers.length === 0) return

    setSuggestedTransfers(transfers)

    // Fetch full player data for incoming transfers
    const enrichedTransfers = await Promise.all(
      transfers.map(async (transfer) => {
        const inPlayerName = transfer.in?.name || transfer.in
        try {
          // Fetch player data from API
          const response = await fetch(`http://localhost:8000/api/player/${encodeURIComponent(inPlayerName)}`)
          if (response.ok) {
            const playerData = await response.json()
            return {
              ...transfer,
              in: {
                ...playerData,
                name: playerData.web_name || playerData.name || inPlayerName,
                web_name: playerData.web_name || inPlayerName,
                is_transfer_in: true
              }
            }
          }
        } catch (err) {
          console.error('Failed to fetch player data:', err)
        }
        // Fallback if API fails
        return {
          ...transfer,
          in: { name: inPlayerName, web_name: inPlayerName, is_transfer_in: true }
        }
      })
    )

    // Helper function to match player names (handles partial matches like "Enzo" -> "Enzo Fernández")
    const playerMatches = (player, searchName) => {
      if (!searchName) return false
      const search = searchName.toLowerCase().trim()
      const fullName = (player.name || '').toLowerCase()
      const webName = (player.web_name || '').toLowerCase()

      // Exact matches
      if (webName === search) return true
      if (fullName === search) return true

      // Search term found in player's name (minimum 3 chars to avoid false matches)
      if (search.length >= 3 && webName.includes(search)) return true
      if (search.length >= 3 && fullName.includes(search)) return true

      return false
    }

    // Create a copy of the current team players
    const newPlayers = team.players.map(p => ({ ...p }))

    // Position string to number mapping
    const positionToNumber = { 'GKP': 1, 'DEF': 2, 'MID': 3, 'FWD': 4 }

    // Track transfer costs for budget calculation
    let transferNetCost = 0

    // Apply each transfer
    enrichedTransfers.forEach(transfer => {
      console.log('Looking for player to replace:', transfer.out?.name)
      console.log('Available players:', newPlayers.map(p => ({ name: p.name, web_name: p.web_name, first_name: p.first_name })))

      const outIndex = newPlayers.findIndex(p => playerMatches(p, transfer.out?.name))

      console.log('Transfer:', transfer.out?.name, '->', transfer.in?.web_name, 'outIndex:', outIndex)

      if (outIndex !== -1 && transfer.in) {
        const outPlayer = newPlayers[outIndex]

        // Calculate cost difference (in tenths, e.g., 141 = £14.1m)
        const outPrice = outPlayer.now_cost || outPlayer.price || 0
        const inPrice = transfer.in.now_cost || transfer.in.price || 0
        transferNetCost += (inPrice - outPrice)

        console.log('Replacing', outPlayer.web_name, '(£' + outPrice/10 + 'm) with', transfer.in.web_name, '(£' + inPrice/10 + 'm)')

        // Convert string position to number if needed
        const inPosition = typeof transfer.in.position === 'string'
          ? positionToNumber[transfer.in.position]
          : transfer.in.position
        const inElementType = transfer.in.element_type || inPosition

        // Replace the player in the array, keeping bench info from the outgoing player
        newPlayers[outIndex] = {
          ...transfer.in,
          id: transfer.in.id || `transfer-in-${Date.now()}`, // Ensure unique ID
          is_bench: outPlayer.is_bench,
          bench_order: outPlayer.bench_order,
          position: inElementType || outPlayer.position,
          element_type: inElementType || outPlayer.element_type,
          is_transfer_in: true
        }
      }
    })

    // Store net cost for budget display
    setTransferNetCost(transferNetCost)

    console.log('Final newPlayers array:', newPlayers.map(p => p.web_name))
    console.log('newPlayers count:', newPlayers.length)

    // Mark players being transferred out (this is only used for display purposes on "current" view)
    const theoreticalPlayers = team.players.map(p => {
      const isOut = transfers.some(t => playerMatches(p, t.out?.name))
      return { ...p, is_transfer_out: isOut }
    })

    setTheoreticalTeam({
      ...team,
      players: newPlayers,
      originalPlayers: theoreticalPlayers
    })

    // Automatically switch to theoretical view when transfers are suggested
    setViewMode('theoretical')
  }

  // Calculate budget info
  const calculateBudget = () => {
    if (!team) return { budget: 0, spent: 0, remaining: 0, bankAfterTransfers: 0 }

    const teamValue = team.team_value || 0
    const bank = team.bank || 0

    // Use override if set, otherwise use team's free transfers
    const freeTransfers = freeTransfersOverride !== null ? freeTransfersOverride : (team.free_transfers || 1)

    // Points cost for extra transfers (0 if wildcard or free hit active)
    let pointsCost = 0
    if (suggestedTransfers.length > 0 && activeChip !== 'wildcard' && activeChip !== 'freehit') {
      const extraTransfers = Math.max(0, suggestedTransfers.length - freeTransfers)
      pointsCost = extraTransfers * 4 // 4 points per extra transfer
    }

    // Calculate remaining budget after transfers
    // transferNetCost is in tenths (positive = spending more, negative = saving)
    const bankAfterTransfers = (bank - transferNetCost) / 10

    return {
      budget: (teamValue + bank) / 10,
      bank: bank / 10,
      bankAfterTransfers: bankAfterTransfers,
      freeTransfers: freeTransfers,
      pointsCost: pointsCost,
      playersSelected: team.players?.length || 0
    }
  }

  const budgetInfo = calculateBudget()

  return (
    <div className="space-y-6">
      {/* Header with Team ID Input */}
      <div className="bg-slate-800/50 rounded-lg p-6">
        <h1 className="text-2xl font-bold text-white mb-4">My FPL Team</h1>
        <form onSubmit={handleSubmit} className="flex gap-4">
          <div className="flex-1">
            <label className="block text-slate-400 text-sm mb-1">
              FPL Team ID
            </label>
            <input
              type="text"
              value={teamId}
              onChange={(e) => setTeamId(e.target.value)}
              placeholder="Enter your team ID (e.g., 8097506)"
              className="w-full px-4 py-2 bg-slate-700 border border-slate-600 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-purple-500"
            />
            <p className="text-slate-500 text-xs mt-1">
              Find your Team ID in your FPL URL: fantasy.premierleague.com/entry/<strong>TEAM_ID</strong>/event/1
            </p>
          </div>
          <div className="flex items-end">
            <button
              type="submit"
              disabled={loading || !teamId}
              className="px-6 py-2 bg-purple-600 hover:bg-purple-700 disabled:bg-slate-600 disabled:cursor-not-allowed rounded-lg text-white font-medium transition-colors"
            >
              {loading ? 'Loading...' : 'Load Team'}
            </button>
          </div>
        </form>

        {error && (
          <div className="mt-4 p-3 bg-red-500/20 border border-red-500 rounded-lg text-red-300">
            {error}
          </div>
        )}
      </div>

      {/* Team Display */}
      {team && (
        <>
          {/* Team Stats */}
          <div className="grid grid-cols-5 gap-4">
            <StatCard label="Manager" value={team.manager_name} icon="👤" />
            <StatCard label="Team" value={team.team_name} icon="⚽" />
            <StatCard label="Total Points" value={team.total_points} icon="🏆" />
            <StatCard label="Overall Rank" value={formatRank(team.overall_rank)} icon="📊" />
            <StatCard label="Team Value" value={`£${(team.team_value / 10).toFixed(1)}m`} icon="💰" />
          </div>

          {/* Budget Bar - FPL Style */}
          <div className="bg-slate-800/50 rounded-lg p-4">
            <div className="flex items-center justify-between">
              <div className="flex gap-6 items-center">
                <div className="text-center">
                  <p className="text-slate-400 text-xs mb-1">Players Selected</p>
                  <p className="text-white font-bold text-lg">{budgetInfo.playersSelected}/15</p>
                </div>
                <div className="text-center">
                  <p className="text-slate-400 text-xs mb-1">
                    {viewMode === 'theoretical' && suggestedTransfers.length > 0 ? 'Budget After Transfers' : 'In The Bank'}
                  </p>
                  <p className={`font-bold text-lg ${
                    viewMode === 'theoretical' && budgetInfo.bankAfterTransfers < 0
                      ? 'text-red-400'
                      : 'text-white'
                  }`}>
                    {viewMode === 'theoretical' && suggestedTransfers.length > 0
                      ? `£${budgetInfo.bankAfterTransfers.toFixed(1)}m`
                      : `£${budgetInfo.bank.toFixed(1)}m`
                    }
                  </p>
                </div>

                {/* Free Transfers with arrows */}
                <div className="text-center">
                  <p className="text-slate-400 text-xs mb-1">Free Transfers</p>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => {
                        const current = freeTransfersOverride !== null ? freeTransfersOverride : (team.free_transfers || 1)
                        if (current > 0) setFreeTransfersOverride(current - 1)
                      }}
                      className="text-slate-400 hover:text-white text-lg font-bold px-1"
                    >
                      ‹
                    </button>
                    <span className="text-white font-bold text-lg w-4 text-center">{budgetInfo.freeTransfers}</span>
                    <button
                      onClick={() => {
                        const current = freeTransfersOverride !== null ? freeTransfersOverride : (team.free_transfers || 1)
                        if (current < 5) setFreeTransfersOverride(current + 1)
                      }}
                      className="text-slate-400 hover:text-white text-lg font-bold px-1"
                    >
                      ›
                    </button>
                  </div>
                </div>

                {suggestedTransfers.length > 0 && (
                  <div className="text-center">
                    <p className="text-slate-400 text-xs mb-1">Points Cost</p>
                    <p className={`font-bold text-lg ${budgetInfo.pointsCost > 0 ? 'text-red-400' : 'text-green-400'}`}>
                      {activeChip === 'wildcard' || activeChip === 'freehit' ? 'FREE' : (budgetInfo.pointsCost > 0 ? `-${budgetInfo.pointsCost} pts` : '0 pts')}
                    </p>
                  </div>
                )}

                {/* Divider */}
                <div className="w-px h-12 bg-slate-600 mx-2" />

                {/* Chips - Inline */}
                <div className="flex items-center gap-1">
                  {/* Bench Boost */}
                  <button
                    onClick={() => setAvailableChips(prev => ({ ...prev, benchboost: !prev.benchboost }))}
                    className={`relative p-1 rounded-lg transition-all ${
                      !availableChips.benchboost ? 'opacity-30' :
                      activeChip === 'benchboost' ? 'ring-2 ring-cyan-400' : 'hover:bg-slate-700'
                    }`}
                    title="Bench Boost - Click to toggle availability"
                  >
                    <div className="w-8 h-8 rounded-full bg-gradient-to-br from-green-400 to-green-600 flex items-center justify-center">
                      <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 11l5-5m0 0l5 5m-5-5v12" />
                      </svg>
                    </div>
                    {availableChips.benchboost && activeChip !== 'benchboost' && (
                      <button
                        onClick={(e) => { e.stopPropagation(); setActiveChip('benchboost'); }}
                        className="absolute -bottom-1 left-1/2 -translate-x-1/2 bg-slate-600 text-[8px] px-1 rounded text-white hover:bg-cyan-500"
                      >
                        Use
                      </button>
                    )}
                    {activeChip === 'benchboost' && (
                      <button
                        onClick={(e) => { e.stopPropagation(); setActiveChip(null); }}
                        className="absolute -bottom-1 left-1/2 -translate-x-1/2 bg-cyan-500 text-[8px] px-1 rounded text-white"
                      >
                        On
                      </button>
                    )}
                  </button>

                  {/* Triple Captain */}
                  <button
                    onClick={() => setAvailableChips(prev => ({ ...prev, triplecaptain: !prev.triplecaptain }))}
                    className={`relative p-1 rounded-lg transition-all ${
                      !availableChips.triplecaptain ? 'opacity-30' :
                      activeChip === 'triplecaptain' ? 'ring-2 ring-cyan-400' : 'hover:bg-slate-700'
                    }`}
                    title="Triple Captain - Click to toggle availability"
                  >
                    <div className="w-8 h-8 rounded-full bg-gradient-to-br from-purple-400 to-purple-600 flex items-center justify-center">
                      <span className="text-white text-xs font-bold">3×</span>
                    </div>
                    {availableChips.triplecaptain && activeChip !== 'triplecaptain' && (
                      <button
                        onClick={(e) => { e.stopPropagation(); setActiveChip('triplecaptain'); }}
                        className="absolute -bottom-1 left-1/2 -translate-x-1/2 bg-slate-600 text-[8px] px-1 rounded text-white hover:bg-cyan-500"
                      >
                        Use
                      </button>
                    )}
                    {activeChip === 'triplecaptain' && (
                      <button
                        onClick={(e) => { e.stopPropagation(); setActiveChip(null); }}
                        className="absolute -bottom-1 left-1/2 -translate-x-1/2 bg-cyan-500 text-[8px] px-1 rounded text-white"
                      >
                        On
                      </button>
                    )}
                  </button>

                  {/* Wildcard */}
                  <button
                    onClick={() => setAvailableChips(prev => ({ ...prev, wildcard: !prev.wildcard }))}
                    className={`relative p-1 rounded-lg transition-all ${
                      !availableChips.wildcard ? 'opacity-30' :
                      activeChip === 'wildcard' ? 'ring-2 ring-cyan-400' : 'hover:bg-slate-700'
                    }`}
                    title="Wildcard - Click to toggle availability"
                  >
                    <div className="w-8 h-8 rounded-full bg-gradient-to-br from-red-400 to-red-600 flex items-center justify-center">
                      <svg className="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 24 24">
                        <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
                      </svg>
                    </div>
                    {availableChips.wildcard && activeChip !== 'wildcard' && (
                      <button
                        onClick={(e) => { e.stopPropagation(); setActiveChip('wildcard'); }}
                        className="absolute -bottom-1 left-1/2 -translate-x-1/2 bg-slate-600 text-[8px] px-1 rounded text-white hover:bg-cyan-500"
                      >
                        Use
                      </button>
                    )}
                    {activeChip === 'wildcard' && (
                      <button
                        onClick={(e) => { e.stopPropagation(); setActiveChip(null); }}
                        className="absolute -bottom-1 left-1/2 -translate-x-1/2 bg-cyan-500 text-[8px] px-1 rounded text-white"
                      >
                        On
                      </button>
                    )}
                  </button>

                  {/* Free Hit */}
                  <button
                    onClick={() => setAvailableChips(prev => ({ ...prev, freehit: !prev.freehit }))}
                    className={`relative p-1 rounded-lg transition-all ${
                      !availableChips.freehit ? 'opacity-30' :
                      activeChip === 'freehit' ? 'ring-2 ring-cyan-400' : 'hover:bg-slate-700'
                    }`}
                    title="Free Hit - Click to toggle availability"
                  >
                    <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-400 to-blue-600 flex items-center justify-center">
                      <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                      </svg>
                    </div>
                    {availableChips.freehit && activeChip !== 'freehit' && (
                      <button
                        onClick={(e) => { e.stopPropagation(); setActiveChip('freehit'); }}
                        className="absolute -bottom-1 left-1/2 -translate-x-1/2 bg-slate-600 text-[8px] px-1 rounded text-white hover:bg-cyan-500"
                      >
                        Use
                      </button>
                    )}
                    {activeChip === 'freehit' && (
                      <button
                        onClick={(e) => { e.stopPropagation(); setActiveChip(null); }}
                        className="absolute -bottom-1 left-1/2 -translate-x-1/2 bg-cyan-500 text-[8px] px-1 rounded text-white"
                      >
                        On
                      </button>
                    )}
                  </button>
                </div>

              </div>

              {/* View Toggle */}
              {theoreticalTeam && (
                <div className="flex bg-slate-700 rounded-lg p-1">
                  <button
                    onClick={() => setViewMode('current')}
                    className={`px-4 py-2 rounded-md text-sm font-medium transition-all ${
                      viewMode === 'current'
                        ? 'bg-purple-600 text-white'
                        : 'text-slate-400 hover:text-white'
                    }`}
                  >
                    Current Squad
                  </button>
                  <button
                    onClick={() => setViewMode('theoretical')}
                    className={`px-4 py-2 rounded-md text-sm font-medium transition-all ${
                      viewMode === 'theoretical'
                        ? 'bg-purple-600 text-white'
                        : 'text-slate-400 hover:text-white'
                    }`}
                  >
                    With Transfers
                  </button>
                </div>
              )}
            </div>

            {/* Active Chip Indicator */}
            {activeChip && (
              <div className="mt-2 flex items-center gap-2">
                <span className="text-cyan-400 text-xs font-medium">
                  {activeChip === 'benchboost' && '✓ Bench Boost active this GW'}
                  {activeChip === 'triplecaptain' && '✓ Triple Captain active this GW'}
                  {activeChip === 'wildcard' && '✓ Wildcard active - Unlimited transfers'}
                  {activeChip === 'freehit' && '✓ Free Hit active - Unlimited transfers'}
                </span>
              </div>
            )}

            {/* Transfer Summary */}
            {suggestedTransfers.length > 0 && viewMode === 'theoretical' && (
              <div className="mt-4 pt-4 border-t border-slate-700">
                <p className="text-slate-400 text-xs mb-2">Suggested Transfers:</p>
                <div className="flex flex-wrap gap-3">
                  {suggestedTransfers.map((transfer, idx) => {
                    // Find the actual player names from team or API response
                    const outPlayer = team.players.find(p =>
                      p.web_name?.toLowerCase().includes(transfer.out?.name?.toLowerCase()) ||
                      p.name?.toLowerCase().includes(transfer.out?.name?.toLowerCase())
                    )
                    const outName = outPlayer?.web_name || transfer.out?.name || transfer.out
                    const inName = transfer.in?.web_name || transfer.in?.name || transfer.in

                    return (
                      <div key={idx} className="flex items-center gap-2 bg-slate-700/50 rounded-lg px-3 py-2">
                        <span className="text-red-400 text-sm font-medium">{outName}</span>
                        <span className="text-slate-500">→</span>
                        <span className="text-green-400 text-sm font-medium">{inName}</span>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>

          {/* Two Column Layout: Formation + Chat */}
          <div className="grid grid-cols-2 gap-6">
            {/* Left Column: Formation */}
            <div>
              <h2 className="text-xl font-semibold text-white mb-4">
                {viewMode === 'current' ? 'Current Squad' : 'Theoretical Squad'}
              </h2>
              <TeamFormation
                players={viewMode === 'current' ? team.players : (theoreticalTeam?.players || team.players)}
                showTransferIndicators={viewMode === 'theoretical'}
              />

              {/* Injury Alerts */}
              {team.injury_risks?.length > 0 && (
                <div className="mt-4 bg-amber-500/20 border border-amber-500 rounded-lg p-4">
                  <h3 className="font-medium text-amber-300 mb-2">Injury Alerts</h3>
                  <div className="space-y-2">
                    {team.injury_risks.map((player, idx) => (
                      <div key={idx} className="flex items-center justify-between text-sm">
                        <span className="text-white">{player.name}</span>
                        <span className={`${
                          player.chance < 50 ? 'text-red-400' : 'text-amber-400'
                        }`}>
                          {player.chance}% chance
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Right Column: Chat - Fixed height with scrolling */}
            <div>
              <h2 className="text-xl font-semibold text-white mb-4">Ask About Your Team</h2>
              <ChatInterface
                teamId={savedTeamId}
                team={theoreticalTeam || team}
                onTransferSuggestion={applyTransfers}
                freeTransfers={freeTransfersOverride !== null ? freeTransfersOverride : (team?.free_transfers || 1)}
                availableChips={availableChips}
                activeChip={activeChip}
                suggestedTransfers={suggestedTransfers}
              />
            </div>
          </div>

          {/* Squad Details Table - Full Width */}
          <SquadTable players={team.players} gameweek={team.gameweek} />
        </>
      )}

      {/* Empty State */}
      {!team && !loading && !error && (
        <div className="bg-slate-800/50 rounded-lg p-12 text-center">
          <div className="text-6xl mb-4">🔍</div>
          <h2 className="text-xl font-semibold text-white mb-2">Enter Your Team ID</h2>
          <p className="text-slate-400 max-w-md mx-auto">
            Enter your FPL Team ID above to see your squad, get transfer recommendations,
            and chat with our AI assistant about your team.
          </p>
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value, icon }) {
  return (
    <div className="bg-slate-800/50 rounded-lg p-4">
      <div className="flex items-center gap-2 mb-1">
        <span>{icon}</span>
        <span className="text-slate-400 text-xs">{label}</span>
      </div>
      <p className="text-lg font-bold text-white truncate">{value}</p>
    </div>
  )
}

function formatRank(rank) {
  if (!rank) return '-'
  if (rank >= 1000000) return `${(rank / 1000000).toFixed(1)}M`
  if (rank >= 1000) return `${(rank / 1000).toFixed(0)}K`
  return rank.toLocaleString()
}

export default UserTeamPage
