function PlayerCard({
  player,
  isBench = false,
  showBenchOrder = false,
  benchOrder = null,
  isTransferOut = false,
  isTransferIn = false,
  isSelectedForSwap = false,
  showPoints = false,
  onClick,
}) {
  const teamIds = {
    'ARS': 3, 'AVL': 7, 'BOU': 91, 'BRE': 94, 'BHA': 36, 'BUR': 90,
    'CHE': 8, 'CRY': 31, 'EVE': 11, 'FUL': 54, 'IPS': 40, 'LEI': 13,
    'LIV': 14, 'MCI': 43, 'MUN': 1, 'NEW': 4, 'NFO': 17, 'SOU': 20,
    'SUN': 56, 'TOT': 6, 'WHU': 21, 'WOL': 39, 'LEE': 2, 'LUT': 95,
  }

  const teamId = player.team_code || teamIds[player.team] || 0
  const isGoalkeeper = player.position === 1 || player.element_type === 1 || player.position === 'GKP' || player.position === 'GK'
  const shirtUrl = isGoalkeeper
    ? `https://fantasy.premierleague.com/dist/img/shirts/standard/shirt_${teamId}_1-110.png`
    : `https://fantasy.premierleague.com/dist/img/shirts/standard/shirt_${teamId}-110.png`

  const positionNames = { 1: 'GKP', 2: 'DEF', 3: 'MID', 4: 'FWD' }
  const fixture = player.next_fixture || player.fixture || ''
  const fixtureDisplay = fixture || player.team

  // Price — now_cost is tenths (141 = £14.1m); price is decimal (14.1)
  const rawPrice = player.now_cost || (player.price ? player.price * 10 : 0)
  const priceDisplay = (rawPrice / 10).toFixed(1)

  const clickable = !!onClick && !isBench

  return (
    <div className={`flex flex-col items-center ${isBench ? 'w-[82px]' : 'w-[88px]'}`}>
      {showBenchOrder && benchOrder !== null && (
        <div className="text-[9px] text-white/70 mb-0.5 px-1.5 py-0.5 rounded" style={{ background: 'rgba(0,0,0,0.35)' }}>
          {benchOrder}. {positionNames[player.position]}
        </div>
      )}

      <button
        type="button"
        onClick={clickable ? onClick : undefined}
        disabled={!clickable}
        className={`relative flex flex-col items-center ${clickable ? 'cursor-pointer' : 'cursor-default'} ${isTransferOut ? 'opacity-40' : ''} transition-transform`}
        style={{
          transform: isSelectedForSwap ? 'translateY(-4px)' : undefined,
        }}
      >
        {/* Price badge */}
        <div
          className="absolute -top-1.5 left-1/2 -translate-x-1/2 z-20 px-1.5 py-[1px] rounded num text-[10px] font-bold"
          style={{
            background: isTransferIn ? 'var(--accent-primary)'
              : isTransferOut ? 'var(--accent-danger)'
              : isSelectedForSwap ? 'var(--accent-warn)'
              : 'rgba(15, 23, 42, 0.95)',
            color: 'white',
            boxShadow: '0 2px 4px rgba(0,0,0,0.3)',
          }}
        >
          £{priceDisplay}m
        </div>

        {/* Status indicator */}
        {player.status && player.status !== 'a' && (
          <span
            className="absolute top-3 left-0 z-10 w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-bold"
            style={getStatusStyle(player.status)}
          >
            {getStatusIcon(player.status)}
          </span>
        )}

        {/* Captain / Vice */}
        {player.is_captain && (
          <span className="absolute top-3 right-0 z-10 w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-bold" style={{ background: 'black', color: '#facc15', border: '1.5px solid #facc15' }}>C</span>
        )}
        {player.is_vice_captain && !player.is_captain && (
          <span className="absolute top-3 right-0 z-10 w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-bold" style={{ background: 'black', color: '#cbd5e1', border: '1.5px solid #94a3b8' }}>V</span>
        )}

        {/* Transfer / swap indicators */}
        {isTransferOut && (
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-30">
            <span className="text-red-400 text-2xl font-bold drop-shadow">✕</span>
          </div>
        )}
        {isTransferIn && (
          <div className="absolute -top-1 -right-1 z-30">
            <span className="w-4 h-4 rounded-full flex items-center justify-center text-[10px] font-bold text-white" style={{ background: 'var(--accent-primary)' }}>+</span>
          </div>
        )}

        {/* Selected-for-swap ring */}
        {isSelectedForSwap && (
          <div className="absolute inset-0 -inset-x-1 z-0 rounded-lg pointer-events-none" style={{ boxShadow: '0 0 0 2px var(--accent-warn)', borderRadius: '10px' }} />
        )}

        {/* Jersey */}
        <div className="w-14 h-14 flex items-center justify-center mt-1.5">
          <img
            src={shirtUrl}
            alt={player.team}
            className="w-12 h-12 object-contain drop-shadow-lg"
            onError={(e) => { e.target.src = 'https://fantasy.premierleague.com/dist/img/shirts/standard/shirt_0-110.png' }}
          />
        </div>

        {/* Name label */}
        <div
          className="px-1.5 py-0.5 rounded-md text-center min-w-[70px] -mt-0.5"
          style={{
            background: 'rgba(10, 15, 26, 0.92)',
            border: '1px solid rgba(255,255,255,0.08)',
          }}
        >
          <p className="text-[11px] font-semibold truncate leading-tight text-white">
            {player.web_name || player.name}
          </p>
          <p className="text-[9px] text-slate-400 num">
            {showPoints ? `${player.last_gw_points ?? player.event_points ?? 0} pts` : fixtureDisplay}
          </p>
        </div>
      </button>
    </div>
  )
}

function getStatusStyle(status) {
  switch (status) {
    case 'i': return { background: 'var(--accent-danger)', color: 'white' }
    case 'd': return { background: 'var(--accent-warn)', color: '#1a1a1a' }
    case 's': return { background: '#f97316', color: 'white' }
    case 'u': return { background: '#991b1b', color: 'white' }
    default: return { background: 'var(--text-muted)', color: 'white' }
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
