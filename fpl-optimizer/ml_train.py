#!/usr/bin/env python3
"""
Retrain the FPL next-gameweek points model on REAL historical outcomes.

Replaces the previous model, which was trained on a synthetic label computed
from the same snapshot's own features (see collect_fpl_training_data.py) and
therefore only re-learned its own label formula.

Everything here is driven by measurements recorded in ROADMAP.md Task 3:

- Label: real `total_points` at GW N+1 (never a formula).
- Data: vaastav/Fantasy-Premier-League per-GW CSVs. Three seasons
  (2023-24 .. 2025-26). Measured: 1->2 seasons is a large gain
  (+0.031 spearman), 2->3 marginal, 3->4 flat, so history stops at 3.
- Features: rolling means over 1/3/5/10 prior gameweeks of the rule-stable
  FPL fields. Measured: the 1-game window matters (adding it took spearman
  0.3174 -> 0.3280); xG/xA add nothing once these are present (0.3259 vs
  0.3280) and DefCon features *hurt* (0.3098), so both are excluded. This
  is deliberately a SMALLER feature set than the 61-feature predecessor.
- Architecture: two-stage hurdle. The target is ~64% zeros overall, driven
  mostly by players who don't play; P(plays) and E[points | plays] are
  different problems, so they get different models.
- Evaluation: rolling-origin (expanding-window) validation on real held-out
  future gameweeks. Headline metrics are reported on REGULARS, because
  including non-playing players inflates ranking metrics by rewarding the
  trivial "benched player scores 0" call (spearman 0.72 all-rows vs 0.26
  regulars for the same predictor).

Metrics: MAE plus Spearman and haul-AUC. MAE alone is misleading here —
always-predicting-0 scores MAE 1.15 on the full population, better than
several "real" predictors — and FPL decisions are rankings, not point
estimates.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import joblib
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor, HistGradientBoostingClassifier
from sklearn.metrics import mean_absolute_error, roc_auc_score

SEASONS = ["2023-24", "2024-25", "2025-26"]
TARGET_SEASON = "2025-26"

# Rule-stable across all three seasons. Deliberately excludes xG/xA (no
# measured benefit, and absent before 2022-23) and the DefCon columns
# (2025-26 only, measured to hurt when null-filled for earlier seasons).
BASE_COLS = [
    "total_points", "minutes", "bps", "ict_index",
    "influence", "creativity", "threat",
]
WINDOWS = [1, 3, 5, 10]
REGULAR_MIN_AVG_MINUTES = 45   # "would you actually consider transferring them in"
PLAYS_THRESHOLD = 60           # minutes; also the FPL appearance-points boundary

DATA_DIR = Path(__file__).parent / "cache" / "backtest" / "seasons"
MODEL_DIR = Path(__file__).parent.parent / "models"

REG_PARAMS = dict(max_iter=400, learning_rate=0.05, max_depth=3,
                  l2_regularization=1.0, min_samples_leaf=60, random_state=0)
CLF_PARAMS = dict(max_iter=300, learning_rate=0.05, max_depth=4,
                  l2_regularization=1.0, min_samples_leaf=40, random_state=0)


def featurize(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rolling-window features from strictly-prior gameweeks.

    Every rolling stat is .shift(1) before .rolling() so a row can never see
    its own gameweek — the classic leakage bug in this kind of pipeline.
    """
    df = df.sort_values(["element", "GW"]).copy()
    grouped = df.groupby("element")

    for window in WINDOWS:
        for col in BASE_COLS:
            df[f"{col}_l{window}"] = grouped[col].transform(
                lambda s: s.shift(1).rolling(window, min_periods=1).mean()
            )

    df["avg_min"] = grouped["minutes"].transform(lambda s: s.shift(1).expanding().mean())
    df["games_so_far"] = grouped["minutes"].transform(lambda s: s.shift(1).expanding().count())
    df["price"] = df["value"] / 10
    df["pos"] = df["position"].map({"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}).fillna(3).astype(int)

    # Targets
    df["next_pts"] = grouped["total_points"].shift(-1)
    df["next_minutes"] = grouped["minutes"].shift(-1)
    return df


FEATURES = [f"{c}_l{w}" for w in WINDOWS for c in BASE_COLS] + ["price", "pos", "avg_min", "games_so_far"]


def load_seasons() -> dict:
    out = {}
    for season in SEASONS:
        path = DATA_DIR / f"{season}.csv"
        if not path.exists():
            raise FileNotFoundError(f"Missing {path} — fetch vaastav merged_gw.csv for {season}")
        df = pd.read_csv(path)
        df["season"] = season
        out[season] = featurize(df)
    return out


def fit_hurdle(train: pd.DataFrame):
    """
    Stage 1: P(plays >= PLAYS_THRESHOLD minutes).
    Stage 2: E[points | played], fit only on rows where they actually played.
    Prediction = P(plays) * E[points | plays].

    Stage 2 regresses log1p(points) rather than raw points. Measured: MAE
    2.132 -> 2.036 (-4.6%) with top-3-pick quality slightly up. Points are
    heavy-tailed (most 0-2, rare 20+); squared error on the raw scale lets a
    handful of hauls dominate the fit, and the log scale tempers that.
    """
    X = train[FEATURES].fillna(0)

    plays = (train["next_minutes"] >= PLAYS_THRESHOLD).astype(int)
    clf = HistGradientBoostingClassifier(**CLF_PARAMS).fit(X, plays)

    played = train[train["next_minutes"] >= PLAYS_THRESHOLD]
    y = np.log1p(played["next_pts"].clip(lower=0))
    reg = HistGradientBoostingRegressor(**REG_PARAMS).fit(played[FEATURES].fillna(0), y)
    return clf, reg


def predict_hurdle(clf, reg, df: pd.DataFrame) -> np.ndarray:
    """Invert the log1p from fit_hurdle's stage 2 before combining."""
    X = df[FEATURES].fillna(0)
    return clf.predict_proba(X)[:, 1] * np.expm1(reg.predict(X))


def fit_direct(train: pd.DataFrame) -> HistGradientBoostingRegressor:
    """Single-stage regressor, kept as the comparison arm for the hurdle."""
    return HistGradientBoostingRegressor(**REG_PARAMS).fit(
        train[FEATURES].fillna(0), train["next_pts"]
    )


def evaluate(preds: np.ndarray, truth: pd.Series) -> dict:
    haul = (truth >= 9).astype(int)
    return {
        "mae": float(mean_absolute_error(truth, preds)),
        "spearman": float(spearmanr(preds, truth).correlation),
        "haul_auc": float(roc_auc_score(haul, preds)) if haul.nunique() > 1 else float("nan"),
    }


def rolling_origin_validation(frames: dict) -> dict:
    """
    Expanding-window validation: train on everything up to GW `cut` (plus all
    prior seasons), test on the next 5 gameweeks. Never trains on the future.
    """
    current = frames[TARGET_SEASON].dropna(subset=["next_pts", "next_minutes"])
    history = pd.concat([
        frames[s].dropna(subset=["next_pts", "next_minutes"])
        for s in SEASONS if s != TARGET_SEASON
    ])

    # FPL's own `xP` is deliberately not used as a baseline: in this dataset
    # it is zero for every row between GW11-20 and mostly zero afterwards
    # (5099/29757 nonzero overall), i.e. the upstream collector stopped
    # capturing it. Scoring against it would report a meaningless number.
    arms = {k: [] for k in ("hurdle", "direct", "form_l5", "last_gw")}
    folds = []

    for cut in [20, 24, 28, 32]:
        train = pd.concat([current[current.GW <= cut], history])
        test = current[(current.GW > cut + 1) & (current.GW <= cut + 5)]
        test = test[test["avg_min"] > REGULAR_MIN_AVG_MINUTES]
        if len(test) < 200:
            continue

        clf, reg = fit_hurdle(train)
        direct = fit_direct(train)
        truth = test["next_pts"]

        arms["hurdle"].append(evaluate(predict_hurdle(clf, reg, test), truth))
        arms["direct"].append(evaluate(direct.predict(test[FEATURES].fillna(0)), truth))
        arms["form_l5"].append(evaluate(test["total_points_l5"].fillna(0), truth))
        arms["last_gw"].append(evaluate(test["total_points_l1"].fillna(0), truth))

        folds.append({
            "cut": cut,
            "n_test": int(len(test)),
            "n_train": int(len(train)),
            "per_arm": {name: results[-1] for name, results in arms.items() if results},
        })

    summary = {}
    for name, results in arms.items():
        if not results:
            continue
        summary[name] = {
            metric: round(float(np.mean([r[metric] for r in results])), 4)
            for metric in ("mae", "spearman", "haul_auc")
        }
    return {"folds": folds, "metrics": summary}


def main():
    print("Loading + featurizing seasons:", ", ".join(SEASONS))
    frames = load_seasons()
    for season, df in frames.items():
        print(f"  {season}: {len(df):>6} player-gameweeks")

    print("\nRolling-origin validation (headline = REGULARS only)")
    report = rolling_origin_validation(frames)
    for fold in report["folds"]:
        per = fold["per_arm"]
        print(f"  fold GW<={fold['cut']:<3} train={fold['n_train']:>6} test={fold['n_test']:>5}  "
              f"hurdle sp={per['hurdle']['spearman']:.4f}  direct sp={per['direct']['spearman']:.4f}  "
              f"form sp={per['form_l5']['spearman']:.4f}")

    print(f"\n{'arm':<12} {'MAE':>8} {'spearman':>10} {'haul_AUC':>10}")
    for name, metrics in report["metrics"].items():
        print(f"{name:<12} {metrics['mae']:>8.4f} {metrics['spearman']:>10.4f} {metrics['haul_auc']:>10.4f}")

    # Final fit on everything available, for deployment.
    all_rows = pd.concat([f.dropna(subset=["next_pts", "next_minutes"]) for f in frames.values()])
    print(f"\nFinal fit on {len(all_rows)} rows")
    clf, reg = fit_hurdle(all_rows)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    # `regressor_target: "log1p"` is load-bearing: the regressor predicts
    # log1p(points), so any consumer MUST apply expm1 before combining with
    # the classifier probability. Omitting it would silently under-predict.
    joblib.dump({"classifier": clf, "regressor": reg, "features": FEATURES,
                 "plays_threshold": PLAYS_THRESHOLD,
                 "regressor_target": "log1p",
                 "predict": "expm1(regressor) * P(plays)"},
                MODEL_DIR / "points_model_v2.pkl")
    (MODEL_DIR / "features_v2.txt").write_text("\n".join(FEATURES))
    (MODEL_DIR / "backtest_report_v2.json").write_text(json.dumps(report, indent=2))
    print(f"Saved -> {MODEL_DIR / 'points_model_v2.pkl'}")
    print(f"Saved -> {MODEL_DIR / 'features_v2.txt'} ({len(FEATURES)} features)")
    print(f"Saved -> {MODEL_DIR / 'backtest_report_v2.json'}")


if __name__ == "__main__":
    main()
