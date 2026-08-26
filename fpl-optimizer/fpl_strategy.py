#!/usr/bin/env python3
"""
FPL squad-construction strategy — the domain knowledge the optimizer lacked.

## Why this exists

`enhanced_optimization.py` was solving the wrong problem. Three defects, all
verified against the live API before this module was written:

1. **The objective was `form`, which is 0.0 for all 600 players pre-season.**
   `_calculate_fixture_scores` computes `base_score = float(player['form'])`,
   then `max(score, 0.01)`. Before a ball is kicked every player scores exactly
   0.01, so the objective is FLAT: the LP is not optimizing, it is returning an
   arbitrary feasible solution. That is precisely when you build your opening
   squad, so the one squad that matters most was chosen by constraint
   satisfaction alone.
2. **The ML model was never in the objective.** `grep -c "ml_predict"` on
   enhanced_optimization.py returns 0. The `predicted_points` on each pick were
   computed *after* selection, for display. The v2 model (+1.52 pts/pick,
   Wilcoxon p=0.014) had no influence on who was picked.
3. **The bench was unscored, yet money was forced into it.** The objective sums
   only `starting[...]` variables, so bench players contribute nothing — but
   `target_spend=budget` adds `total_cost >= 100.0`, so the solver must spend
   the full budget and the only place left to put it is the unscored bench.

## The strategy this encodes (researched, not invented)

From published FPL strategy (see SOURCES below), the parts that are actually
mechanical enough to encode:

- **Spend on the pitch, not the bench.** "There is little value in spending an
  extra £1.0m on a bench player if that money could upgrade someone you expect
  to start every Gameweek." So the bench gets a *cap*, not a share of a forced
  total spend.
- **The bench must still PLAY.** Bench fodder that never features is worthless
  as cover: when a starter is injured or faces a brutal fixture you need a
  substitute who actually gets minutes. So cheap is necessary but not
  sufficient — playing probability is a hard filter on bench picks.
- **Rotation pairs with COMPLEMENTARY fixtures.** The canonical example is two
  budget defenders (£4.0-5.0m each) from teams whose easy fixtures fall in
  different gameweeks, so one of them always has a good fixture. "Rotating the
  two budget defenders and starting only one each week" fields a defender with a
  home fixture every week for ~£8.5m combined.
- **Clean sheets drive defensive picks.** Target defenders from teams with
  genuine defensive quality AND a soft fixture run — a good defender with a hard
  fixture is unlikely to keep a clean sheet, which is exactly when his rotation
  partner should start instead.
- **Minutes certainty above all.** "Back players whose places in the team are
  not in question." Rotation risks and unproven signings are avoided.
- **Leave flexibility.** Managers "leave themselves room to manoeuvre, whether
  that is cash in the bank or an easy transfer to make."

## SOURCES

- RotoWire, "FPL Gameweek 1 Tips 2026/27: How to build the perfect opening
  squad" — bench should be "useful, not expensive"; first sub must have minutes;
  prioritise minutes certainty; keep flexibility for GW2.
- Fantasy Football Fix, "Best FPL Rotation Strategies 2026/27 | GW1-GW6" —
  two budget defenders (£4.0-5.0m) rotated alongside one premium (~£8.0m);
  complementary/alternating fixtures; target teams with strong defensive
  records; rotate on fixture difficulty rather than starting everyone.

## What this module does and does not do

It produces a **tagged shortlist and a set of budget rules**. It does not pick
the squad — the LP still does that, because "£100.0m, 2/5/5/3, max 3 per club"
is constraint satisfaction and PuLP is provably better at it than a language
model. This module decides *which players the LP is allowed to choose from* and
*how much it may spend where*, which is where the strategy actually lives.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Budget rules
# ---------------------------------------------------------------------------
# A bench of 4 at £4.0-4.5m costs £16.0-18.0m. Capping bench spend at £18.0m
# keeps ~£82m for the XI without forcing literally-cheapest picks, which would
# defeat the "bench must play" requirement.
BENCH_SPEND_CAP = float(os.getenv("BENCH_SPEND_CAP", "18.0"))

# Bench players must be plausible starters for their club, or they are not cover
# at all. This is a probability from the v2 model's start-probability head.
BENCH_MIN_START_PROB = float(os.getenv("BENCH_MIN_START_PROB", "0.55"))

# Rotation-defender price band, per the researched strategy.
ROTATION_PRICE_MAX = float(os.getenv("ROTATION_PRICE_MAX", "5.0"))

# FDR at or below this counts as a "good" fixture for rotation planning.
GOOD_FIXTURE_FDR = int(os.getenv("GOOD_FIXTURE_FDR", "3"))

POSITION_NAMES = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


@dataclass
class PlayerTag:
    """Why the strategy layer wants this player, in its own words."""
    player_id: int
    name: str
    position: int
    price: float
    team: int
    team_short: str
    role: str                       # premium | core | value | rotation | bench
    predicted_points: float = 0.0
    start_prob: float = 0.0
    fixture_run: List[Tuple[int, str, int]] = field(default_factory=list)  # (gw, opp, fdr)
    good_fixture_gws: List[int] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    points_per_million: float = 0.0
    xg_signal: Optional[str] = None   # overperforming | underperforming | in-line

    def to_dict(self) -> Dict:
        return {
            "id": self.player_id,
            "name": self.name,
            "position": POSITION_NAMES.get(self.position, "?"),
            "price": self.price,
            "team": self.team_short,
            "role": self.role,
            "predicted_points": round(self.predicted_points, 2),
            "start_prob": round(self.start_prob, 3),
            "points_per_million": round(self.points_per_million, 2),
            "xg_signal": self.xg_signal,
            "good_fixture_gws": self.good_fixture_gws,
            "reasons": self.reasons,
        }


# ---------------------------------------------------------------------------
# Value and underlying numbers
# ---------------------------------------------------------------------------
# How far a player's actual goals can sit above their xG before it reads as
# finishing luck rather than skill. Overperformance is a REGRESSION warning, not
# a buy signal: the goals already banked do not repeat unless the xG supports
# them. Underperformance with strong xG is the genuine bargain — the chances are
# being created, the finishing has lagged, and that tends to correct.
XG_OVERPERFORM_THRESHOLD = float(os.getenv("XG_OVERPERFORM_THRESHOLD", "1.5"))
XG_UNDERPERFORM_THRESHOLD = float(os.getenv("XG_UNDERPERFORM_THRESHOLD", "-1.0"))

# "Unproven in this league" discount, applied to players whose underlying stats
# are BACKFILLED FROM A PRIOR SEASON (see enhanced_features' prior-season pass)
# rather than earned in the current one.
#
# Two distinct populations get this, and both deserve caution:
#   * established players who simply have not featured yet — last season's
#     numbers are real but stale (form, role and team can all have changed);
#   * anyone whose only history is elsewhere — cross-league xG does not
#     translate one-for-one, since league strength differs materially.
# Rather than throw the data away (which made these players INVISIBLE to
# selection — the bug this fixes), the signal is kept and marked down.
PRIOR_SEASON_THREAT_DISCOUNT = float(os.getenv("PRIOR_SEASON_THREAT_DISCOUNT", "0.75"))


def value_and_underlying(player: Dict, predicted_points: float) -> Dict:
    """
    Value (points per £m) plus what the xG data says about sustainability.

    Deliberately reads the ENHANCED fields (`xG_overperformance`, `xG_per_90`,
    `xA_per_90`) that `enhanced_features.py` already computes from Understat and
    that nothing in the selection path was using. Collecting xG and then picking
    on `form` was leaving the most predictive data on the floor.

    Returns a dict rather than a score so the reasoning stays legible — the point
    is for the agent to be able to say *why* a player is good value.
    """
    price = max(player.get("now_cost", 0) / 10, 0.1)
    total_points = float(player.get("total_points") or 0)

    # Pre-season total_points is last season's, which is still the best
    # available value signal; mid-season it is this season's. Either way,
    # points-per-million is only meaningful alongside the xG check below.
    ppm_historic = total_points / price
    ppm_predicted = predicted_points / price

    over = player.get("xG_overperformance")
    xg90 = float(player.get("xG_per_90") or 0)
    xa90 = float(player.get("xA_per_90") or 0)
    threat90 = xg90 + xa90

    # Unproven-in-this-season tax. These numbers were earned in a PRIOR season,
    # so they are evidence but weaker evidence: discount the threat rate and say
    # so explicitly, rather than letting stale xG read as current form.
    is_prior = bool(player.get("stats_are_prior_season"))
    raw_threat90 = threat90
    if is_prior:
        threat90 *= PRIOR_SEASON_THREAT_DISCOUNT

    signal, notes = None, []
    if is_prior:
        season = player.get("stats_season")
        notes.append(
            f"⚠️ underlying stats are from {season or 'a prior season'}, not this one "
            f"(no appearances yet) — discounted {(1 - PRIOR_SEASON_THREAT_DISCOUNT):.0%} "
            f"({raw_threat90:.2f} → {threat90:.2f} xG+xA/90); treat as unproven here"
        )
    if over is not None:
        over = float(over)
        if is_prior:
            # A regression/bargain call needs CURRENT-season finishing data.
            # Declaring "due for goals" off last season's numbers would be a
            # confident claim built on the wrong season.
            signal = "unproven"
        elif over >= XG_OVERPERFORM_THRESHOLD:
            signal = "overperforming"
            notes.append(
                f"scored {over:.1f} above xG — finishing likely to regress, "
                "treat the price as inflated"
            )
        elif over <= XG_UNDERPERFORM_THRESHOLD and threat90 >= 0.35:
            signal = "underperforming"
            notes.append(
                f"{abs(over):.1f} BELOW xG on {threat90:.2f} xG+xA/90 — "
                "chances are there, finishing should correct: genuine bargain"
            )
        else:
            signal = "in-line"

    if threat90 >= 0.60:
        notes.append(f"elite underlying threat ({threat90:.2f} xG+xA/90)")
    elif threat90 >= 0.40:
        notes.append(f"strong underlying threat ({threat90:.2f} xG+xA/90)")

    return {
        "points_per_million_historic": round(ppm_historic, 2),
        "points_per_million_predicted": round(ppm_predicted, 2),
        "xg_signal": signal,
        "threat_per_90": round(threat90, 3),
        "threat_per_90_raw": round(raw_threat90, 3),
        "stats_are_prior_season": is_prior,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Fixture analysis
# ---------------------------------------------------------------------------

def build_fixture_runs(
    fixtures: List[Dict], teams: Dict, start_gw: int, num_gws: int = 5
) -> Dict[int, List[Tuple[int, str, int, bool]]]:
    """
    Per-team fixture run as (gameweek, opponent_short, fdr, is_home).

    Anchored on `start_gw`, which callers must derive from the NEXT unplayed
    gameweek — anchoring on the in-progress one leads the window with a
    gameweek nobody can still transfer for.
    """
    runs: Dict[int, List[Tuple[int, str, int, bool]]] = {}
    short = {tid: t.get("short_name", str(tid)) for tid, t in teams.items()}

    for f in fixtures:
        gw = f.get("event")
        if not gw or not (start_gw <= gw < start_gw + num_gws):
            continue
        h, a = f.get("team_h"), f.get("team_a")
        if h is None or a is None:
            continue
        runs.setdefault(h, []).append(
            (gw, short.get(a, "?"), f.get("team_h_difficulty", 3), True)
        )
        runs.setdefault(a, []).append(
            (gw, short.get(h, "?"), f.get("team_a_difficulty", 3), False)
        )

    for tid in runs:
        runs[tid].sort()
    return runs


def clean_sheet_outlook(
    team_id: int,
    runs: Dict[int, List[Tuple[int, str, int, bool]]],
    defensive_strength: Optional[Dict[int, float]] = None,
) -> Dict:
    """
    How likely this team is to keep clean sheets over the window.

    Two independent components, deliberately kept separate:
      * fixture softness — a good defence with a hard run still concedes;
      * defensive quality — a soft run does not help a leaky defence.
    A defender is only a clean-sheet target when BOTH point the right way, which
    is the reasoning the old `form`-only objective could not express.
    """
    run = runs.get(team_id, [])
    if not run:
        return {"good_fixture_gws": [], "avg_fdr": 5.0, "cs_score": 0.0, "fixtures": 0}

    fdrs = [fdr for _, _, fdr, _ in run]
    avg_fdr = sum(fdrs) / len(fdrs)
    good_gws = [gw for gw, _, fdr, _ in run if fdr <= GOOD_FIXTURE_FDR]

    # Map avg FDR (1 easy .. 5 brutal) onto 0..1, then scale by defensive
    # quality when we have it. Home games help clean sheets, so give a small
    # bump for the share of home fixtures in the window.
    fixture_component = max(0.0, min(1.0, (5.0 - avg_fdr) / 4.0))
    home_share = sum(1 for _, _, _, home in run if home) / len(run)
    quality = 1.0 if defensive_strength is None else defensive_strength.get(team_id, 1.0)

    cs_score = fixture_component * quality * (0.9 + 0.2 * home_share)
    return {
        "good_fixture_gws": good_gws,
        "avg_fdr": round(avg_fdr, 2),
        "cs_score": round(cs_score, 3),
        "fixtures": len(run),
    }


def team_defensive_strength(teams: Dict) -> Dict[int, float]:
    """
    Relative defensive quality from FPL's own published team strength ratings,
    normalised so the league average is 1.0.

    Uses `strength_defence_home/away`, which FPL maintains per team — real data
    rather than a hand-assigned guess, and it already reflects promotion.
    """
    vals = {}
    for tid, t in teams.items():
        home = t.get("strength_defence_home")
        away = t.get("strength_defence_away")
        if home and away:
            vals[tid] = (home + away) / 2.0
    if not vals:
        return {}
    mean = sum(vals.values()) / len(vals)
    if mean <= 0:
        return {}
    # Higher FPL "strength_defence" = stronger defence = better clean-sheet odds.
    return {tid: v / mean for tid, v in vals.items()}


def find_rotation_pairs(
    candidates: List[PlayerTag],
    runs: Dict[int, List[Tuple[int, str, int, bool]]],
    max_pairs: int = 6,
) -> List[Dict]:
    """
    Budget players from different clubs whose good fixtures land in DIFFERENT
    gameweeks — so one of the pair always has a favourable game.

    This is the mechanism behind the researched advice to rotate two budget
    defenders and start whichever has the home/easy fixture. Scored by how much
    of the window is covered by at least one of the two, with a penalty for
    overlap (two teams with identical good weeks are not a rotation pair, they
    are the same bet twice).
    """
    pairs = []
    for i, a in enumerate(candidates):
        for b in candidates[i + 1:]:
            if a.team == b.team:
                continue  # same club: fixtures are identical, no rotation value
            ga, gb = set(a.good_fixture_gws), set(b.good_fixture_gws)
            if not ga and not gb:
                continue
            covered = ga | gb
            overlap = ga & gb
            # Coverage is what matters; overlap is wasted duplication.
            score = len(covered) - 0.5 * len(overlap)
            pairs.append({
                "players": [a.name, b.name],
                "ids": [a.player_id, b.player_id],
                "teams": [a.team_short, b.team_short],
                "combined_price": round(a.price + b.price, 1),
                "covered_gameweeks": sorted(covered),
                "overlap_gameweeks": sorted(overlap),
                "coverage_score": round(score, 2),
                "rationale": (
                    f"{a.name} ({a.team_short}) has good fixtures in "
                    f"{sorted(ga) or 'none'}; {b.name} ({b.team_short}) in "
                    f"{sorted(gb) or 'none'} — start whichever has the better game."
                ),
            })
    pairs.sort(key=lambda p: (-p["coverage_score"], p["combined_price"]))
    return pairs[:max_pairs]


# ---------------------------------------------------------------------------
# Shortlist
# ---------------------------------------------------------------------------

def build_shortlist(
    players: List[Dict],
    teams: Dict,
    runs: Dict[int, List[Tuple[int, str, int, bool]]],
    predictions: Dict[int, Dict],
    per_position: Optional[Dict[int, int]] = None,
) -> Tuple[List[PlayerTag], Dict]:
    """
    Tag and rank candidates so the LP chooses from a strategically sane pool.

    `predictions` maps player id -> {"predicted_points": float,
    "start_prob": float} from the v2 model. This is what replaces `form` as the
    ranking signal: form is structurally 0.0 before a season starts, whereas the
    model was trained on three seasons of real per-gameweek outcomes and
    therefore still discriminates pre-season.

    Roles assigned:
      premium  — expensive and high-ceiling; the players you build around
      core     — mid-price nailed starters
      value    — cheap but genuinely productive
      rotation — budget, playing, with exploitable fixture swings
      bench    — cheap AND likely to play (real cover, not fodder)
    """
    per_position = per_position or {1: 6, 2: 18, 3: 22, 4: 14}
    defensive = team_defensive_strength(teams)
    short = {tid: t.get("short_name", str(tid)) for tid, t in teams.items()}

    tagged: List[PlayerTag] = []
    for p in players:
        pid = p["id"]
        pred = predictions.get(pid) or {}
        pp = float(pred.get("predicted_points") or 0.0)
        sp = float(pred.get("start_prob") or 0.0)
        price = p["now_cost"] / 10
        pos = p["element_type"]
        tid = p["team"]
        outlook = clean_sheet_outlook(tid, runs, defensive)

        # A player with no fixture in the window scores nothing — a blank is not
        # a "hard game", it is zero. Drop them from consideration entirely.
        if outlook["fixtures"] == 0:
            continue

        reasons = []
        if pos in (1, 2) and outlook["cs_score"] >= 0.45:
            reasons.append(
                f"clean-sheet target: {short.get(tid)} avg FDR {outlook['avg_fdr']}, "
                f"defensive strength {defensive.get(tid, 1.0):.2f}"
            )

        # Role assignment. Price bands are position-relative because a £7.0m
        # defender is a premium while a £7.0m midfielder is mid-price.
        premium_bar = {1: 5.5, 2: 6.5, 3: 9.5, 4: 9.0}[pos]
        # Budget tier. Set at the ACTUAL cheapest tier per position for 2026/27
        # (verified: no MID or FWD exists below £5.0m, so a 4.5 bar would leave
        # those positions with no budget role at all and the bench unfillable).
        value_bar = {1: 4.5, 2: 5.0, 3: 5.5, 4: 5.5}[pos]

        if price >= premium_bar:
            role = "premium"
            reasons.append(f"premium {POSITION_NAMES[pos]} at £{price}m")
        elif price <= value_bar:
            if sp >= BENCH_MIN_START_PROB and len(outlook["good_fixture_gws"]) >= 2:
                role = "rotation"
                reasons.append(
                    f"budget rotation option, good fixtures in GW"
                    f"{outlook['good_fixture_gws']}"
                )
            elif sp >= BENCH_MIN_START_PROB:
                role = "bench"
                reasons.append(f"playing bench cover ({sp:.0%} to start)")
            else:
                role = "bench"
                reasons.append(f"cheap but only {sp:.0%} to start — weak cover")
        else:
            role = "core" if sp >= 0.7 else "value"
            reasons.append(f"{role} pick, {sp:.0%} to start")

        # Value + underlying numbers. Surfaced for every player, not just cheap
        # ones — an overperforming premium is exactly the trap worth flagging.
        val = value_and_underlying(p, pp)
        reasons.extend(val["notes"])
        if val["points_per_million_historic"] >= 20 and price <= 6.5:
            reasons.append(
                f"strong value: {val['points_per_million_historic']:.1f} pts/£m historic"
            )

        tagged.append(PlayerTag(
            player_id=pid,
            name=p.get("web_name", "?"),
            position=pos,
            price=price,
            team=tid,
            team_short=short.get(tid, "?"),
            role=role,
            predicted_points=pp,
            start_prob=sp,
            fixture_run=[(gw, opp, fdr) for gw, opp, fdr, _ in runs.get(tid, [])],
            good_fixture_gws=outlook["good_fixture_gws"],
            reasons=reasons,
            points_per_million=val["points_per_million_historic"],
            xg_signal=val["xg_signal"],
        ))

    # Keep the best N per position by predicted points, then GUARANTEE enough
    # cheap-and-playing options that a legal, bench-capped squad stays solvable.
    #
    # This retention step is load-bearing, not a nicety. Ranking by predicted
    # points alone drops the entire £4.0m tier (a 4.0m defender never outscores a
    # 6.0m one), and without it the cheapest possible bench cost exactly equals
    # BENCH_SPEND_CAP — leaving zero slack and making the LP INFEASIBLE. Verified:
    # real £4.0m players with high start probability do exist (Dubravka 0.93,
    # Davies 0.88, Diop 0.87), they were simply being cut before the LP saw them.
    shortlist: List[PlayerTag] = []
    for pos, keep in per_position.items():
        pool = [t for t in tagged if t.position == pos]
        pool.sort(key=lambda t: -t.predicted_points)
        top = pool[:keep]
        chosen_ids = {t.player_id for t in top}

        # Cheapest PLAYING options at this position, by price then start
        # probability — these are the bench/rotation enablers. Taken by absolute
        # price rank rather than a fixed band, so it adapts if a position has no
        # £4.0m tier at all (true for MID/FWD in 2026/27).
        cheap_playing = sorted(
            (t for t in pool
             if t.player_id not in chosen_ids and t.start_prob >= BENCH_MIN_START_PROB),
            key=lambda t: (t.price, -t.start_prob),
        )[:8]
        shortlist.extend(top + cheap_playing)

    rotation_candidates = [
        t for t in shortlist
        if t.position == 2 and t.price <= ROTATION_PRICE_MAX and t.start_prob >= BENCH_MIN_START_PROB
    ]
    rotation_candidates.sort(key=lambda t: -len(t.good_fixture_gws))
    pairs = find_rotation_pairs(rotation_candidates[:12], runs)

    meta = {
        "shortlist_size": len(shortlist),
        "by_role": {
            r: sum(1 for t in shortlist if t.role == r)
            for r in ("premium", "core", "value", "rotation", "bench")
        },
        "rotation_pairs": pairs,
        "clean_sheet_teams": sorted(
            (
                {"team": short.get(tid), "cs_score": clean_sheet_outlook(tid, runs, defensive)["cs_score"],
                 "avg_fdr": clean_sheet_outlook(tid, runs, defensive)["avg_fdr"]}
                for tid in runs
            ),
            key=lambda d: -d["cs_score"],
        )[:8],
        # Surfaced separately because these are the picks a points-maximising
        # objective alone would miss or actively get wrong.
        "value_picks": [
            t.to_dict() for t in sorted(
                (t for t in shortlist if t.price <= 6.5 and t.points_per_million >= 15
                 and t.start_prob >= 0.6),
                key=lambda t: -t.points_per_million,
            )[:10]
        ],
        "underperforming_bargains": [
            t.to_dict() for t in sorted(
                (t for t in shortlist if t.xg_signal == "underperforming"),
                key=lambda t: -t.predicted_points,
            )[:8]
        ],
        "regression_risks": [
            t.to_dict() for t in sorted(
                (t for t in shortlist if t.xg_signal == "overperforming"),
                key=lambda t: -t.price,
            )[:8]
        ],
        "budget_rules": {
            "bench_spend_cap": BENCH_SPEND_CAP,
            "bench_min_start_prob": BENCH_MIN_START_PROB,
            "rationale": (
                "Bench is capped rather than funded: money not spent on the bench "
                "upgrades a starter. Bench picks must still be likely starters for "
                "their own club, or they are not usable cover."
            ),
        },
    }
    return shortlist, meta
