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

## TASK 1 — Match ALL players across data sources  ✅ (done — see outcome below)
**Why it mattered:** if a player isn't matched across sources, they have no advanced stats, and
**the AI will not consider them.** Unmatched = invisible.

**Starting baseline (measured, prior session):** match rate **63.6%** — 218/599 FPL players unmatched
against the Understat baseline. 95 of those were exactly the 3 promoted teams (Coventry/Hull/Ipswich,
structural — zero EPL Understat/FBRef rows exist for them); ~123 were a mix of backup/youth/transferred
players with no current-season data, plus a handful of genuine name-spelling mismatches.

**What shipped this session:**
1. **Championship promoted-team fallback.** `understatapi` has no Championship coverage at all (EPL/La
   Liga/Bundesliga/Serie A/Ligue 1/RFPL only) — that gap for Coventry/Hull/Ipswich's xG/xA is permanent
   and not fixable. FBRef *does* carry the Championship, but `soccerdata`'s bundled league list doesn't
   include it — fixed by registering `ENG-Championship` → FBRef's `"EFL Championship"` via a custom
   `league_dict.json` written at import time (`fbref_scraper.py: _ensure_championship_league_registered`,
   `CHAMPIONSHIP_LEAGUE`). `enhanced_features.py`'s `PROMOTED_TEAM_IDS = {7, 11, 12}` triggers a
   Championship-FBRef retry pass for any promoted-team player still unmatched after the normal EPL pass,
   so those players get real prior-season defensive/progressive stats (still no xG/xA — Understat gap
   is unfixable). Verified with a standalone fetch: 791 Championship players returned, including
   Coventry City/Hull City/Ipswich Town squads with team names matching `TEAM_MAPPING` exactly (no
   team-name-mapping changes needed). The full `collect_enhanced_data` pipeline reached this stage and
   started the Championship fetch successfully in a live end-to-end run, but that particular run's
   Championship fetch stalled on FBRef's anti-bot page (same class of issue as the GCA stall below) and
   was killed before printing final merged stats — so the promoted-team fallback is verified at the
   component level, not confirmed to complete inside one full uninterrupted pipeline run this session.
2. **FBRef library regression fixed.** Independently discovered mid-task: `soccerdata` (1.9.0/1.9.1, both
   checked) silently dropped `stat_type` support for `"defense"`, `"passing"`, `"possession"`, and
   `"goal_shot_creation"` from `read_player_season_stats()` — only `standard/keeper/shooting/
   playing_time/misc` remain whitelisted, even though FBRef still serves those pages at the same URLs.
   This meant **all** FBRef-sourced stats (tackles, interceptions, blocks, progressive passing, SCA/GCA)
   were crashing on every run, silently masked by falling back to a stale Jan-2026 cache. Fixed by
   `_fetch_extended_player_stats()` in `fbref_scraper.py`, which replicates the library's internal
   fetch-and-parse chain (including its `_concat` column-normalization step, required for
   `set_index(["league","season","team","player"])` to resolve) against the still-live URLs. Each of
   the 4 stat types fetches independently and degrades to an empty DataFrame on failure rather than
   blocking the rest — load-bearing in practice, since FBRef intermittently serves a consent-banner
   interstitial that doesn't clear even after retries (observed repeatedly on the goal/shot-creation
   page specifically; defense/passing/possession fetched reliably in every test run). **Residual risk:**
   this is scraping code layered outside the maintained library — more fragile to future FBRef site
   changes than a proper library fix would be, and SCA/GCA in particular may come back empty on a given
   run if FBRef's anti-bot page won't clear.
3. **Manual name-matching, done by hand per the user's steer** (not scripted spelling-inference — a
   script wasn't finding real fixes reliably, so this went team-by-team: FPL's unmatched list vs each
   team's Understat roster, side by side). Result: of 210 Understat-unmatched players, only **2** were
   genuine spelling mismatches — `"Alysson Edward Franco da Rocha dos Santos"` → `"Alysson Edward"` and
   `"Trey Nyoni"` → `"Treymaurice Nyoni"` — added to `manual_mappings.json`. Also fixed a latent bug:
   `manual_mappings.json` had a trailing-space key (`"Pedro Lomba Neto "`, shadowed by a correct
   duplicate elsewhere in the file — removed the bad one) that silently failed to match because FPL
   names are `.strip()`ed before lookup; `name_matcher.py`'s `load_manual_mappings` now strips all
   keys/values on load so this class of bug can't recur.
