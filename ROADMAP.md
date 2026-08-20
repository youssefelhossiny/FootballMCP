# Football-MCP — Working Roadmap

Living task list for the FPL bot/ML/matching work. We tackle these **one at a time**.
Season context: **2026/27 is live; GW1 deadline was Aug 21 1:30pm UK.** FPL API is authoritative for
live data (players/prices/gameweeks). Understat/FBRef advanced stats lag at season start (auto-fallback
to 2025/26 baseline via `season_config.resolve_stats_season`).

Status legend: ⬜ not started · �work in progress · ✅ done

---

## Architecture decision (applies across tasks)
**Tool-based, not context-push. Claude PULLS signals via MCP tools; a two-agent debate cross-checks
autonomous decisions.**

- ML prediction, injuries/news, and price risk become **MCP tools Claude can call** (e.g.
  `get_ml_prediction`, `get_injury_report`, `get_price_risk`) alongside the existing tools
  (`suggest_transfers`, `evaluate_transfer`, `get_fixtures`, ...). Claude decides *what to fetch* and
  digs deeper as needed — rather than being force-fed one giant briefing blob. (This drops the earlier
  `signal_assembler.py` "push everything" idea.)
- `get_ml_prediction` returns **prediction + rationale (top contributing features) + confidence**, so
  Claude knows how much to trust it (esp. early-season on prior-year baseline data).
- ML is *one advisor*; it does **not** drive the LP optimizer.
- **Autonomous bot uses the SAME Claude tool-loop as the chat** — one brain, one tool set, identical
  behavior. No human present at 2am, so:
- **Two-agent debate for autonomous decisions:** a proposer agent and a challenger/critic agent
  deliberate (each with the tools) and converge on the best decision together, reducing single-model
  bias before the bot commits a transfer/captain.

---

## TASK 1 — Match ALL players across data sources  �️ (STARTING HERE)
**Why it's first / critical:** if a player isn't matched across sources, they have no advanced stats, and
**the AI will not consider them.** Unmatched = invisible. So matching must be maximized.

**Known problems (verified):**
- Promoted teams **Coventry City, Hull City, Ipswich Town** + PL new signings have **no 2025/26 EPL**
  rows, so they don't match the prior-season baseline.
- Scrapers hardcode top flight only: `understat_scraper.py:50` (`league="EPL"`),
  `fbref_scraper.py:56` (`leagues="ENG-Premier League"`).
- Unmatched players are **console-print only** (`enhanced_features.py:467-472`) — no persisted list.
- Latent bug: trailing-space keys in `manual_mappings.json` (e.g. `"Pedro Lomba Neto "` line 94)
  mis-key against the `.strip()`ed FPL name.
- `TEAM_MAPPING` already fixed for 2026/27 IDs (done in prior session).

**Plan:**
1. Parameterize league in both scrapers; add **Championship** prior-season fetch so promoted-team /
   Championship-origin players get real baseline xG + defensive stats. Merge by FPL ID, `DataCache`-cached.
2. Auto-dump `matcher.get_unmatched_players()` to a file (close the console-only gap).
3. Add manual mappings for residual misses; fix the trailing-space bug.
4. `GET /api/data/match-report` — per-source match rate + unmatched list, to track toward ~100%.

**Verify:** run enhancement vs live 2026/27; promoted-team players carry xG/def stats; unmatched file
shrinks; match rate climbs.

---

## TASK 2 — Evaluate the ML model (backtest before wiring)  ⬜
**Why:** decide if the current model is reliable enough to be an advisor, or needs rebuild, BEFORE
investing in wiring. User wants proof vs baselines.

**Known problems (verified):**
- Model = RandomForest trained on a **synthetic, 5×-augmented target**
  (`collect_fpl_training_data.py:52-71,157-171`) → re-learns a formula, not real outcomes.
- Model is **loaded but never used** by the REST API; startup bug at `api_server.py:505`
  (`load_model(str(path))` vs no-arg signature `predict_points.py:79`) → `TypeError` when model present.
- Recommendations actually run on `form × fixture-difficulty` heuristics, not ML.

**Plan:** build read-only `ml_backtest.py` — real `(features@GW N)→actual points@GW N+1)` from
`element-summary` history + FPL-Core-Insights; score current model (MAE/RMSE/R²) vs naive baselines
(form, PPG, last-GW) and the MCP heuristic. **Deliverable: a verdict** → wire as-is (low weight) or
retrain first.

---

