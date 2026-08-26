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

## TASK 6 — Autonomous scheduling + AI decision layer  🚧 (agent + scheduler done; debate not started)

### The gap this task actually had to close (found by reading the code, not the plan)
There were **two brains in this repo and they shared nothing**:
- **Chat** (`anthropic_chat.query_anthropic:217`) — a real Claude tool-loop, 18 tools, ML + news.
- **Bot** (`bot_decision_maker.make_decision:1090`) — hand-written arithmetic, and **grep confirms it
  contains zero references to `ml_predict_v2`, `points_model`, `search_player_news`, or
  `get_team_news`**. Concretely: captain = `(form * 3 + fixture_score) * position_weight` (`:994`),
  replacement = `max(form * 2 + (5 - avg_difficulty) * 1.5)` with a hard `form < 3.0` cutoff (`:943`),
  `lineup_changes=[]` with a literal `# TODO: Implement lineup optimization` (`:1105`), and
  `expected_points_gain` = a raw form delta labelled as points.

So the v2 model (+1.52 pts/pick, Wilcoxon p=0.014) and `search_player_news` (the Doku catch) ran in the
chat and in `/api/bot/initial-squad`, but were **invisible to the recurring gameweek decision** — the one
thing that would actually run autonomously. That was a bigger gap than the Doku issue in the handoff, and
the same class of bug: a verified component built, never wired to its consumer.

**Fix chosen: don't write a new agent — point the autonomous path at the chat's tool-loop.**
`api_server.execute_tool:2525` is a plain async function with no FastAPI request coupling, so it is
callable headlessly as-is. The deterministic code becomes the *tools*; the model becomes the *decider*.
That is what the Architecture decision at the top of this file always said; the bot was the one place it
never got applied.

### What shipped
1. **`bot_agent.py`** — autonomous entry point over the existing 18 tools.
   - **Structured output, not prose.** The decision comes back through a `submit_decision` *tool call*
     validated against a JSON schema, so the API retries on a malformed reply. Prose into a write path
     is how you get a wrong captain. `AgentDecision.to_lineup_picks()` emits exactly the 15
     `{element, position, is_captain, is_vice_captain}` dicts `fpl_auth.set_lineup` wants.
   - **Fails loudly.** Every failure raises `BotAgentError`: API error, truncation, prose-without-a-
     decision, iteration cap. Deliberate contrast with `query_anthropic`'s
     `except Exception: return (None, [], [])` — in the chat that degrades to a rule-based fallback
     (which is what hid the retired model for months); at 2am it would make a broken run
     indistinguishable from "no changes needed".
   - **A failing tool is surfaced, not blanked.** One tool raising returns
     `"TOOL ERROR (name): ... Do not treat this as 'no issues found'"` so the model routes around it
     instead of silently concluding nothing was wrong.
   - `make_transfer` is filtered out of the agent's tool set — it only mutates the frontend's
     theoretical squad, so an agent calling it would believe it had acted when nothing happened.
   - Prompt encodes the known-issues list as rules: auto-substitution means **starting** a doubtful
     player is free upside (never bench to "protect"), bench order best-player-first, buying vs
     starting are different bars, live news beats FPL's `chance_of_playing`.
   - Semantic validation the schema can't express: captain ≠ vice, 15 unique lineup ids, no
     buy-and-sell-same-player, no double-sell, chip dropped on an early run.
2. **`bot_scheduler.py`** — deadline detection from FPL's own `bootstrap-static` events (no hardcoded
   calendar to rot), early/final run computation, concurrency lock, and run history in
   `cache/bot_runs.json`. A **failed** run is recorded `ok: False` and therefore **not** treated as done,
   so a retry picks it up.
3. **Endpoints**: `GET /api/bot/agent-decision` (inspect; 503 on agent failure so a caller can tell it
   apart from a valid empty decision), `POST /api/bot/run` (JWT-authed, auto-detects what's due — this is
   the production path), `GET /api/bot/schedule` (deadline, planned runs, due-now, recent runs, bot_mode).
4. **`.github/workflows/fpl-bot.yml`** — external cron every 30 min. See the Render finding below.
5. **`fpl_auth.get_squad_selling_prices`** — a transfer payload needs the **selling** price, which is not
   `now_cost`: FPL returns only half of a price rise (rounded down), so 7.0→7.3 sells at 7.1. Before this
   nothing computed it; `selling_price` appeared only in a docstring. Only the authenticated
   `/api/my-team/{id}/` exposes it.
6. **Prompt caching on the agent loop** — added after measuring the first run's cost. An agentic loop
   resends the whole history every turn, so input grows per iteration: measured **6.3k tokens on call 1,
   27.6k on call 9, ~145k total across 9 calls**, with input ≈ **80% of the run's cost**. Two breakpoints
   (last tool schema + system prompt, ~5.1k identical tokens per call) plus a **rolling breakpoint on the
   newest tool-result block** convert the append-only prefix into 0.1x reads. Only the newest history
   breakpoint is kept — the request cap is 4, and older prefixes stay cached by prefix match anyway.
   `AgentDecision.usage` now reports input/output/cache_read/cache_write so a silent caching regression is
   visible rather than assumed.
   **Verified against the live API** (4-iteration run): `cache_read` = 26,789 of 38,019 input-side tokens
   (**70% served from cache**), 36% cheaper on that short run; the share rises with iteration count as more
   history accumulates.
   **Cost correction:** an earlier estimate in this session used $15/$75 per Mtok. Claude Opus 5 is
   **$5/$25**, so the 2026-08-21 run was ≈**$0.91**, not ~$2. `search_player_news` runs server-side web
   searches billed separately, which is worth remembering when reading a bill against a single run.
   The chat is unaffected by the growth curve — 1-3 tool calls never climbs past the first iterations.
7. **Low-confidence decisions are not submitted.** The agent self-reports confidence and the prompt says
   it gates the write; `submit=true` with `confidence: "low"` returns `submit_skipped`.

### Verified live (2026-08-21, GW1 unplayed)
Full run against real tools with a synthetic Arsenal-heavy squad — GW1 had no picks yet
(`/entry/{id}/event/1/picks/` 404s for everyone pre-deadline), so a real-squad run is blocked by the
calendar, not the code. **16 tool calls across 9 model iterations, 11 distinct tools**, and it produced
things the deterministic path structurally cannot:
- Caught **two 0%-flagged players (J.Timber, Saliba) in the starting XI** and a **second GK started**
  alongside Raya — three slots guaranteed to return ~0. Rebuilt to a legal 3-5-2.
