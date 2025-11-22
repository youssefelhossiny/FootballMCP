import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import accuracy_score, classification_report, mean_squared_error
import joblib


def train_result_classifier(df):
    """Train a model to predict match result (Win/Draw/Loss)"""

    print("\n🎯 Training Result Classifier...")

    # Features for prediction
    feature_cols = [
        "home_goals_scored_avg", "home_goals_conceded_avg", "home_form",
        "home_wins", "home_draws", "home_losses",
        "away_goals_scored_avg", "away_goals_conceded_avg", "away_form",
        "away_wins", "away_draws", "away_losses",
        "h2h_home_wins", "h2h_away_wins", "h2h_draws"
    ]

    X = df[feature_cols]
    y = df["result"]

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    # Train Random Forest Classifier
    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=10,
        min_samples_split=10,
        random_state=42,
        class_weight='balanced'
    )

    model.fit(X_train, y_train)

    # Evaluate
    y_pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)

    print(f"   ✅ Accuracy: {accuracy:.2%}")
    print("\n   Classification Report:")
    print(classification_report(y_test, y_pred))

    # Feature importance
    importance = pd.DataFrame({
        'feature': feature_cols,
        'importance': model.feature_importances_
    }).sort_values('importance', ascending=False)

    print("\n   Top 5 Most Important Features:")
    for idx, row in importance.head(5).iterrows():
        print(f"      {row['feature']}: {row['importance']:.3f}")

    return model, feature_cols


def train_goals_predictor(df):
    """Train models to predict home and away goals"""

    print("\n⚽ Training Goals Predictor...")

    feature_cols = [
        "home_goals_scored_avg", "home_goals_conceded_avg", "home_form",
        "away_goals_scored_avg", "away_goals_conceded_avg", "away_form",
        "h2h_home_wins", "h2h_away_wins", "h2h_draws"
    ]

    X = df[feature_cols]

    # Train separate models for home and away goals
    y_home = df["home_goals"]
    y_away = df["away_goals"]

    # Split data
    X_train, X_test, y_home_train, y_home_test, y_away_train, y_away_test = train_test_split(
        X, y_home, y_away, test_size=0.2, random_state=42
    )

    # Home goals model
    home_model = RandomForestRegressor(
        n_estimators=200,
        max_depth=8,
        min_samples_split=10,
        random_state=42
    )
    home_model.fit(X_train, y_home_train)

    # Away goals model
    away_model = RandomForestRegressor(
        n_estimators=200,
        max_depth=8,
        min_samples_split=10,
        random_state=42
    )
    away_model.fit(X_train, y_away_train)

    # Evaluate
    home_pred = home_model.predict(X_test)
    away_pred = away_model.predict(X_test)

    home_rmse = np.sqrt(mean_squared_error(y_home_test, home_pred))
    away_rmse = np.sqrt(mean_squared_error(y_away_test, away_pred))

    print(f"   ✅ Home Goals RMSE: {home_rmse:.3f}")
    print(f"   ✅ Away Goals RMSE: {away_rmse:.3f}")

    return home_model, away_model, feature_cols


def main():
    """Main training function"""

    print("⚽ Soccer Match Prediction - Model Training")
    print("=" * 50)

    # Load training data
    try:
        df = pd.read_csv("training_data.csv")
        print(f"\n✅ Loaded {len(df)} training samples")
    except FileNotFoundError:
        print("\n❌ training_data.csv not found!")
        print("   Run 'python collect_training_data.py' first to collect data.")
        return

    # Train result classifier
    result_model, result_features = train_result_classifier(df)

    # Train goals predictor
    home_goals_model, away_goals_model, goals_features = train_goals_predictor(df)

    # Save models
    print("\n💾 Saving models...")

    joblib.dump(result_model, "../models/result_classifier.pkl")
    joblib.dump(home_goals_model, "../models/home_goals_predictor.pkl")
    joblib.dump(away_goals_model, "../models/away_goals_predictor.pkl")

    # Save feature lists
    with open("../models/result_features.txt", "w") as f:
        f.write("\n".join(result_features))

    with open("../models/goals_features.txt", "w") as f:
        f.write("\n".join(goals_features))

    print("   ✅ Saved result_classifier.pkl")
    print("   ✅ Saved home_goals_predictor.pkl")
    print("   ✅ Saved away_goals_predictor.pkl")

    print("\n✅ Model training complete!")
    print("\n📝 Next steps:")
    print("   1. Test predictions with: python test_predictions.py")
    print("   2. Add prediction tool to your MCP server")


if __name__ == "__main__":
    # Create models directory if it doesn't exist
    import os

    os.makedirs("../models", exist_ok=True)

    main()