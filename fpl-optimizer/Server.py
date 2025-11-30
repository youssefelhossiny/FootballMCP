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
import logging
from datetime import datetime, timedelta
from typing import Any, Optional
import httpx
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import NotificationOptions, Server
import mcp.server.stdio
from optimization import FPLOptimizer
from predict_points import FPLPointsPredictor
from enhanced_optimization import EnhancedOptimizer, FixtureAnalyzer
from chips_strategy import ChipsStrategyAnalyzer
from enhanced_features import EnhancedDataCollector
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

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

# Load optimization and prediction models
optimizer = FPLOptimizer()
enhanced_optimizer = EnhancedOptimizer()
fixture_analyzer = FixtureAnalyzer()
chips_analyzer = ChipsStrategyAnalyzer()
predictor = FPLPointsPredictor()
enhanced_collector = EnhancedDataCollector(cache_ttl_hours=6)
try:
    predictor.load_model()
    logger.info("✅ Predictor model loaded successfully")
except FileNotFoundError as e:
    logger.warning(f"⚠️ Predictor model not found: {e}")
    logger.warning("Run: python fpl-optimizer/predict_points.py")
except Exception as e:
    logger.error(f"❌ Error loading predictor: {e}")


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


def enhance_players_with_understat(players: list[dict]) -> tuple[list[dict], dict]:
    """
    Enhance FPL player data with Understat xG/xA stats

    Args:
        players: List of player dicts from FPL API

    Returns:
        Tuple of (enhanced_players, match_stats)
    """
    try:
        enhanced_players, match_stats = enhanced_collector.collect_enhanced_data(
            players,
            season="2025",
            use_cache=True
        )
        logger.info(f"✅ Enhanced {len(enhanced_players)} players with Understat data ({match_stats['match_rate']:.1f}% matched)")
        return enhanced_players, match_stats
    except Exception as e:
        logger.warning(f"⚠️  Failed to enhance with Understat data: {e}")
        # Return original players if enhancement fails
        return players, {"match_rate": 0, "methods": {}}


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
                "Returns ranked list of players with key stats including xG/xA data. "
                "Metrics: total_points, form (last 5 GW avg), value (pts/£), "
                "ownership %, transfers_in this GW, bonus points, xG, xG_per_90, xA, xA_per_90. "
                "Use for: 'Top scorers', 'Most in-form players', 'Best value picks', 'Highest xG players'"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "metric": {
                        "type": "string",
                        "enum": ["total_points", "form", "value", "selected_by", "transfers_in", "bonus", "xG", "xG_per_90", "xA", "xA_per_90"],
                        "description": "Metric to rank by (including xG/xA advanced stats)",
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
            name="evaluate_transfer",
            description=(
                "Evaluate a specific transfer you're considering. "
                "Shows: points difference, cost analysis, alternatives. "
                "Recommendation: DO IT / WAIT / RECONSIDER"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "player_out_id": {"type": "number", "description": "Player to transfer OUT"},
                    "player_in_id": {"type": "number", "description": "Player to transfer IN"},
                    "free_transfers": {"type": "number", "default": 1}
                },
                "required": ["player_out_id", "player_in_id"]
            }
        ),
        types.Tool(
            name="optimize_squad_lp",
            description=(
                "Build OPTIMAL 15-player squad from scratch using Enhanced Optimization. "
                "Features: Multi-gameweek fixture analysis (next 3-5 GWs), bench cost minimization, "
                "budget maximization (uses £99-99.5m), identifies best starting 11. "
                "Smart bench strategy: fills bench with cheapest viable players to maximize budget for starters. "
                "Returns: Squad with starting 11/bench breakdown, expected points, fixture analysis"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "budget": {
                        "type": "number",
                        "default": 100.0,
                        "description": "Maximum budget (default £100m)"
                    },
                    "optimize_for": {
                        "type": "string",
                        "enum": ["form", "points", "value", "fixtures"],
                        "default": "fixtures",
                        "description": "Optimization strategy (fixtures = best for multi-GW)"
                    },
                    "target_spend": {
                        "type": "number",
                        "default": 100.0,
                        "description": "Target spending (default £100m - use maximum budget, min £99m)"
                    },
                    "num_gameweeks": {
                        "type": "number",
                        "default": 5,
                        "description": "Number of gameweeks to analyze (default 5)"
                    }
                }
            }
        ),
        types.Tool(
            name="analyze_fixtures",
            description=(
                "Analyze upcoming fixtures for next 3-5 gameweeks. "
                "Returns fixture difficulty ratings (FDR), identifies teams with good/bad runs, "
                "highlights double gameweeks, shows which teams to target/avoid. "
                "Use before making transfers or building squads."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "num_gameweeks": {
                        "type": "number",
                        "default": 5,
                        "description": "Number of gameweeks to analyze"
                    },
                    "team_filter": {
                        "type": "string",
                        "description": "Optional: filter by team name (e.g., 'Arsenal', 'Liverpool')"
                    }
                }
            }
        ),
        types.Tool(
            name="optimize_lineup",
            description=(
                "Select best starting 11 from your 15-player squad. "
                "Uses ML predictions and optimization. "
                "Returns: Starting 11, bench, formation, captain choice"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "team_id": {"type": "number", "description": "Your FPL team ID"},
                    "gameweek": {"type": "number", "description": "Target gameweek"}
                },
                "required": ["team_id"]
            }
        ),
        types.Tool(
            name="suggest_captain",
            description=(
                "Data-driven captain recommendation for this gameweek. "
                "Considers: form, fixtures, opponent strength, position. "
                "Returns: Top 3 captain options with predicted points"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "team_id": {"type": "number"},
                    "gameweek": {"type": "number"}
                },
                "required": ["team_id"]
            }
        ),
        types.Tool(
            name="suggest_chips_strategy",
            description=(
                "Strategic recommendations for when to use your FPL chips. "
                "Analyzes upcoming fixtures to find optimal timing for: "
                "Wildcard (unlimited transfers), Bench Boost (bench scores), "
                "Triple Captain (3x points), Free Hit (one-week team). "
                "Identifies double/blank gameweeks and fixture swings. "
                "REQUIRES: List of available chips (e.g., ['Wildcard', 'Bench Boost'])"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "available_chips": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Chips you still have (e.g., ['Wildcard', 'Triple Captain'])"
                    },
                    "num_gameweeks": {
                        "type": "number",
                        "default": 10,
                        "description": "How many GWs ahead to analyze (default 10)"
                    }
                },
                "required": ["available_chips"]
            }
        ),
        types.Tool(
            name="suggest_transfers",
            description=(
                "Suggest transfer recommendations based on your current team and upcoming fixtures. "
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
                        "description": "Number of free transfers available (0-5). User must provide this.",
                        "minimum": 0,
                        "maximum": 5
                    },
                    "available_chips": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["wildcard", "free_hit", "bench_boost", "triple_captain"]
                        },
                        "description": "List of available chips. User must provide this. Example: ['wildcard', 'free_hit']",
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

        # Enhance players with xG/xA data
        players, _ = enhance_players_with_understat(players)

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

            # Add xG info if available
            xg_info = ""
            if player.get('xG', 0) > 0 or player.get('xA', 0) > 0:
                xg_info = f" | xG: {player.get('xG', 0):.1f} xA: {player.get('xA', 0):.1f}"

            results.append(
                f"{i}. {player['web_name']} | {team['short_name']} | {POSITIONS[player['element_type']]} | "
                f"Price: {format_price(player['now_cost'])} | Points: {player['total_points']} | "
                f"Form: {player.get('form', 0)} | Value: {value:.1f}pts/£{xg_info}"
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

        # Enhance with Understat xG/xA data
        enhanced_players, _ = enhance_players_with_understat([player])
        player = enhanced_players[0] if enhanced_players else player

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

        # Add Understat advanced stats if available
        if player.get('xG', 0) > 0 or player.get('xA', 0) > 0:
            results.append(f"\n⚡ ADVANCED STATS (Understat):")

            # Expected stats (total)
            results.append(f"xG (Expected Goals): {player.get('xG', 0):.2f}")
            results.append(f"xA (Expected Assists): {player.get('xA', 0):.2f}")

            # Non-penalty stats (if available)
            if player.get('npxG', 0) > 0:
                results.append(f"npxG (Non-Penalty xG): {player.get('npxG', 0):.2f}")

            # Per-90 stats
            results.append(f"\nPer-90 Stats:")
            results.append(f"xG per 90: {player.get('xG_per_90', 0):.2f} | xA per 90: {player.get('xA_per_90', 0):.2f}")
            if player.get('npxG_per_90', 0) > 0:
                results.append(f"npxG per 90: {player.get('npxG_per_90', 0):.2f}")

            # Involvement stats
            if player.get('xGChain', 0) > 0 or player.get('xGBuildup', 0) > 0:
                results.append(f"\nAttack Involvement:")
                results.append(f"xG Chain: {player.get('xGChain', 0):.2f} ({player.get('xGChain_per_90', 0):.2f} per 90)")
                results.append(f"xG Buildup: {player.get('xGBuildup', 0):.2f} ({player.get('xGBuildup_per_90', 0):.2f} per 90)")

            # Shooting and passing
            results.append(f"\nShooting & Passing:")
            results.append(f"Shots: {player.get('shots', 0)} | Key Passes: {player.get('key_passes', 0)}")
            if player.get('shots_on_target', 0) > 0:
                shot_accuracy = (player.get('shots_on_target', 0) / player.get('shots', 1)) * 100
                results.append(f"Shot Accuracy: {shot_accuracy:.1f}%")

            # Show over/underperformance
            results.append(f"\nPerformance vs Expected:")
            xg_overperf = player.get('xG_overperformance', 0)
            if xg_overperf > 0.5:
                results.append(f"📈 Overperforming xG by {xg_overperf:.2f} (scoring more than expected!)")
            elif xg_overperf < -0.5:
                results.append(f"📉 Underperforming xG by {abs(xg_overperf):.2f} (due for goals!)")
            else:
                results.append(f"xG overperformance: {xg_overperf:+.2f}")

            # Non-penalty overperformance (if meaningful)
            npxg_overperf = player.get('npxG_overperformance', 0)
            if abs(npxg_overperf) > 0.3:
                results.append(f"npxG overperformance: {npxg_overperf:+.2f}")

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

        # Enhance ALL players with Understat data (for xG info in all metrics)
        players, _ = enhance_players_with_understat(players)

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
        elif metric == 'xG':
            players.sort(key=lambda x: float(x.get('xG', 0)), reverse=True)
            metric_name = "Expected Goals (xG)"
        elif metric == 'xG_per_90':
            players.sort(key=lambda x: float(x.get('xG_per_90', 0)), reverse=True)
            metric_name = "xG per 90"
        elif metric == 'xA':
            players.sort(key=lambda x: float(x.get('xA', 0)), reverse=True)
            metric_name = "Expected Assists (xA)"
        elif metric == 'xA_per_90':
            players.sort(key=lambda x: float(x.get('xA_per_90', 0)), reverse=True)
            metric_name = "xA per 90"

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
            elif metric == 'xG':
                metric_val = f"{player.get('xG', 0):.2f}"
            elif metric == 'xG_per_90':
                metric_val = f"{player.get('xG_per_90', 0):.2f}"
            elif metric == 'xA':
                metric_val = f"{player.get('xA', 0):.2f}"
            elif metric == 'xA_per_90':
                metric_val = f"{player.get('xA_per_90', 0):.2f}"
            else:
                metric_val = f"{player['total_points']}"

            # Add xG info to output if available (for non-xG metrics)
            xg_info = ""
            if metric not in ['xG', 'xG_per_90', 'xA', 'xA_per_90'] and player.get('xG', 0) > 0:
                xg_info = f" | xG: {player.get('xG', 0):.1f}"

            results.append(
                f"{i}. {player['web_name']} | {team['short_name']} | {POSITIONS[player['element_type']]} | "
                f"{format_price(player['now_cost'])} | {metric_name}: {metric_val}{xg_info}"
            )

        return [types.TextContent(type="text", text="\n".join(results))]

    elif name == "optimize_squad_lp":
        try:
            # Handle None arguments
            if arguments is None:
                arguments = {}

            logger.info(f"🔄 Optimizing squad with arguments: {arguments}")

            # Fetch data
            bootstrap = await make_fpl_request("bootstrap-static/")
            if "error" in bootstrap:
                return [types.TextContent(type="text", text=f"❌ Error: {bootstrap['error']}")]

            fixtures_data = await make_fpl_request("fixtures/")
            if "error" in fixtures_data:
                logger.warning("Could not fetch fixtures, using basic optimization")
                fixtures_data = []

            players = bootstrap.get('elements', [])
            teams_data = {team['id']: team for team in bootstrap.get('teams', [])}
            events = bootstrap.get('events', [])
            current_gw = next((e['id'] for e in events if e.get('is_current')), 1)

            # Enhance players with xG/xA data for better predictions
            players, match_stats = enhance_players_with_understat(players)
            logger.info(f"📊 Enhanced {len(players)} players with Understat data ({match_stats.get('match_rate', 0):.1f}% matched)")

            budget = arguments.get('budget', 100.0)
            optimize_for = arguments.get('optimize_for', 'fixtures')
            target_spend = arguments.get('target_spend', 100.0)  # Use maximum budget
            num_gws = arguments.get('num_gameweeks', 5)

            logger.info(f"📊 Using enhanced optimizer: budget=£{budget}m, target=£{target_spend}m, strategy={optimize_for}, GWs={num_gws}")

            # Use Enhanced Optimizer
            squad, lineup_info, status = enhanced_optimizer.optimize_squad_with_fixtures(
                players=players,
                fixtures=fixtures_data,
                teams=teams_data,
                current_gw=current_gw,
                budget=budget,
                optimize_for=optimize_for,
                target_spend=target_spend,
                num_gws=num_gws
            )

            if not squad:
                return [types.TextContent(type="text", text=f"❌ {status}")]

            logger.info(f"✅ Squad optimized: {len(squad)} players, cost=£{lineup_info['total_cost']:.1f}m")

            # Format results
            results = [
                f"🎯 OPTIMAL SQUAD (Enhanced Multi-GW Optimization)",
                f"📅 Analyzed: GW{current_gw} to GW{current_gw + num_gws - 1}",
                f"💰 Cost: £{lineup_info['total_cost']:.1f}m / £{budget}m",
                f"💵 Remaining: £{lineup_info['money_remaining']:.1f}m",
                f"⚡ Expected Points (next {num_gws} GWs): {lineup_info['expected_points']:.1f}",
                f"📐 Formation: {lineup_info['formation']}",
                f"\n🟢 STARTING 11:",
            ]

            # Show starting 11
            for player in lineup_info['starting_11']:
                team = teams_data[player['team']]
                pos = POSITIONS[player['element_type']]
                pred_pts = predictor.predict_player_points(player, {}, {})
                results.append(
                    f"  {pos} | {player['web_name']} ({team['short_name']}) - "
                    f"£{player['now_cost'] / 10}m - {pred_pts:.1f}pts/gw"
                )

            # Show bench
            results.append(f"\n🪑 BENCH (Cost-minimized):")
            bench_cost = sum([p['now_cost'] / 10 for p in lineup_info['bench']])
            results.append(f"  Total bench cost: £{bench_cost:.1f}m")
            for player in lineup_info['bench']:
                team = teams_data[player['team']]
                pos = POSITIONS[player['element_type']]
                results.append(
                    f"  {pos} | {player['web_name']} ({team['short_name']}) - £{player['now_cost'] / 10}m"
                )

            results.append(f"\n💡 Strategy: Optimized for {optimize_for} over next {num_gws} gameweeks")
            results.append(f"📈 Smart bench: Cheap enablers to maximize starting 11 budget")

            return [types.TextContent(type="text", text="\n".join(results))]
        except Exception as e:
            logger.error(f"Error in optimize_squad_lp: {e}", exc_info=True)
            return [types.TextContent(type="text", text=f"❌ Error optimizing squad: {str(e)}\nCheck logs for details.")]

    elif name == "analyze_fixtures":
        try:
            if arguments is None:
                arguments = {}

            logger.info(f"🔄 Analyzing fixtures with arguments: {arguments}")

            # Fetch data
            bootstrap = await make_fpl_request("bootstrap-static/")
            if "error" in bootstrap:
                return [types.TextContent(type="text", text=f"❌ Error: {bootstrap['error']}")]

            fixtures_data = await make_fpl_request("fixtures/")
            if "error" in fixtures_data:
                return [types.TextContent(type="text", text="❌ Could not fetch fixtures data")]

            teams_data = {team['id']: team for team in bootstrap.get('teams', [])}
            events = bootstrap.get('events', [])
            current_gw = next((e['id'] for e in events if e.get('is_current')), 1)

            num_gws = arguments.get('num_gameweeks', 5)
            team_filter = arguments.get('team_filter', '').lower()

            logger.info(f"📊 Analyzing next {num_gws} gameweeks from GW{current_gw}")

            # Analyze fixtures
            analysis = fixture_analyzer.analyze_fixtures(
                fixtures_data, teams_data, current_gw, num_gws
            )

            # Sort teams by difficulty score (easier fixtures first)
            sorted_teams = sorted(
                analysis.items(),
                key=lambda x: x[1]['difficulty_score'],
                reverse=True
            )

            # Filter if requested
            if team_filter:
                sorted_teams = [
                    (tid, data) for tid, data in sorted_teams
                    if team_filter in teams_data[tid]['name'].lower() or
                       team_filter in teams_data[tid]['short_name'].lower()
                ]

            results = [
                f"📅 FIXTURE ANALYSIS: GW{current_gw} to GW{current_gw + num_gws - 1}",
                f"\n🟢 EASIEST FIXTURES (Target these teams):",
            ]

            # Show top 5 easiest
            for team_id, data in sorted_teams[:5]:
                team = teams_data[team_id]
                fdr_rating = "⭐" * max(1, 6 - int(data['fdr_avg']))
                double_marker = " 🔥 DOUBLE!" if data.get('has_doubles') else ""
                results.append(
                    f"  {team['short_name']:<4} | FDR: {data['fdr_avg']:.1f} {fdr_rating} | "
                    f"{data['num_fixtures']} fixtures{double_marker}"
                )

            results.append(f"\n🔴 HARDEST FIXTURES (Avoid these teams):")

            # Show bottom 5 hardest
            for team_id, data in sorted_teams[-5:]:
                team = teams_data[team_id]
                results.append(
                    f"  {team['short_name']:<4} | FDR: {data['fdr_avg']:.1f} | "
                    f"{data['num_fixtures']} fixtures"
                )

            results.append(f"\n💡 Tip: Use 'optimize_squad_lp' with optimize_for='fixtures' to build around easy fixtures")
            results.append(f"📊 FDR Scale: 1=Very Easy ⭐⭐⭐⭐⭐ → 5=Very Hard ⭐")

            return [types.TextContent(type="text", text="\n".join(results))]
        except Exception as e:
            logger.error(f"Error in analyze_fixtures: {e}", exc_info=True)
            return [types.TextContent(type="text", text=f"❌ Error analyzing fixtures: {str(e)}")]

    elif name == "evaluate_transfer":
        try:
            # Handle None arguments
            if arguments is None:
                arguments = {}

            # Fetch bootstrap data
            bootstrap = await make_fpl_request("bootstrap-static/")
            if "error" in bootstrap:
                return [types.TextContent(type="text", text=f"❌ Error: {bootstrap['error']}")]

            players_list = bootstrap.get('elements', [])
            teams_data = {team['id']: team for team in bootstrap.get('teams', [])}

            # Enhance players with xG/xA data for better transfer evaluation
            enhanced_players, _ = enhance_players_with_understat(players_list)
            players_data = {p['id']: p for p in enhanced_players}

            player_out_id = arguments.get('player_out_id')
            player_in_id = arguments.get('player_in_id')

            if not player_out_id or not player_in_id:
                return [types.TextContent(type="text", text="❌ Missing required parameters: player_out_id and player_in_id")]

            free_transfers = arguments.get('free_transfers', 1)

            player_out = players_data.get(player_out_id)
            player_in = players_data.get(player_in_id)

            if not player_out or not player_in:
                return [types.TextContent(type="text", text="❌ Player not found")]

            # Predict points
            out_pred = predictor.predict_player_points(player_out, {}, {})
            in_pred = predictor.predict_player_points(player_in, {}, {})

            # Cost analysis
            cost_diff = (player_in['now_cost'] - player_out['now_cost']) / 10
            hit_cost = 0 if free_transfers > 0 else 4
            expected_gain = (in_pred - out_pred) - hit_cost

            out_team = teams_data[player_out['team']]
            in_team = teams_data[player_in['team']]

            # Get xG comparison
            out_xg = player_out.get('xG', 0)
            in_xg = player_in.get('xG', 0)
            out_xg90 = player_out.get('xG_per_90', 0)
            in_xg90 = player_in.get('xG_per_90', 0)

            results = [
                f"TRANSFER EVALUATION",
                f"OUT: {player_out['web_name']} ({out_team['short_name']}) - £{player_out['now_cost'] / 10}m",
                f"IN: {player_in['web_name']} ({in_team['short_name']}) - £{player_in['now_cost'] / 10}m",
                f"\nPREDICTIONS:",
                f"  {player_out['web_name']}: {out_pred:.1f} pts/gw",
                f"  {player_in['web_name']}: {in_pred:.1f} pts/gw",
            ]

            # Add xG comparison if available
            if in_xg > 0 or out_xg > 0:
                results.append(f"\n⚡ ADVANCED STATS (xG/xA):")
                results.append(f"  {player_out['web_name']}: xG={out_xg:.2f} (xG/90: {out_xg90:.2f})")
                results.append(f"  {player_in['web_name']}: xG={in_xg:.2f} (xG/90: {in_xg90:.2f})")
                xg_diff = in_xg90 - out_xg90
                if xg_diff > 0.1:
                    results.append(f"  📈 {player_in['web_name']} has {xg_diff:.2f} higher xG per 90!")
                elif xg_diff < -0.1:
                    results.append(f"  📉 {player_out['web_name']} has {abs(xg_diff):.2f} higher xG per 90")

            results.extend([
                f"\nCOST ANALYSIS:",
                f"  Price difference: £{cost_diff:.1f}m",
                f"  Hit cost: {hit_cost} pts",
                f"  Expected gain: {expected_gain:.1f} pts",
                f"\nRECOMMENDATION:",
            ])

            if expected_gain > 5:
                results.append("🟢 DO IT! Significant points gain expected")
            elif expected_gain > 0:
                results.append("🟡 CONSIDER IT. Small gain but positive")
            else:
                results.append("🔴 WAIT. Negative expected gain")

            return [types.TextContent(type="text", text="\n".join(results))]
        except Exception as e:
            logger.error(f"Error in evaluate_transfer: {e}", exc_info=True)
            return [types.TextContent(type="text", text=f"❌ Error evaluating transfer: {str(e)}")]

    elif name == "optimize_lineup":
        try:
            # Handle None arguments
            if arguments is None:
                arguments = {}

            # Fetch bootstrap data
            bootstrap = await make_fpl_request("bootstrap-static/")
            if "error" in bootstrap:
                return [types.TextContent(type="text", text=f"❌ Error: {bootstrap['error']}")]

            players_data = {p['id']: p for p in bootstrap.get('elements', [])}
            teams_data = {team['id']: team for team in bootstrap.get('teams', [])}
            events = bootstrap.get('events', [])
            current_gw = next((e['id'] for e in events if e.get('is_current')), 1)

            team_id = arguments.get('team_id')
            if not team_id:
                return [types.TextContent(type="text", text="❌ Missing required parameter: team_id")]

            gameweek = arguments.get('gameweek', current_gw)

            # Get user's squad
            team_data = await make_fpl_request(f"entry/{team_id}/")
            picks_data = await make_fpl_request(f"entry/{team_id}/event/{gameweek}/picks/")

            squad_players = [players_data[p['element']] for p in picks_data.get('picks', [])]

            # Optimize lineup
            lineup_result = optimizer.optimize_lineup(squad_players, gameweek)

            if 'error' in lineup_result:
                return [types.TextContent(type="text", text=f"❌ {lineup_result['error']}")]

            results = [
                f"OPTIMIZED LINEUP - GW{gameweek}",
                f"Formation: {lineup_result['formation']}",
                f"Captain: {lineup_result['captain']['web_name']}",
                f"Vice Captain: {lineup_result['vice_captain']['web_name']}",
                f"Expected Points: {lineup_result['expected_points']:.1f}",
                f"\nSTARTING 11:",
            ]

            for player in lineup_result['starting_11']:
                team = teams_data[player['team']]
                pred_pts = predictor.predict_player_points(player, {}, {})
                captain_mark = " (C)" if player['id'] == lineup_result['captain']['id'] else ""
                results.append(f"  {player['web_name']} ({team['short_name']}) - {pred_pts:.1f}pts{captain_mark}")

            results.append(f"\nBENCH:")
            for player in lineup_result['bench']:
                team = teams_data[player['team']]
                results.append(f"  {player['web_name']} ({team['short_name']})")

            return [types.TextContent(type="text", text="\n".join(results))]
        except Exception as e:
            logger.error(f"Error in optimize_lineup: {e}", exc_info=True)
            return [types.TextContent(type="text", text=f"❌ Error optimizing lineup: {str(e)}")]

    elif name == "suggest_captain":
        try:
            # Handle None arguments
            if arguments is None:
                arguments = {}

            # Fetch bootstrap data
            bootstrap = await make_fpl_request("bootstrap-static/")
            if "error" in bootstrap:
                return [types.TextContent(type="text", text=f"❌ Error: {bootstrap['error']}")]

            players_list = bootstrap.get('elements', [])
            teams_data = {team['id']: team for team in bootstrap.get('teams', [])}
            events = bootstrap.get('events', [])
            current_gw = next((e['id'] for e in events if e.get('is_current')), 1)

            # Enhance players with xG/xA data for better captain predictions
            enhanced_players, _ = enhance_players_with_understat(players_list)
            players_data = {p['id']: p for p in enhanced_players}

            team_id = arguments.get('team_id')
            if not team_id:
                return [types.TextContent(type="text", text="❌ Missing required parameter: team_id")]

            gameweek = arguments.get('gameweek', current_gw)

            # Get squad
            picks_data = await make_fpl_request(f"entry/{team_id}/event/{gameweek}/picks/")
            squad = [players_data[p['element']] for p in picks_data.get('picks', [])]

            # Get fixtures for gameweek
            fixtures_data = await make_fpl_request("fixtures/")
            gw_fixtures = {f['team_h']: {'is_home': True, 'opponent': f['team_a']}
                           for f in fixtures_data if f['event'] == gameweek}

            # Score captaincy options
            captain_scores = {}
            for player in squad:
                # Predict points with 2x multiplier (using enhanced xG data)
                base_pred = predictor.predict_player_points(player, {}, {})
                captaincy_score = base_pred * 2

                # Bonus for premium players
                if player['now_cost'] >= 10.0:
                    captaincy_score += 1

                # Bonus for high xG players (reliable scorers)
                xg_per_90 = player.get('xG_per_90', 0)
                if xg_per_90 > 0.5:  # Elite xG
                    captaincy_score += 1
                elif xg_per_90 > 0.3:  # Good xG
                    captaincy_score += 0.5

                captain_scores[player['id']] = (player, captaincy_score)

            # Top 3
            top_3 = sorted(captain_scores.items(), key=lambda x: x[1][1], reverse=True)[:3]

            results = [
                f"CAPTAIN RECOMMENDATIONS - GW{gameweek}",
                f"\nTop 3 Options:",
            ]

            for rank, (p_id, (player, score)) in enumerate(top_3, 1):
                team = teams_data[player['team']]
                base_pts = score / 2
                captain_pts = score
                xg_info = ""
                if player.get('xG_per_90', 0) > 0:
                    xg_info = f" | xG/90: {player.get('xG_per_90', 0):.2f}"
                results.append(
                    f"{rank}. {player['web_name']} ({team['short_name']}) "
                    f"- Base: {base_pts:.1f}pts, Captain: {captain_pts:.1f}pts{xg_info}"
                )

            return [types.TextContent(type="text", text="\n".join(results))]
        except Exception as e:
            logger.error(f"Error in suggest_captain: {e}", exc_info=True)
            return [types.TextContent(type="text", text=f"❌ Error suggesting captain: {str(e)}")]

    elif name == "suggest_chips_strategy":
        try:
            if arguments is None:
                arguments = {}

            available_chips = arguments.get('available_chips', [])
            if not available_chips:
                return [types.TextContent(type="text", text="❌ Please provide available chips (e.g., ['Wildcard', 'Bench Boost'])")]

            logger.info(f"🎴 Analyzing chips strategy for: {available_chips}")

            # Fetch data
            bootstrap = await make_fpl_request("bootstrap-static/")
            if "error" in bootstrap:
                return [types.TextContent(type="text", text=f"❌ Error: {bootstrap['error']}")]

            fixtures_data = await make_fpl_request("fixtures/")
            if "error" in fixtures_data:
                return [types.TextContent(type="text", text="❌ Could not fetch fixtures data")]

            teams_data = {team['id']: team for team in bootstrap.get('teams', [])}
            events = bootstrap.get('events', [])
            current_gw = next((e['id'] for e in events if e.get('is_current')), 1)

            num_gws = arguments.get('num_gameweeks', 10)

            # Analyze chips
            analysis = chips_analyzer.analyze_chips_strategy(
                available_chips=available_chips,
                fixtures=fixtures_data,
                teams=teams_data,
                current_gw=current_gw,
                num_gws=num_gws
            )

            results = [
                f"🎴 CHIPS STRATEGY ANALYSIS",
                f"📅 Analyzing GW{current_gw} to GW{current_gw + num_gws - 1}",
                f"🎯 Available chips: {', '.join(available_chips)}",
                ""
            ]

            # Show recommendations for each chip
            for chip_name, chip_data in analysis.items():
                chip_display = chip_name.replace('_', ' ').title()
                results.append(f"\n{'='*50}")
                results.append(f"🎴 {chip_display.upper()}")
                results.append(f"{'='*50}")

                if 'recommendations' in chip_data:
                    for i, rec in enumerate(chip_data['recommendations'][:3], 1):  # Top 3 recommendations
                        priority_emoji = {
                            'VERY HIGH': '🔴',
                            'HIGH': '🟠',
                            'MEDIUM': '🟡',
                            'LOW': '🟢'
                        }.get(rec.get('priority', 'MEDIUM'), '🟡')

                        results.append(f"\n{i}. GW{rec['gameweek']} {priority_emoji} {rec['priority']} PRIORITY")
                        results.append(f"   Reason: {rec['reason']}")
                        results.append(f"   Benefit: {rec['benefit']}")

                if 'tip' in chip_data:
                    results.append(f"\n💡 Tip: {chip_data['tip']}")

                if 'best_gw' in chip_data and chip_data['best_gw']:
                    results.append(f"✅ Best gameweek: GW{chip_data['best_gw']}")

            results.append(f"\n\n📊 Summary:")
            results.append(f"Use chips strategically to maximize points over the season.")
            results.append(f"🔴 = Must use here | 🟠 = Highly recommended | 🟡 = Good option | 🟢 = Can wait")

            return [types.TextContent(type="text", text="\n".join(results))]
        except Exception as e:
            logger.error(f"Error in suggest_chips_strategy: {e}", exc_info=True)
            return [types.TextContent(type="text", text=f"❌ Error analyzing chips: {str(e)}")]

    elif name == "suggest_transfers":
        team_id = arguments['team_id']
        free_transfers = arguments.get('free_transfers', 0)
        available_chips = arguments.get('available_chips', [])
        max_transfers = arguments.get('max_transfers', 2)

        # Validate inputs
        if not isinstance(free_transfers, (int, float)):
            return [types.TextContent(
                type="text",
                text=f"❌ Error: free_transfers must be a number (0-5), got {type(free_transfers)}"
            )]

        if not isinstance(available_chips, list):
            return [types.TextContent(
                type="text",
                text=f"❌ Error: available_chips must be a list, got {type(available_chips)}"
            )]

        # Normalize available_chips to lowercase (handle user variations)
        available_chips_normalized = []
        for chip in available_chips:
            if isinstance(chip, str):
                chip_lower = chip.lower().strip()
                # Map common variations
                if chip_lower in ["wildcard", "wc"]:
                    available_chips_normalized.append("wildcard")
                elif chip_lower in ["free_hit", "fh"]:
                    available_chips_normalized.append("free_hit")
                elif chip_lower in ["bench_boost", "bb"]:
                    available_chips_normalized.append("bench_boost")
                elif chip_lower in ["triple_captain", "tc", "triple captain"]:
                    available_chips_normalized.append("triple_captain")
                # Ignore unrecognized chips

        available_chips = list(set(available_chips_normalized))  # Remove duplicates

        # Get current team
        bootstrap = await make_fpl_request("bootstrap-static/")
        if "error" in bootstrap:
            return [types.TextContent(type="text", text=f"❌ Error: {bootstrap['error']}")]

        players_list = bootstrap.get('elements', [])
        teams_data = {team['id']: team for team in bootstrap.get('teams', [])}
        events = bootstrap.get('events', [])
        current_gw = next((e['id'] for e in events if e.get('is_current')), 1)

        # Enhance players with xG/xA data for better transfer suggestions
        enhanced_players, _ = enhance_players_with_understat(players_list)
        players_data = {p['id']: p for p in enhanced_players}

        # Get user's team
        team_data = await make_fpl_request(f"entry/{team_id}/")
        if "error" in team_data:
            return [types.TextContent(type="text", text=f"❌ Team {team_id} not found")]

        picks_data = await make_fpl_request(f"entry/{team_id}/event/{current_gw}/picks/")
        if "error" in picks_data:
            return [types.TextContent(type="text", text=f"❌ Error: {picks_data['error']}")]

        picks = picks_data.get('picks', [])
        bank = (team_data.get('last_deadline_bank', 0) / 10) if team_data.get('last_deadline_bank') else 0.0

        # Analyze each player for transfer potential
        transfer_candidates = []

        for pick in picks:
            player = players_data.get(pick['element'])
            if not player:
                continue

            # Calculate transfer priority score
            form = float(player.get('form', 0)) if player.get('form') is not None else 0.0
            price = player['now_cost'] / 10 if player.get('now_cost') else 0.0

            # Reasons to transfer OUT
            transfer_out_score = 0
            reasons_out = []

            # Low form
            if form < 2.0:
                transfer_out_score += 30
                reasons_out.append(f"Low form ({form})")

            # Injury/suspension
            chance_of_playing = player.get('chance_of_playing_next_round')
            if chance_of_playing is not None and chance_of_playing < 75:
                transfer_out_score += 50
                reasons_out.append(f"Injury risk ({chance_of_playing}%)")

            # Price dropping
            if player.get('cost_change_event', 0) < 0:
                transfer_out_score += 20
                reasons_out.append("Price falling")

            # Low xG underperformance (could regress positively, but risky)
            xg_overperf = player.get('xG_overperformance', 0)
            if xg_overperf > 3.0:  # Massively overperforming xG - regression risk
                transfer_out_score += 15
                reasons_out.append(f"High regression risk (xG overperf: +{xg_overperf:.1f})")

            # Low underlying stats
            xg_per_90 = player.get('xG_per_90', 0)
            position = player.get('element_type', 3)
            if position in [3, 4] and xg_per_90 < 0.15 and form < 4.0:  # Attackers with bad xG
                transfer_out_score += 20
                reasons_out.append(f"Poor xG ({xg_per_90:.2f} per 90)")

            if transfer_out_score > 30:  # Threshold for consideration
                transfer_candidates.append({
                    'player': player,
                    'score': transfer_out_score,
                    'reasons': reasons_out,
                    'position': POSITIONS.get(player['element_type'], 'UNK')
                })

        # Sort by priority
        transfer_candidates.sort(key=lambda x: x['score'], reverse=True)

        # Generate recommendations
        results = [
            f"TRANSFER RECOMMENDATIONS",
            f"Team: {team_data.get('name', 'Unknown')}",
            f"Free Transfers: {int(free_transfers)}",
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
                team = teams_data.get(player['team'], {})

                results.append(f"\nTRANSFER {i}:")
                results.append(
                    f"OUT: {player['web_name']} ({team.get('short_name', 'TBD')}) - {format_price(player['now_cost'])}")
                results.append(f"Reasons: {', '.join(candidate['reasons'])}")
                results.append(f"Priority: {'🔴 HIGH' if candidate['score'] > 50 else '🟡 MEDIUM'}")

                # Suggest replacements (simplified)
                position_id = player['element_type']
                budget_for_replacement = (player['now_cost'] / 10) + bank

                # Find good replacements
                replacements = [p for p in bootstrap.get('elements', [])
                                if p['element_type'] == position_id
                                and (p['now_cost'] / 10) <= budget_for_replacement
                                and p['id'] != player['id']
                                and float(p.get('form', 0) or 0) > 3.0]

                replacements.sort(key=lambda x: float(x.get('form', 0) or 0), reverse=True)

                if replacements:
                    results.append(f"\n🔄 Top 3 Replacements ({candidate['position']}):")
                    for j, rep in enumerate(replacements[:3], 1):
                        rep_team = teams_data.get(rep['team'], {})
                        rep_form = float(rep.get('form', 0) or 0)
                        results.append(
                            f"  {j}. {rep['web_name']} ({rep_team.get('short_name', 'TBD')}) - "
                            f"{format_price(rep['now_cost'])} - Form: {rep_form}"
                        )

        # Calculate hit cost
        transfers_needed = min(len(transfer_candidates), max_transfers)
        hits = max(0, transfers_needed - int(free_transfers))
        hit_cost = hits * 4

        results.append(f"\n💰 COST ANALYSIS:")
        results.append(f"Transfers recommended: {transfers_needed}")
        results.append(f"Free transfers used: {min(transfers_needed, int(free_transfers))}")
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