#!/usr/bin/env python3
"""
Find unmatched FPL players and suggest Understat name mappings
Semi-automated approach to improve match rate
"""
import asyncio
import sys
from pathlib import Path
from thefuzz import fuzz

sys.path.insert(0, str(Path(__file__).parent))
from Server import make_fpl_request
from data_sources.understat_scraper import UnderstatScraper
from player_mapping.name_matcher import PlayerNameMatcher, normalize_name


async def find_and_suggest_mappings():
    """Find unmatched players and suggest mappings"""

    print("=" * 80)
    print("UNMATCHED PLAYER FINDER & MAPPING SUGGESTER")
    print("=" * 80)
    print()

    # Fetch FPL data
    print("📥 Fetching FPL data...")
    data = await make_fpl_request("bootstrap-static/")
    fpl_players = data.get('elements', [])
    teams = {t['id']: t['name'] for t in data.get('teams', [])}
    print(f"✅ Loaded {len(fpl_players)} FPL players")

    # Fetch Understat data
    print("📥 Fetching Understat data...")
    scraper = UnderstatScraper()
    understat_players = scraper.fetch_epl_players(season="2025")
    print(f"✅ Loaded {len(understat_players)} Understat players")
    print()

    # Match players
    print("🔗 Matching players with current system...")
    matcher = PlayerNameMatcher(
        manual_mappings_path="player_mapping/manual_mappings.json"
    )
    matched, unmatched = matcher.match_all_players(
        fpl_players,
        understat_players,
        threshold=75
    )

    stats = matcher.get_match_stats()
    print(f"✅ Current match rate: {stats['matched']}/{stats['total']} ({stats['match_rate']}%)")
    print(f"   Unmatched: {stats['unmatched']} players")
    print()

    # Analyze unmatched players
    print("=" * 80)
    print("ANALYZING UNMATCHED PLAYERS")
    print("=" * 80)
    print()

    # Get unmatched player objects (not just names)
    unmatched_names = matcher.get_unmatched_players()
    unmatched_players = []

    for name in unmatched_names:
        for player in fpl_players:
            fpl_name = f"{player.get('first_name', '')} {player.get('second_name', '')}".strip()
            if fpl_name == name:
                unmatched_players.append(player)
                break

    # Calculate value score for each player
    # Value = minutes * position_multiplier
    # Position multiplier: FWD=3, MID=2, DEF=1, GK=0.5 (xG/xA matters more for attackers)
    position_weights = {1: 0.5, 2: 1.0, 3: 2.0, 4: 3.0}

    for player in unmatched_players:
        position = player.get('element_type', 3)
        minutes = player.get('minutes', 0)
        player['value_score'] = minutes * position_weights.get(position, 1.0)

    # Sort by value score
    unmatched_players.sort(key=lambda p: p['value_score'], reverse=True)

    # Show top unmatched by position
    print("📊 Top Unmatched Players by Position:\n")

    position_names = {1: "Goalkeeper", 2: "Defender", 3: "Midfielder", 4: "Forward"}

    for pos_id in [4, 3, 2, 1]:  # FWD, MID, DEF, GK
        pos_players = [p for p in unmatched_players if p.get('element_type') == pos_id][:10]

        if pos_players:
            print(f"\n{position_names[pos_id]}s ({len([p for p in unmatched_players if p.get('element_type') == pos_id])} unmatched):")
            print(f"{'Player':30} {'Team':20} {'Minutes':>8} {'Points':>7}")
            print("-" * 80)

            for p in pos_players:
                name = f"{p.get('first_name', '')} {p.get('second_name', '')}".strip()
                team = teams.get(p.get('team'), 'Unknown')
                minutes = p.get('minutes', 0)
                points = p.get('total_points', 0)
                print(f"{name:30} {team:20} {minutes:8d} {points:7d}")

    print("\n" + "=" * 80)
    print("SUGGESTING MAPPINGS")
    print("=" * 80)
    print()

    # For high-value players, suggest mappings
    high_value_unmatched = [p for p in unmatched_players if p['value_score'] > 100]

    print(f"🎯 Analyzing {len(high_value_unmatched)} high-value unmatched players...")
    print(f"   (Forwards/Midfielders with significant playing time)\n")

    suggestions = []
    understat_names = [p['name'] for p in understat_players]

    for player in high_value_unmatched:
        fpl_name = f"{player.get('first_name', '')} {player.get('second_name', '')}".strip()
        web_name = player.get('web_name', '')

        # Try fuzzy matching at lower threshold (60-74%)
        # Normalize names for better matching
        fpl_normalized = normalize_name(fpl_name)
        understat_normalized = [normalize_name(name) for name in understat_names]

        # Find best matches
        from thefuzz import process
        matches = process.extract(
            fpl_normalized,
            understat_normalized,
            scorer=fuzz.token_sort_ratio,
            limit=3
        )

        # Also try web_name
        web_matches = []
        if web_name:
            web_normalized = normalize_name(web_name)
            web_matches = process.extract(
                web_normalized,
                understat_normalized,
                scorer=fuzz.token_sort_ratio,
                limit=3
            )

        # Get best overall match
        all_matches = matches + web_matches
        if all_matches:
            best_match = max(all_matches, key=lambda m: m[1])
            score = best_match[1]

            # Find original Understat name (not normalized)
            matched_normalized = best_match[0]
            matched_idx = understat_normalized.index(matched_normalized)
            understat_name = understat_names[matched_idx]

            # Only suggest if score is 60-84% (below current threshold but plausible)
            if 60 <= score < 75:
                suggestions.append({
                    'fpl_name': fpl_name,
                    'understat_name': understat_name,
                    'score': score,
                    'confidence': 'MEDIUM' if score >= 70 else 'LOW',
                    'team': teams.get(player.get('team'), 'Unknown'),
                    'position': position_names[player.get('element_type', 3)],
                    'minutes': player.get('minutes', 0)
                })

    # Sort suggestions by score
    suggestions.sort(key=lambda s: s['score'], reverse=True)

    # Show suggestions
    if suggestions:
        print(f"📋 Found {len(suggestions)} suggested mappings (60-74% match):\n")
        print(f"{'FPL Name':30} {'→':3} {'Understat Name':30} {'Score':>6} {'Conf':>6} {'Team':15}")
        print("-" * 110)

        for s in suggestions[:50]:  # Show top 50
            print(f"{s['fpl_name']:30} {'→':3} {s['understat_name']:30} {s['score']:5d}% {s['confidence']:>6} {s['team']:15}")

        if len(suggestions) > 50:
            print(f"\n... and {len(suggestions) - 50} more")
    else:
        print("✅ No additional high-confidence suggestions found")
        print("   (All high-value players either matched or too dissimilar)")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()
    print(f"Current match rate: {stats['match_rate']}%")
    print(f"High-value unmatched: {len(high_value_unmatched)}")
    print(f"Suggested mappings (60-74% confidence): {len(suggestions)}")
    print()

    # Ask user if they want to apply suggestions
    print("💡 Next Steps:")
    print("   1. Review suggestions above")
    print("   2. Run: python3 fpl-optimizer/apply_suggested_mappings.py")
    print("      (This will let you approve/reject each suggestion)")
    print()

    # Save suggestions to file for later use
    import json
    output_file = "suggested_mappings.json"
    with open(output_file, 'w') as f:
        json.dump(suggestions, f, indent=2)

    print(f"💾 Suggestions saved to: {output_file}")
    print()


if __name__ == "__main__":
    asyncio.run(find_and_suggest_mappings())
