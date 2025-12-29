import PlayerCard from './PlayerCard'

function TeamFormation({ players, showTransferIndicators = false }) {
  if (!players || players.length === 0) {
    return (
      <div className="bg-slate-800/50 rounded-lg p-8 text-center">
        <p className="text-slate-400">No players to display</p>
      </div>
    )
  }

  // Separate starters and bench based on is_bench flag (from actual GW picks)
  const starters = players.filter(p => !p.is_bench)
  const bench = players.filter(p => p.is_bench).sort((a, b) => (a.bench_order || 0) - (b.bench_order || 0))

  // Group starters by position for display (handle both numeric and string positions)
  const getPositionType = (p) => p.element_type || p.position
  const goalkeepers = starters.filter(p => getPositionType(p) === 1 || p.position === 'GKP')
  const defenders = starters.filter(p => getPositionType(p) === 2 || p.position === 'DEF')
  const midfielders = starters.filter(p => getPositionType(p) === 3 || p.position === 'MID')
  const forwards = starters.filter(p => getPositionType(p) === 4 || p.position === 'FWD')

  // Determine formation string (e.g., "3-5-2")
  const formation = `${defenders.length}-${midfielders.length}-${forwards.length}`

  return (
    <div className="rounded-lg overflow-hidden">
      {/* Pitch */}
      <div
        className="relative py-8 px-4 min-h-[480px]"
        style={{
          background: 'linear-gradient(to bottom, #1a472a 0%, #2d5a3c 50%, #1a472a 100%)',
        }}
      >
        {/* Pitch markings */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none opacity-30">
          {/* Center line */}
          <div className="absolute top-1/2 left-0 right-0 h-[2px] bg-white/50" />
          {/* Center circle */}
          <div className="absolute top-1/2 left-1/2 w-24 h-24 border-2 border-white/50 rounded-full -translate-x-1/2 -translate-y-1/2" />
          {/* Center dot */}
          <div className="absolute top-1/2 left-1/2 w-2 h-2 bg-white/50 rounded-full -translate-x-1/2 -translate-y-1/2" />
          {/* Top penalty area */}
          <div className="absolute top-0 left-1/2 -translate-x-1/2 w-48 h-20 border-2 border-t-0 border-white/50" />
          {/* Top goal area */}
          <div className="absolute top-0 left-1/2 -translate-x-1/2 w-24 h-8 border-2 border-t-0 border-white/50" />
          {/* Bottom penalty area */}
          <div className="absolute bottom-0 left-1/2 -translate-x-1/2 w-48 h-20 border-2 border-b-0 border-white/50" />
          {/* Bottom goal area */}
          <div className="absolute bottom-0 left-1/2 -translate-x-1/2 w-24 h-8 border-2 border-b-0 border-white/50" />
        </div>

        {/* Formation display */}
        <div className="absolute top-2 right-3 text-white/60 text-xs font-medium">
          {formation}
        </div>

        {/* Formation Rows - Based on actual picks */}
        <div className="relative z-10 space-y-4">
          {/* Forwards */}
          {forwards.length > 0 && <FormationRow players={forwards} showTransferIndicators={showTransferIndicators} />}

          {/* Midfielders */}
          {midfielders.length > 0 && <FormationRow players={midfielders} showTransferIndicators={showTransferIndicators} />}

          {/* Defenders */}
          {defenders.length > 0 && <FormationRow players={defenders} showTransferIndicators={showTransferIndicators} />}

          {/* Goalkeeper */}
          {goalkeepers.length > 0 && <FormationRow players={goalkeepers} showTransferIndicators={showTransferIndicators} />}
        </div>
      </div>

      {/* Substitutes Section */}
      {bench.length > 0 && (
        <div className="bg-slate-800/80 py-4 px-4">
          <p className="text-white text-center text-sm font-medium mb-3">Substitutes</p>
          <div className="flex justify-center gap-3">
            {bench.map((player, idx) => (
              <PlayerCard
                key={player.id}
                player={player}
                isBench
                showBenchOrder
                benchOrder={idx}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function FormationRow({ players, showTransferIndicators = false }) {
  if (!players || players.length === 0) return null

  return (
    <div className="flex justify-center gap-2">
      {players.map((player) => (
        <PlayerCard
          key={player.id}
          player={player}
          isTransferIn={showTransferIndicators && player.is_transfer_in}
          isTransferOut={showTransferIndicators && player.is_transfer_out}
        />
      ))}
    </div>
  )
}

export default TeamFormation
