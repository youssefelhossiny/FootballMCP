/**
 * SVG chart geometry helpers for the Stats page.
 * Ported from the Matchday "Stats.dc.html" design. Pure functions — no React.
 *
 * All charts share a 820-wide viewBox. Each returns plain data (paths, tick
 * arrays, endpoint labels) that the component renders as <svg> primitives.
 */

export const cum = (arr) => {
  let s = 0
  return arr.map((v) => (s += v))
}

export const fmtK = (k) => {
  if (k >= 1_000_000) return (k / 1_000_000).toFixed(1).replace(/\.0$/, '') + 'M'
  if (k >= 1000) return (k / 1000).toFixed(1).replace(/\.0$/, '') + 'K'
  return String(Math.round(k))
}

// viewBox 820 wide; plot area L..(820-R), T..(H-B)
export const geo = (H, R = 70) => ({ L: 46, R, T: 16, B: 26, W: 820, H })
export const sx = (g, i, n) => g.L + (i * (g.W - g.L - g.R)) / (n - 1)
export const sy = (g, v, min, max) =>
  g.T + (1 - (v - min) / (max - min)) * (g.H - g.T - g.B)

export const linePath = (g, arr, min, max) =>
  arr
    .map(
      (v, i) =>
        (i === 0 ? 'M' : 'L') +
        sx(g, i, arr.length).toFixed(1) +
        ' ' +
        sy(g, v, min, max).toFixed(1)
    )
    .join(' ')

const GW_TICKS = [1, 5, 10, 15, 20, 25]
export const xTicks = (g, n) => {
  const ticks = [...GW_TICKS.filter((gw) => gw <= n), n]
  return [...new Set(ticks)].map((gw) => ({
    key: gw,
    x: sx(g, gw - 1, n).toFixed(1),
    label: gw === 1 ? 'GW1' : String(gw),
  }))
}

/**
 * Build every derived value the Stats charts need from three per-GW series.
 * `user`, `bot`, `avg` are arrays of per-gameweek points; `rankUser`/`rankBot`
 * are per-GW overall ranks; `bench` is per-GW bench points. All same length.
 */