## TASK 3 — Expose ML as an MCP tool + wire predictions  ⬜
(Scope depends on Task 2 verdict.)
1. Fix startup crash (`api_server.py:505`).
2. `attach_predicted_points()` in enhancement path — prediction + rationale (from
   `feature_importance.pkl`) + confidence per player, gracefully degrading if model unloaded.
3. Add **`get_ml_prediction` MCP tool** (returns prediction + rationale + confidence) so Claude can pull
   it. Register alongside existing tools in `Server.py` / `anthropic_chat.py` tool set. Do NOT set the LP
   objective = predicted_points.
4. (If backtest says weak) retrain: real target, drop augmentation, add FDR/home-away/rolling-form/
   opponent features, RandomForest→LightGBM (guarded), add RMSE/R²/CV; preserve `.pkl`/scaler/
   `features.txt` contract; keep `prepare_features` in lockstep.
5. Wire dead frontend columns: `WeeklyPicksPage.jsx:121,181,209` reads `predicted_points` from
   `/api/optimal/wildcard` + `/api/optimal/freehit`, **which don't exist** — add both routes.

---

## TASK 4 — Feed the AI player news / injuries (FREE)  ⬜
**Mostly already built.** FPL `bootstrap-static` has `status` (a/i/d/s/u),
`chance_of_playing_next_round`, `news`, `news_added` (hourly). `availability_filter.py` parses it all
but is **instantiated and never called** (`api_server.py:72`).
1. Expose `availability_filter` as a **`get_injury_report` MCP tool** Claude can pull; add
   `GET /api/injuries` for the frontend.
2. Optional free enrichment: cached RSS/scrape fetcher (reuse BeautifulSoup pattern from
   `bot_decision_maker.fetch_livefpl_predictions:215`), TTL via `DataCache`. No paid API.
3. Refresh `anthropic_chat.py:33-38` `ALLOWED_TOPICS` (drop Leicester/Southampton, add Coventry/Hull).

---

## TASK 5 — Autonomous bot: initial squad + auto-submit  ⬜ (GW1 window is a test-bed)
**Verified state:** `bot_decision_maker.py` = read-only recommender (no initial-squad logic).
`bot_manager.py` = dormant, the only write-capable code, uses `fpl` lib (**not installed / not in
requirements**); `set_captain` is a stub. No scheduler anywhere.

**User decisions:** try full auto-submit for GW1 as a test (unlimited edits pre-deadline); if login
unreliable, do GW1 manually and finish after. GW2+: **fully automatic + notify the user on failure.**

1. `build_initial_squad()` in bot path — reuse `EnhancedOptimizer.optimize_squad_with_fixtures`
   (`enhanced_optimization.py:124`) + `AvailabilityFilter.filter_available_players`. Captain via
   extracted `_score_captain_candidate`. Expose `GET /api/bot/initial-squad` (read-only review).
2. Add `fpl` + `apscheduler` to requirements. `FPLBotManager` reads env creds (drop `bot_config.json`).
3. `submit_initial_squad()` + real `set_captain()` via raw authenticated POST (replay `login()`
   session cookies + CSRF/headers). Modes via `BOT_MODE`: `notify` (default) / `dry_run` / `auto`.
4. Test tonight: `dry_run` → `auto` against real team. Fallback: `notify` + manual apply.

---

## TASK 6 — Autonomous scheduling + two-agent debate (GW2+)  ⬜
`bot_scheduler.py` — in-process APScheduler via FastAPI lifespan. Deadline-detection loop
(`get_next_gameweek:185`, `get_gameweek_deadline:192`) schedules per GW:
- **Decision = Claude tool-loop with a two-agent debate:** a proposer and a challenger/critic (each with
  the MCP tools: ML, injuries, price, fixtures, optimizer) deliberate and converge on the transfer +
  captain before committing. Reduces single-model bias.
- **Early run** (post-matches, pre price-update): transfer early only if merit-justified AND price
  timing costly (new `should_execute_early` gate over price flags `evaluate_transfers:894-897,924-928`).
  No captain/chip early.
- **Final run** (~1–2h pre-deadline): latest news/injuries → transfer + captain + lineup → submit.
- Recompute next deadline each GW. Auth failure → **notify user**, downgrade to `notify`.
- Concurrency lock; stateless recovery (FPL API = source of truth); Render doze mitigation
  (uptime pinger or cron service).

---

## Done previously (committed / this work)
- ✅ Season migration to 2026/27: `season_config.py`, `TEAM_MAPPING` fix, auto-detect fallback,
  FBRef stale-cache fallback, frontend labels. (Commit pending — commit first.)
