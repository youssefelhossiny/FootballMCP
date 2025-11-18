import os
import asyncio
import httpx
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
import json

load_dotenv()

API_KEY = os.getenv("FOOTBALL_DATA_API_KEY")
API_BASE_URL = "https://api.football-data.org/v4"


async def fetch_matches(competition_code="PL", seasons=None):
    """Fetch historical matches for training data"""

    if seasons is None:
        # Get last few seasons of data
        current_year = datetime.now().year
        seasons = [current_year - i for i in range(1, 4)]  # Last 3 years

    headers = {"X-Auth-Token": API_KEY}
    all_matches = []

    async with httpx.AsyncClient() as client:
        for season in seasons:
            print(f"\n📥 Fetching {season}/{season + 1} season data...")

            try:
                # Fetch matches for the season
                response = await client.get(
                    f"{API_BASE_URL}/competitions/{competition_code}/matches",
                    headers=headers,
                    params={
                        "season": season,
                        "status": "FINISHED"
                    },
                    timeout=15.0
                )

                if response.status_code == 200:
                    data = response.json()
                    matches = data.get("matches", [])
                    print(f"   ✅ Found {len(matches)} finished matches")
                    all_matches.extend(matches)

                    # Rate limiting - wait between requests
                    await asyncio.sleep(6)  # 10 requests per minute = wait 6 seconds

                elif response.status_code == 403:
                    print(f"   ⚠️  Season {season} not available on free tier")
                else:
                    print(f"   ❌ Error: {response.status_code}")

            except Exception as e:
                print(f"   ❌ Error fetching season {season}: {e}")

    return all_matches


def process_matches_to_dataframe(matches):
    """Convert raw match data to training dataset"""

    processed_data = []

    for match in matches:
        if match["status"] != "FINISHED":
            continue

        home_team = match["homeTeam"]["name"]
        away_team = match["awayTeam"]["name"]

        score = match.get("score", {}).get("fullTime", {})
        home_goals = score.get("home")
        away_goals = score.get("away")

        if home_goals is None or away_goals is None:
            continue

        # Determine result
        if home_goals > away_goals:
            result = "HOME_WIN"
        elif away_goals > home_goals:
            result = "AWAY_WIN"
        else:
            result = "DRAW"

        match_date = datetime.fromisoformat(match["utcDate"].replace("Z", "+00:00"))

        processed_data.append({
            "date": match_date.date(),
            "home_team": home_team,
            "away_team": away_team,
            "home_goals": home_goals,
            "away_goals": away_goals,
            "result": result,
            "matchday": match.get("matchday"),
            "season": match.get("season", {}).get("startDate", "")[:4]
        })

    df = pd.DataFrame(processed_data)
    df = df.sort_values("date")

    return df


def calculate_team_features(df, team_name, date, lookback_matches=5):
    """Calculate features for a team based on recent matches"""

    # Get recent matches before this date
    recent_matches = df[
        (df["date"] < date) &
        ((df["home_team"] == team_name) | (df["away_team"] == team_name))
        ].tail(lookback_matches)

    if len(recent_matches) == 0:
        return {
            "goals_scored_avg": 0,
            "goals_conceded_avg": 0,
            "points": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "form": 0  # Ensure 'form' is included in the default dictionary
        }

    goals_scored = []
    goals_conceded = []
    points = 0
    wins = 0
    draws = 0
    losses = 0

    for _, match in recent_matches.iterrows():
        if match["home_team"] == team_name:
            goals_scored.append(match["home_goals"])
            goals_conceded.append(match["away_goals"])

            if match["result"] == "HOME_WIN":
                points += 3
                wins += 1
            elif match["result"] == "DRAW":
                points += 1
                draws += 1
            else:
                losses += 1
        else:
            goals_scored.append(match["away_goals"])
            goals_conceded.append(match["home_goals"])

            if match["result"] == "AWAY_WIN":
                points += 3
                wins += 1
            elif match["result"] == "DRAW":
                points += 1
                draws += 1
            else:
                losses += 1

    return {
        "goals_scored_avg": sum(goals_scored) / len(goals_scored),
        "goals_conceded_avg": sum(goals_conceded) / len(goals_conceded),
        "points": points,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "form": points / (len(recent_matches) * 3)  # Normalized form score
    }