4. **Cross-team-transfer matching bug found and fixed** (via the user's request for the actual
   unmatched list + links, which prompted verifying a sample against the live sites). Root cause: FPL
   assigns a player to their *current* (2026/27) club; Understat/FBRef's cached row is still tagged
   with the player's *2025/26* club if that source hasn't recrawled since the transfer. `match_player`'s
   team filter narrowed the candidate pool to the player's new club — which is non-empty (the new
   club's other real players), so the old "fall back to full pool only when the filter yields zero
   candidates" logic never triggered, and the player's row (sitting under their old club) was never
   found. Fixed in `name_matcher.py`: `_match_within()` now retries against the **full unmatched pool**
   at a high-confidence threshold (≥95) whenever the team-scoped search fails, logged as
   `cross_team_transfer` in the match stats. Verified against 4 known 2026/27 transfers (Tonali:
   Newcastle→Spurs, Tielemans: Villa→Utd, Wilson: West Ham→Brentford, Robertson: Liverpool→Spurs) —
   all 4 now resolve correctly. Recovered **20 players**, all confirmed real transfers.
5. **Unmatched-players report persisted.** `enhanced_features.py`'s `_write_unmatched_report` dumps
   full Understat + FBRef unmatched lists (id/name/team/is_promoted_team) to
   `cache/unmatched_players.json` on every collection run — previously console-print only
   (`enhanced_features.py:467-472`), capped at 10 lines, impossible to inspect after the fact.
6. **`GET /api/data/match-report`** added to `api_server.py` — per-source match rate + unmatched list
   (optionally filtered by FPL team id), backed by the same persisted report.
7. **FBRef season-resolution bug found and fixed, then verified end-to-end** (user spotted FBRef's live
   site already has a real "2026-27 Arsenal FC" squad page — proof FBRef publishes ahead of Understat,
   which the pipeline wasn't accounting for). Root cause: `collect_enhanced_data`/`get_enhanced_player`
   resolved Understat's season via `resolve_stats_season`, then reused *that same* resolved year for
   FBRef's fetch too (`fbref_season = to_fbref(season)`) — so even though FBRef might already have
   2026/27 data, the pipeline never tried it, always falling back to whatever season Understat landed
   on (2025/26). Fixed: `collect_enhanced_data` and `get_enhanced_player` in `enhanced_features.py` now
   call `resolve_stats_season` **independently** for FBRef, instead of inheriting Understat's resolved
   year. **Verified with a full live end-to-end run** (ad blocker disabled, per user): FBRef's 2026/27
   `standard` stat page still hits the same anti-bot consent interstitial every attempt (not
   ad-blocker-related — confirmed failing identically with the blocker off), so `resolve_stats_season`
   correctly falls back to 2025/26, which fetches cleanly (551 EPL players + 791 Championship players).
   **The season-independence fix itself is confirmed correct and live**: it's the reason FBRef's match
   rate is now measured at 78.8% instead of being silently capped by Understat's season choice.
   Separately confirmed why Kepa vs. Meslier looked inconsistent: Kepa is on Arsenal's 2025/26 FBRef
   roster (loan spell) so he matches fine; Meslier joined Arsenal only for 2026/27, so he doesn't exist
   in *any* 2025/26 data under any name-matching logic — his page is real but lives only on the
   currently-unscrapable 2026/27 URL. This was never a matching-logic problem, just a season-coverage
   gap that will close once FBRef's 2026/27 pages become reliably scrapable (unrelated to ad blockers;
   likely ties to FBRef's anti-bot rules being more aggressive on freshly-published, low-traffic pages
   early in a season).

**Final measured outcome:** Understat match rate **64.94% → 68.61%** (389 → 411 / 599 matched, all on
2025/26 baseline data), the last jump (65.28%→68.61%) coming entirely from the cross-team-transfer fix.
**FBRef match rate: 78.8%** (472/599, also 2025/26 baseline) — confirmed via a full live
`collect_enhanced_data` run including the promoted-team Championship fallback (791 Championship players
fetched, 89 promoted-team players retried against them).
Combined, only **124 players are unmatched by *both* sources** (down from the 188-player worksheet that
undercounted FBRef coverage before this fix): **97 established-club players** + **27 promoted-team
players**. Of the 97: a handful (Rashford, Ronald Araujo) played abroad last season so neither EPL
source captured them despite now being in the EPL; some (Meslier) are 2026/27-only signings not yet
scrapable per the season-coverage gap above; the rest are genuine backups/academy/minimal-minutes
players with no row under any threshold. `unmatched_players_report.md` (repo root) and
`cache/unmatched_players.json` are both regenerated with these live numbers.

**On the `soccerdata` library specifically** (user asked whether an update would fix it): confirmed via
GitHub research — the restricted `stat_type` whitelist is present on `master` too (not yet released
and fixed upstream), there's no CHANGELOG/issue explaining the removal, and no alternate method exists
in the library for these stat types. This isn't a "just needs updating" situation; the hand-rolled
`_fetch_extended_player_stats` fetch is the correct fix, not a stopgap for a fix that's coming.

