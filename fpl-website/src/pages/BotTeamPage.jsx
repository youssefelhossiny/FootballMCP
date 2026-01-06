import { useState, useEffect } from 'react'
import TeamFormation from '../components/TeamFormation'

function BotTeamPage() {
  const [botTeam, setBotTeam] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [gameweek, setGameweek] = useState(null)

  useEffect(() => {
    fetchBotTeam()
  }, [])

  const fetchBotTeam = async () => {
    try {
      setLoading(true)
      const response = await fetch('/api/bot/team')
      if (!response.ok) throw new Error('Failed to fetch bot team')
      const data = await response.json()
      setBotTeam(data.team)
      setGameweek(data.gameweek)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-purple-500 border-t-transparent"></div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-500/20 border border-red-500 rounded-lg p-6 text-center">
        <p className="text-red-300">Error: {error}</p>
        <button
          onClick={fetchBotTeam}
          className="mt-4 px-4 py-2 bg-red-600 hover:bg-red-700 rounded-lg text-white"
        >
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white">Bot's FPL Team</h1>
          <p className="text-slate-400 mt-1">
            AI-managed team making autonomous transfers, captain picks, and chip decisions based on advanced player stats, fixtures, and price predictions
          </p>
        </div>
        <div className="bg-slate-800 rounded-lg px-6 py-3">
          <span className="text-slate-400 text-sm">Gameweek</span>
          <p className="text-2xl font-bold text-purple-400">{gameweek || '-'}</p>
        </div>
      </div>

      {/* Team Stats */}
      <div className="grid grid-cols-3 md:grid-cols-6 gap-4">
        <StatCard
          label="Total Points"
          value={botTeam?.total_points || 0}
          icon="🏆"
        />
        <StatCard
          label="GW Points"
          value={botTeam?.gw_points || 0}
          icon="⭐"
        />
        <StatCard
          label="Avg Pts/GW"
          value={botTeam?.avg_points_per_gw || 0}
          icon="📈"
        />
        <StatCard
          label="Overall Rank"
          value={formatRank(botTeam?.overall_rank)}
          icon="📊"
        />
        <StatCard
          label="Team Value"
          value={`£${(botTeam?.team_value / 10 || 100).toFixed(1)}m`}
          icon="💰"
        />
        <StatCard
          label="Transfers"
          value={botTeam?.transfers_this_week || 0}
          icon="🔄"
        />
      </div>

      {/* Team Formation + Transfers Side by Side */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-stretch">
        {/* Team Formation - Left Side (2 cols) */}
        <div className="lg:col-span-2">
          {botTeam?.players ? (
            <TeamFormation players={botTeam.players} showPoints={true} />
          ) : (
            <div className="bg-slate-800/50 rounded-lg p-8 text-center">
              <p className="text-slate-400">Bot team not configured yet</p>
              <p className="text-slate-500 text-sm mt-2">
                Set up bot credentials to enable autonomous management
              </p>
            </div>
          )}
        </div>

        {/* Transfer History - Right Side (1 col) */}
        <div className="lg:col-span-1 flex flex-col">
        <div className="bg-slate-800/50 rounded-lg p-6 flex flex-col h-[725px]">
            <h2 className="text-xl font-semibold text-white mb-4">Recent Transfers</h2>
            {botTeam?.transfers?.length > 0 ? (
              <div className="space-y-2 overflow-y-auto flex-1 pr-2">
                {botTeam.transfers.map((transfer, idx) => (
                  <div key={idx} className="flex flex-col p-3 bg-slate-700/50 rounded-lg">
                    <div className="flex items-center gap-2">
                      <span className="text-red-400 text-sm">{transfer.player_out}</span>
                      <span className="text-slate-500">→</span>
                      <span className="text-green-400 text-sm">{transfer.player_in}</span>
                    </div>
                    <span className="text-slate-400 text-xs mt-1">GW {transfer.gameweek}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-slate-500">No transfers made yet</p>
            )}
          </div>
        </div>
      </div>

      {/* Chip Usage */}
      <div className="bg-slate-800/50 rounded-lg p-6">
        <h2 className="text-xl font-semibold text-white mb-4">Chips</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <ChipCard name="Wildcard" status={botTeam?.chips?.wildcard2} />
          <ChipCard name="Free Hit" status={botTeam?.chips?.freehit} />
          <ChipCard name="Bench Boost" status={botTeam?.chips?.benchboost} />
          <ChipCard name="Triple Captain" status={botTeam?.chips?.triplecaptain} />
        </div>
      </div>
    </div>
  )
}

function StatCard({ label, value, icon }) {
  return (
    <div className="bg-slate-800/50 rounded-lg p-4">
      <div className="flex items-center gap-2 mb-2">
        <span>{icon}</span>
        <span className="text-slate-400 text-sm">{label}</span>
      </div>
      <p className="text-2xl font-bold text-white">{value}</p>
    </div>
  )
}

function ChipCard({ name, status }) {
  const isUsed = status?.used
  const usedGW = status?.gameweek

  return (
    <div className={`p-4 rounded-lg border ${
      isUsed
        ? 'bg-slate-700/50 border-slate-600'
        : 'bg-purple-900/30 border-purple-500'
    }`}>
      <p className="font-medium text-white">{name}</p>
      <p className={`text-sm ${isUsed ? 'text-slate-400' : 'text-purple-400'}`}>
        {isUsed ? `Used GW${usedGW}` : 'Available'}
      </p>
    </div>
  )
}

function formatRank(rank) {
  if (!rank) return '-'
  if (rank >= 1000000) return `${(rank / 1000000).toFixed(1)}M`
  if (rank >= 1000) return `${(rank / 1000).toFixed(0)}K`
  return rank.toLocaleString()
}

export default BotTeamPage