export function buildChartModel({ gw, user, bot, avg, rankUser, rankBot, bench }) {
  const n = gw.length
  const cumU = cum(user)
  const cumB = cum(bot)
  const cumA = cum(avg)
  const totU = cumU[n - 1]
  const totB = cumB[n - 1]
  const totA = cumA[n - 1]

  // ----- cumulative points -----
  const gC = geo(280)
  const cumMax = Math.max(250, Math.ceil(totU / 250) * 250)
  const yTickVals = []
  for (let v = 0; v <= cumMax; v += 500) yTickVals.push(v)
  const cumYTicks = yTickVals.map((v) => ({
    key: v,
    y: sy(gC, v, 0, cumMax).toFixed(1),
    ty: (sy(gC, v, 0, cumMax) + 3).toFixed(1),
    label: v === 0 ? '0' : v.toLocaleString(),
  }))
  const endOf = (g, arr, min, max, label, dy = 4) => {
    const x = sx(g, n - 1, n)
    const y = sy(g, arr[n - 1], min, max)
    return {
      x: x.toFixed(1),
      y: y.toFixed(1),
      lx: (x + 8).toFixed(1),
      ly: (y + dy).toFixed(1),
      label,
    }
  }
  const userArea =
    linePath(gC, cumU, 0, cumMax) +
    ' L' +
    sx(gC, n - 1, n).toFixed(1) +
    ' ' +
    (gC.H - gC.B) +
    ' L' +
    gC.L +
    ' ' +
    (gC.H - gC.B) +
    ' Z'

  // ----- rank over time (inverted: bigger rank sits lower) -----
  const gR = geo(230)
  const allRanks = [...rankUser, ...rankBot]
  const rMin = Math.max(1, Math.floor(Math.min(...allRanks) / 250) * 250)
  const rMax = Math.ceil(Math.max(...allRanks) / 250) * 250
  const ryOf = (v) =>
    gR.T + ((v - rMin) / (rMax - rMin || 1)) * (gR.H - gR.T - gR.B)
  const rankPathOf = (arr) =>
    arr
      .map(
        (v, i) =>
          (i === 0 ? 'M' : 'L') + sx(gR, i, n).toFixed(1) + ' ' + ryOf(v).toFixed(1)
      )
      .join(' ')
  const rankStep = (rMax - rMin) / 3
  const rankYTicks = [rMin, rMin + rankStep, rMin + 2 * rankStep, rMax].map((v) => ({
    key: v,
    y: ryOf(v).toFixed(1),
    ty: (ryOf(v) + 3).toFixed(1),
    label: fmtK(v),
  }))
  const rankEnd = (arr, label, dy = 4) => {
    const x = sx(gR, n - 1, n)
    const y = ryOf(arr[n - 1])
    return {
      x: x.toFixed(1),
      y: y.toFixed(1),
      lx: (x + 8).toFixed(1),
      ly: (y + dy).toFixed(1),
      label,
    }
  }

  // ----- per-GW points bars (green when you beat the GW average) -----
  const gB = geo(230, 46)
  const barMax = Math.max(90, Math.ceil(Math.max(...user) / 10) * 10)
  const innerW = gB.W - gB.L - gB.R
  const slot = innerW / n
  const bw = slot * 0.62
  const gwBars = user.map((v, i) => {
    const y = sy(gB, v, 0, barMax)
    const y0 = gB.H - gB.B
    return {
      key: i,
      x: (gB.L + i * slot + (slot - bw) / 2).toFixed(1),
      y: y.toFixed(1),
      w: bw.toFixed(1),
      h: (y0 - y).toFixed(1),
      fill: v >= avg[i] ? 'var(--pitch-500)' : 'var(--ink-650)',
    }
  })
  const avgStepPath = avg
    .map((v, i) => {
      const x0 = gB.L + i * slot
      const x1 = x0 + slot
      const y = sy(gB, v, 0, barMax)
      return (i === 0 ? 'M' : 'L') + x0.toFixed(1) + ' ' + y.toFixed(1) + ' L' + x1.toFixed(1) + ' ' + y.toFixed(1)
    })
    .join(' ')
  const barYTicks = [0, Math.round(barMax / 2), barMax].map((v) => ({
    key: v,
    y: sy(gB, v, 0, barMax).toFixed(1),
    ty: (sy(gB, v, 0, barMax) + 3).toFixed(1),
    label: String(v),
  }))
  const barXTicks = [...new Set([...GW_TICKS.filter((g) => g <= n), n])].map((gw) => ({
    key: gw,
    x: (gB.L + (gw - 1) * slot + slot / 2).toFixed(1),
    label: gw === 1 ? 'GW1' : String(gw),
  }))

  // ----- bench points bars -----
  const gBe = geo(140, 46)
  const beMax = Math.max(8, Math.ceil(Math.max(...bench, 1) / 2) * 2)
  const slotBe = (gBe.W - gBe.L - gBe.R) / n
  const bwBe = slotBe * 0.62
  const benchBars = bench.map((v, i) => {
    const y = sy(gBe, v, 0, beMax)
    const y0 = gBe.H - gBe.B
    return {
      key: i,
      x: (gBe.L + i * slotBe + (slotBe - bwBe) / 2).toFixed(1),
      y: y.toFixed(1),
      w: bwBe.toFixed(1),
      h: Math.max(1.5, y0 - y).toFixed(1),
      fill: v >= 8 ? 'var(--flare-500)' : 'var(--ink-650)',
    }
  })
  const benchXTicks = barXTicks.map((t) => ({
    ...t,
    x: (gBe.L + (t.key - 1) * slotBe + slotBe / 2).toFixed(1),
  }))

  return {
    totals: { user: totU, bot: totB, avg: totA },
    latest: { user: user[n - 1], bot: bot[n - 1], avg: avg[n - 1] },
    ranks: { user: rankUser[n - 1], bot: rankBot[n - 1] },
    n,
    // cumulative
    cumYTicks,
    cumXTicks: xTicks(gC, n),
    cumUserPath: linePath(gC, cumU, 0, cumMax),
    cumBotPath: linePath(gC, cumB, 0, cumMax),
    cumAvgPath: linePath(gC, cumA, 0, cumMax),
    cumUserArea: userArea,
    cumUserEnd: endOf(gC, cumU, 0, cumMax, totU.toLocaleString(), -2),
    cumBotEnd: endOf(gC, cumB, 0, cumMax, totB.toLocaleString(), 12),
    cumAvgEnd: endOf(gC, cumA, 0, cumMax, 'avg ' + totA.toLocaleString(), 4),
    cumGapLabel: `+${totU - totB} on the bot · +${totU - totA} on the field`,
    // rank
    rankYTicks,
    rankXTicks: xTicks(gR, n),
    rankUserPath: rankPathOf(rankUser),
    rankBotPath: rankPathOf(rankBot),
    rankUserEnd: rankEnd(rankUser, fmtK(rankUser[n - 1]), -2),
    rankBotEnd: rankEnd(rankBot, fmtK(rankBot[n - 1]), 12),
    // bars
    gwBars,
    avgStepPath,
    barYTicks,
    barXTicks,
    // bench
    benchBars,
    benchXTicks,
    benchTotal: bench.reduce((a, b) => a + b, 0),
  }
}

/** Bundled sample series (GW1–29) — used until /api/history is live. */
export const SAMPLE_SERIES = {
  gw: Array.from({ length: 29 }, (_, i) => i + 1),
  user: [52, 61, 38, 68, 58, 49, 67, 35, 71, 55, 60, 80, 47, 42, 66, 59, 39, 72, 54, 62, 77, 51, 40, 69, 63, 57, 72, 55, 68],
  bot: [48, 55, 42, 65, 60, 52, 63, 44, 56, 58, 57, 65, 52, 46, 62, 61, 45, 62, 57, 60, 62, 54, 47, 65, 60, 59, 68, 58, 63],
  avg: [46, 50, 44, 57, 52, 48, 55, 41, 49, 53, 47, 58, 51, 45, 54, 50, 43, 56, 49, 52, 60, 47, 44, 55, 51, 48, 53, 50, 49],
  rankUser: [3400000, 2100000, 2900000, 1500000, 1600000, 1750000, 1200000, 1900000, 1100000, 1050000, 980000, 610000, 720000, 800000, 640000, 560000, 690000, 430000, 470000, 420000, 290000, 340000, 410000, 330000, 300000, 320000, 270000, 305000, 312000],
  rankBot: [2800000, 1700000, 2400000, 1100000, 900000, 950000, 780000, 1300000, 1150000, 900000, 850000, 520000, 590000, 700000, 610000, 520000, 640000, 420000, 400000, 380000, 310000, 360000, 430000, 350000, 330000, 310000, 280000, 296000, 338000],
  bench: [2, 5, 1, 8, 3, 0, 6, 2, 9, 4, 1, 7, 3, 2, 5, 12, 0, 4, 6, 1, 3, 8, 2, 5, 0, 7, 4, 3, 6],
}

export const FIELD_SIZE = 11_500_000 // ~ total FPL managers, for percentile