def create_ml_features(df):
    """Create machine learning features from match data"""

    ml_data = []

    print("\n🔧 Creating ML features...")

    for idx, match in df.iterrows():
        if idx % 50 == 0:
            print(f"   Processing match {idx}/{len(df)}...")

        home_features = calculate_team_features(df, match["home_team"], match["date"])
        away_features = calculate_team_features(df, match["away_team"], match["date"])

        # Head-to-head features
        h2h_matches = df[
            (df["date"] < match["date"]) &
            (((df["home_team"] == match["home_team"]) & (df["away_team"] == match["away_team"])) |
             ((df["home_team"] == match["away_team"]) & (df["away_team"] == match["home_team"])))
            ].tail(5)

        h2h_home_wins = 0
        h2h_away_wins = 0
        h2h_draws = 0

        for _, h2h in h2h_matches.iterrows():
            if h2h["home_team"] == match["home_team"]:
                if h2h["result"] == "HOME_WIN":
                    h2h_home_wins += 1
                elif h2h["result"] == "AWAY_WIN":
                    h2h_away_wins += 1
                else:
                    h2h_draws += 1
            else:
                if h2h["result"] == "HOME_WIN":
                    h2h_away_wins += 1
                elif h2h["result"] == "AWAY_WIN":
                    h2h_home_wins += 1
                else:
                    h2h_draws += 1

        ml_data.append({
            # Target variables
            "home_goals": match["home_goals"],
            "away_goals": match["away_goals"],
            "result": match["result"],

            # Home team features
            "home_goals_scored_avg": home_features["goals_scored_avg"],
            "home_goals_conceded_avg": home_features["goals_conceded_avg"],
            "home_form": home_features["form"],
            "home_wins": home_features["wins"],
            "home_draws": home_features["draws"],
            "home_losses": home_features["losses"],

            # Away team features
            "away_goals_scored_avg": away_features["goals_scored_avg"],
            "away_goals_conceded_avg": away_features["goals_conceded_avg"],
            "away_form": away_features["form"],
            "away_wins": away_features["wins"],
            "away_draws": away_features["draws"],
            "away_losses": away_features["losses"],

            # Head-to-head
            "h2h_home_wins": h2h_home_wins,
            "h2h_away_wins": h2h_away_wins,
            "h2h_draws": h2h_draws,

            # Match metadata
            "home_team": match["home_team"],
            "away_team": match["away_team"],
            "date": match["date"]
        })

    return pd.DataFrame(ml_data)


async def main():
    """Main function to collect and process training data"""

    print("⚽ Soccer Match Prediction - Data Collection")
    print("=" * 50)

    # Fetch matches
    matches = await fetch_matches(competition_code="PL")

    if not matches:
        print("\n❌ No matches found. Check your API key and try again.")
        return

    print(f"\n✅ Total matches fetched: {len(matches)}")

    # Process to DataFrame
    df_matches = process_matches_to_dataframe(matches)
    print(f"\n✅ Processed {len(df_matches)} matches into dataset")

    # Create ML features
    df_ml = create_ml_features(df_matches)

    # Remove rows with missing values (first few matches without history)
    df_ml = df_ml.dropna()

    print(f"\n✅ Created {len(df_ml)} training samples with features")

    # Save to CSV
    df_ml.to_csv("training_data.csv", index=False)
    print(f"\n💾 Saved training data to: training_data.csv")

    # Print summary statistics
    print("\n📊 Dataset Summary:")
    print(f"   Date range: {df_ml['date'].min()} to {df_ml['date'].max()}")
    print(f"   Results distribution:")
    print(f"      Home wins: {(df_ml['result'] == 'HOME_WIN').sum()}")
    print(f"      Draws: {(df_ml['result'] == 'DRAW').sum()}")
    print(f"      Away wins: {(df_ml['result'] == 'AWAY_WIN').sum()}")
    print(f"\n   Average goals per match: {df_ml[['home_goals', 'away_goals']].sum().sum() / len(df_ml):.2f}")

    print("\n✅ Data collection complete! Ready to train the model.")


if __name__ == "__main__":
    asyncio.run(main())