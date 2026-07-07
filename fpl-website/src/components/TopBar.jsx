/**
 * TopBar — sticky strip showing squad-level stats for the decision cockpit.
 * Displays Players / Bank / Free Transfers / Points Hit / Value.
 */
function TopBar({
  playersSelected = 0,
  bank = 0,
  bankAfterTransfers = null,
  teamValue = 0,
  freeTransfers = 1,
  onFreeTransfersChange,
  pointsCost = 0,
  pendingTransfers = 0,
  activeChip = null,
  onResetChanges,
  viewMode,
  onViewModeChange,
  hasTheoretical = false,
}) {
  const bankDisplay = bankAfterTransfers !== null ? bankAfterTransfers : bank
  const bankLabel = bankAfterTransfers !== null ? 'Bank (after)' : 'Bank'
  const bankNegative = bankDisplay < 0
  const hitFree = activeChip === 'wildcard' || activeChip === 'freehit'

  return (
    <div className="card px-5 py-3 flex items-center flex-wrap gap-x-8 gap-y-3">
      <Stat label="Players" value={`${playersSelected}/15`} accent={playersSelected === 15 ? 'good' : null} />
      <Stat
        label={bankLabel}
        value={`£${bankDisplay.toFixed(1)}m`}
        accent={bankNegative ? 'bad' : (bankAfterTransfers !== null ? 'warn' : null)}
      />
      <div className="flex flex-col">
        <span className="text-[10px] uppercase tracking-wider text-muted font-medium">Free Transfers</span>
        <div className="flex items-center gap-1.5 mt-0.5">
          <button
            onClick={() => onFreeTransfersChange?.(Math.max(0, freeTransfers - 1))}
            className="w-5 h-5 rounded text-muted hover:text-primary hover:bg-white/5 transition-colors text-sm leading-none"
            aria-label="Decrease free transfers"
          >‹</button>
          <span className="num text-[15px] font-semibold text-primary w-4 text-center">{freeTransfers}</span>
          <button
            onClick={() => onFreeTransfersChange?.(Math.min(5, freeTransfers + 1))}
            className="w-5 h-5 rounded text-muted hover:text-primary hover:bg-white/5 transition-colors text-sm leading-none"
            aria-label="Increase free transfers"
          >›</button>
        </div>
      </div>
      {pendingTransfers > 0 && (
        <Stat
          label="Points Hit"
          value={hitFree ? 'FREE' : (pointsCost > 0 ? `−${pointsCost}` : '0')}
          accent={hitFree ? 'good' : (pointsCost > 0 ? 'bad' : 'good')}
        />
      )}
      <Stat label="Team Value" value={`£${teamValue.toFixed(1)}m`} />

      <div className="ml-auto flex items-center gap-2">
        {pendingTransfers > 0 && (
          <button
            onClick={onResetChanges}
            className="text-[12px] px-2.5 py-1 rounded text-muted hover:text-primary hover:bg-white/5 transition-colors"
          >
            Reset ({pendingTransfers})
          </button>
        )}
        {hasTheoretical && (
          <div className="flex rounded-lg p-0.5" style={{ background: 'var(--bg-elevated)' }}>
            <ViewTab active={viewMode === 'current'} onClick={() => onViewModeChange?.('current')}>Current</ViewTab>
            <ViewTab active={viewMode === 'theoretical'} onClick={() => onViewModeChange?.('theoretical')}>With Changes</ViewTab>
          </div>
        )}
      </div>
    </div>
  )
}

function Stat({ label, value, accent }) {
  const color =
    accent === 'good' ? 'var(--accent-primary)'
    : accent === 'bad' ? 'var(--accent-danger)'
    : accent === 'warn' ? 'var(--accent-warn)'
    : 'var(--text-primary)'
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wider text-muted font-medium">{label}</span>
      <span className="num text-[15px] font-semibold mt-0.5" style={{ color }}>{value}</span>
    </div>
  )
}

function ViewTab({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className="px-3 py-1 rounded-md text-[12px] font-medium transition-all"
      style={active
        ? { background: 'var(--accent-primary-soft)', color: 'var(--accent-primary)' }
        : { color: 'var(--text-secondary)' }
      }
    >
      {children}
    </button>
  )
}

export default TopBar
