function PlayerCard({ player, isBench = false, showBenchOrder = false, benchOrder = null, isTransferOut = false, isTransferIn = false }) {
  // FPL Team IDs for shirt URLs
  const teamIds = {
    'ARS': 3,
    'AVL': 7,
    'BOU': 91,
    'BRE': 94,
    'BHA': 36,
    'BUR': 90,
    'CHE': 8,
    'CRY': 31,
    'EVE': 11,
    'FUL': 54,
    'IPS': 40,
    'LEI': 13,
    'LIV': 14,
    'MCI': 43,
    'MUN': 1,
    'NEW': 4,
    'NFO': 17,
    'SOU': 20,
    'SUN': 56,
    'TOT': 6,
    'WHU': 21,
    'WOL': 39,
    'LEE': 2,
    'LUT': 95,
  }

  // Get team ID - prefer team_code from API, fallback to lookup table
  const teamId = player.team_code || teamIds[player.team] || 0

  // Build shirt URL - use png format which is more reliable
  const isGoalkeeper = player.position === 1 || player.element_type === 1
  const shirtUrl = isGoalkeeper
    ? `https://fantasy.premierleague.com/dist/img/shirts/standard/shirt_${teamId}_1-110.png`
    : `https://fantasy.premierleague.com/dist/img/shirts/standard/shirt_${teamId}-110.png`

  // Position names for bench labels
  const positionNames = { 1: 'GKP', 2: 'DEF', 3: 'MID', 4: 'FWD' }

  // Get fixture info - format: OPP (H) or OPP (A)
  const fixture = player.next_fixture || player.fixture || ''
  const fixtureDisplay = fixture ? `${fixture}` : `${player.team}`

  // Format price - now_cost is always in tenths (e.g., 78 = £7.8m, 149 = £14.9m)
  const rawPrice = player.now_cost || player.price || 0
  const price = (rawPrice / 10).toFixed(1)

  return (
    <div className={`flex flex-col items-center ${isBench ? 'w-[85px]' : 'w-[90px]'}`}>
      {/* Bench order label */}
      {showBenchOrder && benchOrder !== null && (
        <div className="text-[10px] text-slate-300 mb-1 bg-slate-700/80 px-2 py-0.5 rounded">
          {benchOrder}. {positionNames[player.position]}
        </div>
      )}

      {/* Player Card */}
      <div className={`relative flex flex-col items-center ${isTransferOut ? 'opacity-50' : ''}`}>
        {/* Price badge - top of card like FPL */}
        <div className={`absolute -top-2 left-1/2 -translate-x-1/2 z-20 px-1.5 py-0.5 rounded text-[9px] font-bold shadow-md ${
          isTransferIn ? 'bg-green-500 text-white' : isTransferOut ? 'bg-red-500 text-white' : 'bg-purple-600 text-white'
        }`}>
          £{price}m
        </div>

        {/* Status indicator (injury/doubt) */}
        {player.status && player.status !== 'a' && (
          <div className="absolute top-4 left-0 z-10">
            <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold shadow-md ${getStatusStyle(player.status)}`}>
              {getStatusIcon(player.status)}
            </span>
          </div>
        )}

        {/* Captain/Vice badge */}
        {player.is_captain && (
          <div className="absolute top-4 right-0 z-10">
            <span className="bg-black text-yellow-400 text-[10px] w-5 h-5 rounded-full flex items-center justify-center font-bold border-2 border-yellow-400 shadow-md">C</span>
          </div>
        )}
        {player.is_vice_captain && !player.is_captain && (
          <div className="absolute top-4 right-0 z-10">
            <span className="bg-black text-slate-300 text-[10px] w-5 h-5 rounded-full flex items-center justify-center font-bold border-2 border-slate-400 shadow-md">V</span>
          </div>
        )}

        {/* Transfer indicator */}
        {isTransferOut && (
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-30">
            <span className="text-red-500 text-2xl font-bold">✕</span>
          </div>
        )}
        {isTransferIn && (
          <div className="absolute -top-1 -right-1 z-30">
            <span className="bg-green-500 text-white text-[10px] w-5 h-5 rounded-full flex items-center justify-center font-bold shadow-md">+</span>
          </div>
        )}

        {/* Jersey Image */}
        <div className="w-16 h-16 flex items-center justify-center mt-2">
          <img
            src={shirtUrl}
            alt={player.team}
            className="w-14 h-14 object-contain drop-shadow-lg"
            onError={(e) => {
              e.target.src = 'https://fantasy.premierleague.com/dist/img/shirts/standard/shirt_0-110.png'
            }}
          />
        </div>

        {/* Name Label */}
        <div className="bg-slate-800 text-white px-2 py-1 rounded-md text-center min-w-[75px] shadow-md -mt-1">
          <p className="text-[11px] font-semibold truncate leading-tight">
            {player.web_name || player.name}
          </p>
          <p className="text-[10px] text-slate-400">
            {fixtureDisplay}
          </p>
        </div>
      </div>
    </div>
  )
}

function getStatusStyle(status) {
  switch (status) {
    case 'i': return 'bg-red-500 text-white'
    case 'd': return 'bg-yellow-500 text-black'
    case 's': return 'bg-orange-500 text-white'
    case 'u': return 'bg-red-600 text-white'
    default: return 'bg-slate-500 text-white'
  }
}

function getStatusIcon(status) {
  switch (status) {
    case 'i': return '!'
    case 'd': return '?'
    case 's': return 'S'
    case 'u': return 'X'
    default: return '?'
  }
}

export default PlayerCard
