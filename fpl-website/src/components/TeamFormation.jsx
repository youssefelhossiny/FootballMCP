import PlayerCard from './PlayerCard'

function TeamFormation({
  players,
  showTransferIndicators = false,
  showPoints = false,
  selectedOutId = null,
  onSelectOut,
}) {
  if (!players || players.length === 0) {
    return (
      <div className="card p-8 text-center">
        <p className="text-muted">No players to display</p>
      </div>
    )
  }

  const starters = players.filter(p => !p.is_bench)
  const bench = players.filter(p => p.is_bench).sort((a, b) => (a.bench_order || 0) - (b.bench_order || 0))

  const getPositionType = (p) => p.element_type || p.position
  const gks = starters.filter(p => getPositionType(p) === 1 || p.position === 'GKP' || p.position === 'GK')
  const defs = starters.filter(p => getPositionType(p) === 2 || p.position === 'DEF')
  const mids = starters.filter(p => getPositionType(p) === 3 || p.position === 'MID')
  const fwds = starters.filter(p => getPositionType(p) === 4 || p.position === 'FWD')

  const formation = `${defs.length}-${mids.length}-${fwds.length}`

  const handleClick = (player) => {
    if (onSelectOut) onSelectOut(player)
  }

  return (
    <div className="card overflow-hidden">
      {/* Pitch */}
      <div className="relative pitch-bg py-6 px-4 min-h-[480px]">
        {/* Pitch markings */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none opacity-30">
          <div className="absolute top-1/2 left-0 right-0 h-[2px] bg-white/60" />
          <div className="absolute top-1/2 left-1/2 w-24 h-24 border-2 border-white/60 rounded-full -translate-x-1/2 -translate-y-1/2" />
          <div className="absolute top-1/2 left-1/2 w-2 h-2 bg-white/60 rounded-full -translate-x-1/2 -translate-y-1/2" />
          <div className="absolute top-0 left-1/2 -translate-x-1/2 w-48 h-20 border-2 border-t-0 border-white/60" />
          <div className="absolute top-0 left-1/2 -translate-x-1/2 w-24 h-8 border-2 border-t-0 border-white/60" />
          <div className="absolute bottom-0 left-1/2 -translate-x-1/2 w-48 h-20 border-2 border-b-0 border-white/60" />
          <div className="absolute bottom-0 left-1/2 -translate-x-1/2 w-24 h-8 border-2 border-b-0 border-white/60" />
        </div>

        {/* Formation label */}
        <div className="absolute top-2 right-3 z-10 text-white/70 text-[11px] font-semibold num px-2 py-0.5 rounded" style={{ background: 'rgba(0,0,0,0.35)' }}>
          {formation}
        </div>

        {/* Rows */}
        <div className="relative z-10 flex flex-col justify-between h-full min-h-[440px]">
          <Row players={fwds} {...{ showTransferIndicators, showPoints, selectedOutId, onClick: handleClick }} />
          <Row players={mids} {...{ showTransferIndicators, showPoints, selectedOutId, onClick: handleClick }} />
          <Row players={defs} {...{ showTransferIndicators, showPoints, selectedOutId, onClick: handleClick }} />
          <Row players={gks} {...{ showTransferIndicators, showPoints, selectedOutId, onClick: handleClick }} />
        </div>
      </div>

      {/* Bench */}
      {bench.length > 0 && (
        <div className="py-4 px-4" style={{ background: 'var(--bg-elevated)' }}>
          <p className="text-center text-[11px] uppercase tracking-wider text-muted font-semibold mb-3">Bench</p>
          <div className="flex justify-center gap-3">
            {bench.map((player, idx) => (
              <PlayerCard
                key={player.id}
                player={player}
                isBench
                showBenchOrder
                benchOrder={idx}
                showPoints={showPoints}
                isSelectedForSwap={selectedOutId === player.id}
                onClick={onSelectOut ? () => onSelectOut(player) : undefined}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function Row({ players, showTransferIndicators, showPoints, selectedOutId, onClick }) {
  if (!players || players.length === 0) return null
  return (
    <div className="flex justify-center gap-2">
      {players.map(p => (
        <PlayerCard
          key={p.id}
          player={p}
          isTransferIn={showTransferIndicators && p.is_transfer_in}
          isTransferOut={showTransferIndicators && p.is_transfer_out}
          isSelectedForSwap={selectedOutId === p.id}
          showPoints={showPoints}
          onClick={() => onClick?.(p)}
        />
      ))}
    </div>
  )
}

export default TeamFormation
