#!/usr/bin/env python3
"""
Serving layer for the v2 points model (models/points_model_v2.pkl).

v2 has a different contract from v1 and is NOT a drop-in replacement:
  v1: single RandomForest + StandardScaler, 61 season-total features
  v2: two models (P(plays) classifier + log1p-points regressor), no scaler,
      32 features that are ROLLING MEANS over prior gameweeks

That last part is the hard part of serving. The features are windowed means
over the player's previous 1/3/5/10 gameweeks, so predictions need per-GW
history — which `bootstrap-static` does not carry. Two regimes:

  * IN-SEASON: pull each player's per-GW history from `element-summary/{id}/`
    and build the same rolling windows `ml_train.featurize` builds. This is
    the accurate path.
  * COLD START (pre-season / no history yet, i.e. right now): `element-summary`
    history is empty for everyone, so fall back to per-game rates derived from
    the season totals on `bootstrap-static`. Every window then gets the same
    per-game value. This is a genuine approximation and is reported as
    `confidence: "low"` so callers (and Claude) don't over-trust it.

Train/serve parity matters more than anything else here: the feature names,
order, and construction below must mirror ml_train.featurize exactly, or the
model silently returns garbage. FEATURES is read from the saved bundle rather
than redefined, so the two cannot drift apart.
"""
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

MODEL_PATH = Path(__file__).parent.parent / "models" / "points_model_v2.pkl"

# Mirrors ml_train.BASE_COLS / WINDOWS. Kept as literals (not imported) so
# serving doesn't pull in ml_train's pandas-heavy data-loading module, but
# verified against the bundle's feature list at load time.
BASE_COLS = ["total_points", "minutes", "bps", "ict_index",
             "influence", "creativity", "threat"]
WINDOWS = [1, 3, 5, 10]

_bundle = None


def load_bundle(path: Path = MODEL_PATH) -> Optional[Dict]:
    """Load and validate the v2 bundle once. Returns None if unavailable."""
    global _bundle
    if _bundle is not None:
        return _bundle
    if not path.exists():
        return None

    import joblib
    bundle = joblib.load(path)

    for key in ("classifier", "regressor", "features"):
        if key not in bundle:
            raise ValueError(f"v2 bundle missing '{key}' — refusing to serve a malformed model")

    # The regressor predicts log1p(points); serving MUST invert it. Fail loudly
    # rather than silently under-predict if a future retrain changes this.
    target = bundle.get("regressor_target")
    if target != "log1p":
        raise ValueError(
            f"v2 bundle regressor_target={target!r}, expected 'log1p'. "
            "predict_points() inverts with expm1 and would be wrong otherwise."
        )

    expected = [f"{c}_l{w}" for w in WINDOWS for c in BASE_COLS] + \
               ["price", "pos", "avg_min", "games_so_far"]
    if list(bundle["features"]) != expected:
        raise ValueError(
            "v2 feature list does not match this serving module's construction "
            f"(bundle has {len(bundle['features'])}, expected {len(expected)}). "
            "Train/serve skew would produce silently wrong predictions."
        )

    _bundle = bundle
    return _bundle


def _row_from_history(player: Dict, history: List[Dict]) -> Dict:
    """
    Build one feature row from a player's real per-GW history.

    Mirrors ml_train.featurize: each window is the mean over the most recent
    `w` COMPLETED gameweeks. featurize() uses .shift(1) so a training row
    never sees its own gameweek; here every row in `history` is already a
    completed past gameweek, so taking the tail is the equivalent.
    """
    hist = sorted(history, key=lambda h: h.get("round", 0))
    frame = pd.DataFrame(hist)

    row: Dict[str, float] = {}
    for window in WINDOWS:
        recent = frame.tail(window)
        for col in BASE_COLS:
            values = pd.to_numeric(recent.get(col), errors="coerce") if col in recent else None
            row[f"{col}_l{window}"] = float(values.mean()) if values is not None and len(values) else 0.0

    minutes = pd.to_numeric(frame.get("minutes"), errors="coerce").fillna(0) if "minutes" in frame else pd.Series(dtype=float)
    row["avg_min"] = float(minutes.mean()) if len(minutes) else 0.0
    row["games_so_far"] = float(len(frame))
    row["price"] = float(player.get("now_cost", 0)) / 10
    row["pos"] = int(player.get("element_type", 3))
    return row


