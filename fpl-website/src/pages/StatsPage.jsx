import { useState, useEffect, useMemo } from 'react'
import { historyAPI, botAPI } from '../api/fplApi'
import { buildChartModel, SAMPLE_SERIES, fmtK, FIELD_SIZE } from '../lib/statsCharts'

const CARD = {
  background: 'var(--surface-2)',
  backgroundImage: 'var(--grad-card)',
  border: '1px solid var(--border-subtle)',
  borderRadius: '16px',
  boxShadow: 'var(--shadow-card)',
}

const CHART_LABEL = {
  fontSize: '11px',
  letterSpacing: '0.12em',
  textTransform: 'uppercase',
  color: 'var(--text-400)',
  fontWeight: 700,
}

function StatsPage() {
  const [series, setSeries] = useState(SAMPLE_SERIES)
  const [live, setLive] = useState(false)
  const [intel, setIntel] = useState(null)

  // Try to load real per-GW history for the user + bot. Falls back to sample.
  useEffect(() => {
    let cancelled = false
    const teamId = localStorage.getItem('fpl_team_id')

    async function load() {
      try {
        const real = await historyAPI.getSeries(teamId)
        if (!cancelled && real && real.gw && real.gw.length > 1) {
          setSeries(real)
          setLive(true)
        }
      } catch {
        /* keep sample series */
      }
      try {
        const decision = await botAPI.getDecision()
        if (!cancelled && decision) setIntel(decision)
      } catch {
        /* intel section falls back to sample below */
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [])

  const m = useMemo(() => buildChartModel(series), [series])
  const n = series.gw.length

  const pctU = ((m.ranks.user / FIELD_SIZE) * 100).toFixed(1)
  const pctB = ((m.ranks.bot / FIELD_SIZE) * 100).toFixed(1)

  const h2h = [
    {
      key: 'you',
      tag: 'You',
      sub: 'your squad',
      name: localStorage.getItem('fpl_team_id') ? 'Your team' : 'Load a team',
      tagBg: 'var(--accent-soft)',
      tagFg: 'var(--pitch-400)',
      accent: 'var(--pitch-500)',
      border: 'rgba(245,158,11,0.35)',
      shadow: 'var(--glow-gold), var(--shadow-card)',
      leading: m.totals.user >= m.totals.bot,
      total: m.totals.user.toLocaleString(),
      totalColor: 'var(--pitch-500)',
      rows: [
        { label: `GW${n} points`, value: String(m.latest.user), color: 'var(--pitch-400)' },
        { label: 'Average / GW', value: (m.totals.user / n).toFixed(1) },
        { label: 'Overall rank', value: fmtK(m.ranks.user) },
        { label: 'Percentile', value: 'Top ' + pctU + '%', color: 'var(--gold-400)' },
      ],
    },
    {
      key: 'bot',
      tag: 'The Bot',
      sub: 'autonomous manager',
      name: 'Machina XI',
      tagBg: 'var(--info-soft)',
      tagFg: 'var(--azure-400)',
      accent: 'var(--azure-500)',
      border: 'var(--border-subtle)',
      shadow: 'var(--shadow-card)',
      leading: m.totals.bot > m.totals.user,
      total: m.totals.bot.toLocaleString(),
      totalColor: 'var(--azure-400)',
      rows: [
        { label: `GW${n} points`, value: String(m.latest.bot), color: 'var(--azure-400)' },
        { label: 'Average / GW', value: (m.totals.bot / n).toFixed(1) },
        { label: 'Overall rank', value: fmtK(m.ranks.bot) },
        { label: 'Percentile', value: 'Top ' + pctB + '%' },
      ],
    },
    {
      key: 'world',
      tag: 'The World',
      sub: fmtK(FIELD_SIZE) + ' managers',
      name: 'The field',
      tagBg: 'rgba(255,255,255,0.06)',
      tagFg: 'var(--text-300)',
      accent: 'var(--ink-500)',
      border: 'var(--border-subtle)',
      shadow: 'var(--shadow-card)',
      leading: false,
      total: m.totals.avg.toLocaleString(),
      totalColor: 'var(--text-200)',
      rows: [
        { label: `GW${n} average`, value: String(m.latest.avg) },
        { label: 'Average / GW', value: (m.totals.avg / n).toFixed(1) },
        { label: 'Median rank', value: fmtK(FIELD_SIZE / 2) },
        { label: 'You beat', value: (100 - +pctU).toFixed(1) + '% of it', color: 'var(--pitch-400)' },
      ],
    },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '26px', animation: 'mdFadeUp .4s var(--ease-out) both' }}>
      {/* Header */}
      <header style={{ display: 'flex', alignItems: 'flex-end', gap: '16px', flexWrap: 'wrap' }}>
        <div style={{ flex: 1, minWidth: '260px' }}>
          <div style={{ fontSize: '11px', letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--text-400)', marginBottom: '5px' }}>
            Season 2026/27 · after GW{n}
          </div>
          <h1 style={{ margin: 0, fontFamily: 'var(--font-display)', fontWeight: 900, fontSize: '38px', letterSpacing: '-0.02em', textTransform: 'uppercase', color: 'var(--text-100)', lineHeight: 1 }}>
            You vs the bot vs the world
          </h1>
        </div>
        <span
          title="Charts run on a bundled sample series until the /api/history endpoint returns live data"
          style={{
            display: 'inline-flex', alignItems: 'center', gap: '7px', padding: '6px 13px', borderRadius: '999px',
            background: live ? 'var(--accent-soft)' : 'var(--gold-soft)',
            border: `1px solid ${live ? 'rgba(16,185,129,0.3)' : 'rgba(245,158,11,0.3)'}`,
            fontSize: '11px', fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase',
            color: live ? 'var(--pitch-400)' : 'var(--gold-400)',
          }}
        >
          {live ? 'Live · /api/history' : 'Sample series · live via /api/history'}
        </span>
      </header>

      {/* Head-to-head */}
      <section style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px' }} className="md-h2h">
        {h2h.map((c) => (
          <div key={c.key} style={{ ...CARD, position: 'relative', border: `1px solid ${c.border}`, boxShadow: c.shadow, padding: '18px 20px 16px', overflow: 'hidden' }}>
            <span style={{ position: 'absolute', left: 0, top: '14px', bottom: '14px', width: '3px', borderRadius: '0 3px 3px 0', background: c.accent }} />
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
              <span style={{ padding: '2px 10px', borderRadius: '999px', background: c.tagBg, color: c.tagFg, fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: '10px', letterSpacing: '0.1em', textTransform: 'uppercase' }}>{c.tag}</span>
              <span style={{ fontSize: '12px', color: 'var(--text-400)' }}>{c.sub}</span>
              {c.leading && (
                <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: '5px', padding: '3px 10px', borderRadius: '999px', background: 'var(--gold-soft)', border: '1px solid rgba(245,158,11,0.35)', color: 'var(--gold-400)', fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: '10px', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                  🏆 Leading
                </span>
              )}
            </div>
            <div style={{ fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: '15px', letterSpacing: '-0.01em', textTransform: 'uppercase', color: 'var(--text-100)', marginBottom: '2px' }}>{c.name}</div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px', marginBottom: '12px' }}>
              <span className="tnum" style={{ fontWeight: 900, fontSize: '40px', letterSpacing: '-0.02em', color: c.totalColor, lineHeight: 1 }}>{c.total}</span>
              <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-400)' }}>PTS</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
              {c.rows.map((r) => (
                <div key={r.label} style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: '8px', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '5px' }}>
                  <span style={{ fontSize: '12px', color: 'var(--text-400)' }}>{r.label}</span>
                  <span className="tnum" style={{ fontWeight: 800, fontSize: '14px', color: r.color || 'var(--text-100)' }}>{r.value}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </section>

      {/* Season tracker */}
      <section style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '12px', flexWrap: 'wrap' }}>
          <h2 style={{ margin: 0, fontFamily: 'var(--font-display)', fontWeight: 900, fontSize: '20px', letterSpacing: '-0.01em', textTransform: 'uppercase', color: 'var(--text-100)' }}>Season tracker</h2>
          <span style={{ fontSize: '12px', color: 'var(--text-400)' }}>week by week, GW1–{n}</span>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '12px' }}>
            <Legend color="var(--pitch-500)" label="You" />
            <Legend color="var(--azure-500)" label="Bot" />
            <Legend color="var(--gold-500)" label="GW average" />
          </div>
        </div>

        {/* Cumulative points */}
        <div style={{ ...CARD, padding: '18px 20px 12px' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px', marginBottom: '6px' }}>
            <span style={CHART_LABEL}>Cumulative points</span>
            <span className="tnum" style={{ fontSize: '12px', color: 'var(--pitch-400)', fontWeight: 700 }}>{m.cumGapLabel}</span>
          </div>
          <svg viewBox="0 0 820 280" style={{ width: '100%', height: 'auto', display: 'block' }}>
            {m.cumYTicks.map((t) => (
              <g key={t.key}>
                <line x1="46" x2="750" y1={t.y} y2={t.y} stroke="rgba(255,255,255,0.06)" strokeWidth="1" />
                <text x="40" y={t.ty} textAnchor="end" fontSize="10" fill="#6C7888" fontFamily="Archivo, sans-serif">{t.label}</text>
              </g>
            ))}
            {m.cumXTicks.map((t) => (
              <text key={t.key} x={t.x} y="272" textAnchor="middle" fontSize="10" fill="#6C7888" fontFamily="Archivo, sans-serif">{t.label}</text>
            ))}
            <path d={m.cumUserArea} fill="rgba(16,185,129,0.08)" />
            <path d={m.cumAvgPath} fill="none" stroke="var(--gold-500)" strokeWidth="1.6" strokeDasharray="5 5" opacity="0.75" />
            <path d={m.cumBotPath} fill="none" stroke="var(--azure-500)" strokeWidth="2.2" strokeLinejoin="round" />
            <path d={m.cumUserPath} fill="none" stroke="var(--pitch-500)" strokeWidth="2.6" strokeLinejoin="round" />
            <circle cx={m.cumUserEnd.x} cy={m.cumUserEnd.y} r="4" fill="var(--pitch-500)" />
            <circle cx={m.cumBotEnd.x} cy={m.cumBotEnd.y} r="4" fill="var(--azure-500)" />
            <text x={m.cumUserEnd.lx} y={m.cumUserEnd.ly} fontSize="12" fontWeight="800" fill="var(--pitch-400)" fontFamily="Archivo, sans-serif">{m.cumUserEnd.label}</text>
            <text x={m.cumBotEnd.lx} y={m.cumBotEnd.ly} fontSize="12" fontWeight="800" fill="var(--azure-400)" fontFamily="Archivo, sans-serif">{m.cumBotEnd.label}</text>
            <text x={m.cumAvgEnd.lx} y={m.cumAvgEnd.ly} fontSize="11" fontWeight="700" fill="var(--gold-400)" fontFamily="Archivo, sans-serif">{m.cumAvgEnd.label}</text>
          </svg>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }} className="md-chart-grid">
          {/* Rank over time */}
          <div style={{ ...CARD, padding: '18px 20px 12px' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px', marginBottom: '6px' }}>
              <span style={CHART_LABEL}>Overall rank</span>
              <span style={{ fontSize: '11px', color: 'var(--text-500)' }}>lower is better — axis inverted</span>
            </div>
            <svg viewBox="0 0 820 230" style={{ width: '100%', height: 'auto', display: 'block' }}>
              {m.rankYTicks.map((t) => (
                <g key={t.key}>
                  <line x1="46" x2="750" y1={t.y} y2={t.y} stroke="rgba(255,255,255,0.06)" strokeWidth="1" />
                  <text x="40" y={t.ty} textAnchor="end" fontSize="10" fill="#6C7888" fontFamily="Archivo, sans-serif">{t.label}</text>
                </g>
              ))}
              {m.rankXTicks.map((t) => (
                <text key={t.key} x={t.x} y="222" textAnchor="middle" fontSize="10" fill="#6C7888" fontFamily="Archivo, sans-serif">{t.label}</text>
              ))}
              <path d={m.rankBotPath} fill="none" stroke="var(--azure-500)" strokeWidth="2" strokeLinejoin="round" />
              <path d={m.rankUserPath} fill="none" stroke="var(--pitch-500)" strokeWidth="2.4" strokeLinejoin="round" />
              <circle cx={m.rankUserEnd.x} cy={m.rankUserEnd.y} r="4" fill="var(--pitch-500)" />
              <circle cx={m.rankBotEnd.x} cy={m.rankBotEnd.y} r="4" fill="var(--azure-500)" />
              <text x={m.rankUserEnd.lx} y={m.rankUserEnd.ly} fontSize="12" fontWeight="800" fill="var(--pitch-400)" fontFamily="Archivo, sans-serif">{m.rankUserEnd.label}</text>
              <text x={m.rankBotEnd.lx} y={m.rankBotEnd.ly} fontSize="12" fontWeight="800" fill="var(--azure-400)" fontFamily="Archivo, sans-serif">{m.rankBotEnd.label}</text>
            </svg>
          </div>

          {/* Per-GW points */}
          <div style={{ ...CARD, padding: '18px 20px 12px' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px', marginBottom: '6px' }}>
              <span style={CHART_LABEL}>Points per gameweek</span>
              <span style={{ fontSize: '11px', color: 'var(--text-500)' }}>green = beat the GW average</span>
            </div>
            <svg viewBox="0 0 820 230" style={{ width: '100%', height: 'auto', display: 'block' }}>
              {m.barYTicks.map((t) => (
                <g key={t.key}>
                  <line x1="46" x2="774" y1={t.y} y2={t.y} stroke="rgba(255,255,255,0.06)" strokeWidth="1" />
                  <text x="40" y={t.ty} textAnchor="end" fontSize="10" fill="#6C7888" fontFamily="Archivo, sans-serif">{t.label}</text>
                </g>
              ))}
              {m.barXTicks.map((t) => (
                <text key={t.key} x={t.x} y="222" textAnchor="middle" fontSize="10" fill="#6C7888" fontFamily="Archivo, sans-serif">{t.label}</text>
              ))}
              {m.gwBars.map((b) => (
                <rect key={b.key} x={b.x} y={b.y} width={b.w} height={b.h} rx="2" fill={b.fill} />
              ))}
              <path d={m.avgStepPath} fill="none" stroke="var(--gold-500)" strokeWidth="1.8" strokeDasharray="4 4" opacity="0.9" />
            </svg>
          </div>
        </div>

        {/* Bench points + data source note */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 380px', gap: '12px' }} className="md-bench-grid">
          <div style={{ ...CARD, padding: '18px 20px 12px' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px', marginBottom: '6px' }}>
              <span style={CHART_LABEL}>Points left on your bench</span>
              <span className="tnum" style={{ fontSize: '12px', color: 'var(--flare-400)', fontWeight: 700 }}>{m.benchTotal} pts this season</span>
            </div>
            <svg viewBox="0 0 820 140" style={{ width: '100%', height: 'auto', display: 'block' }}>
              {m.benchBars.map((b) => (
                <rect key={b.key} x={b.x} y={b.y} width={b.w} height={b.h} rx="2" fill={b.fill} />
              ))}
              {m.benchXTicks.map((t) => (
                <text key={t.key} x={t.x} y="132" textAnchor="middle" fontSize="10" fill="#6C7888" fontFamily="Archivo, sans-serif">{t.label}</text>
              ))}
            </svg>
          </div>
          <div style={{ background: 'var(--surface-1)', border: '1px dashed var(--border-strong)', borderRadius: '16px', padding: '18px 20px' }}>
            <div style={{ ...CHART_LABEL, marginBottom: '10px' }}>Where the data plugs in</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '12px', lineHeight: 1.5 }}>
              <div style={{ display: 'flex', gap: '8px', alignItems: 'baseline' }}>
                <span style={{ padding: '1px 8px', borderRadius: '999px', background: live ? 'var(--accent-soft)' : 'var(--gold-soft)', color: live ? 'var(--pitch-400)' : 'var(--gold-400)', fontSize: '10px', fontWeight: 800, letterSpacing: '0.05em' }}>{live ? 'LIVE' : 'PENDING'}</span>
                <code style={{ color: 'var(--text-200)', fontSize: '11px' }}>/api/history/&#123;team_id&#125;</code>
              </div>
              <p style={{ margin: 0, color: 'var(--text-400)' }}>
                Proxies FPL <code style={{ fontSize: '11px' }}>entry/&#123;id&#125;/history/</code> — per-GW points, total, overall &amp; percentile rank, bench points, for your ID and the bot's. GW average comes from <code style={{ fontSize: '11px' }}>bootstrap-static events[].average_entry_score</code>. Charts fall back to a sample series until then.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Bot intelligence */}
      <BotIntelligence intel={intel} />
    </div>
  )
}

function Legend({ color, label }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '11px', fontWeight: 600, color: 'var(--text-300)' }}>
      <span style={{ width: '14px', height: '3px', borderRadius: '2px', background: color }} />
      {label}
    </span>
  )
}

function BotIntelligence({ intel }) {
  // Prefer live bot decision data; otherwise show the design's sample calls.
  const recs = intel?.transfers?.length
    ? intel.transfers.map((t, i) => ({
        key: i,
        out: t.out || t.player_out,
        in: t.in || t.player_in,
        priceFlag: t.price_rising ? 'Price rising' : false,
        reasons: t.reasons || (t.reason ? [t.reason] : []),
      }))
    : [
        { key: 1, out: 'Watkins', in: 'Gyökeres', priceFlag: 'Price rising', reasons: ['Watkins flagged at 50% — 0.44 xG/90 over the last 6', 'Gyökeres in league-best form: 0.71 xG/90', 'Frees £0.4m; fits inside 1 free transfer'] },
        { key: 2, out: 'Kudus', in: 'Rogers', priceFlag: false, reasons: ['Kudus dropping with TOT blank in GW31', 'Rogers has 5 attacking returns in 6'] },
      ]

  const chip = intel?.chip_strategy || { call: 'Hold all chips', score: 38, reasons: ['No double gameweek until GW34 — Triple Captain waits', 'Bench Boost value is low with two flagged starters'] }
  const captain = intel?.captain || { name: 'Haaland', why: 'SUN (H) · 1.02 xG/90' }
  const vice = intel?.vice_captain || { name: 'Salah', why: 'BRE (A) · 8.2 form' }

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: '12px', flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0, fontFamily: 'var(--font-display)', fontWeight: 900, fontSize: '20px', letterSpacing: '-0.01em', textTransform: 'uppercase', color: 'var(--text-100)' }}>Bot intelligence</h2>
        <span style={{ fontSize: '12px', color: 'var(--text-400)' }}>this week's calls, with the reasoning</span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }} className="md-intel-grid">
        {/* Transfer recommendations */}
        <div style={{ ...CARD, padding: '16px 18px' }}>
          <div style={{ ...CHART_LABEL, marginBottom: '10px' }}>Recommended transfers</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {recs.map((rec) => (
              <div key={rec.key} style={{ background: 'var(--ink-850)', border: '1px solid var(--border-subtle)', borderRadius: '12px', padding: '11px 14px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px', flexWrap: 'wrap' }}>
                  <span style={{ color: 'var(--flare-400)', fontWeight: 700, fontSize: '13px' }}>{rec.out}</span>
                  <span style={{ color: 'var(--text-500)' }}>→</span>
                  <span style={{ color: 'var(--pitch-400)', fontWeight: 700, fontSize: '13px' }}>{rec.in}</span>
                  {rec.priceFlag && (
                    <span style={{ padding: '2px 9px', borderRadius: '999px', background: 'var(--gold-soft)', color: 'var(--gold-400)', fontSize: '10px', fontWeight: 800, letterSpacing: '0.04em', textTransform: 'uppercase' }}>{rec.priceFlag}</span>
                  )}
                </div>
                {rec.reasons.map((r, i) => (
                  <div key={i} style={{ fontSize: '12px', color: 'var(--text-300)', lineHeight: 1.5 }}>• {r}</div>
                ))}
              </div>
            ))}
          </div>
        </div>

        {/* Chip + captaincy */}
        <div style={{ ...CARD, padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div>
            <div style={{ ...CHART_LABEL, marginBottom: '8px' }}>Chip strategy</div>
            <div style={{ background: 'var(--ink-850)', border: '1px solid var(--border-subtle)', borderRadius: '12px', padding: '11px 14px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '5px' }}>
                <span style={{ fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: '13px', letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--text-100)' }}>{chip.call || chip.type}</span>
                <span className="tnum" style={{ fontSize: '11px', color: 'var(--text-500)' }}>score {chip.score}/100</span>
              </div>
              {(chip.reasons || []).map((r, i) => (
                <div key={i} style={{ fontSize: '12px', color: 'var(--text-300)', lineHeight: 1.5 }}>• {r}</div>
              ))}
            </div>
          </div>
          <div>
            <div style={{ ...CHART_LABEL, marginBottom: '8px' }}>Armband</div>
            <div style={{ display: 'flex', gap: '8px' }}>
              <div style={{ flex: 1, background: 'var(--gold-soft)', border: '1px solid rgba(245,158,11,0.35)', borderRadius: '12px', padding: '10px 14px' }}>
                <div style={{ fontSize: '10px', letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--gold-400)', fontWeight: 700 }}>Captain</div>
                <div style={{ fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: '16px', textTransform: 'uppercase', color: 'var(--text-100)' }}>{captain.name}</div>
                <div className="tnum" style={{ fontSize: '11px', color: 'var(--text-400)' }}>{captain.why}</div>
              </div>
              <div style={{ flex: 1, background: 'var(--ink-850)', border: '1px solid var(--border-default)', borderRadius: '12px', padding: '10px 14px' }}>
                <div style={{ fontSize: '10px', letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-400)', fontWeight: 700 }}>Vice</div>
                <div style={{ fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: '16px', textTransform: 'uppercase', color: 'var(--text-100)' }}>{vice.name}</div>
                <div className="tnum" style={{ fontSize: '11px', color: 'var(--text-400)' }}>{vice.why}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

export default StatsPage
