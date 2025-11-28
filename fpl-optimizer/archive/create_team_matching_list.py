#!/usr/bin/env python3
"""
Create a comprehensive team-by-team matching list
Shows ALL unmatched players with their team's Understat roster
"""
import asyncio
import sys
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).parent))
from Server import make_fpl_request
from data_sources.understat_scraper import UnderstatScraper
from player_mapping.name_matcher import PlayerNameMatcher


async def create_matching_list():
    """Generate team-by-team matching list"""

    print("Generating team-by-team matching list...")
    print()

    # Fetch data
    data = await make_fpl_request("bootstrap-static/")
    fpl_players = data.get('elements', [])
    teams_data = data.get('teams', [])
    teams = {t['id']: t['name'] for t in teams_data}

    scraper = UnderstatScraper()
    understat_players = scraper.fetch_epl_players(season="2025")

    # Match with current system
    matcher = PlayerNameMatcher("player_mapping/manual_mappings.json")
    matched, unmatched_list = matcher.match_all_players(fpl_players, understat_players, threshold=75)

    # Group unmatched players by team
    unmatched_by_team = {}
    for player in unmatched_list:
        team_id = player.get('team')
        team_name = teams.get(team_id, 'Unknown')

        if team_name not in unmatched_by_team:
            unmatched_by_team[team_name] = []

        unmatched_by_team[team_name].append({
            'name': f"{player.get('first_name', '')} {player.get('second_name', '')}".strip(),
            'position': player.get('element_type'),
            'minutes': player.get('minutes', 0),
            'points': player.get('total_points', 0),
            'web_name': player.get('web_name', '')
        })

    # Group Understat players by team
    understat_by_team = {}
    for player in understat_players:
        team = player.get('team', 'Unknown')
        if team not in understat_by_team:
            understat_by_team[team] = []
        understat_by_team[team].append(player['name'])

    # Position names
    pos_names = {1: 'GK', 2: 'DEF', 3: 'MID', 4: 'FWD'}

    # Output
    output = []
    output.append("=" * 100)
    output.append("COMPLETE TEAM-BY-TEAM MATCHING LIST (2025/26 Season)")
    output.append("=" * 100)
    output.append("")
    output.append(f"Total Unmatched Players: {len(unmatched_list)}")
    output.append(f"Teams with Unmatched Players: {len(unmatched_by_team)}")
    output.append("")
    output.append("Instructions:")
    output.append("1. For each team, find the unmatched FPL player in the Understat roster")
    output.append("2. Add to player_mapping/manual_mappings.json:")
    output.append('   "FPL Name": "Exact Understat Name"')
    output.append("")
    output.append("=" * 100)
    output.append("")

    # Sort teams alphabetically
    for team_name in sorted(unmatched_by_team.keys()):
        players = unmatched_by_team[team_name]

        # Sort by position (FWD, MID, DEF, GK) then by minutes
        players.sort(key=lambda p: (-p['position'], -p['minutes']))

        output.append("")
        output.append("=" * 100)
        output.append(f"TEAM: {team_name}")
        output.append("=" * 100)
        output.append("")

        # Show unmatched players
        output.append(f"📋 UNMATCHED FPL PLAYERS ({len(players)}):")
        output.append("")

        for p in players:
            pos = pos_names.get(p['position'], '???')
            output.append(f"  [{pos:3}] {p['name']:40} - {p['minutes']:4d} min, {p['points']:3d} pts")

        output.append("")
        output.append("-" * 100)
        output.append(f"🔍 UNDERSTAT ROSTER FOR {team_name}:")
        output.append("")

        # Show Understat roster
        understat_roster = understat_by_team.get(team_name, [])
        if understat_roster:
            for name in sorted(understat_roster):
                output.append(f"  → {name}")
        else:
            output.append("  (No Understat data for this team)")

        output.append("")

    # Save to file
    output_text = "\n".join(output)

    with open("TEAM_BY_TEAM_MATCHING.txt", "w", encoding='utf-8') as f:
        f.write(output_text)

    print(f"✅ Created TEAM_BY_TEAM_MATCHING.txt")
    print(f"   {len(unmatched_list)} unmatched players across {len(unmatched_by_team)} teams")
    print()
    print("Open the file to see team-by-team matching guide!")
    print()


if __name__ == "__main__":
    asyncio.run(create_matching_list())
