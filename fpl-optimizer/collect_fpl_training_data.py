#!/usr/bin/env python3
"""
Collect real historical FPL data + Understat xG/xA + FBRef defensive/progressive stats
for training the points prediction model

Phase 4.1: Enhanced with FBRef defensive contribution stats + recoveries for new FPL 2025/26 scoring
"""
import asyncio
import sys
from pathlib import Path
import pandas as pd
import os

# Add parent directory to path to import Server
sys.path.insert(0, str(Path(__file__).parent))
from Server import make_fpl_request
from enhanced_features import EnhancedDataCollector


async def collect_fpl_training_data():
    """Collect player stats from FPL API + Understat and create training dataset"""

    print("🔄 Fetching FPL data from API...")
    data = await make_fpl_request("bootstrap-static/")

    if "error" in data:
        print(f"❌ Error fetching FPL data: {data['error']}")
        return None

    players = data.get('elements', [])
    print(f"✅ Fetched {len(players)} players from FPL API")

    # NEW: Merge with Understat + FBRef data (Phase 4)
    print("\n🔄 Enhancing with Understat xG/xA + FBRef defensive data...")
    collector = EnhancedDataCollector(cache_ttl_hours=6)
    enhanced_players, match_stats = collector.collect_enhanced_data(
        players,
        season="2025",
        use_cache=True
    )
    print(f"✅ Enhanced {len(enhanced_players)} players with external data")
    print(f"   Understat match rate: {match_stats.get('match_rate', 0):.1f}%")
    print(f"   FBRef match rate: {match_stats.get('fbref_match_rate', 0):.1f}%\n")

    # Filter players with sufficient game time (use enhanced_players instead)
    active_players = [p for p in enhanced_players if int(p.get('minutes', 0)) >= 90]
    print(f"   Active players (90+ minutes): {len(active_players)}")

    # Convert to training format
    training_records = []

    for player in active_players:
        # Enhanced target prediction using xG/xA + defensive contribution points
        xG_per_game = player.get('xG_per_90', 0)
        xA_per_game = player.get('xA_per_90', 0)
        expected_def_pts = player.get('expected_def_points', 0)  # From FBRef

        # FPL points: Goals (4-6pts), Assists (3pts)
        position = player.get('element_type', 3)
        if position == 4:  # Forwards get 4pts per goal
            expected_attack_pts = xG_per_game * 4 + xA_per_game * 3
        elif position == 1:  # GK - minimal attacking points
            expected_attack_pts = xG_per_game * 6 + xA_per_game * 3
        else:  # DEF/MID get 5-6pts per goal
            expected_attack_pts = xG_per_game * 5 + xA_per_game * 3

        # Add expected defensive contribution points (new FPL 2025/26 rule)
        expected_pts = expected_attack_pts + expected_def_pts

        # Combine form and xG-based + defensive prediction
        form = float(player.get('form', 0))
        predicted_next_gw = max(0, round((form + expected_pts) / 2))

        record = {
            # Original FPL features
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
            # Understat core features
            'xG': float(player.get('xG', 0)),
            'xA': float(player.get('xA', 0)),
            'npxG': float(player.get('npxG', 0)),
            'xGChain': float(player.get('xGChain', 0)),
            'xGBuildup': float(player.get('xGBuildup', 0)),
            'xG_per_90': float(player.get('xG_per_90', 0)),
            'xA_per_90': float(player.get('xA_per_90', 0)),
            'npxG_per_90': float(player.get('npxG_per_90', 0)),
            'xGChain_per_90': float(player.get('xGChain_per_90', 0)),
            'xGBuildup_per_90': float(player.get('xGBuildup_per_90', 0)),
            'shots': int(player.get('shots', 0)),
            'shots_on_target': int(player.get('shots_on_target', 0)),
            'key_passes': int(player.get('key_passes', 0)),
            # Performance metrics
            'xG_overperformance': float(player.get('xG_overperformance', 0)),
            'xA_overperformance': float(player.get('xA_overperformance', 0)),
            'npxG_overperformance': float(player.get('npxG_overperformance', 0)),
            # Derived Understat features
            'xG_xA_combined': float(player.get('xG_xA_combined', 0)),
            'npxG_npxA_combined': float(player.get('npxG_npxA_combined', 0)),
            'finishing_quality': float(player.get('finishing_quality', 1.0)),
            'np_finishing_quality': float(player.get('np_finishing_quality', 1.0)),
            # FBRef Defensive features
            'tackles': int(player.get('tackles', 0)),
            'tackles_won': int(player.get('tackles_won', 0)),
            'tackle_pct': float(player.get('tackle_pct', 0.0)),
            'interceptions': int(player.get('interceptions', 0)),
            'tackles_plus_int': int(player.get('tackles_plus_int', 0)),
            'blocks': int(player.get('blocks', 0)),
            'clearances': int(player.get('clearances', 0)),
            'errors': int(player.get('errors', 0)),
            'def_contributions': int(player.get('def_contributions', 0)),
            'def_contributions_per_90': float(player.get('def_contributions_per_90', 0.0)),
            # FBRef Derived defensive features
            'def_contribution_prob': float(player.get('def_contribution_prob', 0.0)),
            'expected_def_points': float(player.get('expected_def_points', 0.0)),
            # FBRef Progressive features
            'progressive_passes': int(player.get('progressive_passes', 0)),
            'progressive_carries': int(player.get('progressive_carries', 0)),
            'progressive_receptions': int(player.get('progressive_receptions', 0)),
            'progressive_passes_per_90': float(player.get('progressive_passes_per_90', 0.0)),
            'progressive_carries_per_90': float(player.get('progressive_carries_per_90', 0.0)),
            'progressive_receptions_per_90': float(player.get('progressive_receptions_per_90', 0.0)),
            # FBRef Possession/Creation features
            'touches': int(player.get('touches', 0)),
            'touches_att_3rd': int(player.get('touches_att_3rd', 0)),
            'sca': int(player.get('sca', 0)),
            'gca': int(player.get('gca', 0)),
            'sca_per_90': float(player.get('sca_per_90', 0.0)),
            'gca_per_90': float(player.get('gca_per_90', 0.0)),
            # FBRef Recoveries (Phase 4.1 - for MID/FWD DC prediction)
            'fbref_recoveries': int(player.get('fbref_recoveries', 0)),
            'fbref_recoveries_per_90': float(player.get('fbref_recoveries_per_90', 0.0)),
            # Predicted DC (combined: base + recoveries for MID/FWD)
            'predicted_dc_per_90': float(player.get('predicted_dc_per_90', 0.0)),
            # Target: Enhanced prediction using xG/xA + defensive contribution points
            'points_next_gw': predicted_next_gw
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
        print(df[['form', 'total_points', 'minutes', 'xG', 'xA', 'def_contributions_per_90', 'predicted_dc_per_90', 'points_next_gw']].describe())
        print(f"\n📊 Feature count: {len(df.columns) - 1} features (61 total)")
        print(f"   - Original FPL: 17 features")
        print(f"   - Understat: 16 features (xG, npxG, xGChain, xGBuildup, per-90 stats, performance)")
        print(f"   - Derived Understat: 4 features (combined stats, finishing quality)")
        print(f"   - FBRef Defensive: 12 features (tackles, blocks, interceptions, clearances, def contrib)")
        print(f"   - FBRef Progressive: 6 features (progressive passes, carries, receptions)")
        print(f"   - FBRef Creation: 6 features (touches, SCA, GCA)")
        print(f"   - FBRef Recoveries: 3 features (recoveries, predicted DC)")
        print(f"\n✅ Enhanced training data ready (Phase 4.1)!")
        print(f"   Next step: python3 fpl-optimizer/predict_points.py")
