#!/usr/bin/env python3
"""
Verify Understat xG/xA Stats Accuracy
Compare scraped data against known values and check player matching
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from Server import make_fpl_request
from enhanced_features import EnhancedDataCollector


async def verify_stats_accuracy():
    """Verify the accuracy of scraped Understat stats"""

    print("=" * 80)
    print("STATS ACCURACY VERIFICATION")
    print("=" * 80)
    print()

    # Get FPL data
    print("📥 Fetching FPL data...")
    data = await make_fpl_request("bootstrap-static/")
    players = data.get('elements', [])
    teams_dict = {t['id']: t for t in data.get('teams', [])}

    # Get enhanced data
    print("🔄 Enhancing with Understat...")
    collector = EnhancedDataCollector(cache_ttl_hours=6)
    enhanced, stats = collector.collect_enhanced_data(
        players,
        season="2024",
        use_cache=True
    )

    print(f"\n✅ Data collected")
    print(f"   Total players: {len(enhanced)}")
    print(f"   Match rate: {stats['match_rate']:.1f}%")
    print()

    # ====================
    # TEST 1: Known High xG Players
    # ====================
    print("=" * 80)
    print("TEST 1: Verify Known Top xG Players")
    print("=" * 80)
    print()

    # These are known top scorers with high xG
    known_high_xg = [
        "Mohamed Salah",
        "Erling Haaland",
        "Alexander Isak",
        "Cole Palmer",
        "Ollie Watkins"
    ]

    print(f"Checking {len(known_high_xg)} known top scorers:")
    print(f"{'Player':25} {'FPL Goals':>10} {'xG':>10} {'Status':>15}")
    print("-" * 80)

    for name in known_high_xg:
        # Find player
        player = None
        for p in enhanced:
            full_name = f"{p.get('first_name', '')} {p.get('second_name', '')}".strip()
            if name.lower() in full_name.lower():
                player = p
                break

        if player:
            goals = player.get('goals_scored', 0)
            xG = player.get('xG', 0)

            # xG should be close to goals (within reasonable range)
            if xG > 0:
                ratio = goals / xG if xG > 0 else 0
                if 0.7 <= ratio <= 1.5:
                    status = "✅ Good"
                elif ratio > 1.5:
                    status = "🔥 Overperforming"
                else:
                    status = "⚠️  Underperforming"
            else:
                status = "❌ No xG data"

            print(f"{name:25} {goals:10d} {xG:10.2f} {status:>15}")
        else:
            print(f"{name:25} {'NOT FOUND':>10} {'---':>10} {'❌ Missing':>15}")

    print()

    # ====================
    # TEST 2: Compare FPL Stats vs Understat
    # ====================
    print("=" * 80)
    print("TEST 2: FPL Goals vs Understat xG Correlation")
    print("=" * 80)
    print()

    # Get active players with xG data
    active_with_xg = [
        p for p in enhanced
        if p.get('minutes', 0) >= 270 and p.get('xG', 0) > 0
    ]

    print(f"Analyzing {len(active_with_xg)} active players (270+ minutes, xG > 0)")
    print()

    # Calculate correlation metrics
    total_goals = sum(p.get('goals_scored', 0) for p in active_with_xg)
    total_xg = sum(p.get('xG', 0) for p in active_with_xg)

    overperformers = [p for p in active_with_xg if p.get('xG_overperformance', 0) > 3]
    underperformers = [p for p in active_with_xg if p.get('xG_overperformance', 0) < -3]

    print(f"📊 Overall Statistics:")
    print(f"   Total goals scored: {total_goals}")
    print(f"   Total xG: {total_xg:.2f}")
    print(f"   Ratio: {total_goals / total_xg:.2f}x (should be ~1.0)")
    print()
    print(f"   Overperformers (>3 goals vs xG): {len(overperformers)}")
    print(f"   Underperformers (<-3 goals vs xG): {len(underperformers)}")
    print()

    # Show top overperformers
    print("🔥 Top 5 Overperformers (scoring above xG):")
    top_over = sorted(overperformers, key=lambda p: p.get('xG_overperformance', 0), reverse=True)[:5]
    print(f"{'Player':25} {'Goals':>8} {'xG':>8} {'Diff':>8}")
    print("-" * 60)
    for p in top_over:
        name = f"{p['first_name']} {p['second_name']}"
        goals = p.get('goals_scored', 0)
        xG = p.get('xG', 0)
        diff = p.get('xG_overperformance', 0)
        print(f"{name:25} {goals:8d} {xG:8.2f} {diff:+8.2f}")

    print()

    # Show top underperformers
    print("❄️  Top 5 Underperformers (scoring below xG):")
    top_under = sorted(underperformers, key=lambda p: p.get('xG_overperformance', 0))[:5]
    print(f"{'Player':25} {'Goals':>8} {'xG':>8} {'Diff':>8}")
    print("-" * 60)
    for p in top_under:
        name = f"{p['first_name']} {p['second_name']}"
        goals = p.get('goals_scored', 0)
        xG = p.get('xG', 0)
        diff = p.get('xG_overperformance', 0)
        print(f"{name:25} {goals:8d} {xG:8.2f} {diff:+8.2f}")

    print()

    # ====================
    # TEST 3: Assists vs xA
    # ====================
    print("=" * 80)
    print("TEST 3: FPL Assists vs Understat xA Correlation")
    print("=" * 80)
    print()

    active_with_xa = [
        p for p in enhanced
        if p.get('minutes', 0) >= 270 and p.get('xA', 0) > 0
    ]

    total_assists = sum(p.get('assists', 0) for p in active_with_xa)
    total_xa = sum(p.get('xA', 0) for p in active_with_xa)

    print(f"📊 Assists Statistics:")
    print(f"   Total assists: {total_assists}")
    print(f"   Total xA: {total_xa:.2f}")
    print(f"   Ratio: {total_assists / total_xa:.2f}x (should be ~1.0)")
    print()

    # Top assisters
    print("🎯 Top 5 xA Players:")
    top_xa = sorted(active_with_xa, key=lambda p: p.get('xA', 0), reverse=True)[:5]
    print(f"{'Player':25} {'Assists':>8} {'xA':>8} {'xA/90':>8}")
    print("-" * 60)
    for p in top_xa:
        name = f"{p['first_name']} {p['second_name']}"
        assists = p.get('assists', 0)
        xA = p.get('xA', 0)
        xA_90 = p.get('xA_per_90', 0)
        print(f"{name:25} {assists:8d} {xA:8.2f} {xA_90:8.2f}")

    print()

    # ====================
    # TEST 4: Data Freshness
    # ====================
    print("=" * 80)
    print("TEST 4: Data Freshness Check")
    print("=" * 80)
    print()

    from data_sources.data_cache import DataCache
    cache = DataCache()
    info = cache.get_cache_info()

    if info['total_files'] > 0:
        for file_info in info['files']:
            if 'understat' in file_info['key']:
                age = file_info['age_hours']
                expired = file_info['expired']

                print(f"📦 Cache Status:")
                print(f"   File: {file_info['key']}")
                print(f"   Age: {age:.1f} hours")
                print(f"   Size: {file_info['size_kb']} KB")
                print(f"   Expired: {'❌ Yes' if expired else '✅ No'}")
                print(f"   TTL: {info['ttl_hours']} hours")
    else:
        print("⚠️  No cache files found")

    print()

    # ====================
    # FINAL VERDICT
    # ====================
    print("=" * 80)
    print("FINAL VERDICT")
    print("=" * 80)
    print()

    issues = []

    # Check overall goals vs xG ratio
    if abs((total_goals / total_xg) - 1.0) > 0.2:
        issues.append("⚠️  Goals/xG ratio is off (should be ~1.0)")

    # Check assists vs xA ratio
    if abs((total_assists / total_xa) - 1.0) > 0.2:
        issues.append("⚠️  Assists/xA ratio is off (should be ~1.0)")

    # Check match rate
    if stats['match_rate'] < 25:
        issues.append(f"⚠️  Low match rate ({stats['match_rate']:.1f}%)")

    if issues:
        print("❌ ISSUES FOUND:")
        for issue in issues:
            print(f"   {issue}")
    else:
        print("✅ ALL CHECKS PASSED!")
        print()
        print("The Understat data appears accurate:")
        print(f"   ✓ Goals vs xG ratio: {total_goals / total_xg:.2f}x (good)")
        print(f"   ✓ Assists vs xA ratio: {total_assists / total_xa:.2f}x (good)")
        print(f"   ✓ Match rate: {stats['match_rate']:.1f}%")
        print()
        print("The system is ready for predictions!")

    print()
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(verify_stats_accuracy())