- Recorded **5 availability overrides** where live news contradicted FPL's flag.
- Chose **Rice over Saka as captain on minutes certainty** despite Saka having the higher ML score
  (3.94 vs 3.65) — explicitly reasoning that a captain who plays 25 minutes costs double.
- Applied the auto-sub rule correctly *and* argued a deliberate exception (benching G.Jesus, who no
  source could even place in the squad, while keeping him first sub to retain the upside).
- **Noticed `evaluate_transfer` returned "WAIT" for the wrong reason** — it compares raw season stats and
  doesn't know Timber is 0%.
- Declined to fabricate an element id it couldn't verify, and rolled the free transfer instead.
Scheduler verified against live FPL data (GW1 deadline 2026-08-21T17:30Z → final run 15:30Z), plus unit
coverage of midweek/tight-turnaround ordering, double-run skip, force, and failure recording.

### Render free tier — the doze problem is NOT solved by a pinger; scheduler defaults OFF
An in-process scheduler **cannot** be made reliable on Render free: the service is spun down when idle,
and a spun-down process isn't late — it doesn't exist to fire. A self-pinger burns the same free instance
hours it's trying to protect and Render still reserves the right to spin down. So `BOT_SCHEDULER_ENABLED`
defaults to **false**, specifically so deploying this doesn't create the illusion of a bot watching the
deadline while the host sleeps. The supported path is the external cron hitting `POST /api/bot/run`, which
wakes the service by the act of calling it. The in-process scheduler remains for paid/always-on or local.

### Also found (pre-existing, now surfaced)
**`BOT_TEAM_ID`'s default team does not exist.** `GET /api/entry/12777515/` returns **404** (verified
live), and `BOT_TEAM_ID` is set in no `.env` — so `/api/bot/decision`, `/api/bot/team` and the new agent
endpoints have all been failing with a confusing "Team not found". Added `require_bot_team_id()`, which
returns an actionable 503 naming the env var instead. **Set `BOT_TEAM_ID` in `.env` before the bot can
run for real.**

### Self-review pass (same session) — 4 real bugs found and fixed
Reviewed the day's wiring rather than trusting it. All four were verified against the live API before
fixing, and all are in code written *this session*:
1. **Wrong gameweek on every write (worst of the four).** `run_agent_and_maybe_submit` derived the target
   as `get_user_team()["gameweek"] + 1`. That field comes from FPL's `is_current` event, which is **empty
   before a season's first deadline** and falls back to `1` — so the agent was told GW**2** while the
   deadline actually being played was GW**1** (verified live 2026-08-21: `is_current: []`, `is_next: [1]`).
   `make_transfers` posts that id as `event`, so transfers would have targeted the wrong gameweek — not
   cosmetic. Now taken from `bot_scheduler.get_gameweek_schedule()`'s `next_gameweek`, the same source the
   scheduler uses, and it **refuses to run** rather than guess when FPL reports no upcoming gameweek.
2. **Wildcard/freehit silently dropped.** Those chips activate through the **transfer** endpoint, but the
   submit path only called `make_transfers` when `decision.transfers` was non-empty, and `set_lineup` only
   forwards `bboost`/`3xc`. So a wildcard decided with an empty transfer list was discarded while the run
   still reported success. Now raises an explicit `FPLAuthError` instead of pretending the chip was played.
3. **Duplicate `BotAgentError` import** inside one function (harmless, removed) — and the gameweek fix
   needed it hoisted to the top of the function anyway, since it's now raised earlier.
4. **`purchase_price` semantics undocumented**, which is what made it look wrong on review: for the
   *incoming* player `now_cost` genuinely is correct (it's what you pay); only the *outgoing* side needs
   the half-rise `selling_price`. Comment added so the next reader doesn't re-litigate it.

Also confirmed correct and left alone: chip enum matches FPL's real names (`wildcard`/`freehit`/`bboost`/
`3xc`, checked against `bootstrap-static`); early runs skip `set_lineup` entirely, so the placeholder
captain the early prompt asks for can never reach FPL; `submit_decision` is excluded from `tools_used`;
`make_transfer` stays filtered out of the agent's tool set.

### Fixture-horizon audit — the agent was planning from the wrong gameweek
Checked whether the bot actually reasons about *upcoming* gameweeks, not just which GW it writes to.
Two separate problems, both real:

**1. Every forward-planning tool anchored on `is_current` (off-by-one, mid-season).**
`tool_get_fixtures`, `tool_analyze_fixtures` and `tool_chip_strategy` all built their window from
`next((e['id'] for e in events if e.get('is_current')), 1)`. Mid-season that points at the gameweek whose
matches are *being played* — so a requested 5-gameweek window returned GW6-GW10 while the bot was deciding
GW7: the first slot is a gameweek nobody can transfer for, and the real forward view is only 4 deep.
Pre-season the flag is absent entirely and the `, 1` fallback **hides the bug**, which is why the
2026-08-21 run looked fine — GW1 is the one case where the fallback happens to equal the target.
Fixed with a shared `planning_gameweek(events)` helper (`api_server.py`), which prefers `is_next`, then the
first unfinished event, then `is_current`, then 1. Verified across four scenarios: pre-season → GW1,
mid-season (GW6 current / GW7 next) → GW7, no-`is_next` → GW7, season-over → GW38 (degrades to the last
gameweek rather than snapping back to GW1). Live check confirms `get_fixtures` now returns GW1-GW5 with
Arsenal's real run (COV H, AVL A, CHE H, SUN A, BHA A).
The other 11 `is_current` uses were left alone deliberately — they serve the chat and "current" is
genuinely correct there. Only the three forward-planning tools were wrong.

