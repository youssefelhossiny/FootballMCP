import pandas as pd
import numpy as np
import joblib


def load_models():
    """Load trained models"""
    result_model = joblib.load("../models/result_classifier.pkl")
    home_goals_model = joblib.load("../models/home_goals_predictor.pkl")
    away_goals_model = joblib.load("../models/away_goals_predictor.pkl")

    with open("../models/result_features.txt", "r") as f:
        result_features = [line.strip() for line in f.readlines()]

    with open("../models/goals_features.txt", "r") as f:
        goals_features = [line.strip() for line in f.readlines()]

    return result_model, home_goals_model, away_goals_model, result_features, goals_features


def predict_match(home_team_stats, away_team_stats, h2h_stats, models):
    """Make a prediction for a match"""

    result_model, home_goals_model, away_goals_model, result_features, goals_features = models

    # Prepare result prediction features
    result_input = pd.DataFrame([{
        "home_goals_scored_avg": home_team_stats["goals_scored_avg"],
        "home_goals_conceded_avg": home_team_stats["goals_conceded_avg"],
        "home_form": home_team_stats["form"],
        "home_wins": home_team_stats["wins"],
        "home_draws": home_team_stats["draws"],
        "home_losses": home_team_stats["losses"],
        "away_goals_scored_avg": away_team_stats["goals_scored_avg"],
        "away_goals_conceded_avg": away_team_stats["goals_conceded_avg"],
        "away_form": away_team_stats["form"],
        "away_wins": away_team_stats["wins"],
        "away_draws": away_team_stats["draws"],
        "away_losses": away_team_stats["losses"],
        "h2h_home_wins": h2h_stats["home_wins"],
        "h2h_away_wins": h2h_stats["away_wins"],
        "h2h_draws": h2h_stats["draws"]
    }])

    # Prepare goals prediction features
    goals_input = pd.DataFrame([{
        "home_goals_scored_avg": home_team_stats["goals_scored_avg"],
        "home_goals_conceded_avg": home_team_stats["goals_conceded_avg"],
        "home_form": home_team_stats["form"],
        "away_goals_scored_avg": away_team_stats["goals_scored_avg"],
        "away_goals_conceded_avg": away_team_stats["goals_conceded_avg"],
        "away_form": away_team_stats["form"],
        "h2h_home_wins": h2h_stats["home_wins"],
        "h2h_away_wins": h2h_stats["away_wins"],
        "h2h_draws": h2h_stats["draws"]
    }])

    # Get predictions
    result_proba = result_model.predict_proba(result_input[result_features])[0]
    result_pred = result_model.predict(result_input[result_features])[0]

    home_goals_pred = home_goals_model.predict(goals_input[goals_features])[0]
    away_goals_pred = away_goals_model.predict(goals_input[goals_features])[0]

    # Map probabilities to labels
    classes = result_model.classes_
    proba_dict = {cls: prob for cls, prob in zip(classes, result_proba)}

    return {
        "predicted_result": result_pred,
        "home_win_probability": proba_dict.get("HOME_WIN", 0),
        "draw_probability": proba_dict.get("DRAW", 0),
        "away_win_probability": proba_dict.get("AWAY_WIN", 0),
        "predicted_home_goals": round(home_goals_pred, 1),
        "predicted_away_goals": round(away_goals_pred, 1)
    }


def main():
    """Test the prediction models"""

    print("⚽ Soccer Match Prediction - Testing")
    print("=" * 50)

    # Load models
    print("\n📥 Loading models...")
    models = load_models()
    print("   ✅ Models loaded successfully")

    # Example prediction
    print("\n🎯 Example Prediction: Strong Home Team vs Weak Away Team")
    print("=" * 50)

    # Simulate a strong home team
    home_team_stats = {
        "goals_scored_avg": 2.5,
        "goals_conceded_avg": 0.8,
        "form": 0.8,  # 80% form
        "wins": 4,
        "draws": 1,
        "losses": 0
    }

    # Simulate a weak away team
    away_team_stats = {
        "goals_scored_avg": 1.0,
        "goals_conceded_avg": 2.2,
        "form": 0.3,  # 30% form
        "wins": 1,
        "draws": 1,
        "losses": 3
    }

    # Head-to-head history favoring home team
    h2h_stats = {
        "home_wins": 3,
        "away_wins": 1,
        "draws": 1
    }

    prediction = predict_match(home_team_stats, away_team_stats, h2h_stats, models)

    print("\n📊 Prediction Results:")
    print(f"   Most Likely Result: {prediction['predicted_result']}")
    print(f"\n   Win Probabilities:")
    print(f"      Home Win: {prediction['home_win_probability']:.1%}")
    print(f"      Draw: {prediction['draw_probability']:.1%}")
    print(f"      Away Win: {prediction['away_win_probability']:.1%}")
    print(f"\n   Expected Goals:")
    print(f"      Home Team: {prediction['predicted_home_goals']} goals")
    print(f"      Away Team: {prediction['predicted_away_goals']} goals")

    # Example 2: Evenly matched teams
    print("\n\n🎯 Example Prediction: Evenly Matched Teams")
    print("=" * 50)

    balanced_home = {
        "goals_scored_avg": 1.6,
        "goals_conceded_avg": 1.4,
        "form": 0.55,
        "wins": 2,
        "draws": 2,
        "losses": 1
    }

    balanced_away = {
        "goals_scored_avg": 1.5,
        "goals_conceded_avg": 1.5,
        "form": 0.50,
        "wins": 2,
        "draws": 1,
        "losses": 2
    }

    balanced_h2h = {
        "home_wins": 2,
        "away_wins": 2,
        "draws": 1
    }

    prediction2 = predict_match(balanced_home, balanced_away, balanced_h2h, models)

    print("\n📊 Prediction Results:")
    print(f"   Most Likely Result: {prediction2['predicted_result']}")
    print(f"\n   Win Probabilities:")
    print(f"      Home Win: {prediction2['home_win_probability']:.1%}")
    print(f"      Draw: {prediction2['draw_probability']:.1%}")
    print(f"      Away Win: {prediction2['away_win_probability']:.1%}")
    print(f"\n   Expected Goals:")
    print(f"      Home Team: {prediction2['predicted_home_goals']} goals")
    print(f"      Away Team: {prediction2['predicted_away_goals']} goals")

    print("\n\n✅ Model testing complete!")
    print("\n📝 Next step: Add predict_match tool to your MCP server")


if __name__ == "__main__":
    main()