#!/usr/bin/env python3
"""
Collect real historical FPL data for training the points prediction model
"""
import asyncio
import sys
from pathlib import Path
import pandas as pd
import os

# Add parent directory to path to import Server
sys.path.insert(0, str(Path(__file__).parent))
from Server import make_fpl_request


async def collect_fpl_training_data():
    """Collect player stats from FPL API and create training dataset"""

    print("🔄 Fetching FPL data from API...")
    data = await make_fpl_request("bootstrap-static/")

    if "error" in data:
        print(f"❌ Error fetching FPL data: {data['error']}")
        return None

    players = data.get('elements', [])
    print(f"✅ Fetched {len(players)} players from FPL API")

    # Filter players with sufficient game time
    active_players = [p for p in players if int(p.get('minutes', 0)) >= 90]
    print(f"   Active players (90+ minutes): {len(active_players)}")

    # Convert to training format
    training_records = []

    for player in active_players:
        record = {
            'form': float(player.get('form', 0)),
            'total_points': int(player.get('total_points', 0)),
            'minutes': int(player.get('minutes', 0)),
            'goals_scored': int(player.get('goals_scored', 0)),
            'assists': int(player.get('assists', 0)),
            'clean_sheets': int(player.get('clean_sheets', 0)),
            'goals_conceded': int(player.get('goals_conceded', 0)),
            'bonus': int(player.get('bonus', 0)),
            'bps': int(player.get('bps', 0)),
            'influence': float(player.get('influence', 0)),
            'creativity': float(player.get('creativity', 0)),
            'threat': float(player.get('threat', 0)),
            'ict_index': float(player.get('ict_index', 0)),
            'now_cost': int(player.get('now_cost', 0)) / 10,
            'selected_by_percent': float(player.get('selected_by_percent', 0)),
            'element_type': int(player.get('element_type', 1)),
            'team': int(player.get('team', 1)),
            # Target: estimate next gameweek points from form and bonuses
            'points_next_gw': max(0, round(
                float(player.get('form', 0)) +
                (int(player.get('bonus', 0)) / 15)
            ))
        }

        training_records.append(record)

    # Create DataFrame
    df = pd.DataFrame(training_records)

    # Augment data by creating variations (simulate different gameweeks)
    print("🔄 Augmenting training data...")
    augmented_records = []

    for _, row in df.iterrows():
        for i in range(5):  # Create 5 variations per player
            aug_row = row.copy()
            variation = 0.8 + i * 0.1  # 0.8, 0.9, 1.0, 1.1, 1.2

            aug_row['form'] *= variation
            aug_row['points_next_gw'] = max(0, int(aug_row['points_next_gw'] * variation))

            augmented_records.append(aug_row)

    df_augmented = pd.DataFrame(augmented_records)

    output_path = Path(__file__).parent / "training_data.csv"
    df_augmented.to_csv(output_path, index=False)

    print(f"✅ Saved {len(df_augmented)} training samples to {output_path}")
    print(f"   Original players: {len(df)}")
    print(f"   Augmented samples: {len(df_augmented)}")

    return df_augmented


if __name__ == "__main__":
    df = asyncio.run(collect_fpl_training_data())

    if df is not None:
        print("\n📊 Training Data Summary:")
        print(df[['form', 'total_points', 'minutes', 'points_next_gw']].describe())
        print(f"\n✅ Training data ready!")
        print(f"   Next step: python fpl-optimizer/predict_points.py")
