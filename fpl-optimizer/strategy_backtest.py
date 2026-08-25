#!/usr/bin/env python3
"""
Does the strategy-driven squad builder actually score more points?

## What this tests

Builds an opening squad from GW1-of-2025/26 information only, then scores it
against what those players ACTUALLY scored over the following gameweeks. Two
builders, same budget, same constraints, same data:

  A. **form objective** — what `enhanced_optimization` did: score = form *
     fixture_weight, bench unscored, full budget force-spent.
  B. **strategy objective** — `optimize_from_shortlist`: predicted points as the
     objective, bench scored at a discount, bench spend capped, budget not
     force-spent.

The point is to avoid the mistake this project already made once: asserting that
a change helps because the reasoning sounds right. A previous "model beats form"
verdict in this repo turned out to be measuring a crippled feature vector.

## The honest methodological caveats

- **`form` at GW1 of a real season is not 0.0 here.** vaastav's export carries a
  real `value` and the players had 2024/25 histories, so builder A is being given
  a *working* form signal — a FAIRER test than live pre-season, where form is
  literally 0.0 for all 600 players and builder A degenerates to an arbitrary
  feasible squad. So this comparison UNDERSTATES the live improvement.
- Scoring uses actual `total_points` with FPL's real starting/bench rules
  approximated: the starting XI scores, and a benched player only counts when a
  starter in the same position blanked (a simplification of auto-subs).
- No transfers, no chips, no captaincy — a pure squad-quality comparison. Real
  FPL managers transfer weekly, so this isolates the opening-squad decision.
- One season, one starting point. A single sample: treat the direction as
  informative and the magnitude as noisy.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from enhanced_optimization import EnhancedOptimizer  # noqa: E402

CACHE = Path(__file__).parent / "cache" / "backtest"
MERGED = CACHE / "merged_gw_2025_26.csv"

POS_ID = {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}
QUOTA = {1: 2, 2: 5, 3: 5, 4: 3}


def load() -> pd.DataFrame:
    if not MERGED.exists():
        raise SystemExit(f"Missing {MERGED}")
    return pd.read_csv(MERGED)


def build_player_pool(df: pd.DataFrame, upto_gw: int) -> List[Dict]:
    """
    One row per player using information available at `upto_gw` only.

    `form` is the mean of the trailing 4 gameweeks' points BEFORE upto_gw, which
    is what FPL's own form field approximates. At upto_gw == 1 there is no prior
    data in this season, so form is 0 — the same degenerate case as live
    pre-season, which is exactly the scenario worth testing.
    """
    hist = df[df.GW < upto_gw]
    fut = df[df.GW >= upto_gw]

    pool = []
    for element, grp in df.groupby("element"):
        rows = grp.sort_values("GW")
        first = rows.iloc[0]
        pos = str(first["position"])
        if pos not in POS_ID:
            continue

        prior = hist[hist.element == element].sort_values("GW")
        form = float(prior["total_points"].tail(4).mean()) if len(prior) else 0.0
        # Season-to-date totals, the cold-start signal a real builder would have.
        prior_pts = float(prior["total_points"].sum()) if len(prior) else 0.0
        prior_mins = float(prior["minutes"].sum()) if len(prior) else 0.0

        # Price as of the build gameweek.
        at = rows[rows.GW == upto_gw]
        price = float((at.iloc[0]["value"] if len(at) else first["value"])) / 10

        future = fut[fut.element == element]
        pool.append({
            "id": int(element),
            "name": str(first["name"]),
            "position_id": POS_ID[pos],
            "team": str(first["team"]),
            "team_id": abs(hash(str(first["team"]))) % 100000,
            "price": price,
            "form": form,
            "prior_points": prior_pts,
            "prior_minutes": prior_mins,
            "actual_future_points": float(future["total_points"].sum()),
            "actual_by_gw": dict(zip(future["GW"], future["total_points"])),
            "minutes_by_gw": dict(zip(future["GW"], future["minutes"])),
            "future_minutes": float(future["minutes"].sum()),
        })
    return pool


def real_model_predictions(
    df: pd.DataFrame, pool: List[Dict], build_gw: int
) -> Dict[int, Dict]:
    """
    Score the REAL v2 model, not a proxy.

    Confirmed possible: `ml_predict_v2._row_from_history` needs per-gameweek rows
    carrying BASE_COLS (total_points, minutes, bps, ict_index, influence,
    creativity, threat) and vaastav's export has **all seven**, plus `round`. So
    the model's own feature builder can be fed genuine history as-of the build
    gameweek — no reconstruction, no proxy.

    Returns {} when the model is unavailable, so the caller can fall back rather
    than silently comparing against nothing.
    """
    import ml_predict_v2

    hist = df[df.GW < build_gw]
    if hist.empty:
        return {}

    histories: Dict[int, List[Dict]] = {}
    players: List[Dict] = []
    by_id = {p["id"]: p for p in pool}

    for element, grp in hist.groupby("element"):
        element = int(element)
        if element not in by_id:
            continue
        rows = grp.sort_values("GW")
        histories[element] = [
            {**{c: r[c] for c in ml_predict_v2.BASE_COLS if c in rows.columns},
             "round": int(r["GW"])}
            for _, r in rows.iterrows()
        ]
        players.append({
            "id": element,
            "now_cost": int(round(by_id[element]["price"] * 10)),
            "element_type": by_id[element]["position_id"],
        })

    try:
        return ml_predict_v2.predict_points(players, histories)
    except Exception as e:  # pragma: no cover - diagnostic path
        print(f"  real model unavailable ({e})")
        return {}


def proxy_predicted_points(p: Dict, horizon: int) -> float:
    """
    Stand-in for the v2 model, using only pre-build information.

    The real model needs its full 32-feature vector, which this historical export
    cannot reconstruct faithfully. Rather than fake that, this uses
    points-per-90 from prior data — a deliberately SIMPLE and honest proxy that
    still has the property that matters for the comparison: unlike raw `form`, it
    is defined when a player has history but no recent gameweeks, and it scales
    with minutes reliability.

    This makes the test CONSERVATIVE: the real v2 model should beat this proxy,
    so any measured gain here is a floor, not a ceiling.
    """
    mins = p["prior_minutes"]
    if mins >= 90:
        per90 = p["prior_points"] / (mins / 90.0)
        # Minutes reliability: a player with few minutes is a worse bet than his
        # per-90 suggests.
        reliability = min(1.0, mins / (horizon * 60.0)) if horizon else 1.0
        return per90 * reliability
    # No usable history: fall back to a small price-implied prior so the
    # objective is not flat (price is the market's own expectation).
    return max(0.0, (p["price"] - 4.0) * 0.6)


def start_probability(p: Dict, horizon: int, played_gws: int = 0) -> float:
    """
    Minutes-reliability proxy for the bench-playability filter.

    Normalised by gameweeks ACTUALLY PLAYED before the build, not by the scoring
    horizon. The earlier version divided by `horizon * 90`, which made every
    probability collapse toward 0.25-0.35 at GW1 (no prior gameweeks exist in
    this export) — nothing cleared the 0.55 bench bar and the LP went infeasible.
    That was a harness artefact, not a defect in the shipped builder, which uses
    the v2 model's real start probabilities (measured 0.88-0.93).
    """
    if played_gws <= 0:
        # No history at all: price is the only signal. FPL's cheapest tier is
        # mostly backups, but £4.5m+ players are usually squad regulars.
        return 0.60 if p["price"] >= 4.5 else 0.45
    return min(0.98, p["prior_minutes"] / (played_gws * 90.0))


# ---------------------------------------------------------------------------
# Builder A — the old form objective, reimplemented faithfully
# ---------------------------------------------------------------------------

def build_form_squad(pool: List[Dict], budget: float = 100.0) -> List[Dict]:
    """
    Replicates the OLD behaviour: objective = form only, bench contributes
    nothing, and the full budget must be spent (`total_cost >= budget`).
    """
    from pulp import (LpProblem, LpMaximize, LpVariable, lpSum, LpStatus,
                      PULP_CBC_CMD)

    prob = LpProblem("form_squad", LpMaximize)
    sel = {p["id"]: LpVariable(f"s{p['id']}", cat="Binary") for p in pool}
    st = {p["id"]: LpVariable(f"t{p['id']}", cat="Binary") for p in pool}
    by = {p["id"]: p for p in pool}

    # The old objective, including its `max(score, 0.01)` floor.
    prob += lpSum(max(p["form"], 0.01) * st[p["id"]] for p in pool)

    prob += lpSum(sel[i] for i in sel) == 15
    prob += lpSum(st[i] for i in st) == 11
    for i in sel:
        prob += st[i] <= sel[i]
    # Force-spend, as the old target_spend=budget did.
    prob += lpSum(by[i]["price"] * sel[i] for i in sel) >= budget - 0.5
    prob += lpSum(by[i]["price"] * sel[i] for i in sel) <= budget
    for pid, q in QUOTA.items():
        prob += lpSum(sel[i] for i in sel if by[i]["position_id"] == pid) == q
    prob += lpSum(st[i] for i in st if by[i]["position_id"] == 1) == 1
    for pid, (lo, hi) in ((2, (3, 5)), (3, (2, 5)), (4, (1, 3))):
        pool_ids = [i for i in st if by[i]["position_id"] == pid]
        prob += lpSum(st[i] for i in pool_ids) >= lo
        prob += lpSum(st[i] for i in pool_ids) <= hi
    teams: Dict[str, List[int]] = {}
    for p in pool:
        teams.setdefault(p["team"], []).append(p["id"])
    for ids in teams.values():
        prob += lpSum(sel[i] for i in ids) <= 3

    prob.solve(PULP_CBC_CMD(msg=0))
    if LpStatus[prob.status] != "Optimal":
        return []
    return [
        {**by[i], "is_starting": st[i].varValue == 1}
        for i in sel if sel[i].varValue == 1
    ]


# ---------------------------------------------------------------------------
# Builder B — the strategy objective
# ---------------------------------------------------------------------------

def build_strategy_squad(pool: List[Dict], horizon: int, budget: float = 100.0,
                         bench_cap: float = 18.0, played_gws: int = 0,
                         model_preds: Dict[int, Dict] = None) -> List[Dict]:
    """
    Uses the shipped `optimize_from_shortlist`, with a shortlist that keeps the
    cheap-and-playing tier (the retention fix that made it feasible).

    When `model_preds` is supplied it is the REAL v2 model's output and is used
    for both the objective and the bench-playability filter — that is the
    configuration the live endpoint runs. Falls back to the per-90 proxy only
    when the model has no history to work from (GW1), and says which it used.
    """
    model_preds = model_preds or {}
    rows = []
    for p in pool:
        mp = model_preds.get(p["id"]) or {}
        pred = mp.get("predicted_points")
        prob = mp.get("play_probability")
        rows.append({
            **p,
            "predicted_points": (
                float(pred) if pred is not None
                else proxy_predicted_points(p, horizon)
            ),
            "start_prob": (
                float(prob) if prob is not None
                else start_probability(p, horizon, played_gws)
            ),
        })

    # Same shortlist shape as fpl_strategy: best-N per position by predicted
    # points, PLUS guaranteed cheapest-playing options so the bench cap stays
    # satisfiable.
    shortlist = []
    for pid, keep in {1: 8, 2: 22, 3: 26, 4: 16}.items():
        p_pool = [r for r in rows if r["position_id"] == pid]
        p_pool.sort(key=lambda r: -r["predicted_points"])
        top = p_pool[:keep]
        ids = {r["id"] for r in top}
        cheap = sorted(
            (r for r in p_pool if r["id"] not in ids and r["start_prob"] >= 0.55),
            key=lambda r: (r["price"], -r["start_prob"]),
        )[:8]
        shortlist.extend(top + cheap)

    squad, lineup, status = EnhancedOptimizer().optimize_from_shortlist(
        shortlist, budget=budget, bench_spend_cap=bench_cap, min_bank=0.0
    )
    if not squad:
        print(f"  strategy build failed: {status}")
        return []
    start_ids = {p["id"] for p in lineup["starting"]}
    return [{**p, "is_starting": p["id"] in start_ids} for p in squad]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_squad(squad: List[Dict], gws: List[int]) -> Dict:
    """
    Actual points over `gws` under FPL's real auto-substitution rules.

    The earlier version credited the BEST bench scores whenever any starter
    blanked, which massively overpaid a stacked bench: at GW1 the form builder
    benched **Salah (£14.5m) and Haaland (£14.0m)** — an absurd squad — and
    collected 190 "auto-sub" points from it, enough to beat a squad whose XI
    actually scored 73 more. That was a scoring artefact, not a real result.

    Real FPL rules, now implemented:
      * a starter is only replaced if he played **0 minutes**;
      * substitutes come on in strict **bench order**, not best-first;
      * each bench player can be used **once** per gameweek;
      * the replacement must keep the formation legal (>=1 GK, >=3 DEF, >=1 FWD),
        and a GK can only replace a GK.
    """
    xi = [p for p in squad if p["is_starting"]]
    bench = [p for p in squad if not p["is_starting"]]

    # Bench order: outfield by descending expected value, GK separate — FPL only
    # ever subs a keeper for a keeper, and the order is the manager's choice.
    bench_gk = [b for b in bench if b["position_id"] == 1]
    # Bench order uses PRICE descending — the one signal both builders share.
    # Ordering by predicted_points silently gave the strategy squad a better
    # bench order than the form squad (whose rows carry no predicted_points),
    # which would flatter the strategy builder for a reason unrelated to
    # selection. Price is a fair, builder-agnostic proxy for who a manager would
    # bring on first, and FPL bench order is the manager's choice anyway.
    bench_out = sorted(
        (b for b in bench if b["position_id"] != 1),
        key=lambda b: -b["price"],
    )

    total = 0.0
    autosub_credit = 0.0

    for gw in gws:
        for p in xi:
            total += float(p["actual_by_gw"].get(gw, 0) or 0)

        # Which starters actually blanked on MINUTES (the real trigger).
        blanked = [p for p in xi if not _mins(p, gw)]
        if not blanked:
            continue

        survivors = [p for p in xi if _mins(p, gw)]
        used = set()

        for out in blanked:
            if out["position_id"] == 1:
                pool = [b for b in bench_gk if id(b) not in used]
            else:
                pool = [b for b in bench_out if id(b) not in used]

            for cand in pool:
                if not _mins(cand, gw):
                    continue  # a sub who also didn't play cannot come on
                trial = survivors + [cand]
                if _formation_legal(trial):
                    autosub_credit += float(cand["actual_by_gw"].get(gw, 0) or 0)
                    survivors = trial
                    used.add(id(cand))
                    break

    return {
        "xi_points": round(total, 1),
        "autosub_points": round(autosub_credit, 1),
        "total": round(total + autosub_credit, 1),
        "squad_cost": round(sum(p["price"] for p in squad), 1),
        "bench_cost": round(sum(p["price"] for p in bench), 1),
        "bench_minutes": int(sum(p["future_minutes"] for p in bench)),
        "xi_blank_rate": round(
            sum(1 for gw in gws for p in xi if not _mins(p, gw))
            / max(1, len(gws) * len(xi)), 3),
    }


def _mins(player: Dict, gw: int) -> float:
    """Minutes played by this player in this gameweek (0 if absent)."""
    return float(player.get("minutes_by_gw", {}).get(gw, 0) or 0)


def _formation_legal(players: List[Dict]) -> bool:
    """FPL requires >=1 GK, >=3 DEF, >=1 FWD in an 11 (max 11 on the pitch)."""
    if len(players) > 11:
        return False
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for p in players:
        counts[p["position_id"]] += 1
    return counts[1] >= 1 and counts[2] >= 3 and counts[4] >= 1


def run(build_gw: int, horizon: int) -> Dict:
    df = load()
    pool = build_player_pool(df, build_gw)
    gws = list(range(build_gw, build_gw + horizon))

    print(f"\n{'='*74}")
    print(f"Build at GW{build_gw}, scored over GW{gws[0]}-GW{gws[-1]} "
          f"({len(pool)} players in pool)")
    print("=" * 74)

    preds = real_model_predictions(df, pool, build_gw)
    covered = sum(1 for p in pool if p["id"] in preds)
    print(f"v2 model predictions: {len(preds)} players "
          f"({covered}/{len(pool)} of pool)" if preds
          else "v2 model: no history at this build point — proxy fallback")

    results = {}
    for label, squad in (
        ("form (old)", build_form_squad(pool)),
        ("strategy (new)", build_strategy_squad(
            pool, horizon, played_gws=build_gw - 1, model_preds=preds)),
    ):
        if not squad:
            print(f"{label}: BUILD FAILED")
            continue
        s = score_squad(squad, gws)
        results[label] = s
        print(f"\n{label}")
        print(f"  cost £{s['squad_cost']}m (bench £{s['bench_cost']}m)  "
              f"bench minutes over window: {s['bench_minutes']}")
        print(f"  XI {s['xi_points']} + autosub {s['autosub_points']} = "
              f"TOTAL {s['total']}   XI blank rate {s['xi_blank_rate']:.1%}")

    if len(results) == 2:
        a, b = results["form (old)"]["total"], results["strategy (new)"]["total"]
        diff = b - a
        pct = (diff / a * 100) if a else 0
        print(f"\n  >>> strategy {'BEATS' if diff > 0 else 'LOSES TO'} form by "
              f"{abs(diff):.1f} pts ({pct:+.1f}%) over {horizon} GWs")
    return results


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=10)
    ap.add_argument("--build-gws", type=int, nargs="+", default=[1, 5, 12, 20])
    args = ap.parse_args()

    all_res = {}
    for gw in args.build_gws:
        all_res[gw] = run(gw, args.horizon)

    print(f"\n{'='*74}\nSUMMARY across build points\n{'='*74}")
    wins = 0
    total_diff = 0.0
    for gw, r in all_res.items():
        if len(r) != 2:
            continue
        a, b = r["form (old)"]["total"], r["strategy (new)"]["total"]
        total_diff += b - a
        wins += 1 if b > a else 0
        print(f"  GW{gw:>2}: form {a:>7.1f}   strategy {b:>7.1f}   diff {b-a:>+7.1f}")
    n = sum(1 for r in all_res.values() if len(r) == 2)
    if n:
        print(f"\n  strategy won {wins}/{n} build points, "
              f"mean diff {total_diff/n:+.1f} pts")
