import { useState, useEffect } from 'react'

function AnalyticsPage() {
  const [botData, setBotData] = useState(null)
  const [userData, setUserData] = useState(null)
  const [priceChanges, setPriceChanges] = useState(null)
  const [botDecision, setBotDecision] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [userTeamId, setUserTeamId] = useState(localStorage.getItem('fpl_team_id') || '')

  useEffect(() => {
    fetchData()
  }, [])

  const fetchData = async () => {
    try {
      setLoading(true)
      setError(null)

      // Fetch bot team data
      const botRes = await fetch('/api/bot/team')
      if (botRes.ok) {
        const data = await botRes.json()
        setBotData(data.team)
      }

      // Fetch price changes
      const priceRes = await fetch('/api/bot/price-changes')
      if (priceRes.ok) {
        const data = await priceRes.json()
        setPriceChanges(data)
      }

      // Fetch bot decision
      const decisionRes = await fetch('/api/bot/decision')
      if (decisionRes.ok) {
        const data = await decisionRes.json()
        setBotDecision(data)
      }

      // Fetch user team if ID is saved
      if (userTeamId) {
        const userRes = await fetch(`/api/team/${userTeamId}`)
        if (userRes.ok) {
          const data = await userRes.json()
          setUserData(data.team)
        }
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleUserTeamSubmit = async (e) => {
    e.preventDefault()
    localStorage.setItem('fpl_team_id', userTeamId)
    await fetchData()
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-purple-500 border-t-transparent"></div>
      </div>
    )
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white">Analytics</h1>
          <p className="text-slate-400 mt-1">
            Real-time price change predictions from LiveFPL, transfer recommendations with reasoning, chip strategy analysis, and head-to-head comparison with your team
          </p>
        </div>
        <button
          onClick={fetchData}
          className="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-white text-sm"
        >
          Refresh
        </button>
      </div>

      {/* User Team ID Input */}
      <div className="bg-slate-800/50 rounded-lg p-4">
        <form onSubmit={handleUserTeamSubmit} className="flex gap-4 items-center">
          <label className="text-slate-400 text-sm">Compare with your team:</label>
          <input
            type="text"
            value={userTeamId}
            onChange={(e) => setUserTeamId(e.target.value)}
            placeholder="Enter FPL Team ID"
            className="px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg text-white text-sm"
          />
          <button
            type="submit"
            className="px-4 py-2 bg-green-600 hover:bg-green-700 rounded-lg text-white text-sm"
          >
            Load Team
          </button>
        </form>
      </div>

      {/* Points Comparison */}
      {(botData || userData) && (
        <div className="bg-slate-800/50 rounded-lg p-6">
          <h2 className="text-xl font-semibold text-white mb-4">Points Comparison</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <ComparisonCard
              label="Total Points"
              botValue={botData?.total_points || 0}
              userValue={userData?.total_points}
            />
            <ComparisonCard
              label="GW Points"
              botValue={botData?.gw_points || 0}
              userValue={userData?.gw_points}
            />
            <ComparisonCard
              label="Avg Points/GW"
              botValue={botData?.avg_points_per_gw || 0}
              userValue={userData?.avg_points_per_gw}
            />
            <ComparisonCard
              label="Overall Rank"
              botValue={formatRank(botData?.overall_rank)}
              userValue={formatRank(userData?.overall_rank)}
              lowerIsBetter
            />
          </div>
        </div>
      )}

      {/* Bot Decision Section */}
      {botDecision && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Transfer Recommendations */}
          <div className="bg-slate-800/50 rounded-lg p-6">
            <h2 className="text-xl font-semibold text-white mb-4">Transfer Recommendations</h2>
            {botDecision.transfers?.length > 0 ? (
              <div className="space-y-3">
                {botDecision.transfers.map((transfer, idx) => (
                  <div key={idx} className="bg-slate-700/50 rounded-lg p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-red-400 font-medium">{transfer.out.name}</span>
                      <span className="text-slate-500">→</span>
                      <span className="text-green-400 font-medium">{transfer.in.name}</span>
                      {transfer.price_change_risk && (
                        <span className="text-yellow-400 text-xs">Price Rising!</span>
                      )}
                    </div>
                    <ul className="text-sm text-slate-400 space-y-1">
                      {transfer.reasons.map((reason, i) => (
                        <li key={i}>• {reason}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-slate-500">No transfer recommendations</p>
            )}
          </div>

          {/* Chip Strategy */}
          <div className="bg-slate-800/50 rounded-lg p-6">
            <h2 className="text-xl font-semibold text-white mb-4">Chip Strategy</h2>
            {botDecision.chip?.should_play ? (
              <div className="bg-purple-900/50 border border-purple-500 rounded-lg p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-purple-400 font-bold text-lg uppercase">
                    {botDecision.chip.type}
                  </span>
                  <span className="text-slate-400 text-sm">
                    (Score: {botDecision.chip.score}/100)
                  </span>
                </div>
                <ul className="text-sm text-slate-300 space-y-1">
                  {botDecision.chip.reasons.map((reason, i) => (
                    <li key={i}>• {reason}</li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="text-slate-500">No chip recommended this gameweek</p>
            )}

            {/* Captain Selection */}
            <div className="mt-4 pt-4 border-t border-slate-700">
              <h3 className="text-white font-medium mb-2">Captain Selection</h3>
              <div className="flex gap-4">
                <div className="bg-yellow-900/30 border border-yellow-500/50 rounded-lg px-4 py-2">
                  <span className="text-xs text-yellow-400">Captain</span>
                  <p className="text-white font-medium">{botDecision.captain?.name || '-'}</p>
                </div>
                <div className="bg-slate-700/50 border border-slate-600 rounded-lg px-4 py-2">
                  <span className="text-xs text-slate-400">Vice Captain</span>
                  <p className="text-white font-medium">{botDecision.vice_captain?.name || '-'}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Price Changes Section */}
      {priceChanges && (
        <div className="space-y-4">
          {/* Source indicator */}
          <div className="flex items-center gap-2">
            <span className="text-slate-400 text-sm">Data source:</span>
            <span className={`px-2 py-1 rounded text-xs font-medium ${
              priceChanges.source === 'livefpl.net'
                ? 'bg-green-900/50 text-green-400 border border-green-500/50'
                : 'bg-slate-700 text-slate-300'
            }`}>
              {priceChanges.source === 'livefpl.net' ? 'LiveFPL.net' : 'FPL API'}
            </span>
            {priceChanges.accuracy && (
              <span className="text-slate-500 text-xs">
                ({priceChanges.accuracy.rise}% rise / {priceChanges.accuracy.fall}% fall accuracy)
              </span>
            )}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Rising Players */}
          <div className="bg-slate-800/50 rounded-lg p-6">
            <h2 className="text-xl font-semibold text-white mb-4 flex items-center gap-2">
              <span className="text-green-400">↑</span> Price Rising
            </h2>
            <div className="space-y-2 max-h-96 overflow-y-auto">
              {priceChanges.rising?.map((player, idx) => (
                <div key={idx} className="flex items-center justify-between bg-slate-700/50 rounded-lg p-3">
                  <div>
                    <span className="text-white font-medium">{player.name}</span>
                    <span className="text-slate-400 text-sm ml-2">{player.team}</span>
                  </div>
                  <div className="text-right">
                    <span className="text-green-400 font-medium">£{player.price}m</span>
                    <p className="text-xs text-slate-400">
                      {player.progress != null
                        ? `${player.progress.toFixed(0)}% progress`
                        : `+${formatNumber(player.net_transfers)} transfers`}
                    </p>
                    {player.time_estimate && (
                      <p className="text-xs text-green-400">{player.time_estimate}</p>
                    )}
                    <span className={`text-xs ${player.risk_level === 'high' ? 'text-red-400' : 'text-yellow-400'}`}>
                      {player.risk_level} risk
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Falling Players */}
          <div className="bg-slate-800/50 rounded-lg p-6">
            <h2 className="text-xl font-semibold text-white mb-4 flex items-center gap-2">
              <span className="text-red-400">↓</span> Price Falling
            </h2>
            <div className="space-y-2 max-h-96 overflow-y-auto">
              {priceChanges.falling?.map((player, idx) => (
                <div key={idx} className="flex items-center justify-between bg-slate-700/50 rounded-lg p-3">
                  <div>
                    <span className="text-white font-medium">{player.name}</span>
                    <span className="text-slate-400 text-sm ml-2">{player.team}</span>
                  </div>
                  <div className="text-right">
                    <span className="text-red-400 font-medium">£{player.price}m</span>
                    <p className="text-xs text-slate-400">
                      {player.progress != null
                        ? `${player.progress.toFixed(0)}% progress`
                        : `${formatNumber(player.net_transfers)} transfers`}
                    </p>
                    {player.time_estimate && (
                      <p className="text-xs text-red-400">{player.time_estimate}</p>
                    )}
                    <span className={`text-xs ${player.risk_level === 'high' ? 'text-red-400' : 'text-yellow-400'}`}>
                      {player.risk_level} risk
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
          </div>
        </div>
      )}

      {/* Squad Price Risks */}
      {botDecision?.squad_price_risks?.length > 0 && (
        <div className="bg-slate-800/50 rounded-lg p-6">
          <h2 className="text-xl font-semibold text-white mb-4">Squad Price Risks</h2>
          <div className="flex flex-wrap gap-2">
            {botDecision.squad_price_risks.map((player, idx) => (
              <div
                key={idx}
                className={`px-3 py-2 rounded-lg border ${
                  player.direction === 'falling'
                    ? 'bg-red-900/30 border-red-500/50 text-red-300'
                    : 'bg-green-900/30 border-green-500/50 text-green-300'
                }`}
              >
                <span className="font-medium">{player.name}</span>
                <span className="text-xs ml-2">
                  {player.direction === 'falling' ? '↓' : '↑'} £{player.price}m
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Bot Reasoning */}
      {botDecision?.reasoning && (
        <div className="bg-slate-800/50 rounded-lg p-6">
          <h2 className="text-xl font-semibold text-white mb-2">Bot Analysis</h2>
          <p className="text-slate-300">{botDecision.reasoning}</p>
          <p className="text-slate-500 text-sm mt-2">
            Decision made: {new Date(botDecision.timestamp).toLocaleString()}
          </p>
        </div>
      )}

      {error && (
        <div className="bg-red-500/20 border border-red-500 rounded-lg p-4">
          <p className="text-red-300">Error: {error}</p>
        </div>
      )}
    </div>
  )
}

function ComparisonCard({ label, botValue, userValue, lowerIsBetter = false }) {
  const botWins = lowerIsBetter
    ? (botValue < userValue)
    : (botValue > userValue)
  const userWins = lowerIsBetter
    ? (userValue < botValue)
    : (userValue > botValue)

  return (
    <div className="bg-slate-700/50 rounded-lg p-4">
      <p className="text-slate-400 text-sm mb-2">{label}</p>
      <div className="flex justify-between items-end">
        <div>
          <span className="text-xs text-purple-400">Bot</span>
          <p className={`text-xl font-bold ${userValue != null && botWins ? 'text-green-400' : 'text-white'}`}>
            {botValue}
          </p>
        </div>
        {userValue != null && (
          <div className="text-right">
            <span className="text-xs text-blue-400">You</span>
            <p className={`text-xl font-bold ${userWins ? 'text-green-400' : 'text-white'}`}>
              {userValue}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

function formatRank(rank) {
  if (!rank) return '-'
  if (rank >= 1000000) return `${(rank / 1000000).toFixed(1)}M`
  if (rank >= 1000) return `${(rank / 1000).toFixed(0)}K`
  return rank.toLocaleString()
}

function formatNumber(num) {
  if (!num) return '0'
  if (Math.abs(num) >= 1000000) return `${(num / 1000000).toFixed(1)}M`
  if (Math.abs(num) >= 1000) return `${(num / 1000).toFixed(0)}K`
  return num.toLocaleString()
}

export default AnalyticsPage
