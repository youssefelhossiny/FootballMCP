#!/usr/bin/env python3
"""
Manually match top unmatched players by searching Understat data
Focus on high-value forwards and midfielders
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from Server import make_fpl_request
from data_sources.understat_scraper import UnderstatScraper
from player_mapping.name_matcher import PlayerNameMatcher


async def manual_match():
    """Find exact Understat names for top unmatched players"""

    print("=" * 80)
    print("MANUAL MATCHING TOOL - Top Unmatched Players")
    print("=" * 80)
    print()

    # Fetch data
    print("📥 Fetching data...")
    data = await make_fpl_request("bootstrap-static/")
    fpl_players = data.get('elements', [])
    teams = {t['id']: t['name'] for t in data.get('teams', [])}

    scraper = UnderstatScraper()
    understat_players = scraper.fetch_epl_players(season="2025")

    # Match with current system
    matcher = PlayerNameMatcher("player_mapping/manual_mappings.json")
    matched, unmatched = matcher.match_all_players(fpl_players, understat_players, threshold=75)
    stats = matcher.get_match_stats()

    print(f"✅ Current match rate: {stats['match_rate']}%")
    print()

    # Get top unmatched by value
    unmatched_names = matcher.get_unmatched_players()
    unmatched_players = []

    for name in unmatched_names:
        for player in fpl_players:
            fpl_name = f"{player.get('first_name', '')} {player.get('second_name', '')}".strip()
            if fpl_name == name:
                position = player.get('element_type', 3)
                minutes = player.get('minutes', 0)
                position_weights = {1: 0.5, 2: 1.0, 3: 2.0, 4: 3.0}
                player['value_score'] = minutes * position_weights.get(position, 1.0)
                unmatched_players.append(player)
                break

    unmatched_players.sort(key=lambda p: p['value_score'], reverse=True)

    # Focus on top forwards and midfielders
    top_attackers = [p for p in unmatched_players if p.get('element_type') in [3, 4]][:30]

    print("=" * 80)
    print("TOP 30 UNMATCHED ATTACKERS (Forwards & Midfielders)")
    print("=" * 80)
    print()

    # Group Understat players by team for easier searching
    understat_by_team = {}
    for p in understat_players:
        team = p.get('team', 'Unknown')
        if team not in understat_by_team:
            understat_by_team[team] = []
        understat_by_team[team].append(p['name'])

    for i, player in enumerate(top_attackers, 1):
        fpl_name = f"{player.get('first_name', '')} {player.get('second_name', '')}".strip()
        team_id = player.get('team')
        team_name = teams.get(team_id, 'Unknown')
        minutes = player.get('minutes', 0)
        points = player.get('total_points', 0)
        pos = "FWD" if player.get('element_type') == 4 else "MID"

        print(f"{i:2d}. {fpl_name:35} ({team_name:15}) {pos} - {minutes:4d} min, {points:3d} pts")

        # Show Understat players from same team
        if team_name in understat_by_team:
            teammates = understat_by_team[team_name]
            print(f"    Understat players from {team_name}:")
            for teammate in sorted(teammates):
                print(f"      - {teammate}")
        print()

    print("=" * 80)
    print("INSTRUCTIONS")
    print("=" * 80)
    print()
    print("1. Review the list above")
    print("2. For each player, find their exact Understat name from their team")
    print("3. Add manual mappings to: player_mapping/manual_mappings.json")
    print()
    print("Format:")
    print('  "FPL Name": "Exact Understat Name"')
    print()
    print("Example:")
    print('  "Jean-Philippe Mateta": "Jean Philippe Mateta"')
    print()


if __name__ == "__main__":
    asyncio.run(manual_match())
