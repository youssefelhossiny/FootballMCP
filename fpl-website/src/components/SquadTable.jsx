function SquadTable({ players, gameweek }) {
  if (!players || players.length === 0) {
    return null
  }

  // Separate starters and bench
  const starters = players.filter(p => !p.is_bench)
  const bench = players.filter(p => p.is_bench).sort((a, b) => a.bench_order - b.bench_order)

  const positionNames = {
    1: 'GK',
    2: 'DEF',
    3: 'MID',
    4: 'FWD'
  }

  const positionColors = {
    1: 'bg-yellow-600',
    2: 'bg-green-600',
    3: 'bg-blue-600',
    4: 'bg-red-600'
  }

  return (
    <div className="bg-slate-800/50 rounded-lg p-6">
      <h2 className="text-xl font-semibold text-white mb-4">Squad Details</h2>

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="text-slate-400 text-sm border-b border-slate-700">
              <th className="text-left py-3 px-3">Player</th>
              <th className="text-left py-3 px-3">Team</th>
              <th className="text-center py-3 px-3">Pos</th>
              <th className="text-right py-3 px-3">Price</th>
              <th className="text-right py-3 px-3">GW{gameweek} Pts</th>
              <th className="text-right py-3 px-3">Total Pts</th>
              <th className="text-right py-3 px-3">Form</th>
              <th className="text-right py-3 px-3">Selected</th>
            </tr>
          </thead>
          <tbody>
            {/* Starting XI */}
            {starters.map((player, idx) => (
              <PlayerRow key={player.id} player={player} positionNames={positionNames} positionColors={positionColors} />
            ))}

            {/* Bench separator */}
            <tr>
              <td colSpan="8" className="py-2">
                <div className="border-t border-slate-600 my-2"></div>
                <span className="text-slate-500 text-sm">Bench</span>
              </td>
            </tr>

            {/* Bench players */}
            {bench.map((player, idx) => (
              <PlayerRow key={player.id} player={player} positionNames={positionNames} positionColors={positionColors} isBench />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function PlayerRow({ player, positionNames, positionColors, isBench = false }) {
  return (
    <tr className={`border-b border-slate-700/50 hover:bg-slate-700/30 ${isBench ? 'opacity-70' : ''}`}>
      <td className="py-3 px-3">
        <div className="flex items-center gap-2">
          <span className="text-white font-medium">{player.web_name}</span>
          {player.is_captain && (
            <span className="bg-yellow-500 text-black text-xs px-1.5 py-0.5 rounded font-bold">C</span>
          )}
          {player.is_vice_captain && !player.is_captain && (
            <span className="bg-yellow-500/50 text-black text-xs px-1.5 py-0.5 rounded font-bold">V</span>
          )}
          {player.status !== 'a' && (
            <span className={`text-xs px-1.5 py-0.5 rounded ${getStatusStyle(player.status)}`}>
              {getStatusLabel(player.status)}
            </span>
          )}
        </div>
      </td>
      <td className="py-3 px-3 text-slate-400">{player.team}</td>
      <td className="py-3 px-3 text-center">
        <span className={`text-xs px-2 py-1 rounded text-white ${positionColors[player.position]}`}>
          {positionNames[player.position]}
        </span>
      </td>
      <td className="py-3 px-3 text-right text-white">£{(player.price / 10).toFixed(1)}m</td>
      <td className="py-3 px-3 text-right">
        <span className={`font-medium ${getPointsColor(player.last_gw_points)}`}>
          {player.last_gw_points}
        </span>
      </td>
      <td className="py-3 px-3 text-right text-slate-300">{player.total_points}</td>
      <td className="py-3 px-3 text-right">
        <span className={`font-medium ${getFormColor(parseFloat(player.form))}`}>
          {player.form}
        </span>
      </td>
      <td className="py-3 px-3 text-right text-slate-400">{player.selected_by_percent}%</td>
    </tr>
  )
}

function getStatusStyle(status) {
  switch (status) {
    case 'i': return 'bg-red-500 text-white'
    case 'd': return 'bg-amber-500 text-white'
    case 's': return 'bg-orange-500 text-white'
    default: return 'bg-slate-500 text-white'
  }
}

function getStatusLabel(status) {
  switch (status) {
    case 'i': return 'INJ'
    case 'd': return '?'
    case 's': return 'SUS'
    default: return status
  }
}

function getPointsColor(points) {
  if (points >= 10) return 'text-green-400'
  if (points >= 6) return 'text-green-300'
  if (points >= 2) return 'text-white'
  if (points === 0) return 'text-slate-400'
  return 'text-red-400' // negative points
}

function getFormColor(form) {
  if (form >= 6) return 'text-green-400'
  if (form >= 4) return 'text-green-300'
  if (form >= 2) return 'text-slate-300'
  return 'text-red-400'
}

export default SquadTable