---

## TASK 2 — Evaluate the ML model (backtest before wiring)  ✅ done — verdict: retrain before wiring
**Why:** decide if the current model is reliable enough to be an advisor, or needs rebuild, BEFORE
investing in wiring. User wants proof vs baselines.

**Known problems (verified):**
- Model = RandomForest trained on a **synthetic, 5×-augmented target**
  (`collect_fpl_training_data.py:52-71,157-171`) → confirmed circular: the "target" is computed from
  the same snapshot's own `form`/xG via a formula (`(form + expected_pts) / 2`), then augmentation
  multiplies BOTH the `form` input feature and the target by the same scalar (0.8-1.2) — the model can
  trivially re-derive its own label formula without ever seeing a real outcome during training.
- Model is **loaded but never used** by the REST API; startup bug at `api_server.py:706-708`
  (`load_model(str(path))` vs no-arg signature `predict_points.py:79`) → `TypeError` when model present.
  Confirmed the no-arg `load_model()` itself works fine in isolation — the bug is purely the call site.
- Recommendations actually run on `FPLOptimizer._calculate_player_gameweek_score` (`predict_points.py:507`)
  — `form × 2` plus a flat price adjustment (±2/-0.5), not ML, not even fixture-difficulty despite the
  docstring's claim (fixture data is accepted as a param but never used in the formula).

**Real historical data used (no synthetic/proxy data for ground truth or FPL/Understat features):**
FPL's own API only exposes per-GW granularity for the *current* season (empty right now — 2026/27 GW1
deadline is tomorrow, zero matches played yet), so 2025/26 (last completed season) was used as the real
backtest season, sourced from:
- **vaastav/Fantasy-Premier-League** (`data/2025-26/gws/merged_gw.csv`) — real per-GW FPL stats +
  actual `total_points` ground truth, confirmed all 38 gameweeks populated, 841 players.
- **Understat**, real per-match xG/xA via `understatapi`'s per-player match endpoint (confirmed it
  exposes real per-match data with dates, not just season aggregates) — aggregated as cumulative
  "as of GW N" for each backtest row, exactly matching how these features work live. 481/841 players
  matched (57.19%) using a simplified name-only match (no numeric FPL team id available at this stage,
  so the team-scoped disambiguation from Task 1 was unavailable — lower than Task 1's ~68% because
  this pool includes far more fringe/bench players across a full season, not just current squads).
- **FBRef**: checked directly whether per-match defensive/progressive/creation data exists —
  `read_player_match_stats` only exposes `summary`/`keeper` tables per match; inspected a live match
  page's raw HTML (including HTML comments) and confirmed tackles/blocks/clearances/progressive
  passes/SCA/GCA genuinely don't exist at per-match granularity anywhere on FBRef, not a scraping gap.
  Used 2025/26 **season-end** per-90 rates as a constant per-player proxy across all gameweeks instead
  (489/841 matched, 58.15%) — the one real limitation in this backtest's fidelity, introducing mild
  look-ahead bias for these ~24 features specifically (a player's defensive stats at GW10 aren't
  identical to their final-season numbers).

**Built:** `ml_backtest.py` — builds one row per (player, gameweek N) for GW 6-37 (needs prior history
for rolling form; stops one GW before season end), features "as of GW N" (real cumulative FPL +
Understat stats, static FBRef proxy), target = actual `total_points` at GW N+1. Scored the real trained
model (`models/points_model.pkl`, loaded via the correct no-arg call) against naive baselines and the
real current heuristic formula (not a re-invented one). **24,500 rows** — a large, real sample.

**Results (full sample, all player-gameweeks including unused bench players):**