**2. The prompt never stated a planning horizon.** It said "check fixtures" but never how far ahead, and
never distinguished which decisions are horizon-sensitive. Added an explicit section: captain/lineup are
**this gameweek only** (they reset weekly — never captain for next week's fixture), transfers are judged
over **3-5 gameweeks** (a transfer persists, so one good fixture followed by four hard ones is a bad buy),
chips over the whole horizon. Also flagged the things that only surface when looking forward — blanks
(no fixture = zero), doubles, fixture swings right after the target GW — plus an explicit warning that
`get_ml_prediction` covers **one** gameweek and must never stand in for a fixture run. The task prompt now
leads with `[TARGET GAMEWEEK] N — ... The fixture tools list GWN first`, so the horizon is unambiguous.

### GW1 opening squad — built 2026-08-21, by hand-driving the tools (NOT the agent)
Done deliberately without `bot_agent`: it is built to *adjust an existing squad* (transfers/captain/
lineup) and `submit_decision` has no way to express an initial 15. Rather than bolt on a second agent
path, the tools were driven directly — LP builder proposes, judgment layer reviews. Same division of
labour the architecture calls for.

**What the deterministic builder produced** (`/api/bot/initial-squad`): legal 3-5-2, exactly £100.0m,
40.2 predicted points, C B.Fernandes / VC Cherki.

**What the judgment layer changed, and why.** The builder put **two 75%-flagged players in the XI**
(`START_MIN_CHANCE=1` allows it by design). Live news search on both:
- **Doku (MCI, FPL 75%)** — withdrawn at half-time of the Community Shield with a re-aggravated calf;
  Belgian press (Nieuwsblad) suggests **several weeks** out. This is the exact case in the handoff notes,
  still live and still wrong in FPL's data.
- **Šeško (MUN, FPL 75%)** — back in training but **zero pre-season minutes**; press consensus is a
  fitness exclusion for GW1 with a ~Aug 30 return.
Both replaced. Note the replacement shortlist itself needed filtering: **Bruno G. (75% thigh),
Kroupi.Jr (0% foot) and Welbeck (75%)** all ranked well on ML but are flagged — ML ranks, it does not
screen. Also MCI/MUN were already at the 3-club cap, so same-club swaps (Foden, Marmoush) were illegal.
- Doku → **Rogers (CHE, £7.5m)** — price-neutral, ML 3.71, unflagged; CHE run FUL(A) BHA(H) ARS(A) HUL(H).
- Šeško → **Woltemade (NEW, £6.0m)** — frees £1.0m, ML 3.21, unflagged, and NEW's GW5 HUL(2H) is soft.
Final: **£99.0m, £1.0m in the bank**, 2/5/5/3, max 3 per club (LIV) — legality verified in code.

**Deliberately NOT auto-submitted.** FPL publishes no endpoint for initial-squad creation (Task 5
finding), so this is entered by hand. That is a platform gap, not an oversight.

### Context for the NEXT session — RE-DERIVE, do not inherit
Everything above was true at ~04:00 UTC on 2026-08-21, **before the GW1 deadline (17:30 UTC)**. Treat it
as a starting hypothesis to test, not a conclusion:
1. **Re-run the availability checks from scratch.** The news above is press-tier, not manager-tier. Friday/
   Saturday pressers supersede it and may well upgrade Doku or Šeško. Re-check both, plus every flagged
   player, before acting.
2. **Prices and form will have moved.** The ML numbers above are pre-GW1 with zero real form data; after
   GW1 the model has actual per-GW outcomes and its ranking should be expected to change materially.
   Re-run `/api/predictions` rather than reusing these figures.
3. **The fixture-horizon fix is still UNVERIFIED in production.** Pre-season `is_current` is empty, so the
   old buggy `, 1` fallback and the new `planning_gameweek()` both return GW1 — the bug is invisible today.
   **GW2 (deadline 2026-08-28T17:30Z) is the first run that can actually prove it.** Check that fixture
   windows start at the *upcoming* gameweek, not the one in progress.
4. **`BOT_TEAM_ID` still needs setting** once the team exists, or every squad-resolving endpoint 503s (by
   design now, with an actionable message).
5. **Writes remain impossible until a refresh token is present**; `FPL_BOT_MODE` defaults to `notify`.
6. Whether the swaps above were *right* is measurable after GW1 — compare Rogers/Woltemade's actual returns
   against Doku/Šeško's. Do that rather than assuming the judgment layer helped.

## TASK 8 — Real FPL strategy in squad construction  ✅ (built and tested 2026-08-21)

### Why the old squad builder was not doing strategy at all
Traced after the user asked what the actual thought process behind the GW1 squad was. Three defects,
each verified against the live API, all in `enhanced_optimization.py`:
1. **The objective was `form`, and `form` is 0.0 for all 600 players pre-season** (measured:
   `nonzero form = 0`). `_calculate_fixture_scores` does `base_score = float(player['form'])` then
   `max(score, 0.01)` — so **every player scored exactly 0.01 and the objective was FLAT**. The LP was
   not optimising; it was returning an arbitrary feasible squad. That is the state it was in for the
   opening squad, the one that matters most.
2. **The ML model was never in the objective** — `grep -c "ml_predict\|predicted_points"` on that file
   returns **0**. The `predicted_points` shown per pick were computed *after* selection, as display
   annotations. The verified +1.52 pts/pick model had zero influence on who was picked.
3. **The bench was unscored while money was force-spent into it.** The objective summed only
   `starting[...]`, so bench players were worth nothing, yet `target_spend=budget` imposes
   `total_cost >= 100.0`. The unscored bench was the only place the forced money could go — which is
   exactly how the first squad ended up with Steele (1% to start), Elvedi (10%), Mheuka (3%), Thomas (2%)
   on the bench: **unusable cover**, since a substitute who never plays cannot cover anything.

### The strategy, researched not invented
Sources: [RotoWire — FPL GW1 2026/27 opening-squad guide](https://www.rotowire.com/soccer/article/best-fpl-gameweek-1-tips-2026-27-how-to-build-the-perfect-opening-squad-127299)
and [Fantasy Football Fix — Best FPL Rotation Strategies 2026/27](https://www.fantasyfootballfix.com/blog-index/best-fpl-rotation-strategies-2026-27/).
Encoded principles:
- **Spend on the pitch, not the bench** — "little value in spending an extra £1.0m on a bench player if
  that money could upgrade someone you expect to start every Gameweek." So bench spend is **capped**,
  never funded by a forced total spend.
- **The bench must still PLAY** — the first sub especially. Cheap is necessary but not sufficient;
  `BENCH_MIN_START_PROB` makes playing probability a hard filter, which is what turns bench fodder into
  real rotation cover for an injury or a brutal fixture.
- **Rotation pairs with COMPLEMENTARY fixtures** — two budget defenders (£4.0-5.0m) from different clubs
  whose good fixtures fall in *different* gameweeks, so one always has a favourable game. Scored by
  window coverage minus overlap (two teams with identical good weeks are the same bet twice, not a pair).
- **Clean sheets need BOTH a soft run and a real defence** — `clean_sheet_outlook` multiplies fixture
  softness by FPL's own `strength_defence_home/away` ratings (normalised to league average 1.0), with a
  small home-share bump. A good defender with a hard fixture is unlikely to keep a clean sheet, which is
  precisely when his rotation partner should start.
- **Minutes certainty above all**, and **keep flexibility** (`min_bank` supports holding cash).

### Value and underlying numbers (user addition)
`value_and_underlying()` reads the Understat fields `enhanced_features.py` was already collecting and
**nothing in the selection path was using** — collecting xG then picking on `form` left the most
predictive data on the floor. Points-per-£m plus an xG verdict, deliberately signed the right way:
**overperformance is a REGRESSION WARNING, not a buy signal** (the banked goals do not repeat unless the
xG supports them), while **underperformance on high xG+xA/90 is the genuine bargain**. Live output is
informative rather than decorative: flags Semenyo (+4.2 above xG), Gibbs-White (+3.3) and Cunha (+2.9)
as regression risks — Gibbs-White **while the LP has him in the XI** — and Haaland (-1.8 on 1.04
xG+xA/90), Saka (-1.7) and B.Fernandes (-2.9 on 0.87) as underperforming bargains.

### What shipped
- **`fpl_strategy.py`** — fixture runs, clean-sheet outlook, rotation-pair finder, value/xG analysis, and
  a role-tagged shortlist (premium/core/value/rotation/bench).
- **`EnhancedOptimizer.optimize_from_shortlist`** — objective is **v2 predicted points**; the bench is
  scored at `BENCH_WEIGHT = 0.25` (real via rotation and auto-subs, but not worth paying up for); bench
  spend is **capped**; budget is **not** force-spent; `min_bank` supported.
- **`GET /api/strategy/squad`** — two-stage: strategy shortlists, LP assembles. **Refuses (503) if the v2
  model is unavailable** rather than silently reverting to the flat `form` objective.

### Measured before/after (same £100m, same GW1)
| | old builder | strategy builder |
|---|---|---|
| objective | `form` → flat 0.01 for all | v2 predicted points |
| bench | Steele 1%, Elvedi 10%, Mheuka 3%, Thomas 2% | Dubravka 92%, Kostoulas 93%, Hume 92%, Davies 88% |
| spend split | £100.0m forced, bench unconstrained | XI £81.5m + bench £18.0m, £0.5m banked |
Rotation pairs found (Diop IPS / O'Nien SUN, £8.0m, covers GW1-5), top clean-sheet teams ranked
(LIV 0.588, LEE/TOT/MCI 0.561), 8 value picks, 8 xG bargains, 8 regression risks.

### Bug found and fixed during testing (worth recording)
First run returned **`Infeasible`**. Cause: ranking the shortlist by predicted points alone **drops the
entire £4.0m tier** — a £4.0m defender never outscores a £6.0m one — so the cheapest possible bench cost
came to *exactly* `BENCH_SPEND_CAP` (£18.0m), leaving zero slack. Real £4.0m starters do exist (Dubravka
0.93, Davies 0.88, Diop 0.87); they were being cut before the LP ever saw them. Fixed by guaranteeing a
cheapest-playing retention block per position, and by setting `value_bar` to each position's **actual**
cheapest tier (verified: **no MID or FWD exists below £5.0m** in 2026/27, so a £4.5m bar left those
positions with no budget role at all). Min bench cost is now £16.0m against an £18.0m cap.

### BACKTEST — strategy WINS once the harness is correct (measured, 2026-08-21)
`strategy_backtest.py`, run on real 2025/26 per-GW outcomes (vaastav export, 841 players). Two harness
bugs had to be fixed before the numbers meant anything — recording both, because the first run said the
strategy LOST and that conclusion was an artefact.

**Harness bug 1: the objective was tested with a proxy, not the real model.** The first version used
prior points-per-90 because the export supposedly couldn't rebuild the v2 feature vector. That was wrong:
`ml_predict_v2._row_from_history` needs BASE_COLS (total_points, minutes, bps, ict_index, influence,
creativity, threat) plus `round`, and vaastav's export has **all seven**. Feeding the real model its own
features moved the result from **mean −8.3** to **mean +18.2**.

**Harness bug 2 (the big one): auto-sub scoring rewarded an absurd bench.** The scoring rule credited the
BEST bench scores whenever any starter blanked. At GW1 the old form builder benched **Salah (£14.5m) and
Haaland (£14.0m)** — a nonsense squad — and collected **190 "auto-sub" points**, beating a squad whose XI
scored 73 MORE. Real FPL: a starter is only replaced on **0 minutes**, subs come on in strict **bench
order** (not best-first), each sub is used once, and the formation must stay legal. Implemented properly
(`_mins`, `_formation_legal`); GW1 flipped from **−84 to +33**.

**Harness bug 3: bench ordering was unfair to the form builder.** `score_squad` ordered substitutes by
`b.get("predicted_points", b.get("form", 0))` — but `build_form_squad` rows carry NO `predicted_points`
key, so the strategy squad was ordered by model predictions while the form squad fell back to form. That
flattered the strategy builder for a reason unrelated to selection. Now ordered by **price descending**,
the one signal both builders share (and FPL bench order is the manager's choice anyway). Also removed a
dead nested `played()` function left over from the rewrite and an unused `Tuple` import.

**Final measured result (all three harness bugs fixed) — strategy wins 5/6 build points, mean +38.2 pts:**
| build GW | form | strategy | diff |
|---|---|---|---|
| GW1  | 240 | **273** | +33 |
| GW5  | 494 | **501** | +7 |
| GW12 | **423** | 403 | −20 |
| GW20 | 415 | **528** | +113 |
| GW26 | 447 | **504** | +57 |
| GW32 | 368 | **407** | +39 |

**GW12 investigated, and it is NOT a bug.** The strategy XI's players actually out-scored the form XI's
over the rest of the season (1156 vs 1066); the loss comes from the XI/bench split. Elliot Anderson
(£5.3m) went to the bench and then scored 139, but his predicted 2.73 was genuinely below the benched-out
alternative (Anthony 2.82) — the LP split the squad rationally on the information it had. That is
prediction noise, not a modelling error, and "fixing" it would mean overfitting to one known outcome.

**Superseded table (before the bench-order fix):**
| build GW | form (old) | strategy (new) | diff |
|---|---|---|---|
| GW1  | 240 | **273** | +33 |
| GW5  | 494 | **501** | +7 |
| GW12 | **430** | 403 | −27 |
| GW20 | 415 | **528** | +113 |
| GW26 | 444 | **504** | +60 |

Robust across horizons (not a single-window fluke): **5 GWs → 3/4 wins, mean +30.0**; **15 GWs → 3/4 wins,
mean +76.8**. GW12 is the consistent loss across every configuration and is worth investigating rather
than dismissing.

### Earlier (superseded) reading of the same test

Built `strategy_backtest.py` and ran it on real 2025/26 per-GW outcomes (vaastav export, 841 players)
before wiring anything into the agent. **Result: the full strategy builder LOST — 1 win in 3 build
points, mean −8.3 pts over 10-gameweek windows.** Recorded as-is; the change is not vindicated.

Decomposing the two changes separately is what made it informative:

| build GW | old (form obj + old structure) | **form obj + NEW structure** | proxy obj + new structure |
|---|---|---|---|
| GW5  | 503 | 494 | 491 |
| GW12 | 462 | **484** | 495 |
| GW20 | 424 | **443** | 378 |

- **The STRUCTURAL fix is the part that works: 2 wins / 3, mean +10 pts.** Bench spend fell from
  £20-25m to ~£18m and bench MINUTES roughly doubled (2,800→5,201 at GW20; 3,796→9,028 at GW5) — the
  bench became real rotation cover rather than dead weight, which is exactly the intent.
- **The OBJECTIVE substitution is what loses.** The backtest's per-90 proxy picked players with good
  historical rates who then barely featured — Isak (41 pts over the window) and Malen (**2**) both
  entered the XI. Form, for all its faults, at least tracks who is currently playing.

**Important caveat on what this does and does not test.** The proxy is NOT the v2 model — the historical
export cannot reconstruct its 32-feature vector, so `proxy_predicted_points` uses prior points-per-90.
So this measures "structure + a weak predictor", and the objective result says nothing about the real
model. It does say the structure earns its place on its own.

**The GW1 case is the most telling, and favours the new structure emphatically.** At GW1 the old builder
produced: bench **£41.0m**, XI blank rate **58.2%**, and an XI scoring **174** against **190 from
auto-subs** — the bench outscored the starters. That is the flat-objective failure this task diagnosed,
confirmed on real data. (The strategy builder went infeasible at GW1 in the *harness only*: this export
has no prior-season minutes, so the proxy `start_probability` maxes at 0.35 and nothing clears the 0.55
bench filter. Live, the v2 model supplies real start probabilities of 0.88-0.93 — verified — so this is a
harness limitation, not a shipped defect. Worth fixing in the harness before drawing GW1 conclusions.)

**Decision (superseded by the corrected run above):** at the time, keep the structure and treat the
objective as unproven. The corrected harness then measured the objective change as a WIN with the real
model, so both halves now have evidence. The lesson worth keeping: the first run's negative verdict came
from the test, not the code — check the harness before believing a surprising result.

### Season hygiene: live picks are 2026/27 only (user caught this)
The Salah/Haaland bench example above comes from `strategy_backtest.py`, which reads
`cache/backtest/merged_gw_2025_26.csv` — **last** season. That is correct for a backtest (you can only
score against outcomes that already happened, and 2026/27 has zero played gameweeks), but it must never
leak into live picks: **Salah is not in the 2026/27 game at all** (verified against bootstrap-static).
Confirmed by grep that the live path (`api_server`, `fpl_strategy`, `bot_agent`) never reads the backtest
cache — it is bootstrap-static only. Live squad re-verified: **all 15 picks exist in the 2026/27
bootstrap**, £99.5m, XI £81.5m + bench £18.0m, £0.5m banked.

### MCP parity for Claude Desktop  ✅ (2026-08-21)
Audited `Server.py` (MCP) against `api_server.FPL_TOOLS` (chat/REST). Most apparent gaps were just name
differences (`analyze_fixtures` vs `analyze_team_fixtures`, `get_top_performers` vs `get_top_players`,
`optimize_squad_lp` vs `optimize_squad`), but **the two most valuable NEW tools were genuinely absent** —
`get_squad_strategy` and `search_player_news` — and neither `fpl_strategy` nor `player_news_search` was
imported. MCP is now **17 tools**, both added with the descriptions written for Claude Desktop's
tool-picking (concrete "Use for:" examples, and an explicit warning that search_player_news is slow).

**Two real bugs caught by checking signatures instead of assuming them** — both would have failed at
runtime inside Claude Desktop:
1. `fetch_knocks_and_bans` / `fetch_ffscout_team_news` are **async and take an aiohttp session**. Calling
   them bare returned un-awaited coroutines, so the cross-reference would silently have had no
   third-party data. Fixed to the same `async with aiohttp.ClientSession()` + `asyncio.gather` pattern
   `get_team_news` already used. Verified live: 91 Knocks-and-Bans entries, 20 FFScout teams.
2. `collect_enhanced_data` returns a **(players, match_stats) tuple**, not a list. Treating it as a list
   of players would have yielded garbage xG data. Now unpacked.

Also added `planning_gameweek()` to `Server.py`, mirroring the api_server fix — MCP had the same
`is_current` off-by-one in 8 places. The new strategy tool uses it; the pre-existing tools still use
`is_current` and should be migrated (listed as a gap below).

**Verified via the real MCP handler** (`handle_call_tool`), not just imports: `get_squad_strategy`
returns the full 2,629-char analysis; `search_player_news` reaches the search layer and degrades
gracefully to an actionable message when no API key/credit is present.

### Task 7 items done (FBRef waste)
- **Negative-cache TTL 1h → 12h** (`FBREF_FAILURE_TTL_HOURS`). A retry costs ~11 minutes (5 stat types x
  2-3 attempts x 40s marker timeout) and **cannot succeed before a season's first matches** — there is no
  table to serve. The hourly retry was pure waste and repeatedly stalled interactive tool calls, including
  three times while testing today.
- **Error message now distinguishes blocked from absent.** It inspects the retained page text for
  Cloudflare fingerprints (`cf-mitigated`, `just a moment`, `challenge-platform`, …) and says either
  "challenge did not clear — retrying may help" or "the page loaded but contains no `stats_<type>` table
  — most likely no published data yet; retrying will NOT help". Conflating these is exactly what produced
  the wrong diagnosis this ROADMAP carried for weeks.

### MCP `optimize_squad_lp` was still on the broken objective — found by Claude Desktop
The very first real Claude Desktop session called `optimize_squad_lp` and refused to use the result:
"The LP optimizer is spitting out nonsense (Haaland and Isak on the bench, 0.0 expected points). I'll
build this myself." **It was right.** Reproduced exactly: a **£39.5m bench** holding Haaland (£15.5m),
Isak (£9.0m) and Palmer (£9.5m), while STARTING a £4.0m defender projected at 0.2 pts/gw, with
"Expected Points: 0.0".

Cause: Task 8 fixed the objective in `api_server` (`/api/strategy/squad`) but `Server.py`'s MCP handler
still called the old `optimize_squad_with_fixtures` with `target_spend=100.0`. All three original defects
were therefore live on the MCP path: flat `form` objective (0.0 for all 600 pre-season), bench excluded
from the objective, and the full budget force-spent — so premiums landed on the unscored bench because it
was the only place the forced money could go.

Fixed: the handler now builds via `fpl_strategy.build_shortlist` +
`EnhancedOptimizer.optimize_from_shortlist`, uses `planning_gameweek`, and **refuses** (rather than
silently falling back to `form`) if the v2 model is unavailable. Output rewritten to report the real
objective — XI/bench cost split, per-pick predicted points and start probability, xG flags, rotation
pairs, and an explicit reminder to check press conferences.

Verified via the MCP handler: **£100.0m = XI £83.0m + bench £17.0m**, bench picks 79-92% to start,
predicted XI points 40.5. Compare the old output above.

**Lesson worth keeping: fixing a shared bug in one entry point does not fix the others.** The same class
of miss as the bot brain (Task 6) and the flat objective (Task 8) — a verified fix wired to one consumer
only. When fixing an objective/model path, grep for every caller.

## TASK 9 — Real automation via headless Claude Code  ✅ (built and tested 2026-08-22)

### The finding that unlocked it
`claude --print --mcp-config ...` loads the **local** MCP server and can call all 17 tools headlessly.
Verified on this machine — and it worked while the project's `ANTHROPIC_API_KEY` had **zero credit**, so
it authenticated through the Claude Code subscription session rather than the API key. That is the whole
cost argument for this approach over the API path.

Ruled out (researched, not assumed): **plugins cannot schedule anything** (they are skills/agents/hooks/
MCP configs); **cloud Routines and Cowork tasks cannot reach a local MCP server** (Anthropic-hosted
connectors only); **Desktop scheduled tasks** only fire while the app is open; **`/loop`** expires after
7 days and needs a live session.

### What shipped
- **`run_bot.sh`** — launchd entry point. Ticks hourly, asks `bot_scheduler.due_runs()` whether anything
  is actually due, and only then invokes Claude. Measured: a not-due tick costs **0.9s** and invokes no
  model at all, so hourly polling is effectively free while staying robust to FPL moving a deadline
  (hardcoded cron times rot; FPL's own published deadlines do not).
  Writes each decision to `logs/decision_<ts>_<type>.md`, records the run so it is not repeated, fires a
  macOS notification, and on failure does **not** record the run so it retries.
- **`mcp_bot.json`** — MCP config for the headless runs.
- **`com.clankerfc.fplbot.plist`** — launchd job (`plutil -lint` clean). Sets PATH/CLAUDE_BIN explicitly
  because launchd's minimal environment does not include nvm. `RunAtLoad` is on so a machine that was
  asleep through a window can still catch it inside `due_runs()`'s grace period.

### Safety
The agent gets an explicit **read-only** `--allowedTools` allowlist. Even a badly-worded prompt cannot
submit a transfer, and if a write tool is ever added to the MCP server it cannot silently become
reachable from cron. Writes stay behind `fpl_auth`'s `FPL_BOT_MODE` (default `notify`).

### End-to-end test (real, not simulated)
`./run_bot.sh --force final` → **SUCCESS in 792s, 4,536-byte briefing**. The output is genuine FPL
reasoning, not a stats dump: captained Haaland on fixture, flagged that **Saka is absent from Arsenal's
predicted XI despite carrying no FPL flag** (~71% to start) and said don't captain him, told the reader
to **own Isak but not captain him** (new club + away at his former club, the best CS defence in the
league), correctly applied the auto-sub rule to 75% doubts, dismissed the GW1 form table as
promoted-side clean-sheet luck, and noticed that **Newcastle and Liverpool — the two best clean-sheet
outlooks — play each other this week**, so neither is a GW2 CS play. It also flagged its own limitation:
live web search was unavailable, so it told the reader to hand-check Saka.

### The fixture-horizon fix is NOW VERIFIED (it could not be, until today)
GW1 has been played: `is_current=1`, `is_next=2`. So for the first time the buggy and fixed code diverge:
| | result |
|---|---|
| OLD `is_current` anchor | **GW1** — already being played |
| NEW `planning_gameweek()` | **GW2** — the one being decided |
Confirmed correct against live data. Previously this was unprovable, since pre-season both returned GW1.

### Caveats to carry forward
- **A run takes ~13 minutes.** Fine against a deadline hours away, but the launchd window must allow it.
- **launchd does not run while the Mac is off**, and a sleeping Mac only runs it on wake. For reliable
  deadline coverage schedule a wake: `sudo pmset repeat wakeorpoweron MTWRFSU 13:00:00`. Until then this
  is best-effort — another reason the tools are read-only and the mode is `notify`.
- **Billing is unconfirmed.** The run succeeded with zero API credit, implying subscription auth, but
  there are reports that headless runs may bill at API rates. **Check the usage dashboard after the first
  few real runs** rather than assuming either way.

### launchd install — TCC blocker found and solved (2026-08-25)
`launchctl load` succeeded but the job exited **126** immediately:
`/bin/bash: .../run_bot.sh: Operation not permitted` — despite the script being `-rwxr-xr-x`. Cause is
**macOS TCC**, not Unix permissions: launchd-spawned processes cannot read `~/Documents` at all.
Rejected granting `/bin/bash` Full Disk Access (that hands EVERY bash script on the machine full disk
access — far too broad for one bot). Instead `run_bot.sh` + `mcp_bot.json` are copied to
**`~/.clankerfc/`** (not TCC-protected) with logs alongside; the repo keeps the canonical copies under
version control. **Re-copy after editing** — the plist header documents this so nobody "helpfully" points
it back at the repo. Job now loads clean (**exit 0**, empty stderr) and the hourly tick works from the
new location.

### Second end-to-end run (early type) — passed
`./run_bot.sh --force early` → SUCCESS, 2,468-byte report. It did exactly what an early run should: told
the difference between a **price trap** and a **timing play**. Flagged De Cuyper (top of form AND
transfers-in at +328k, so a rise was locked in) as **do NOT chase** — one goal from ~0.5 xG is finishing
luck, and Brighton face Chelsea then Arsenal; but flagged João Pedro as the genuine early move on **xG
3.0**, real underlying threat rather than a spike. Recommended rolling otherwise. It also declared its
own blind spots (news tools offline, no API key).

### 2026/27 advanced stats went LIVE (and two predictions came true)
GW1 has been played, and both sources now return real current-season data: **Understat 310 players,
FBRef 310 players** for 2026/27 (Haaland xG 0.75 from 5 shots — real, not the placeholder the bot
complained about pre-GW1). This retires the long-running fallback-to-2025/26 caveat.
Both Task 7 predictions are confirmed:
1. **The wall was never permanent** — 4 of 5 FBRef stat types now fetch cleanly through the same code.
2. **The new error message did its job** — `goal_shot_creation` failed with *"the page loaded but
   contains no table — most likely this season has no published data yet ... Retrying will NOT help"*,
   correctly distinguishing "not published" from "Cloudflare blocked us". Under the old message this
   would have been misfiled as an anti-bot block again.

### Name matching re-audited on live 2026/27 data — 100% of players who have PLAYED (2026-08-25)
The headline match rate LOOKS like a regression (Understat 68.6% → 50.98%) but that is a **denominator
artifact, not a fault**: Understat and FBRef only carry rows for players who have actually appeared.
After one gameweek exactly **310 of 612** FPL players have any minutes, and Understat publishes exactly
310 rows — so ~50.7% is the arithmetic CEILING, not a shortfall. Judge coverage by
players-with-minutes, never by the raw rate; the raw number will climb on its own as the season runs.

Measured against the meaningful denominator, six real gaps existed and all six are now fixed:
- **Understat (2):** `António João Pereira de Albuquerque Tavares da Silva` → `António Silva` (a
  six-token Portuguese name fuzzy matching cannot bridge to a two-token one), and `Abdoul Ouattara` →
  `Guemissongui Ouattara` — **different given names for the same player**, with a decoy present
  (`Dango Ouattara` at Brentford matches on his own, so a surname-only rule would silently attach the
  wrong club's player).
- **FBRef (4):** `Igor Thiago`, `Estêvão Willian`, `Abdul Fatawu Issahaku`, and `Bachir Belloumi`
  (FPL calls him *Mohamed* Belloumi — same club, Hull City, confirms identity).

**Structural bug found while fixing this, worth recording.** Adding the FBRef names to the shared
`manual_mappings.json` **silently broke two working Understat matches**: Understat spells them `Thiago`
and `Estêvão`, FBRef spells them `Igor Thiago` and `Estêvão Willian`, and one file cannot hold two
targets for one FPL name (verified — `Igor Thiago` does not exist in Understat's data at all). A single
shared matcher for two differently-spelled sources is the underlying design flaw. Fixed properly:
`load_manual_mappings` now **merges** instead of replacing, and `EnhancedDataCollector` builds a separate
`fbref_matcher` that layers `player_mapping/fbref_mappings.json` on top of the shared file. All three
FBRef call sites (bulk match, per-player match, and the promoted-team Championship fallback — also FBRef
data) use it.

**Verified after the fix:** Understat 312 matched, FBRef 352 matched, and **0 players with minutes
unmatched on either source**.

### Prior-season backfill — 171 established players were INVISIBLE (2026-08-25)
Follow-up to the audit above, prompted by asking whether coverage held for players with **no** minutes.
It did not. Understat only publishes a player once he has appeared, so after GW1 **300 of 612 FPL
players had no row to match against** — not a name-matching failure, an absence of data. The consequence
was a real blind spot rather than a cosmetic one: an unmatched player is invisible to the strategy layer,
and the list included **Watkins (9% owned, £8.0m), Gyökeres (7.6%), Bruno G., Pedro Porro (13.9%) and
Dubravka (18.9% owned — a bench pick this project itself recommended)**.

Fix: `collect_enhanced_data` now runs a **prior-season backfill pass** for anyone unmatched against the
current season, reusing the existing matcher against `PRIOR_SEASON`. Stale-but-real beats absent.
Measured: **171 of 300 recovered**, taking the Understat rate **50.98% → 78.92%**. The remaining 129 are
genuine newcomers with no EPL history in either season — uncoverable by any means.

**Second bug caught while verifying, and worth the extra step.** The first run backfilled correctly but
reported `prior=None` — `merge_player_data` copies named fields, so the `_stats_are_prior_season` tag was
being silently dropped. Untagged stale data is **worse than no data**, because a consumer treats last
season's xG as this season's form. Now propagated as `stats_are_prior_season` / `stats_season`.
Verified: Watkins/Gyökeres/Bruno G. carry `prior_season=True, season=2025`; Haaland's genuine 2026/27
xG (0.75) is untagged.

**Downstream note for the next session:** `fpl_strategy.value_and_underlying()` reads `xG_overperformance`
without checking these flags, so a backfilled player's regression/bargain verdict is currently based on
last season. That is still better than the player being invisible, but the flags exist now and the
strategy layer should discount or annotate them.

### Prior-season / unproven tax on backfilled stats (2026-08-25)
Closes the follow-up flagged above. `fpl_strategy.value_and_underlying()` was reading
`xG_overperformance` without checking the backfill flags, so a player whose stats came from LAST season
got the same confident verdict as one with current-season data.

Now `stats_are_prior_season` triggers three things:
1. **A 25% discount on the threat rate** (`PRIOR_SEASON_THREAT_DISCOUNT`, env-tunable) — the data is kept,
   because discarding it is what made these players invisible in the first place, but marked down.
2. **The xG verdict becomes `unproven`** rather than `overperforming`/`underperforming`. A
   regression-or-bargain call needs CURRENT-season finishing data; declaring someone "due for goals" off
   last season's numbers is a confident claim built on the wrong season.
3. **An explicit note** naming the season and the discount, so the agent can reason about it rather than
   silently inheriting it.
Verified with identical inputs: prior-season → `unproven`, 0.75 → 0.56 xG+xA/90 with a warning;
current-season → `underperforming`, full 0.75, "genuine bargain".

This also covers the **non-Premier-League** case the user asked about. ~17 of the 129 permanently
unmatched are notable outfielders (N.Jackson, Kulusevski, Promise David, Manzambi, Touré) who are absent
because they **did not play in the EPL last season** — new signings from abroad, long-term injuries,
returning loanees. Verified absent from both 2026/27 and 2025/26 EPL datasets, so no name mapping can
reach them. Scraping their foreign-league profiles was considered and **rejected**: cross-league xG does
not translate one-for-one (league strength differs materially), it would not help the injured ones at all
(Kulusevski/Manzambi have unknown return dates — that is a team-news problem, already covered by
`search_player_news`), and all 17 have zero minutes, so each resolves automatically the moment he plays.
Of the remaining 129: **31 are goalkeepers** (Understat is an xG/xA dataset and does not model keepers,
so a profile would add nothing) and 108 are sub-0.5%-owned fringe/academy players.

### Clanker FC is live
Team **7575639** verified against the FPL API: real entry, joined 2026-08-21, **29 points in GW1**,
£100.0m squad value. `BOT_TEAM_ID` is now set in the plist (both the repo copy and the installed one), so
the bot analyses the actual squad instead of giving generic advice.

### Known remaining gaps (do not assume these are done)
- The `value` and `bench` **roles are never assigned** (both show 0) — every budget pick lands in
  `rotation` because the rotation test is checked first. Cosmetic for selection (the LP reads price and
  start_prob, not the role label) but the tags are misleading and should be tightened.
- **`form` still has no weight once real gameweeks exist.** The user's steer was that ML leads but form
  should carry weight after some games have been played. The v2 model already ingests rolling form as a
  feature, so this may need nothing — but it is **unverified**, and worth an explicit blend test once GW3-4
  data exists rather than assuming the feature covers it.
- ✅ **DONE — the agent now reads the strategy.** `get_squad_strategy` is registered as the 19th tool
  (dispatcher + `tool_squad_strategy`), returning clean-sheet rankings, rotation pairs, value picks, xG
  bargains and regression risks as prose to reason over — deliberately NOT a squad to copy, since handing
  the agent a finished squad would replace the judgment the tool exists to inform. `SYSTEM_PROMPT` now
  teaches the four principles (clean sheets need soft run AND real defence; rotation pairs cover a run
  cheaply; overperforming xG is a WARNING not a buy signal; spend on the pitch but the bench must PLAY),
  and the parallel-call step includes it. Verified live: it flagged **Rogers +2.9 above xG as a regression
  risk — a player the earlier hand-built squad had bought**, which is exactly the check that was missing.
- The **two-agent debate** is still not built; it should own the judgment layer over this analysis.
- Whether this squad **actually scores better** is unmeasured. `ml_backtest.py` can build a squad on a past
  season's GW1 data and score it against real outcomes vs the form-based version. Do that before trusting
  the improvement.

---

### Remaining in Task 6
- ⬜ **Two-agent debate** (proposer + challenger). Deliberately sequenced *after* the single loop: its
  value is unmeasured, whereas the wiring gap above was a known deficit with an already-measured fix.
  Build it, then measure whether the challenger ever *flips* a verdict — if it never does, it's cost with
  no signal and that's worth knowing.
- ⬜ **Real-squad end-to-end run** once GW1 is played and picks exist.
- ⬜ Notify channel on failure/low-confidence (currently recorded in `cache/bot_runs.json` and the
  workflow's step summary only).

---

## TASK 7 (proposed) — FBRef: stop paying for pages that cannot exist yet  ⬜
**The ROADMAP's own diagnosis of this was wrong; corrected by direct testing 2026-08-21.**
- It is **not** a consent banner. Response headers are `cf-mitigated: challenge`, `server: cloudflare` —
  a Cloudflare bot challenge.
- Plain HTTP now 403s on the **entire domain**, `fbref.com/en/` included. So the earlier theory
  ("freshly-published, low-traffic early-season pages are more aggressively protected") does not hold.
- **Selenium still clears the challenge**: 551 rows of 2025/26 `standard` fetched fresh with
  `no_cache=True, no_store=True` in 172s.
- Decisively: 2026/27 via Selenium fails with `ValueError: not enough values to unpack (expected 1, got 0)`
  — **not** a 403 and not a challenge. That is the parser finding no table, through the identical code
  path that works for 2025/26.

**Conclusion: there is nothing to "fix". The 2026/27 pages have no player-stats tables yet** because no
matches have been played. `_fetch_extended_player_stats` reports a table-not-found as an
"anti-bot interstitial", which is what produced the wrong diagnosis above.

**Selenium is permanent and that is fine.** `sd.FBref` subclasses `BaseSeleniumReader` with **no requests
backend anywhere in its MRO** (verified) — there is no non-Selenium path to switch to, and since plain
HTTP 403s the whole domain, Selenium is precisely what clears Cloudflare. It is not a workaround to be
removed.

**The ~11 min is failure cost, not Selenium cost — so it mostly disappears once the tables exist.**
`_wait_for_table_html` polls up to **40s** for a table marker; when the table does not exist every attempt
burns the full timeout, and 5 stat types × 2-3 attempts ≈ the measured 11 min. When the table *does*
exist the marker appears in seconds. Measured on 2025/26 through the identical path:
| | now (no 2026/27 tables) | once tables exist |
|---|---|---|
| Cold / cache expired | ~11 min (all timeouts) | ~2-3 min (browser start + soccerdata's fixed 7s/request rate limit) |
| Warm cache | ~0.5s | ~0.5s |
The bot runs twice a gameweek and the cache holds between runs, so the warm path is the common case; the
17-min run measured on 2026-08-21 was near worst-case.

Still worth doing (smaller than first framed — the wasted-time half self-resolves):
- Distinguish "Cloudflare blocked us" from "page has no table" in the error message. This is the item that
  actually matters: conflating them is what produced the wrong diagnosis above.
- Optionally extend the negative cache beyond 1h *while a season is unplayed*.

**Caveat, do not over-promise:** `_fetch_extended_player_stats` is hand-rolled scraping outside the
maintained library (see Task 1 item 2), and `goal_shot_creation` was the flakiest stat type even on
2025/26. Expect "much faster, occasionally one stat type empty", not "perfectly clean".
Also re-confirmed live: `stat_type="defense"` still raises `TypeError ... should be in ['standard',
'keeper', 'shooting', 'playing_time', 'misc']` — the soccerdata whitelist regression is unchanged, which
is why the hand-rolled fetch is load-bearing rather than optional.

**Timing note (measured, for expectation-setting):** the 2026-08-21 agent run took ~17 min total —
~11 min of it FBRef retries in `fetch_enhanced_players()`, only ~6.5 min of actual agent deliberation
(9 iterations, 16 tool calls, 2 web searches). On a warm cache a full decision is ~6-7 min. **The chat
does not pay this**: its FBRef data is cached and a normal turn is 1-3 tool calls, so it stays in seconds.

---

## Done previously (committed / this work)
- ✅ Season migration to 2026/27: `season_config.py`, `TEAM_MAPPING` fix, auto-detect fallback,
  FBRef stale-cache fallback, frontend labels. (Commit pending — commit first.)
