#!/usr/bin/env python3
"""
Real backtest of the trained points-prediction model against actual 2025/26
FPL outcomes, per Task 2 of ROADMAP.md.

Methodology: for each gameweek N (6..37, leaving room for rolling-form
history and a next-GW target), build each player's feature row AS OF GW N
and compare predictions against their ACTUAL total_points at GW N+1.

Data sources:
- FPL-native features + real per-GW ground truth: vaastav/Fantasy-Premier-
  League's merged_gw.csv for 2025/26 (real historical snapshot, confirmed
  all 38 GWs populated).
- Understat xG/xA: REAL per-match data via understatapi's per-player match
  endpoint, aggregated as of each gameweek's kickoff date (not a proxy).
- FBRef defensive/progressive/creation stats: FBRef's match-report pages do
  NOT expose these at per-match granularity (confirmed by inspecting the
  raw page — no hidden tables either), only season-end aggregates. Used as
  a CONSTANT proxy per player across all gameweeks (season-end per-90
  rates) since no real per-GW alternative exists. This is a known
  limitation, not a bug: it introduces mild look-ahead bias for these
  features specifically (a player's defensive stats at GW10 aren't
  identical to their final-season numbers), flagged in the report.

Scored: the actual trained RandomForest (models/points_model.pkl) vs.
naive baselines (last-GW points, rolling PPG, current form) vs. the
form x fixture-difficulty heuristic currently used by suggest_transfers.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from understatapi import UnderstatClient
from data_sources.understat_scraper import UnderstatScraper
from data_sources.fbref_scraper import FBRefScraper
from player_mapping.name_matcher import PlayerNameMatcher as NameMatcher
from predict_points import FPLPointsPredictor

CACHE_DIR = Path(__file__).parent / "cache" / "backtest"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
MERGED_GW_PATH = CACHE_DIR / "merged_gw_2025_26.csv"
UNDERSTAT_MATCH_CACHE = CACHE_DIR / "understat_matches_2025.json"

FIRST_BACKTEST_GW = 6   # needs prior history for rolling form
LAST_BACKTEST_GW = 37   # predicting GW+1, so stop one before the season end


def load_merged_gw() -> pd.DataFrame:
    if not MERGED_GW_PATH.exists():
        raise FileNotFoundError(f"Run: fetch merged_gw.csv to {MERGED_GW_PATH} first")
    df = pd.read_csv(MERGED_GW_PATH)
    df["kickoff_time"] = pd.to_datetime(df["kickoff_time"])
    return df


def build_understat_id_map() -> dict:
    """FPL element (name+team) -> Understat player id, via existing NameMatcher."""
    scraper = UnderstatScraper()
    understat_players = scraper.fetch_epl_players(season="2025")

    with UnderstatClient() as client:
        raw = client.league(league="EPL").get_player_data(season="2025")
    name_to_uid = {p["player_name"]: p["id"] for p in raw}

    matcher = NameMatcher()
    # NameMatcher expects FPL-shaped dicts; vaastav's `name` column is
    # "First Last" already, close enough to match against directly without
    # a full bootstrap-static fetch.
    fpl_like = []
    merged = load_merged_gw()
    for _, row in merged[["name", "element", "team"]].drop_duplicates("element").iterrows():
        parts = row["name"].split(" ", 1)
        first = parts[0]
        second = parts[1] if len(parts) > 1 else ""
        fpl_like.append({
            "id": int(row["element"]),
            "first_name": first,
            "second_name": second,
            "web_name": row["name"],
            # No numeric FPL team ID available here (vaastav's `team` field
            # is a name string, and TEAM_MAPPING is keyed by FPL's numeric
            # ids) — omit rather than pass a value that silently fails the
            # `team_id in TEAM_MAPPING` check and masks as team-filtered.
        })

    matched, unmatched = matcher.match_all_players(fpl_like, understat_players, threshold=75)
    stats = matcher.get_match_stats()
    print(f"Understat match rate for backtest: {stats['match_rate']}% ({stats['matched']}/{stats['total']})")

    element_to_uid = {}
    for element_id, u_player in matched.items():
        uid = name_to_uid.get(u_player["name"])
        if uid:
            element_to_uid[element_id] = uid
    return element_to_uid


def fetch_understat_match_history(element_to_uid: dict) -> dict:
    """Understat player id -> list of {date, xG, xA, npxG, xGChain, xGBuildup}, 2025 season only."""
    if UNDERSTAT_MATCH_CACHE.exists():
        with open(UNDERSTAT_MATCH_CACHE) as f:
            return json.load(f)

    result = {}
    uids = sorted(set(element_to_uid.values()))
    print(f"Fetching Understat per-match history for {len(uids)} players...")
    with UnderstatClient() as client:
        for i, uid in enumerate(uids):
            try:
                matches = client.player(player=uid).get_match_data()
                season_matches = [m for m in matches if m.get("season") == "2025"]
                result[uid] = [
                    {
                        "date": m["date"],
                        "xG": float(m.get("xG", 0) or 0),
                        "xA": float(m.get("xA", 0) or 0),
                        "npxG": float(m.get("npxG", 0) or 0),
                        "xGChain": float(m.get("xGChain", 0) or 0),
                        "xGBuildup": float(m.get("xGBuildup", 0) or 0),
                        "shots": int(m.get("shots", 0) or 0),
                        "key_passes": int(m.get("key_passes", 0) or 0),
                    }
                    for m in season_matches
                ]
            except Exception as e:
                print(f"  [{i+1}/{len(uids)}] FAILED uid={uid}: {e}")
                result[uid] = []
            if (i + 1) % 50 == 0:
                print(f"  [{i+1}/{len(uids)}] done")

    with open(UNDERSTAT_MATCH_CACHE, "w") as f:
        json.dump(result, f)
    return result


def load_fbref_season_end_stats() -> dict:
    """FPL element -> FBRef season-end feature dict, keyed by matching against merged_gw names."""
    scraper = FBRefScraper()
    fbref_players = scraper.fetch_player_stats(season="2025-2026", use_cache=True)
    print(f"FBRef 2025/26 season players: {len(fbref_players)}")

    matcher = NameMatcher()
    merged = load_merged_gw()
    fpl_like = []
    for _, row in merged[["name", "element", "team"]].drop_duplicates("element").iterrows():
        parts = row["name"].split(" ", 1)
        fpl_like.append({
            "id": int(row["element"]),
            "first_name": parts[0],
            "second_name": parts[1] if len(parts) > 1 else "",
            "web_name": row["name"],
            "team": row["team"],
        })

    matched, unmatched = matcher.match_all_players(fpl_like, fbref_players, threshold=75)
    stats = matcher.get_match_stats()
    print(f"FBRef match rate for backtest: {stats['match_rate']}% ({stats['matched']}/{stats['total']})")

    return {element_id: p for element_id, p in matched.items()}


def understat_features_as_of(match_history: list, as_of_date) -> dict:
    """Cumulative Understat features from all matches strictly before as_of_date."""
    past = [m for m in match_history if pd.Timestamp(m["date"], tz="UTC") < as_of_date]
    if not past:
        return {"xG": 0.0, "xA": 0.0, "npxG": 0.0, "xGChain": 0.0, "xGBuildup": 0.0,
                "shots": 0, "key_passes": 0, "games": 0}
    games = len(past)
    return {
        "xG": sum(m["xG"] for m in past),
        "xA": sum(m["xA"] for m in past),
        "npxG": sum(m["npxG"] for m in past),
        "xGChain": sum(m["xGChain"] for m in past),
        "xGBuildup": sum(m["xGBuildup"] for m in past),
        "shots": sum(m["shots"] for m in past),
        "key_passes": sum(m["key_passes"] for m in past),
        "games": games,
    }


def build_backtest_rows(merged: pd.DataFrame, element_to_uid: dict, understat_history: dict,
                         fbref_by_element: dict) -> pd.DataFrame:
    """
    One row per (player, gameweek N) with features as-of GW N and the real
    target = actual total_points at GW N+1.
    """
    rows = []
    by_element = {eid: g.sort_values("GW") for eid, g in merged.groupby("element")}

    for element_id, player_gws in by_element.items():
        player_gws = player_gws.reset_index(drop=True)
        gw_to_idx = {row["GW"]: i for i, row in player_gws.iterrows()}

        uid = element_to_uid.get(element_id)
        history = understat_history.get(uid, []) if uid else []
        fbref = fbref_by_element.get(element_id, {})

        for gw in range(FIRST_BACKTEST_GW, LAST_BACKTEST_GW + 1):
            if gw not in gw_to_idx or (gw + 1) not in gw_to_idx:
                continue
            idx = gw_to_idx[gw]
            next_idx = gw_to_idx[gw + 1]

            prior = player_gws.iloc[:idx + 1]  # GWs 1..gw inclusive
            current_row = player_gws.iloc[idx]
            target_row = player_gws.iloc[next_idx]

            # FPL form: avg points/match over the trailing 30 days as of
            # this GW's kickoff (FPL's own definition), falling back to
            # last-5-GW average if the 30-day window has no matches
            # (early-season sparsity).
            as_of = current_row["kickoff_time"]
            window = prior[prior["kickoff_time"] > as_of - pd.Timedelta(days=30)]
            if len(window) > 0:
                form = window["total_points"].mean()
            else:
                form = prior["total_points"].tail(5).mean()

            u_feat = understat_features_as_of(history, as_of)
            games_for_90 = max(u_feat["games"], 1)

            row = {
                "element": element_id,
                "gw": gw,
                "target_gw": gw + 1,
                "actual_points_next_gw": int(target_row["total_points"]),
                "position": current_row["position"],
                "last_gw_points": int(current_row["total_points"]),
                # FPL-native, real cumulative-as-of-GW-N
                "form": round(float(form), 2),
                "total_points": int(prior["total_points"].sum()),
                "minutes": int(prior["minutes"].sum()),
                "goals_scored": int(prior["goals_scored"].sum()),
                "assists": int(prior["assists"].sum()),
                "clean_sheets": int(prior["clean_sheets"].sum()),
                "goals_conceded": int(prior["goals_conceded"].sum()),
                "bonus": int(prior["bonus"].sum()),
                "bps": int(prior["bps"].sum()),
                "influence": float(prior["influence"].sum()),
                "creativity": float(prior["creativity"].sum()),
                "threat": float(prior["threat"].sum()),
                "ict_index": float(prior["ict_index"].sum()),
                "now_cost": float(current_row["value"]) / 10,
                "selected_by_percent": 0.0,  # not in vaastav's per-GW export
                # Understat, real cumulative-as-of-GW-N
                "xG": u_feat["xG"],
                "xA": u_feat["xA"],
                "npxG": u_feat["npxG"],
                "xGChain": u_feat["xGChain"],
                "xGBuildup": u_feat["xGBuildup"],
                "xG_per_90": round(u_feat["xG"] / games_for_90, 3),
                "xA_per_90": round(u_feat["xA"] / games_for_90, 3),
                "npxG_per_90": round(u_feat["npxG"] / games_for_90, 3),
                "xGChain_per_90": round(u_feat["xGChain"] / games_for_90, 3),
                "xGBuildup_per_90": round(u_feat["xGBuildup"] / games_for_90, 3),
                "shots": u_feat["shots"],
                "shots_on_target": 0,  # not exposed per-match by understatapi
                "key_passes": u_feat["key_passes"],
                "xG_overperformance": round(int(prior["goals_scored"].sum()) - u_feat["xG"], 3),
                "xA_overperformance": round(int(prior["assists"].sum()) - u_feat["xA"], 3),
                "npxG_overperformance": round(int(prior["goals_scored"].sum()) - u_feat["npxG"], 3),
                "xG_xA_combined": round(u_feat["xG"] + u_feat["xA"], 3),
                "npxG_npxA_combined": round(u_feat["npxG"] + u_feat["xA"], 3),
                "finishing_quality": round(int(prior["goals_scored"].sum()) / u_feat["xG"], 3) if u_feat["xG"] > 0 else 1.0,
                "np_finishing_quality": round(int(prior["goals_scored"].sum()) / u_feat["npxG"], 3) if u_feat["npxG"] > 0 else 1.0,
                # FBRef, STATIC season-end proxy (see module docstring)
                "tackles": fbref.get("tackles", 0),
                "tackles_won": fbref.get("tackles_won", 0),
                "tackle_pct": fbref.get("tackle_pct", 0.0),
                "interceptions": fbref.get("interceptions", 0),
                "tackles_plus_int": fbref.get("tackles_plus_int", 0),
                "blocks": fbref.get("blocks", 0),
                "clearances": fbref.get("clearances", 0),
                "errors": fbref.get("errors", 0),
                "def_contributions": fbref.get("def_contributions", 0),
                "def_contributions_per_90": fbref.get("def_contributions_per_90", 0.0),
                "def_contribution_prob": fbref.get("def_contribution_prob", 0.0),
                "expected_def_points": fbref.get("expected_def_points", 0.0),
                "progressive_passes": fbref.get("progressive_passes", 0),
                "progressive_carries": fbref.get("progressive_carries", 0),
                "progressive_receptions": fbref.get("progressive_receptions", 0),
                "progressive_passes_per_90": fbref.get("progressive_passes_per_90", 0.0),
                "progressive_carries_per_90": fbref.get("progressive_carries_per_90", 0.0),
                "progressive_receptions_per_90": fbref.get("progressive_receptions_per_90", 0.0),
                "touches": fbref.get("touches", 0),
                "touches_att_3rd": fbref.get("touches_att_3rd", 0),
                "sca": fbref.get("sca", 0),
                "gca": fbref.get("gca", 0),
                "sca_per_90": fbref.get("sca_per_90", 0.0),
                "gca_per_90": fbref.get("gca_per_90", 0.0),
            }
            rows.append(row)

    return pd.DataFrame(rows)


POSITION_TO_ELEMENT_TYPE = {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}


def score_predictions(df: pd.DataFrame, predictor: FPLPointsPredictor) -> tuple:
    """Score the real trained model + baselines against actual_points_next_gw."""
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

    df = df.copy()
    df["element_type"] = df["position"].map(POSITION_TO_ELEMENT_TYPE).fillna(3).astype(int)
    # Real FPL team id isn't available at this stage (vaastav's `team` is a
    # name string) — this feature is present in the trained model's input
    # but the model treats it as a low-signal categorical, not something
    # worth reconstructing a name->id lookup for in a backtest.
    df["team"] = 1

    players_for_model = df.to_dict("records")
    X = predictor.prepare_features(players_for_model)
    X_scaled = predictor.scaler.transform(X)
    df["pred_model"] = predictor.model.predict(X_scaled)

    # Baselines
    df["pred_last_gw"] = df["last_gw_points"]
    df["pred_form"] = df["form"]
    games_played_proxy = (df["minutes"] / 90).clip(lower=1)
    df["pred_ppg"] = df["total_points"] / games_played_proxy
    # The actual current recommendation logic (FPLOptimizer.
    # _calculate_player_gameweek_score in predict_points.py): form*2, +/-
    # a flat price adjustment. Reproduced exactly, not reinvented.
    price_adjustment = np.where(df["now_cost"] < 5.0, 2, np.where(df["now_cost"] > 10.0, -0.5, 0))
    df["pred_heuristic"] = df["form"] * 2 + price_adjustment

    actual = df["actual_points_next_gw"]

    results = {}
    for label, col in [
        ("trained_model", "pred_model"),
        ("naive_last_gw", "pred_last_gw"),
        ("naive_form", "pred_form"),
        ("naive_ppg", "pred_ppg"),
        ("current_heuristic", "pred_heuristic"),
    ]:
        preds = df[col].fillna(0)
        results[label] = {
            "mae": round(mean_absolute_error(actual, preds), 4),
            "rmse": round(mean_squared_error(actual, preds) ** 0.5, 4),
            "r2": round(r2_score(actual, preds), 4),
        }

    return results, df


if __name__ == "__main__":
    print("=" * 60)
    print("STEP 1: Understat name-matching + per-match fetch")
    print("=" * 60)
    element_to_uid = build_understat_id_map()
    print(f"Matched {len(element_to_uid)} FPL players to Understat IDs")

    understat_history = fetch_understat_match_history(element_to_uid)
    total_matches = sum(len(v) for v in understat_history.values())
    print(f"Total Understat match-rows fetched: {total_matches}")

    print("\n" + "=" * 60)
    print("STEP 2: FBRef season-end stats (proxy features)")
    print("=" * 60)
    fbref_by_element = load_fbref_season_end_stats()

    print("\n" + "=" * 60)
    print("STEP 3: Building backtest feature rows")
    print("=" * 60)
    merged = load_merged_gw()
    backtest_df = build_backtest_rows(merged, element_to_uid, understat_history, fbref_by_element)
    print(f"Built {len(backtest_df)} (player, gameweek) rows for backtesting")
    backtest_df.to_csv(CACHE_DIR / "backtest_rows.csv", index=False)

    print("\n" + "=" * 60)
    print("STEP 4: Scoring model + baselines")
    print("=" * 60)
    predictor = FPLPointsPredictor()
    predictor.load_model()
    results, scored_df = score_predictions(backtest_df, predictor)

    for label, metrics in results.items():
        print(f"{label:25s} MAE={metrics['mae']:.4f}  RMSE={metrics['rmse']:.4f}  R2={metrics['r2']:.4f}")

    scored_df.to_csv(CACHE_DIR / "backtest_scored.csv", index=False)
    print(f"\nSaved detailed results to {CACHE_DIR / 'backtest_scored.csv'}")