| Method | MAE | RMSE | R² |
|---|---|---|---|
| Trained RandomForest model | 1.0203 | 2.1295 | 0.1749 |
| Naive form (trailing 30-day avg) | 1.0367 | 2.1035 | **0.1949** |
| Naive last-GW points | 1.1231 | 2.5546 | -0.1874 |
| Naive PPG | 1.9669 | 3.0323 | -0.6731 |
| **Current heuristic (what's actually live today)** | **2.8551** | 3.8230 | **-1.6593** |

**Restricted to players who actually played minutes** (15,070 rows — the players a real transfer/
captain decision is about, not benched no-shows both the model and form trivially predict as 0):

| Method | MAE | R² |
|---|---|---|
| Trained RandomForest model | **1.5342** | **0.0378** |
| Naive form | 1.6758 | 0.0588 |
| Current heuristic | 3.5569 | -1.8366 |

Sanity-checked: predictions correlate with actual outcomes at a similar strength to the naive form
baseline (r≈0.47 model vs r≈0.50 form) — not degenerate/broken, just not adding much beyond form alone
on this label. The model's predictions are also visibly compressed (mean 0.71, max 5.79) vs. real
outcomes (mean 1.14, max 23) — consistent with OpenFPL's published finding (researched this session)
that FPL prediction models universally struggle hardest on big hauls; this model is on the more
conservative/compressed end of that same known weakness, not an outlier failure.

**Verdict:**
1. **The current heuristic in production is measurably worse than doing nothing** (negative R² — worse
   than just predicting the average every time). This is the most actionable finding: whatever ships
   next for Task 3 should not be *this* formula, model or no model.
2. **The trained model is not obviously better than naive form** on the full sample, but **does show a
   real, modest edge (~8% lower MAE) once restricted to players who actually play** — the population a
   real decision is about. It is not a broken model; it's a mediocre one, roughly performing at the
   lower end of realistic published benchmarks (researched this session: MAE ~0.8-1.3 typical for
   comparable published FPL models, e.g. OpenFPL, a well-benchmarked open-source reference architecturally
   similar to this project's FPL+Understat+FBRef+RF approach).
3. **Root cause is confirmed to be the synthetic training label**, not the modeling approach or feature
   set — this project's architecture is already reasonably aligned with the strongest researched
   open-source reference. **Recommendation: retrain (Task 3 item 4) using this backtest's real historical
   pipeline as the real training-label source** (real `total_points@GW N+1`, not the circular formula in
   `collect_fpl_training_data.py`), rather than adopting a different tool or paying for an external
   prediction API (researched and ruled out this session — no free/cheap API exists with programmatic
   access; the best commercial tools gate output behind manual-use paywalls).
4. **Do not wire the current heuristic or the current model as the primary driver** of `suggest_transfers`
   /`evaluate_transfer` as-is. Once retrained per Task 3, wire the ML prediction as one advisory signal
   Claude can pull (`get_ml_prediction`, already planned in Task 3) rather than the sole driver — matches
   the existing architecture decision at the top of this file ("ML is one advisor; it does not drive the
   LP optimizer").

**Reusable artifacts for Task 3's retrain:** `cache/backtest/merged_gw_2025_26.csv` (real per-GW FPL
data), `cache/backtest/understat_matches_2025.json` (real per-match Understat history, 10,342 rows
across 471 players), `cache/backtest/backtest_rows.csv` (built feature rows), `cache/backtest/
backtest_scored.csv` (scored predictions, for further error analysis e.g. by position).

> ### ⚠️ CORRECTION — the numbers in the two tables above are INVALID
> A follow-up audit (see Task 3 below) found **22 of the 61 features were constant** in that backtest's
> feature matrix, because `cache/fbref_eng_premier_league_2025_2026.json` is hollow (0/551 rows nonzero
> for tackles/blocks/clearances/progressive/sca/gca/touches — fallout from this session's FBRef scrape
> failures silently zero-filling and caching). The model was scored on a crippled input vector.
>
> Two further methodology errors made the verdict itself unsafe:
> - **MAE is the wrong headline metric here.** The target is 63.8% zeros and always-predicting-0 scores
>   MAE 1.1505 — so "model 1.02 vs form 1.04" was mostly measuring which predictor shrinks harder
>   toward zero, not which is more useful.
> - **The population was wrong.** Restricting to *regulars* (>45 avg min — the only players a transfer
>   decision concerns) collapses ranking quality from spearman 0.72 → 0.26 and doubles MAE. The strong
>   all-rows numbers were dominated by the trivial "benched player scores 0" call.
>
> Corrected conclusion: conclusions #1 (live heuristic is bad) and #3 (synthetic label is the root cause)
> **stand and were confirmed**. Conclusion #2 ("model shows a real ~8% edge") does **not** stand — on
> ranking among regulars the old model (0.257) was *behind* naive form (0.265). See Task 3 for the
> re-measured, leak-free numbers.

---

## TASK 3 — Expose ML as an MCP tool + wire predictions  ✅ DONE (all 5 items)
1. **Fix startup crash — ✅.** There were actually *two* bugs on those three lines: `load_model(str(path))`
   passed an argument to a no-arg method, **and** the path pointed at `fpl-optimizer/models/` while the
   models live at repo-root `models/`. The path check silently failed first, so the TypeError never even
   fired and **v1 had never once loaded** — confirmed by `grep`: there were zero `predictor.` call sites
   left in `api_server.py`. Startup now loads v2 and prints its architecture, or warns clearly if absent.
2. **Predictions in the serving path — ✅** via `ml_predict_v2.predict_points()`, returning
   `predicted_points`, `play_probability`, `points_if_plays`, `confidence` and `basis` per player, and
   degrading gracefully (returns `{}`) when no model is present.
3. **`get_ml_prediction` MCP tool — ✅** registered (17 tools total; verified every tool in the schema
   has a dispatch branch). Two modes: named players (fetches real per-GW history for the accurate
   prediction) or a ranked list by position. The LP objective was **not** touched — ML remains one
   advisory signal, per this file's architecture decision.
4. **Retrain — ✅ DONE, see below.**
5. **Frontend routes — ✅.** `WeeklyPicksPage.jsx` had been calling `/api/optimal/wildcard` and
   `/api/optimal/freehit` against routes that never existed (the whole page was dead). Both now exist,
   built on `EnhancedOptimizer.optimize_squad_with_fixtures` + `AvailabilityFilter` (never builds a
   squad around unavailable players), returning the exact contract the JSX consumes. Two easy-to-miss
   details matched deliberately: `player.price` and `total_cost` are returned in **tenths** (the JSX
   divides each by 10), and `player.position` is the **numeric** `element_type` (`getPositionShort()`
   maps 1-4 and renders `?` for a string). `vite.config.js` already proxies `/api`, so no frontend
   change was needed.

   **A real pre-season problem found and fixed while wiring this.** The optimizer scores *every*
   strategy off `player['form']` (`enhanced_optimization._calculate_fixture_scores`), but FPL resets
   form to `0.0` pre-season — verified **0 of 599** players had nonzero form. Every score therefore
   floored to `max(score, 0.01)`, so the "optimal" squad was arbitrary **and identical for both
   strategies** (confirmed: the first implementation returned the same 15 players and 22.8 predicted
   points for wildcard and free hit). Fixed by seeding `form` with the v2 model's predicted points when
   FPL's form is uniformly zero — in-season this is a no-op and real form is used untouched. Result:
   the two strategies now diverge properly (9/15 squad overlap), predicted points ~40 instead of 22.8,
   and free hit correctly picks easier single-GW fixtures (avg FDR 2.73 vs the wildcard's 3.07 over 5
   GWs). The UI's Form column deliberately reports FPL's *real* form, not the seeded value, so nothing
   displayed is fabricated.

### Serving the v2 contract (`ml_predict_v2.py`)
v2 is not a drop-in for v1 (v1: one RandomForest + scaler, 61 season-total features; v2: two models,
no scaler, 32 rolling-window features), so it got its own serving module rather than being forced into
`FPLPointsPredictor`. Three things that would otherwise silently corrupt predictions are guarded:
- **log1p inversion.** The regressor predicts `log1p(points)`; serving applies `expm1`. The loader
  *hard-fails* if the bundle's `regressor_target` isn't `"log1p"`, rather than quietly under-predicting.
- **Train/serve skew.** `FEATURES` is read from the saved bundle and validated against this module's
  own construction at load time, so the two cannot drift apart unnoticed.
- **The rolling-window problem.** v2's features are means over *prior gameweeks*, which
  `bootstrap-static` does not carry. In-season, per-GW history comes from `element-summary/{id}/`
  (one request per player, concurrency-capped at 8, failures degrade rather than 500). **Pre-season —
  i.e. right now, GW1 hasn't kicked off, so `element-summary` history is empty for everyone** — it
  falls back to per-game rates from season totals, which cannot represent recent form and is therefore
  reported as `confidence: "low"` with an explicit caveat in the tool's own output.

**Verified end-to-end:** startup loads v2; `/api/health` reports model status; `/api/predictions`
(with `limit`/`position`/`team`/`with_history`) returns 200; the MCP tool returns sensible output in
both modes. Both serving paths were tested for real — the history path was exercised against actual
2025/26 data (train through GW30, predict GW31): **spearman 0.419 on regulars, top-3 picks averaged
7.00 actual points vs a 2.93 field mean.** The cold-start path ranks 599/599 current players with
plausible ordering (B.Fernandes, Haaland, Saka, Palmer at the top).

**Note on v1:** the `predictor` global in `api_server.py` is retained only for the co-located
`FPLOptimizer`/LP helpers and is annotated as serving no predictions. `Server.py` (MCP) still
instantiates it and would need the same treatment if it should also serve v2.

### Item 4 — Retrain (done): `ml_train.py` → `models/points_model_v2.pkl`

**Bug fixed first (root cause of Task 2's invalid backtest).** `fbref_scraper.fetch_player_stats`'s
`_fetch_or_empty` degraded a failed stat-type fetch to an empty DataFrame; `_process_stats` then
zero-filled the affected columns and the result was cached as if valid — **the cache could not
distinguish "genuinely zero" from "fetch failed"**. Fixed: failures are now tracked, the affected
column names are printed explicitly, and every cached row carries `_incomplete_stat_types` so
consumers can refuse to trust those fields. Added `_STAT_TYPE_COLUMNS` mapping stat-type → affected
output columns (including that `def_contributions` is corrupted if *either* defense or passing fails,
since it's derived as tackles+interceptions+blocks+clearances). The existing hollow 2025/26 cache was
retro-stamped rather than silently reused.

**Every design choice below was measured, not assumed** (rolling-origin validation, regulars only):

| question | measurement | decision |
|---|---|---|
| How many seasons? | 1→2: **+0.031** spearman; 2→3: +0.005; 3→4: **−0.001** (plateau) | **3 seasons** (2023-24…2025-26) |
| Recompute old labels for DefCon? | 2023-24 and 2024-25 have **no** defensive-action columns at all | impossible — pool anyway, still wins 4/4 folds |
| Keep xG/xA? | 0.3259 with vs **0.3280** without | **dropped** (also absent pre-2022-23) |
| Keep DefCon features? | 0.3098 with vs 0.3174 without | **dropped** |
| Rolling windows? | adding the 1-game window: 0.3174 → **0.3280** | **1/3/5/10** |
| Model architecture? | hurdle 2.130 MAE vs direct 2.182 | **hurdle** (P(plays) × E[pts∣plays]) |

The **counterintuitive headline: rolling points+minutes alone scores 0.3148**, and every extra feature
block was flat or *worse*. The winning model is deliberately **32 features, not 61**. The single
biggest win was not more data or a fancier model — it was an **encoding fix**: cumulative
season-to-date rates barely move week-to-week so they cannot explain week-to-week variance; re-encoded
as 3-game rolling means, xG signal rose 0.043→0.150 and xA 0.030→0.156 (4–5×).

**Final results** — rolling-origin (expanding-window) validation, 4 folds, **regulars only**
(>45 avg min), never training on the future:

| arm | MAE | spearman | haul-AUC |
|---|---|---|---|
| **hurdle + log1p (shipped)** | **2.0330** | **0.3326** | 0.6443 |
| direct single-stage | 2.1817 | 0.3290 | **0.6531** |
| naive form (l5) | 2.4250 | 0.2357 | 0.6039 |
| naive last-GW | 2.7334 | 0.2655 | 0.5804 |
| *old 61-feature RF* | *2.209* | *0.257* | — |

vs naive form: **+41% ranking (0.333 vs 0.236)** and **−16% MAE**. Beats form in **4/4 folds**.
Honest caveat: hurdle-vs-direct ranking is **within noise** — hurdle wins folds 1–2, direct wins folds
3–4. Hurdle shipped on the consistent MAE edge, the decision-quality result below, and a cleaner
interpretation (it exposes P(plays), directly useful for rotation risk).

### Does the ranking gain convert into actual POINTS? (yes — this is the decision that matters)
Correlation is not decision quality, so this was measured directly: each gameweek, pick the top-N
players by each method (regulars only), then score the **actual** points those picks went on to score.
Mean over 16 held-out gameweeks:

| method | top-1 | top-3 | top-5 | top-10 |
|---|---|---|---|---|
| **hurdle** | **6.56** | **5.52** | **4.76** | **4.56** |
| direct | 5.25 | 4.38 | 4.04 | 4.19 |
| naive form (l5) | 4.06 | 4.00 | 4.12 | 3.68 |
| naive last-GW | 4.38 | 3.40 | 3.30 | 3.16 |
| random | 2.94 | 2.67 | 2.95 | 2.81 |

**The top pick averages +2.50 points more than naive form**, and the model beats form at every N.
Consistency on top-3: hurdle better in **13/16 gameweeks (81%)**, mean **+1.52 pts/pick**, median
+2.17, worst week −2.33, best +4.67. Statistically significant: **Wilcoxon p=0.014, paired t-test
p=0.005**. This also breaks the hurdle-vs-direct tie decisively (6.56 vs 5.25 on top-1).

### Improvement experiments (what was tried, what was kept)
| idea | result | kept? |
|---|---|---|
| log1p target on stage 2 | MAE 2.132 → **2.036**, top-3 5.52 → 5.65 | ✅ **shipped** |
| opponent rolling strength + home flag | spearman 0.3319 → 0.3366, top-3 5.52 → 5.56 | ❌ marginal; doesn't stack with log1p (combined 0.3346 / 5.52) |
| position-specific models (one per GK/DEF/MID/FWD) | spearman **0.302**, top-3 **4.94** — clearly worse | ❌ fragments training data |
| absolute_error loss | top-3 collapses to 3.92 | ❌ |
| upweight hauls 3× | spearman flat, top-3 5.10 (worse) | ❌ |
| poisson loss | errors — target has negative values (FPL allows negative points) | ❌ n/a |

Deliberately left out rather than added for noise: the opponent/home features were a real but tiny
gain that vanished once combined with log1p, so v2 stays at 32 features.

**Metric discipline (why the numbers look "worse" than Task 2's):** MAE alone is misleading on a
63.8%-zero target — always-predicting-0 scores 1.1505. Headline metrics are therefore reported on
**regulars** with **Spearman + haul-AUC** alongside MAE. Task 2's flattering all-rows numbers were
mostly the trivial "benched player scores 0" call.

**Dropped baseline:** FPL's own `xP` is unusable in this dataset — zero for *every* row in GW11–20 and
mostly zero after (5,099/29,757 nonzero); the upstream collector stopped capturing it. Reporting
against it would have been a meaningless number.

**Known limit (not a defect):** predictions compress (max ~6.4 vs actual max 18-23). Squared-error
regression on a heavy-tailed target under-predicts hauls; matches the published finding that no FPL
model — commercial or academic — predicts hauls well (reference MAE ~4.3 on haul rows alone).

**Artifacts:** `ml_train.py` (self-documenting; re-runs end-to-end in ~1 min),
`models/points_model_v2.pkl` (bundle: classifier + regressor + feature list + threshold),
`models/features_v2.txt` (32), `models/backtest_report_v2.json` (per-fold metrics),
`cache/backtest/seasons/*.csv` (7 seasons cached). Round-trip verified: reloads and predicts, scoring
spearman 0.347 on a held-out GW≥35 regulars slice.

**v2 is intentionally NOT yet wired into the API** — items 1-3 above. It has a different contract from
v1 (two models + no scaler vs single model + scaler), so `predict_points.FPLPointsPredictor` needs a
v2-aware load path; wiring it without that would break the existing `.pkl`/scaler/`features.txt`
contract that `prepare_features` depends on.

---

## TASK 4 — Feed the AI player news / injuries (FREE)  ✅ (core items done)
**Mostly already built.** FPL `bootstrap-static` has `status` (a/i/d/s/u),
`chance_of_playing_next_round`, `news`, `news_added` (hourly). `availability_filter.py` parses it all
but was **instantiated and never called** (`api_server.py:72`).

**What shipped:**
1. **`get_injury_report` MCP tool** added (`FPL_TOOLS` schema + `execute_tool` dispatch +
   `tool_get_injury_report` in `api_server.py`) — categorizes players into injured/suspended/doubtful/
   available via the existing `AvailabilityFilter.get_injury_report`, with an optional team-name filter.
   Verified live: correctly surfaced 51 injured/3 suspended players from bootstrap-static, e.g. Timber
   and Saliba (Arsenal, both 0% chance) and Bruno G. (Arsenal, 75% chance/doubtful).
2. **`GET /api/injuries`** added for the frontend (optional `?team=<fpl_team_id>` filter), returning the
   same categorized report enriched with team names. Verified via `TestClient` — 200 OK, live data.
3. **`ALLOWED_TOPICS` refreshed** in `anthropic_chat.py` for 2026/27: dropped relegated Leicester/
   Southampton, added promoted-team names actually missing (Coventry, Hull) plus two more that were
   also absent (Leeds, Sunderland) — cross-checked against the live 20-team `bootstrap-static` list to
   confirm exact team-name coverage.

4. **Fast third-party team news added** (`data_sources/team_news_scraper.py`) — user flagged that FPL's
   own `news`/`status` fields lag real announcements (FPL's editorial team updates manually, sometimes a
   day+ behind). Researched candidates: Knocks and Bans, FFScout, Premier Injuries. Premier Injuries has
   the deepest medical detail (run by a recognized injury analyst) but sits behind Cloudflare's Managed
   Challenge — no API/RSS, ~5-15s per fetch even with a headless-browser bypass, and this project has no
   scheduler yet to run that off the request path (Render free tier sleeps when idle — the "doze
   mitigation" problem is still open, see Task 6). Not worth the latency for a live chat tool call, so
   skipped in favor of two plain-HTTP sources with no bot-protection at all:
   - **Knocks and Bans** (`knocksandbans.com`) — per-player injury/suspension status, type, expected
     return, with a per-entry last-updated timestamp where available.
   - **FFScout team news** (`fantasyfootballscout.co.uk/team-news`) — per-team predicted starting XI +
     Out/Doubts/Banned lists + a per-team last-updated timestamp. This is data FPL doesn't have at all
     (who's actually expected to start vs. just "available") — closer to what "is X likely to play" needs
     than injury status alone.

   Both are plain server-rendered HTML (confirmed via direct fetch — no JS rendering, no Cloudflare),
   scraped with the same `aiohttp`+`BeautifulSoup` pattern as `bot_decision_maker.fetch_livefpl_predictions`.
   Wired in as `get_team_news` MCP tool + `GET /api/team-news`, cached 15 min (`team_news_cache`, separate
   short-TTL `DataCache` instance — these sources update close to real-time, so the default 6h TTL used
   elsewhere would defeat the purpose). **Verified live:** cold fetch takes **~1.0s** (both sources
   fetched concurrently via `asyncio.gather`), cache hits are near-instant; correctly surfaced Arsenal's
   predicted XI, Out (Saliba, Timber), and Doubts (Bruno G. 75%) matching what `get_injury_report` showed
   separately, plus lineup detail `get_injury_report` doesn't have.

   **Known data-quality caveat** (not a scraper bug): Knocks and Bans' own entries are sometimes stale —
   e.g. Rodri showed status "doubtful (25% chance)" while also carrying an "out" record with a return
   date in the past (04/05/26, before today 2026-08-20) elsewhere in the same dataset. Treat it as a
   second opinion alongside FPL's own data and FFScout's team news, not a sole source of truth.

**Not done (optional, deferred):** Premier Injuries integration (see above — needs a scheduler to be
worth the Cloudflare-bypass cost; revisit once Task 6's autonomous-bot scheduler exists anyway, since the
background-refresh infra would already be there for other reasons).

---

## TASK 5 — Autonomous bot: initial squad + auto-submit  ✅ (auth path replaced; see below)

### ⚠️ The original plan was built on a dead endpoint
Item 3 ("replay `login()` session cookies") **cannot work**, and neither can anything else based on
email/password. Verified directly:
- **`users.premierleague.com` no longer resolves at all** (no DNS). That is the host `bot_manager.
  login()` POSTs credentials to. `fantasy.` and `account.premierleague.com` both resolve fine.
- FPL moved to **PingFederate/PingOne SSO**. The live OIDC discovery document at
  `account.premierleague.com/as/.well-known/openid-configuration` advertises
  `authorization_code, implicit, client_credentials, refresh_token, device_code, ciba, token-exchange`
  — **no `password` grant**, so credentials can never be exchanged for a token. Repairing `login()`
  is not possible; the mechanism it depends on is gone.

What *does* work, verified live:
- The `refresh_token` grant is real — `POST /as/token` with a deliberately invalid token returns a
  clean OAuth `invalid_grant`, proving the endpoint accepts that grant for FPL's public client id.
- The write endpoints are alive and only lack a session: `POST /api/transfers/` and
  `POST /api/my-team/{id}/` both return DRF `403 "Authentication credentials were not provided."`
  (not 404, not a bot-block). No Cloudflare on the FPL API host (`server: openresty`).
- **No documented endpoint exists for submitting an initial 15-player squad.** Transfers and
  lineup/captain are documented; first-squad creation is not — so that step stays manual.

### What shipped
1. **`GET /api/bot/initial-squad`** — a full reviewable opening squad, read-only. Reuses
   `build_optimal_squad` (EnhancedOptimizer + `AvailabilityFilter` + the v2 model) and adds what you
   need to enter it by hand: bench order (backup GK forced to bench slot 1, then outfield by
   descending prediction), a vice-captain (best predicted starter who isn't captain), and a
   per-pick justification (prediction, start probability, fixture, differential flag). Verified:
   legal 3-5-2, exactly £100.0m, 3-per-club respected, captain B.Fernandes / vice Cherki.
2. **`fpl_auth.py`** — authenticated writes via a **browser-extracted refresh token**, so the
   password is never stored or seen by this project. Exchanges for short-lived access tokens and
   persists the rotated refresh token (FPL rotates on every use — losing it breaks the chain).
   Implements `set_lineup` (captain/vice/order via `/api/my-team/{id}/`) and `make_transfers`
   (validate with `confirmed=false`, then commit — so a rejected transfer never half-applies).
3. **Safety gating** via `FPL_BOT_MODE`, defaulting to the safest value:
   `notify` (default, never writes) / `dry_run` (authenticates + validates, never commits) /
   `auto` (writes). Verified: `notify` returns the intended change without writing; malformed
   payloads are rejected locally (wrong pick count, not exactly one captain); an invalid token fails
   with an actionable message even in `auto`. `GET /api/bot/auth-status` reports mode + whether
   writes are possible without attempting one.
4. **Removed a dangerous lie.** `bot_manager.set_captain(confirm=True)` previously set
   `confirmed: True` and logged success **without issuing any request** — it reported the captain as
   set when nothing had changed. It now refuses and points at `fpl_auth.set_lineup`.
5. `apscheduler` added to requirements. **`fpl` deliberately NOT added** — it is dead code aimed at a
   host that no longer exists; a comment in requirements.txt records why.

**Residual risk (honest):** the refresh-token flow depends on an undocumented (though publicly
visible) client id, Cloudflare bot management sits on the auth host, and FPL re-enabled optional 2FA
for 2025/26 — any of these can break it. Refresh tokens rotate and can be revoked, so expect
occasional manual re-copying from the browser. Treat unattended auto-submit as a best-effort
convenience layer, never as a guarantee that a deadline was met.

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
