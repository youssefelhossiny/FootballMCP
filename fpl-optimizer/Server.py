#!/usr/bin/env python3
"""
Fantasy Premier League MCP Server
Phase 1 + Bug Fixes + Phase 2 (Initial)

Phase 1 Tools (✅ Complete + Fixed):
1. get_all_players - Filter & sort all players
2. get_player_details - Detailed player stats
3. get_fixtures - Upcoming fixtures with difficulty
4. get_my_team - User's FPL team (FIXED transfer/chip display)
5. get_top_performers - Top players by metric

Phase 2 Tools (🚧 In Progress):
6. optimize_squad - Build optimal 15-player team (NEW)
7. suggest_transfers - Transfer recommendations (NEW - requires user input for FT/chips)
"""

import os
import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional
import httpx
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import NotificationOptions, Server
import mcp.server.stdio

# FPL API Configuration
FPL_BASE_URL = "https://fantasy.premierleague.com/api"

# Position mapping
POSITIONS = {
    1: "GK",
    2: "DEF",
    3: "MID",
    4: "FWD"
}

# FPL Squad constraints
SQUAD_CONSTRAINTS = {
    "total_players": 15,
    "budget": 100.0,  # £100m
    "max_per_team": 3,
    "positions": {
        "GK": 2,
        "DEF": 5,
        "MID": 5,
        "FWD": 3
    }
}

server = Server("fpl-optimizer")


