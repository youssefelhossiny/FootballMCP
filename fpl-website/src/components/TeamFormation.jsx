import { useState } from 'react'
import PlayerCard from './PlayerCard'

function TeamFormation({
  players,
  showTransferIndicators = false,
  showPoints = false,
  selectedOutId = null,
  onPlayerClick,
  onSubstitute,
  canSubstitute,
}) {
  const [dragId, setDragId] = useState(null)
  const [dropTargetId, setDropTargetId] = useState(null)

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

  // Drag-and-drop substitution wiring. A card is a valid drop target when a
  // legal bench<->XI sub would result (checked via canSubstitute).
  const dnd = onSubstitute
    ? (player) => ({
        draggable: true,
        onDragStart: () => setDragId(player.id),
        onDragEnd: () => { setDragId(null); setDropTargetId(null) },
        onDragOver: (e) => {
          if (dragId && dragId !== player.id && (!canSubstitute || canSubstitute(dragId, player.id))) {
            e.preventDefault()
            setDropTargetId(player.id)
          }
        },
        onDragLeave: () => setDropTargetId(prev => (prev === player.id ? null : prev)),
        onDrop: (e) => {
          e.preventDefault()
          if (dragId && dragId !== player.id) onSubstitute(dragId, player.id)
          setDragId(null)
          setDropTargetId(null)
        },
        isDropTarget: dropTargetId === player.id,
        isDragging: dragId === player.id,
      })
    : () => ({})

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
          <Row players={fwds} {...{ showTransferIndicators, showPoints, selectedOutId, onPlayerClick, dnd }} />
          <Row players={mids} {...{ showTransferIndicators, showPoints, selectedOutId, onPlayerClick, dnd }} />
          <Row players={defs} {...{ showTransferIndicators, showPoints, selectedOutId, onPlayerClick, dnd }} />
          <Row players={gks} {...{ showTransferIndicators, showPoints, selectedOutId, onPlayerClick, dnd }} />
        </div>
      </div>

      {/* Bench */}
      {bench.length > 0 && (
        <div className="py-4 px-4" style={{ background: 'var(--bg-elevated)' }}>
          <p className="text-center text-[11px] uppercase tracking-wider text-muted font-semibold mb-3">
            Bench{onSubstitute ? ' · drag to sub' : ''}
          </p>
          <div className="flex justify-center gap-3">
            {bench.map((player, idx) => {
              const d = dnd(player)
              return (
                <PlayerCard
                  key={player.id}
                  player={player}
                  isBench
                  showBenchOrder
                  benchOrder={idx}
                  showPoints={showPoints}
                  isSelectedForSwap={selectedOutId === player.id}
                  onClick={onPlayerClick ? () => onPlayerClick(player) : undefined}
                  {...d}
                />
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

function Row({ players, showTransferIndicators, showPoints, selectedOutId, onPlayerClick, dnd }) {
  if (!players || players.length === 0) return null
  return (
    <div className="flex justify-center gap-2">
      {players.map(p => {
        const d = dnd(p)
        return (
          <PlayerCard
            key={p.id}
            player={p}
            isTransferIn={showTransferIndicators && p.is_transfer_in}
            isTransferOut={showTransferIndicators && p.is_transfer_out}
            isSelectedForSwap={selectedOutId === p.id}
            showPoints={showPoints}
            onClick={onPlayerClick ? () => onPlayerClick(p) : undefined}
            {...d}
          />
        )
      })}
    </div>
  )
}

export default TeamFormation
