import { useState, useEffect } from 'react'
import TeamFormation from '../components/TeamFormation'

function WeeklyPicksPage() {
  const [activeTab, setActiveTab] = useState('wildcard')
  const [wildcardTeam, setWildcardTeam] = useState(null)
  const [freehitTeam, setFreehitTeam] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchOptimalTeams()
  }, [])

  const fetchOptimalTeams = async () => {
    try {
      setLoading(true)
      const [wcResponse, fhResponse] = await Promise.all([
        fetch('/api/optimal/wildcard'),
        fetch('/api/optimal/freehit')
      ])

      if (!wcResponse.ok || !fhResponse.ok) {
        throw new Error('Failed to fetch optimal teams')
      }

      const [wcData, fhData] = await Promise.all([
        wcResponse.json(),
        fhResponse.json()
      ])

      setWildcardTeam(wcData)
      setFreehitTeam(fhData)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const currentTeam = activeTab === 'wildcard' ? wildcardTeam : freehitTeam

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
          onClick={fetchOptimalTeams}
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
      <div>
        <h1 className="text-3xl font-bold text-white">Weekly Optimal Teams</h1>
        <p className="text-slate-400 mt-1">
          Best possible squads for Wildcard and Free Hit chips
        </p>
      </div>

      {/* Tab Selector */}
      <div className="flex gap-2">
        <button
          onClick={() => setActiveTab('wildcard')}
          className={`px-6 py-3 rounded-lg font-medium transition-all ${
            activeTab === 'wildcard'
              ? 'bg-purple-600 text-white'
              : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
          }`}
        >
          Wildcard Team
        </button>
        <button
          onClick={() => setActiveTab('freehit')}
          className={`px-6 py-3 rounded-lg font-medium transition-all ${
            activeTab === 'freehit'
              ? 'bg-purple-600 text-white'
              : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
          }`}
        >
          Free Hit Team
        </button>
      </div>

      {/* Description */}
      <div className={`p-4 rounded-lg ${
        activeTab === 'wildcard' ? 'bg-purple-500/20 border border-purple-500' : 'bg-blue-500/20 border border-blue-500'
      }`}>
        {activeTab === 'wildcard' ? (
          <div className="text-purple-300">
            <strong>Wildcard Team:</strong> Best £100m squad optimized for long-term value.
            Consider fixture runs, form, and price changes.
          </div>
        ) : (
          <div className="text-blue-300">
            <strong>Free Hit Team:</strong> Best £100m squad for THIS GAMEWEEK ONLY.
            Focus on single-gameweek fixtures and captain picks.
          </div>
        )}
      </div>

      {/* Team Stats */}
      {currentTeam && (
        <div className="grid grid-cols-4 gap-4">
          <StatCard
            label="Predicted Points"
            value={currentTeam.predicted_points?.toFixed(1) || '-'}
            icon="⭐"
          />
          <StatCard
            label="Team Value"
            value={`£${(currentTeam.total_cost || 1000).toFixed(1)}m`}
            icon="💰"
          />
          <StatCard
            label="Budget Remaining"
            value={`£${((1000 - (currentTeam.total_cost || 0)) / 10).toFixed(1)}m`}
            icon="🏦"
          />
          <StatCard
            label="Fixture Difficulty"
            value={currentTeam.avg_fixture_difficulty?.toFixed(1) || '-'}
            icon="📅"
          />
        </div>
      )}

      {/* Formation Display */}
      {currentTeam?.players ? (
        <TeamFormation players={currentTeam.players} />
      ) : (
        <div className="bg-slate-800/50 rounded-lg p-8 text-center">
          <p className="text-slate-400">No optimal team data available</p>
        </div>
      )}

      {/* Player List with Details */}
      {currentTeam?.players && (
        <div className="bg-slate-800/50 rounded-lg p-6">
          <h2 className="text-xl font-semibold text-white mb-4">Squad Details</h2>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="text-slate-400 text-sm border-b border-slate-700">
                  <th className="text-left py-2 px-3">Player</th>
                  <th className="text-left py-2 px-3">Team</th>
                  <th className="text-right py-2 px-3">Price</th>
                  <th className="text-right py-2 px-3">Pred. Pts</th>
                  <th className="text-right py-2 px-3">Form</th>
                  <th className="text-center py-2 px-3">Next Fixture</th>
                </tr>
              </thead>
              <tbody>
                {currentTeam.players.map((player, idx) => (
                  <tr key={idx} className="border-b border-slate-700/50 hover:bg-slate-700/30">
                    <td className="py-2 px-3">
                      <div className="flex items-center gap-2">
                        <span className={`text-xs px-1.5 py-0.5 rounded ${getPositionColor(player.position)}`}>
                          {getPositionShort(player.position)}
                        </span>
                        <span className="text-white">{player.name}</span>
                        {player.is_captain && <span className="text-yellow-400">©</span>}
                      </div>
                    </td>
                    <td className="py-2 px-3 text-slate-400">{player.team}</td>
                    <td className="py-2 px-3 text-right text-white">£{(player.price / 10).toFixed(1)}m</td>
                    <td className="py-2 px-3 text-right text-purple-400">{player.predicted_points?.toFixed(1)}</td>
                    <td className="py-2 px-3 text-right text-slate-300">{player.form}</td>
                    <td className="py-2 px-3 text-center">
                      <span className={`px-2 py-1 rounded text-xs ${getFixtureColor(player.fixture_difficulty)}`}>
                        {player.next_opponent} ({player.fixture_difficulty})
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Differential Picks */}
      {currentTeam?.differentials?.length > 0 && (
        <div className="bg-slate-800/50 rounded-lg p-6">
          <h2 className="text-xl font-semibold text-white mb-4">Differential Picks ({"<"}5% owned)</h2>
          <div className="grid grid-cols-3 gap-4">
            {currentTeam.differentials.map((player, idx) => (
              <div key={idx} className="bg-slate-700/50 rounded-lg p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-white font-medium">{player.name}</span>
                  <span className="text-purple-400">{player.ownership}%</span>
                </div>
                <p className="text-slate-400 text-sm">{player.team}</p>
                <p className="text-green-400 text-sm mt-1">
                  {player.predicted_points?.toFixed(1)} predicted pts
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
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

function getPositionShort(position) {
  const map = { 1: 'GK', 2: 'DEF', 3: 'MID', 4: 'FWD' }
  return map[position] || '?'
}

function getPositionColor(position) {
  const colors = {
    1: 'bg-yellow-600 text-white',
    2: 'bg-green-600 text-white',
    3: 'bg-blue-600 text-white',
    4: 'bg-red-600 text-white'
  }
  return colors[position] || 'bg-slate-600 text-white'
}

function getFixtureColor(difficulty) {
  if (difficulty <= 2) return 'bg-green-600 text-white'
  if (difficulty === 3) return 'bg-yellow-600 text-white'
  if (difficulty === 4) return 'bg-orange-600 text-white'
  return 'bg-red-600 text-white'
}

export default WeeklyPicksPage