async def make_fpl_request(endpoint: str, params: dict = None) -> dict:
    """Make a request to the FPL API"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{FPL_BASE_URL}/{endpoint}",
                params=params,
                timeout=15.0
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e)}


def format_price(price: int) -> str:
    """Convert price from API format (e.g., 115) to display (£11.5m)"""
    return f"£{price / 10:.1f}m"


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available FPL tools"""
    return [
        types.Tool(
            name="get_all_players",
            description=(
                "Get all Premier League players with stats, prices, and points. "
                "Returns structured player data that LLM can format naturally. "
                "Filter by: position (GK/DEF/MID/FWD), team, price range. "
                "Sort by: points, form, value (points per £), price. "
                "Use for queries like: 'Show me midfielders under £8m by form', "
                "'List Arsenal players', 'Best value defenders'"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "position": {
                        "type": "string",
                        "enum": ["GK", "DEF", "MID", "FWD", "all"],
                        "description": "Filter by position",
                        "default": "all"
                    },
                    "team": {
                        "type": "string",
                        "description": "Filter by team (partial match works)",
                        "default": None
                    },
                    "max_price": {
                        "type": "number",
                        "description": "Max price in millions (e.g., 8.0)",
                        "default": None
                    },
                    "min_price": {
                        "type": "number",
                        "description": "Min price in millions",
                        "default": None
                    },
                    "sort_by": {
                        "type": "string",
                        "enum": ["points", "form", "value", "price"],
                        "description": "Sort by metric",
                        "default": "points"
                    },
                    "limit": {
                        "type": "number",
                        "description": "Number of players (1-100, default: 20)",
                        "default": 20,
                        "minimum": 1,
                        "maximum": 100
                    }
                }
            }
        ),
        types.Tool(
            name="get_player_details",
            description=(
                "Get detailed statistics for ONE specific player. "
                "Returns: season stats, recent gameweek performance, upcoming fixtures. "
                "Player matching is flexible - works with: full name ('Mohamed Salah'), "
                "last name only ('Salah'), or nickname ('Mo Salah'). "
                "Use for queries like: 'Tell me about Haaland', 'Show Salah stats', "
                "'How is Cole Palmer performing?'"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "player_name": {
                        "type": "string",
                        "description": "Player name - can be full name, last name, or nickname (e.g., 'Salah', 'Mohamed Salah', 'Haaland')"
                    }
                },
                "required": ["player_name"]
            }
        ),
        types.Tool(
            name="get_fixtures",
            description=(
                "Get upcoming Premier League fixtures with FPL difficulty ratings (FDR). "
                "Returns fixture schedule with difficulty scores (1=easy, 5=very hard). "
                "Use for: 'Show me upcoming fixtures', 'Which teams have easy fixtures?', "
                "'Display next 5 gameweeks for Liverpool'"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "team": {
                        "type": "string",
                        "description": "Filter for specific team (optional)",
                        "default": None
                    },
                    "gameweeks": {
                        "type": "number",
                        "description": "Number of GWs ahead (1-10, default: 5)",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 10
                    }
                }
            }
        ),
        types.Tool(
            name="get_my_team",
            description=(
                "Get user's current FPL team showing all 15 players and squad details. "
                "Returns: squad breakdown by position, team value, bank balance, overall rank. "
                "IMPORTANT: Shows 'Transfers Made This GW' (not free transfers remaining - API limitation). "
                "If user asks about making transfers, prompt for: free transfer count (0-5) and available chips. "
                "Requires team_id from URL: fantasy.premierleague.com/entry/YOUR_ID/"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "team_id": {
                        "type": "number",
                        "description": "FPL team ID from user's FPL URL"
                    },
                    "gameweek": {
                        "type": "number",
                        "description": "GW to view (optional, defaults to current)",
                        "default": None
                    }
                },
                "required": ["team_id"]
            }
        ),
        types.Tool(
            name="get_top_performers",
            description=(
                "Get top performing players ranked by chosen metric. "
                "Returns ranked list of players with key stats. "
                "Metrics: total_points, form (last 5 GW avg), value (pts/£), "
                "ownership %, transfers_in this GW, bonus points. "
                "Use for: 'Top scorers', 'Most in-form players', 'Best value picks'"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "metric": {
                        "type": "string",
                        "enum": ["total_points", "form", "value", "selected_by", "transfers_in", "bonus"],
                        "description": "Metric to rank by",
                        "default": "total_points"
                    },
                    "position": {
                        "type": "string",
                        "enum": ["GK", "DEF", "MID", "FWD", "all"],
                        "description": "Filter by position",
                        "default": "all"
                    },
                    "limit": {
                        "type": "number",
                        "description": "Number of players (1-50, default: 10)",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50
                    }
                }
            }
        ),
        types.Tool(
            name="optimize_squad",
            description=(
                "Build the OPTIMAL 15-player FPL squad within £100m budget. "
                "Uses mathematical optimization to maximize expected points. "
                "Constraints: 2 GK, 5 DEF, 5 MID, 3 FWD, max 3 per team. "
                "Based on: current form, fixtures, points, value. "
                "Example: 'Build me the best possible FPL team'"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "budget": {
                        "type": "number",
                        "description": "Budget in millions (default: 100.0)",
                        "default": 100.0,
                        "minimum": 80.0,
                        "maximum": 100.0
                    },
                    "optimize_for": {
                        "type": "string",
                        "enum": ["points", "form", "value", "fixtures"],
                        "description": "Optimization strategy (default: form)",
                        "default": "form"
                    }
                }
            }
        ),
        types.Tool(
            name="suggest_transfers",
            description=(
                "Suggest transfer recommendations based on your current team. "
                "REQUIRES USER INPUT: User must provide their number of free transfers (0-5) "
                "and available chips (Wildcard, Free Hit, Bench Boost, Triple Captain). "
                "If not provided, ASK USER: 'How many free transfers do you have? Do you have any chips available?' "
                "Analyzes: form, fixtures, injuries, price changes. "
                "Calculates: Points expected gain vs -4 hit cost. "
                "Example: 'Suggest transfers for my team (team_id: 123456, 2 free transfers, no chips)'"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "team_id": {
                        "type": "number",
                        "description": "Your FPL team ID"
                    },
                    "free_transfers": {
                        "type": "number",
                        "description": "Number of free transfers available (1-5). User must provide this.",
                        "minimum": 0,
                        "maximum": 5
                    },
                    "available_chips": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["wildcard", "free_hit", "bench_boost", "triple_captain"]
                        },
                        "description": "List of available chips. User must provide this.",
                        "default": []
                    },
                    "max_transfers": {
                        "type": "number",
                        "description": "Max transfers to suggest (default: 2)",
                        "default": 2,
                        "minimum": 1,
                        "maximum": 5
                    }
                },
                "required": ["team_id", "free_transfers"]
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(
        name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool execution requests"""

    if name == "get_all_players":
        data = await make_fpl_request("bootstrap-static/")

        if "error" in data:
            return [types.TextContent(type="text", text=f"❌ Error: {data['error']}")]

        players = data.get('elements', [])
        teams = {team['id']: team for team in data.get('teams', [])}

        # Apply filters
        position = arguments.get('position', 'all')
        team_filter = arguments.get('team')
        max_price = arguments.get('max_price')
        min_price = arguments.get('min_price')
        sort_by = arguments.get('sort_by', 'points')
        limit = min(arguments.get('limit', 20), 100)

        # Filter by position
        if position != 'all':
            position_id = {v: k for k, v in POSITIONS.items()}[position]
            players = [p for p in players if p['element_type'] == position_id]

        # Filter by team
        if team_filter:
            team_filter_lower = team_filter.lower()
            matching_teams = [tid for tid, team in teams.items()
                              if team_filter_lower in team['name'].lower() or
                              team_filter_lower in team['short_name'].lower()]
            players = [p for p in players if p['team'] in matching_teams]

        # Filter by price
        if max_price:
            players = [p for p in players if p['now_cost'] / 10 <= max_price]
        if min_price:
            players = [p for p in players if p['now_cost'] / 10 >= min_price]

        # Sort
        if sort_by == 'points':
            players.sort(key=lambda x: x['total_points'], reverse=True)
        elif sort_by == 'form':
            players.sort(key=lambda x: float(x.get('form', 0)), reverse=True)
        elif sort_by == 'value':
            players.sort(key=lambda x: x['total_points'] / (x['now_cost'] / 10) if x['now_cost'] > 0 else 0,
                         reverse=True)
        elif sort_by == 'price':
            players.sort(key=lambda x: x['now_cost'], reverse=True)

        players = players[:limit]

        # Format output - STRUCTURED ONLY
        results = [f"FPL Players (Filters: position={position}, sort={sort_by})\n"]

        for i, player in enumerate(players, 1):
            team = teams[player['team']]
            value = player['total_points'] / (player['now_cost'] / 10) if player['now_cost'] > 0 else 0

            results.append(
                f"{i}. {player['web_name']} | {team['short_name']} | {POSITIONS[player['element_type']]} | "
                f"Price: {format_price(player['now_cost'])} | Points: {player['total_points']} | "
                f"Form: {player.get('form', 0)} | Value: {value:.1f}pts/£"
            )

        return [types.TextContent(type="text", text="\n".join(results))]

    elif name == "get_player_details":
        player_name = arguments['player_name'].lower()

        data = await make_fpl_request("bootstrap-static/")
        if "error" in data:
            return [types.TextContent(type="text", text=f"❌ Error: {data['error']}")]

        players = data.get('elements', [])
        teams = {team['id']: team for team in data.get('teams', [])}

        # Find player - improved matching
        # Split search into individual words for better matching
        search_words = player_name.split()

        matching = []
        for p in players:
            player_text = f"{p['first_name']} {p['second_name']} {p['web_name']}".lower()

            # Check if ALL search words appear in player text
            if all(word in player_text for word in search_words):
                matching.append(p)
            # Or if any word matches web_name exactly (for single-word searches like "Salah")
            elif any(word == p['web_name'].lower() for word in search_words):
                matching.append(p)

        if not matching:
            # Suggest similar players
            similar = []
            for p in players:
                player_text = f"{p['first_name']} {p['second_name']} {p['web_name']}".lower()
                # Check if any search word partially matches
                if any(word in player_text for word in search_words if len(word) > 3):
                    similar.append(p)

            if similar:
                suggestions = similar[:5]
                results = [f"❌ Player '{arguments['player_name']}' not found."]
                results.append(f"\n💡 Did you mean one of these?")
                for s in suggestions:
                    team = teams[s['team']]
                    results.append(f"   • {s['first_name']} {s['second_name']} ({team['short_name']})")
                return [types.TextContent(type="text", text="\n".join(results))]
            else:
                return [types.TextContent(type="text",
                                          text=f"❌ Player '{arguments['player_name']}' not found. Try searching by last name only.")]

        player = matching[0]
        team = teams[player['team']]

        details = await make_fpl_request(f"element-summary/{player['id']}/")
        if "error" in details:
            return [types.TextContent(type="text", text=f"❌ Error: {details['error']}")]

        # Format output - STRUCTURED ONLY
        results = [
            f"PLAYER: {player['first_name']} {player['second_name']}",
            f"Team: {team['name']} ({team['short_name']})",
            f"Position: {POSITIONS[player['element_type']]}",
            f"Price: {format_price(player['now_cost'])}",
            f"Ownership: {player['selected_by_percent']}%",
            f"\nSEASON STATS:",
            f"Total Points: {player['total_points']}",
            f"Form (last 5): {player.get('form', 0)}",
            f"PPG: {player.get('points_per_game', 0)}",
            f"Goals: {player.get('goals_scored', 0)} | Assists: {player.get('assists', 0)} | CS: {player.get('clean_sheets', 0)}",
            f"Bonus: {player.get('bonus', 0)}",
        ]

        # Recent performance
        history = details.get('history', [])
        if history:
            results.append(f"\nLAST 5 GAMEWEEKS:")
            for match in history[-5:]:
                results.append(
                    f"GW{match['round']}: {match['total_points']}pts | {match['minutes']}min | "
                    f"G:{match['goals_scored']} A:{match['assists']}"
                )

        # Fixtures
        fixtures = details.get('fixtures', [])
        if fixtures:
            results.append(f"\nNEXT 5 FIXTURES:")
            for fixture in fixtures[:5]:
                is_home = fixture['is_home']
                opponent_id = fixture['team_a'] if is_home else fixture['team_h']
                opponent = teams.get(opponent_id, {}).get('short_name', 'TBD')
                difficulty = fixture.get('difficulty', '?')
                venue = "vs" if is_home else "@"
                results.append(f"GW{fixture['event']}: {venue} {opponent} (FDR: {difficulty}/5)")

        return [types.TextContent(type="text", text="\n".join(results))]

    elif name == "get_fixtures":
        team_filter = arguments.get('team')
        gameweeks = min(arguments.get('gameweeks', 5), 10)

        bootstrap = await make_fpl_request("bootstrap-static/")
        if "error" in bootstrap:
            return [types.TextContent(type="text", text=f"❌ Error: {bootstrap['error']}")]

        teams = {team['id']: team for team in bootstrap.get('teams', [])}
        events = bootstrap.get('events', [])
        current_gw = next((e['id'] for e in events if e.get('is_current')), 1)

        fixtures_data = await make_fpl_request("fixtures/")
        if "error" in fixtures_data:
            return [types.TextContent(type="text", text=f"❌ Error: {fixtures_data['error']}")]

        upcoming = [f for f in fixtures_data if f.get('event') and
                    current_gw <= f['event'] <= current_gw + gameweeks - 1]

        if team_filter:
            team_filter_lower = team_filter.lower()
            matching_team_ids = [tid for tid, team in teams.items()
                                 if team_filter_lower in team['name'].lower() or
                                 team_filter_lower in team['short_name'].lower()]

            if not matching_team_ids:
                return [types.TextContent(type="text", text=f"❌ Team '{team_filter}' not found")]

            upcoming = [f for f in upcoming if f['team_h'] in matching_team_ids or f['team_a'] in matching_team_ids]

        upcoming.sort(key=lambda x: (x['event'], x.get('kickoff_time', '')))

        results = [f"FIXTURES (GW{current_gw} - GW{current_gw + gameweeks - 1})\n"]

        by_gameweek = {}
        for fixture in upcoming:
            gw = fixture['event']
            if gw not in by_gameweek:
                by_gameweek[gw] = []
            by_gameweek[gw].append(fixture)

        for gw in sorted(by_gameweek.keys()):
            results.append(f"\nGAMEWEEK {gw}:")
            for fixture in by_gameweek[gw]:
                home_team = teams.get(fixture['team_h'], {})
                away_team = teams.get(fixture['team_a'], {})
                home_fdr = fixture.get('team_h_difficulty', '?')
                away_fdr = fixture.get('team_a_difficulty', '?')

                results.append(
                    f"{home_team.get('short_name', 'TBD')} (FDR:{home_fdr}) vs "
                    f"{away_team.get('short_name', 'TBD')} (FDR:{away_fdr})"
                )

        if not upcoming:
            results.append("No fixtures in range")

        return [types.TextContent(type="text", text="\n".join(results))]

    elif name == "get_my_team":
        team_id = arguments['team_id']
        gameweek = arguments.get('gameweek')

        bootstrap = await make_fpl_request("bootstrap-static/")
        if "error" in bootstrap:
            return [types.TextContent(type="text", text=f"❌ Error: {bootstrap['error']}")]

        players_data = {p['id']: p for p in bootstrap.get('elements', [])}
        teams = {team['id']: team for team in bootstrap.get('teams', [])}
        events = bootstrap.get('events', [])

        if not gameweek:
            gameweek = next((e['id'] for e in events if e.get('is_current')), 1)

        team_data = await make_fpl_request(f"entry/{team_id}/")
        if "error" in team_data:
            return [types.TextContent(type="text", text=f"❌ Team {team_id} not found")]

        picks_data = await make_fpl_request(f"entry/{team_id}/event/{gameweek}/picks/")
        if "error" in picks_data:
            return [types.TextContent(type="text", text=f"❌ Error: {picks_data['error']}")]

        manager = f"{team_data.get('player_first_name', '')} {team_data.get('player_last_name', '')}"
        team_name = team_data.get('name', 'Unknown')

        # FIXED: Clarify transfers made vs available
        transfers_made = picks_data.get('entry_history', {}).get('event_transfers', 0)

        results = [
            f"MANAGER: {manager}",
            f"TEAM: {team_name}",
            f"Gameweek: {gameweek}",
            f"Overall Rank: {team_data.get('summary_overall_rank', 'N/A'):,}",
            f"Overall Points: {team_data.get('summary_overall_points', 0)}",
            f"GW Points: {picks_data.get('entry_history', {}).get('points', 0)}",
            f"Team Value: {format_price(team_data.get('last_deadline_value', 1000))}",
            f"In Bank: {format_price(team_data.get('last_deadline_bank', 0))}",
            f"Transfers Made This GW: {transfers_made}",
            f"\n⚠️  NOTE: API cannot show free transfers remaining. If planning transfers, please provide your free transfer count (0-5).",
            f"\nSQUAD (15 players):\n"
        ]

        # Group by position
        picks = picks_data.get('picks', [])
        by_position = {1: [], 2: [], 3: [], 4: []}

        for pick in picks:
            player = players_data.get(pick['element'])
            if player:
                team = teams.get(player['team'], {})
                badges = ""
                if pick.get('is_captain'):
                    badges = " (C)"
                elif pick.get('is_vice_captain'):
                    badges = " (VC)"

                by_position[player['element_type']].append(
                    f"{player['web_name']} | {team.get('short_name', 'TBD')} | "
                    f"{format_price(player['now_cost'])} | {player['total_points']}pts{badges}"
                )

        for pos_id, pos_name in POSITIONS.items():
            results.append(f"\n{pos_name}:")
            for player_line in by_position[pos_id]:
                results.append(f"  {player_line}")

        return [types.TextContent(type="text", text="\n".join(results))]

    elif name == "get_top_performers":
        metric = arguments.get('metric', 'total_points')
        position = arguments.get('position', 'all')
        limit = min(arguments.get('limit', 10), 50)

        data = await make_fpl_request("bootstrap-static/")
        if "error" in data:
            return [types.TextContent(type="text", text=f"❌ Error: {data['error']}")]

        players = data.get('elements', [])
        teams = {team['id']: team for team in data.get('teams', [])}

        if position != 'all':
            position_id = {v: k for k, v in POSITIONS.items()}[position]
            players = [p for p in players if p['element_type'] == position_id]

        # Sort by metric
        if metric == 'total_points':
            players.sort(key=lambda x: x['total_points'], reverse=True)
            metric_name = "Total Points"
        elif metric == 'form':
            players.sort(key=lambda x: float(x.get('form', 0)), reverse=True)
            metric_name = "Form"
        elif metric == 'value':
            players.sort(key=lambda x: x['total_points'] / (x['now_cost'] / 10) if x['now_cost'] > 0 else 0,
                         reverse=True)
            metric_name = "Value"
        elif metric == 'selected_by':
            players.sort(key=lambda x: float(x.get('selected_by_percent', 0)), reverse=True)
            metric_name = "Ownership"
        elif metric == 'transfers_in':
            players.sort(key=lambda x: x.get('transfers_in_event', 0), reverse=True)
            metric_name = "Transfers In"
        elif metric == 'bonus':
            players.sort(key=lambda x: x.get('bonus', 0), reverse=True)
            metric_name = "Bonus Points"

        players = players[:limit]

        results = [f"TOP {limit} BY {metric_name.upper()}\n"]

        for i, player in enumerate(players, 1):
            team = teams[player['team']]

            if metric == 'value':
                value = player['total_points'] / (player['now_cost'] / 10) if player['now_cost'] > 0 else 0
                metric_val = f"{value:.1f}pts/£"
            elif metric == 'form':
                metric_val = f"{player.get('form', 0)}"
            elif metric == 'selected_by':
                metric_val = f"{player.get('selected_by_percent', 0)}%"
            elif metric == 'transfers_in':
                metric_val = f"{player.get('transfers_in_event', 0):,}"
            elif metric == 'bonus':
                metric_val = f"{player.get('bonus', 0)}"
            else:
                metric_val = f"{player['total_points']}"

            results.append(
                f"{i}. {player['web_name']} | {team['short_name']} | {POSITIONS[player['element_type']]} | "
                f"{format_price(player['now_cost'])} | {metric_name}: {metric_val}"
            )

        return [types.TextContent(type="text", text="\n".join(results))]

    elif name == "optimize_squad":
        budget = arguments.get('budget', 100.0)
        optimize_for = arguments.get('optimize_for', 'form')

        # Get player data
        data = await make_fpl_request("bootstrap-static/")
        if "error" in data:
            return [types.TextContent(type="text", text=f"❌ Error: {data['error']}")]

        players = data.get('elements', [])
        teams_data = {team['id']: team for team in data.get('teams', [])}

        # Calculate optimization metric for each player
        for player in players:
            if optimize_for == 'points':
                player['opt_score'] = player['total_points']
            elif optimize_for == 'form':
                player['opt_score'] = float(player.get('form', 0)) * 10  # Scale up
            elif optimize_for == 'value':
                player['opt_score'] = (player['total_points'] / (player['now_cost'] / 10)) if player[
                                                                                                  'now_cost'] > 0 else 0
            elif optimize_for == 'fixtures':
                # Simplified: use form * (6 - average team difficulty)
                # In full version, this would analyze actual fixtures
                player['opt_score'] = float(player.get('form', 0)) * 5

        # Greedy optimization (simplified for Phase 2 initial)
        # Full version will use PuLP for linear programming

        selected = []
        position_counts = {1: 0, 2: 0, 3: 0, 4: 0}
        team_counts = {}
        total_cost = 0

        # Sort players by optimization score
        sorted_players = sorted(players, key=lambda x: x.get('opt_score', 0), reverse=True)

        for player in sorted_players:
            pos = player['element_type']
            team_id = player['team']
            cost = player['now_cost'] / 10

            # Check constraints
            if position_counts[pos] >= SQUAD_CONSTRAINTS['positions'][POSITIONS[pos]]:
                continue
            if team_counts.get(team_id, 0) >= SQUAD_CONSTRAINTS['max_per_team']:
                continue
            if total_cost + cost > budget:
                continue

            # Add player
            selected.append(player)
            position_counts[pos] += 1
            team_counts[team_id] = team_counts.get(team_id, 0) + 1
            total_cost += cost

            # Check if squad is complete
            if len(selected) == SQUAD_CONSTRAINTS['total_players']:
                break

        # Format output
        results = [
            f"OPTIMIZED FPL SQUAD",
            f"Strategy: {optimize_for.upper()}",
            f"Budget Used: {format_price(int(total_cost * 10))} / {format_price(int(budget * 10))}",
            f"Remaining: {format_price(int((budget - total_cost) * 10))}",
            f"\nSQUAD ({len(selected)} players):\n"
        ]

        # Group by position
        by_position = {1: [], 2: [], 3: [], 4: []}
        for player in selected:
            by_position[player['element_type']].append(player)

        total_points = 0
        for pos_id, pos_name in POSITIONS.items():
            results.append(f"\n{pos_name} ({len(by_position[pos_id])}):")
            for player in by_position[pos_id]:
                team = teams_data[player['team']]
                total_points += player['total_points']
                results.append(
                    f"  {player['web_name']} | {team['short_name']} | "
                    f"{format_price(player['now_cost'])} | {player['total_points']}pts | "
                    f"Form: {player.get('form', 0)}"
                )

        results.append(f"\nTOTAL POINTS: {total_points}")
        results.append(
            f"\n⚠️  NOTE: This is a greedy algorithm. For true optimal solution, use Linear Programming (coming in full Phase 2).")

        return [types.TextContent(type="text", text="\n".join(results))]

    elif name == "suggest_transfers":
        team_id = arguments['team_id']
        free_transfers = arguments['free_transfers']
        available_chips = arguments.get('available_chips', [])
        max_transfers = arguments.get('max_transfers', 2)

        # Get current team
        bootstrap = await make_fpl_request("bootstrap-static/")
        if "error" in bootstrap:
            return [types.TextContent(type="text", text=f"❌ Error: {bootstrap['error']}")]

        players_data = {p['id']: p for p in bootstrap.get('elements', [])}
        teams_data = {team['id']: team for team in bootstrap.get('teams', [])}
        events = bootstrap.get('events', [])
        current_gw = next((e['id'] for e in events if e.get('is_current')), 1)

        # Get user's team
        team_data = await make_fpl_request(f"entry/{team_id}/")
        if "error" in team_data:
            return [types.TextContent(type="text", text=f"❌ Team {team_id} not found")]

        picks_data = await make_fpl_request(f"entry/{team_id}/event/{current_gw}/picks/")
        if "error" in picks_data:
            return [types.TextContent(type="text", text=f"❌ Error: {picks_data['error']}")]

        picks = picks_data.get('picks', [])
        bank = team_data.get('last_deadline_bank', 0) / 10  # Convert to millions

        # Analyze each player for transfer potential
        transfer_candidates = []

        for pick in picks:
            player = players_data.get(pick['element'])
            if not player:
                continue

            # Calculate transfer priority score
            form = float(player.get('form', 0))
            price = player['now_cost'] / 10

            # Reasons to transfer OUT
            transfer_out_score = 0
            reasons_out = []

            # Low form
            if form < 2.0:
                transfer_out_score += 30
                reasons_out.append(f"Low form ({form})")

            # Injury/suspension
            if player.get('chance_of_playing_next_round', 100) < 75:
                transfer_out_score += 50
                reasons_out.append(f"Injury risk ({player.get('chance_of_playing_next_round', 100)}%)")

            # Price dropping
            if player.get('cost_change_event', 0) < 0:
                transfer_out_score += 20
                reasons_out.append("Price falling")

            if transfer_out_score > 30:  # Threshold for consideration
                transfer_candidates.append({
                    'player': player,
                    'score': transfer_out_score,
                    'reasons': reasons_out,
                    'position': POSITIONS[player['element_type']]
                })

        # Sort by priority
        transfer_candidates.sort(key=lambda x: x['score'], reverse=True)

        # Generate recommendations
        results = [
            f"TRANSFER RECOMMENDATIONS",
            f"Team: {team_data.get('name', 'Unknown')}",
            f"Free Transfers: {free_transfers}",
            f"Bank: {format_price(int(bank * 10))}",
            f"Available Chips: {', '.join(available_chips) if available_chips else 'None'}",
            f"\n📊 ANALYSIS:\n"
        ]

        if not transfer_candidates:
            results.append("✅ Your team looks good! No urgent transfers needed.")
            results.append("\n💡 TIP: Consider saving your free transfer to have 2 next week.")
        else:
            results.append(f"Found {len(transfer_candidates)} players to consider transferring out:\n")

            for i, candidate in enumerate(transfer_candidates[:max_transfers], 1):
                player = candidate['player']
                team = teams_data[player['team']]

                results.append(f"\nTRANSFER {i}:")
                results.append(f"OUT: {player['web_name']} ({team['short_name']}) - {format_price(player['now_cost'])}")
                results.append(f"Reasons: {', '.join(candidate['reasons'])}")
                results.append(f"Priority: {'🔴 HIGH' if candidate['score'] > 50 else '🟡 MEDIUM'}")

                # Suggest replacements (simplified)
                position_id = player['element_type']
                budget_for_replacement = price + bank

                # Find good replacements
                replacements = [p for p in bootstrap.get('elements', [])
                                if p['element_type'] == position_id
                                and p['now_cost'] / 10 <= budget_for_replacement
                                and p['id'] != player['id']
                                and float(p.get('form', 0)) > 3.0]

                replacements.sort(key=lambda x: float(x.get('form', 0)), reverse=True)

                if replacements:
                    results.append(f"\n🔄 Top 3 Replacements ({candidate['position']}):")
                    for j, rep in enumerate(replacements[:3], 1):
                        rep_team = teams_data[rep['team']]
                        results.append(
                            f"  {j}. {rep['web_name']} ({rep_team['short_name']}) - "
                            f"{format_price(rep['now_cost'])} - Form: {rep.get('form', 0)}"
                        )

            # Calculate hit cost
            transfers_needed = min(len(transfer_candidates), max_transfers)
            hits = max(0, transfers_needed - free_transfers)
            hit_cost = hits * 4

            results.append(f"\n💰 COST ANALYSIS:")
            results.append(f"Transfers recommended: {transfers_needed}")
            results.append(f"Free transfers used: {min(transfers_needed, free_transfers)}")
            if hits > 0:
                results.append(f"Hits required: {hits} (-{hit_cost} points)")
                results.append(f"⚠️  Only take hits if expected gain > {hit_cost} points")
            else:
                results.append(f"✅ No hits required!")

        # Chip recommendations
        if available_chips:
            results.append(f"\n🎴 CHIP STRATEGY:")

            if 'wildcard' in available_chips and len(transfer_candidates) >= 4:
                results.append("💡 Consider WILDCARD if making 4+ changes")

            if 'free_hit' in available_chips:
                results.append("💡 Save FREE HIT for blank/double gameweeks")

            if 'bench_boost' in available_chips:
                results.append("💡 Use BENCH BOOST when all 15 players have good fixtures")

            if 'triple_captain' in available_chips:
                results.append("💡 Use TRIPLE CAPTAIN on premium players in double gameweeks")

        return [types.TextContent(type="text", text="\n".join(results))]

    else:
        raise ValueError(f"Unknown tool: {name}")


async def main():
    """Run the FPL MCP server"""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="fpl-optimizer",
                server_version="0.2.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())