def _row_from_season_totals(player: Dict) -> Dict:
    """
    Cold-start fallback: no per-GW history exists yet (pre-season), so derive
    a per-game rate from season totals and use it for every window.

    Deliberately crude — it cannot represent recent form, which is the single
    strongest signal the model uses. Callers get confidence="low".
    """
    minutes = float(player.get("minutes", 0) or 0)
    games = max(minutes / 90.0, 1.0)

    row: Dict[str, float] = {}
    for window in WINDOWS:
        for col in BASE_COLS:
            total = float(player.get(col, 0) or 0)
            row[f"{col}_l{window}"] = (minutes / games) if col == "minutes" else total / games

    row["avg_min"] = minutes / games
    row["games_so_far"] = float(int(games))
    row["price"] = float(player.get("now_cost", 0)) / 10
    row["pos"] = int(player.get("element_type", 3))
    return row


def predict_points(
    players: List[Dict],
    histories: Optional[Dict[int, List[Dict]]] = None,
) -> Dict[int, Dict]:
    """
    Predict next-gameweek points for a list of bootstrap-static player dicts.

    Args:
        players: FPL player dicts (need id, now_cost, element_type + the
            BASE_COLS season totals for the cold-start path).
        histories: optional {player_id: element-summary 'history' list}. Any
            player with a non-empty history uses the accurate rolling-window
            path; the rest fall back to season totals.

    Returns {player_id: {predicted_points, play_probability, points_if_plays,
    confidence, basis}}. Empty dict if the model isn't available.
    """
    bundle = load_bundle()
    if bundle is None or not players:
        return {}

    histories = histories or {}
    rows, meta = [], []
    for player in players:
        history = histories.get(player.get("id")) or []
        if history:
            rows.append(_row_from_history(player, history))
            meta.append((player["id"], "history", len(history)))
        else:
            rows.append(_row_from_season_totals(player))
            meta.append((player["id"], "season_totals", 0))

    features = bundle["features"]
    X = pd.DataFrame(rows).reindex(columns=features).fillna(0.0)

    play_prob = bundle["classifier"].predict_proba(X)[:, 1]
    # Invert the log1p target the regressor was trained on.
    points_if_plays = np.expm1(bundle["regressor"].predict(X))
    expected = play_prob * points_if_plays

    out = {}
    for (player_id, basis, games), prob, cond, exp in zip(meta, play_prob, points_if_plays, expected):
        if basis == "season_totals":
            confidence = "low"          # no recent form available at all
        elif games >= 5:
            confidence = "high"
        else:
            confidence = "medium"       # thin history, windows partly repeat
        out[player_id] = {
            "predicted_points": round(float(max(exp, 0.0)), 2),
            "play_probability": round(float(prob), 3),
            "points_if_plays": round(float(max(cond, 0.0)), 2),
            "confidence": confidence,
            "basis": basis,
            "gameweeks_of_history": int(games),
        }
    return out


def model_info() -> Dict:
    """Describe the loaded model, for /api/health and tool rationale text."""
    bundle = load_bundle()
    if bundle is None:
        return {"available": False, "path": str(MODEL_PATH)}
    return {
        "available": True,
        "version": "v2",
        "architecture": "two-stage hurdle: P(plays>=60min) x expm1(log1p-points regressor)",
        "n_features": len(bundle["features"]),
        "plays_threshold_minutes": bundle.get("plays_threshold"),
        "trained_on": "real per-GW outcomes, 2023-24..2025-26 (84,577 player-gameweeks)",
        "validation": "rolling-origin, regulars only: MAE 2.033, spearman 0.333; "
                      "top-3 picks averaged 5.52 actual pts vs 4.00 for naive form",
        "known_limits": "predictions compress on hauls (ranks well, does not size hauls); "
                        "pre-season predictions use season-total fallback (confidence=low)",
    }
