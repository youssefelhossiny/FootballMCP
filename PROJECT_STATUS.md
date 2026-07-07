# Football-MCP — Project Status

> Consolidated status doc. Replaces the old per-phase notes
> (`NEXT_PHASE.md`, `PHASE_3_COMPLETE.md`, `FINAL_RESULTS.md`,
> `TEST_PHASE4_FEATURES.md`). Last updated: 2026-07-06.

## What this is

A full-stack AI system for Fantasy Premier League (FPL) decision-making.
Football intelligence is exposed as **MCP (Model Context Protocol) tools**
that an LLM (Claude) can call, and the same logic is mirrored as a REST API
behind a React web app.

Two surfaces, one backend:

- **MCP servers** — used by any MCP client (Claude Desktop, etc.).
- **Web app** — FastAPI backend + React 19 frontend (chat, team viewer,
  formation display, transfer suggestions, autonomous "bot team").

## Architecture

```
Football-MCP/
├── fpl-optimizer/            # FPL MCP server + FastAPI backend
│   ├── Server.py             # MCP server (~12 tools)
│   ├── api_server.py         # FastAPI REST API for the website
│   ├── enhanced_features.py  # Merges FPL + Understat + FBRef into 58 features
│   ├── predict_points.py     # Random Forest points predictor
│   ├── enhanced_optimization.py / optimization.py  # squad optimization (PuLP)
│   ├── chips_strategy.py     # chip timing advice
│   ├── bot_decision_maker.py # autonomous gameweek bot (wired into api_server)
│   ├── anthropic_chat.py     # Claude tool-calling orchestration
│   ├── auth.py               # JWT auth for the chat endpoint
│   ├── data_sources/         # understat_scraper, fbref_scraper, data_cache, availability_filter
│   └── player_mapping/       # fuzzy name matching across data sources
├── soccer-stats/             # Soccer Stats MCP server (live scores, standings, match prediction)
├── fpl-website/              # React 19 + Vite 7 + Tailwind 4 frontend
└── models/                   # Trained ML models (.pkl) + feature lists
```

## ML pipeline — current state

**Model:** Random Forest, trained on **58 engineered features** merged from
three data sources.

| Source | Features | Examples |
|---|---|---|
| Official FPL API | 17 | form, total_points, minutes, goals, assists, ICT, price, ownership |
| Understat | 20 | xG, xA, npxG, xGChain, xGBuildup, per-90 variants, over/underperformance |
| FBRef | 21 | tackles, interceptions, blocks, clearances, def_contributions_per_90, progressive passes/carries, SCA, GCA |

**Data-source match rate:** Understat ~57%, FBRef ~55% of all players
(≈100% for active players with 90+ minutes). Unmatched players fall back to
position-based defaults.

**Top feature by importance:** `form` (~78%), then `xG_per_90`, `npxG_per_90`,
`xGChain_per_90`, and `def_contributions_per_90`.

**2025/26 rules note:** FPL now awards 2 pts for defensive contributions
(10 actions for DEF, 12 for MID/FWD). `def_contributions_per_90`,
`def_contribution_prob`, and `expected_def_points` model this.

## MCP tools (fpl-optimizer)

`get_all_players`, `get_player_details`, `get_top_performers`,
`optimize_squad_lp`, `evaluate_transfer`, `suggest_transfers`,
`suggest_captain`, `suggest_chips_strategy`, plus fixtures/team viewing.
All predictions use the full 58-feature model.

## Running locally

```bash
# One-shot: backend (:8000) + frontend (:3000)
./start_website.sh
```

Backend only: `python -m uvicorn api_server:app --reload` (from `fpl-optimizer/`).
Frontend only: `npm run dev` (from `fpl-website/`).

> **Note:** `fpl-website/vite.config.js` proxies `/api` to the hosted Render
> backend by default. To use the local backend instead, point that proxy
> `target` at `http://localhost:8000`. The hosted backend is on Render's free
> tier and cold-starts (~15s) after idle.

## Manual test prompts

Quick smoke sequence against the MCP server / chat:

1. `Top 10 defenders by defensive contributions per 90`
2. `Show me Van Dijk's full stats`
3. `Evaluate transfer: Gabriel out, Saliba in`
4. `Top 10 midfielders by SCA per 90`
5. `Build optimal squad with 100m budget`
6. `Show all Manchester City players`

Expected: defensive stats appear for DEF/MID, xG/xA for attackers,
optimization uses all 58 features, unmatched players don't crash (defaults).

## Roadmap (not yet done)

- Fixture-aware ML model (opponent FDR, home/away as training features)
- Multi-gameweek transfer planning (3–5 GW horizon, transfer chains)
- Rotation-risk scoring; differential finder; price-change predictor
- Performance: cache FPL API responses, sub-1s optimization

## Data sources

- **FPL API** — no key, no rate limit, real-time.
- **Understat** — xG/xA (scraped, 6h cache).
- **FBRef** (via `soccerdata`) — defensive/progressive stats (scraped, cached).
- **Football-Data.org** — used by `soccer-stats/` (free key required).
