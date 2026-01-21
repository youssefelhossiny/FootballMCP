"""
FastAPI Backend Server for FPL Website
Provides REST API endpoints for the React frontend
Integrates ALL MCP tools: Understat xG/xA, FBRef defensive stats, optimization algorithms
"""

import os
from pathlib import Path

# Load environment variables from .env file
from dotenv import load_dotenv
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, List, Optional, Any
import asyncio
import aiohttp
import ssl
import certifi
import json
import httpx
import re
from pathlib import Path

# Authentication imports
from auth import (
    AccessCodeRequest,
    TokenResponse,
    verify_access_code,
    create_access_token,
    verify_token,
    check_auth_configured
)

# Anthropic chat integration (replaces Ollama)
from anthropic_chat import query_anthropic

# Import existing modules - FULL MCP INTEGRATION
from enhanced_features import EnhancedDataCollector
from predict_points import FPLPointsPredictor
from data_sources.availability_filter import AvailabilityFilter
from enhanced_optimization import EnhancedOptimizer, FixtureAnalyzer
from chips_strategy import ChipsStrategyAnalyzer

app = FastAPI(title="FPL Optimizer API", version="2.0.0")

# CORS middleware for React frontend
# Production origins can be set via ALLOWED_ORIGINS env var (comma-separated)
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "").split(",") if os.getenv("ALLOWED_ORIGINS") else []
DEFAULT_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001"
]
ALL_ORIGINS = list(set(DEFAULT_ORIGINS + [o.strip() for o in ALLOWED_ORIGINS if o.strip()]))

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALL_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global instances - matching MCP Server
enhanced_collector = EnhancedDataCollector()
predictor = FPLPointsPredictor()
availability_filter = AvailabilityFilter()
fixture_analyzer = FixtureAnalyzer()
chips_analyzer = ChipsStrategyAnalyzer()

# FPL API Configuration
FPL_BASE_URL = "https://fantasy.premierleague.com/api"

# Position mapping
POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
POSITIONS_REV = {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}

# Cache for enhanced player data
player_cache = {
    "players": None,
    "teams": None,
    "fixtures": None,
    "last_update": None
}

# ============== OLLAMA TOOL DEFINITIONS ==============
# These define the tools the LLM can call dynamically
# ALL 12 MCP tools are now available to Ollama
FPL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_all_players",
            "description": "Get all Premier League players with comprehensive stats including prices, total points, form, and ownership. Use this tool when the user wants to browse players, find budget options, or search for players by position or team. You can filter by position (GK/DEF/MID/FWD), team name, or price range. Results can be sorted by points, form, value (points per million), or price. Returns up to 50 players with key FPL metrics.",
            "parameters": {
                "type": "object",
                "properties": {
                    "position": {
                        "type": "string",
                        "enum": ["all", "GK", "DEF", "MID", "FWD"],
                        "description": "Filter by position (default: all)"
                    },
                    "team": {
                        "type": "string",
                        "description": "Filter by team name (e.g., 'Arsenal', 'Liverpool')"
                    },
                    "max_price": {
                        "type": "number",
                        "description": "Maximum price in millions (e.g., 8.0)"
                    },
                    "min_price": {
                        "type": "number",
                        "description": "Minimum price in millions (e.g., 5.0)"
                    },
                    "sort_by": {
                        "type": "string",
                        "enum": ["points", "form", "value", "price"],
                        "description": "Sort by metric (default: points)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of players to return (default 20, max 50)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_player_details",
            "description": "Get comprehensive detailed statistics for a specific player. Returns xG (expected goals), xA (expected assists), defensive contributions, form over last 5 gameweeks, upcoming fixtures with difficulty ratings, price changes, and ownership percentage. Use this when the user asks about a specific player's performance, stats, or whether they should buy/sell them. Essential for deep-diving into individual player analysis.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_name": {
                        "type": "string",
                        "description": "The name of the player to look up (e.g., 'Salah', 'Haaland', 'Palmer')"
                    }
                },
                "required": ["player_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_fixtures",
            "description": "Get upcoming Premier League fixtures with FPL Fixture Difficulty Ratings (FDR 1-5, where 1 is easiest and 5 is hardest). Use this to analyze fixture swings, identify good/bad runs of games, and plan transfers around favorable matchups. Can filter by specific team or show all fixtures. Critical for planning transfers and captain picks based on opponent strength.",
            "parameters": {
                "type": "object",
                "properties": {
                    "team": {
                        "type": "string",
                        "description": "Team name to filter fixtures (optional, e.g., 'Arsenal', 'Liverpool')"
                    },
                    "num_gameweeks": {
                        "type": "integer",
                        "description": "Number of gameweeks to look ahead (default 5, max 10)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_team",
            "description": "Fetch the user's complete FPL squad including all 15 players (starting XI and bench), current formation, team value, bank balance, overall rank, and gameweek points. Use this when you need to see the user's actual team to make personalized recommendations. The team_id is usually already provided in the context - check there first before asking the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "team_id": {
                        "type": "integer",
                        "description": "FPL team ID from the user's FPL URL"
                    },
                    "gameweek": {
                        "type": "integer",
                        "description": "Gameweek to view (optional, defaults to current)"
                    }
                },
                "required": ["team_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_players",
            "description": "Get the top performing players ranked by a specific advanced metric. Available metrics: total_points, form, xG, xG_per_90, xA, xA_per_90, value (points per million), def_contributions_per_90, selected_by (ownership), transfers_in, and bonus points. Use this to find the best players in any category, identify differential picks with low ownership, or find undervalued gems. Can filter by position.",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {
                        "type": "string",
                        "enum": ["total_points", "form", "xG", "xG_per_90", "xA", "xA_per_90", "value", "def_contributions_per_90", "selected_by", "transfers_in", "bonus"],
                        "description": "The metric to rank players by"
                    },
                    "position": {
                        "type": "string",
                        "enum": ["all", "GK", "DEF", "MID", "FWD"],
                        "description": "Filter by position (optional, defaults to 'all')"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of players to return (default 10, max 20)"
                    }
                },
                "required": ["metric"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_transfer",
            "description": "Evaluate a specific transfer by comparing player_out vs player_in across multiple metrics: points projection, xG/xA comparison, fixture difficulty, form trends, and price difference. Returns a clear recommendation: DO IT (strong upgrade), WAIT (marginal), or RECONSIDER (downgrade). Use this AFTER suggest_transfers when the user wants to analyze a specific swap, or when they ask 'should I transfer X for Y?'. Always use this to provide data-backed transfer advice.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_out": {
                        "type": "string",
                        "description": "Name of player to transfer OUT"
                    },
                    "player_in": {
                        "type": "string",
                        "description": "Name of player to transfer IN"
                    },
                    "free_transfers": {
                        "type": "integer",
                        "description": "Number of free transfers available (default 1)"
                    }
                },
                "required": ["player_out", "player_in"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "optimize_squad",
            "description": "Build an optimal 15-player FPL squad from scratch using advanced optimization algorithms and multi-gameweek fixture analysis. Considers budget constraints, FPL rules (max 3 per team), and optimizes for form, points, value, or fixture difficulty. Returns a complete squad with starting XI, bench order, captain pick, and projected points. Use this for Wildcard planning or when users want to see the 'optimal' team they could build.",
            "parameters": {
                "type": "object",
                "properties": {
                    "budget": {
                        "type": "number",
                        "description": "Maximum budget in millions (default 100.0)"
                    },
                    "optimize_for": {
                        "type": "string",
                        "enum": ["form", "points", "value", "fixtures"],
                        "description": "Optimization strategy (default: fixtures)"
                    },
                    "num_gameweeks": {
                        "type": "integer",
                        "description": "Number of gameweeks to analyze (default 5)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_team_fixtures",
            "description": "Analyze and rank all Premier League teams by their upcoming fixture difficulty. Returns teams sorted from easiest to hardest fixtures with average FDR scores. Use this to identify which teams have favorable fixture runs (target their players) and which have tough schedules (avoid or sell). Essential for planning transfers around fixture swings and identifying teams to target.",
            "parameters": {
                "type": "object",
                "properties": {
                    "num_gameweeks": {
                        "type": "integer",
                        "description": "Number of gameweeks to analyze (default 5)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "optimize_lineup",
            "description": "Select the optimal starting 11 from a user's 15-player squad using ML-based point predictions. Analyzes each player's expected points based on form, fixtures, and historical data to determine the best formation and bench order. Returns recommended starting XI, bench order, optimal formation (e.g., 3-4-3, 4-4-2), and captain/vice-captain picks. Use this when users ask 'who should I start?' or 'what's my best lineup?'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "team_id": {
                        "type": "integer",
                        "description": "FPL team ID"
                    },
                    "gameweek": {
                        "type": "integer",
                        "description": "Target gameweek (optional, defaults to current)"
                    }
                },
                "required": ["team_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_captain",
            "description": "Generate data-driven captain recommendations for the user's squad. Analyzes form, upcoming fixture difficulty, xG/xA stats, historical performance against opponent, and home/away splits. Returns top 3 captain options ranked by expected points with detailed reasoning for each pick. Use this whenever the user asks about captain choices or who to captain this gameweek.",
            "parameters": {
                "type": "object",
                "properties": {
                    "team_id": {
                        "type": "integer",
                        "description": "FPL team ID"
                    },
                    "gameweek": {
                        "type": "integer",
                        "description": "Target gameweek (optional, defaults to current)"
                    }
                },
                "required": ["team_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_transfers",
            "description": "Generate personalized transfer recommendations based on the user's current squad. Identifies underperforming players to sell and suggests optimal replacements considering: budget constraints, fixture difficulty, form trends, injury risks, and price changes. Returns prioritized transfer targets with reasoning. Use this when users ask 'who should I transfer?' or 'what transfers should I make?'. Can filter by position or price range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "position": {
                        "type": "string",
                        "enum": ["any", "GK", "DEF", "MID", "FWD"],
                        "description": "Position to target for transfers (optional)"
                    },
                    "max_price": {
                        "type": "number",
                        "description": "Maximum price in millions (e.g., 8.5)"
                    },
                    "min_price": {
                        "type": "number",
                        "description": "Minimum price in millions (e.g., 5.0)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compare_players",
            "description": "Compare 2-4 players side-by-side across all key FPL metrics: price, total points, form, xG, xA, xG per 90, xA per 90, minutes played, ownership percentage, and upcoming fixtures. Use this when users ask 'should I get X or Y?' or 'compare Palmer vs Saka'. Provides a clear visual comparison to help with transfer decisions between similar-priced or same-position players.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of player names to compare (2-4 players)"
                    }
                },
                "required": ["player_names"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_chip_strategy",
            "description": "Get strategic recommendations for when to use FPL chips: Wildcard (unlimited free transfers), Bench Boost (bench players score), Triple Captain (3x captain points), and Free Hit (one-week unlimited transfers). Analyzes upcoming fixtures, blank/double gameweeks, and team state to suggest optimal chip timing. Use this when users ask 'when should I use my wildcard?' or 'is this a good week for bench boost?'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "available_chips": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of available chips (e.g., ['wildcard', 'benchboost', 'triplecaptain', 'freehit'])"
                    }
                },
                "required": ["available_chips"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "make_transfer",
            "description": "Execute a transfer in the theoretical lineup by swapping player_out for player_in. This updates the visual squad display in the frontend WITHOUT making actual FPL transfers. Use this when: 1) User explicitly agrees to a suggested transfer, 2) User asks to 'replace X with Y' or 'swap X for Y', 3) User says 'do it' or 'make that transfer' after a suggestion. Always include a brief reason. The frontend will show the updated theoretical squad.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_out": {
                        "type": "string",
                        "description": "Name of the player to transfer OUT (must be in user's current team)"
                    },
                    "player_in": {
                        "type": "string",
                        "description": "Name of the player to transfer IN (replacement)"
                    },
                    "reason": {
                        "type": "string",
                        "description": "Brief reason for the transfer (e.g., 'better fixtures', 'higher form', 'injury replacement')"
                    }
                },
                "required": ["player_out", "player_in"]
            }
        }
    }
]


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str

class ChatRequest(BaseModel):
    message: str
    team_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    history: Optional[List[ChatMessage]] = None  # Conversation history for context


class TransferAction(BaseModel):
    player_out: str
    player_in: str
    reason: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    tools_used: List[str] = []
    transfers: List[TransferAction] = []  # Transfers to apply to theoretical lineup
    model: str = "ollama"


def get_ssl_context():
    """Get SSL context with proper certificates"""
    return ssl.create_default_context(cafile=certifi.where())


def format_price(price: int) -> str:
    """Convert price from API format (e.g., 115) to display (£11.5m)"""
    return f"£{price / 10:.1f}m"


async def make_fpl_request(endpoint: str, params: dict = None) -> dict:
    """Make a request to the FPL API"""
    ssl_context = get_ssl_context()
    async with httpx.AsyncClient(verify=ssl_context) as client:
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


def enhance_players_with_understat(players: list) -> tuple:
    """Enhance FPL player data with Understat xG/xA and FBRef defensive stats"""
    try:
        enhanced_players, match_stats = enhanced_collector.collect_enhanced_data(
            players,
            season="2025",
            use_cache=True
        )
        return enhanced_players, match_stats
    except Exception as e:
        print(f"Warning: Failed to enhance with Understat/FBRef data: {e}")
        return players, {"matched": 0, "total": len(players), "match_rate": 0}


async def fetch_enhanced_players() -> tuple:
    """Fetch FPL players enhanced with Understat and FBRef data"""
    data = await make_fpl_request("bootstrap-static/")
    if "error" in data:
        return [], {}, data

    players = data.get('elements', [])
    teams = {team['id']: team for team in data.get('teams', [])}

    # Enhance with xG/xA and FBRef stats
    enhanced_players, match_stats = enhance_players_with_understat(players)

    return enhanced_players, teams, data


@app.on_event("startup")
async def startup_event():
    """Initialize models and fetch initial data"""
    print("Starting FPL Optimizer API v2.0 with full MCP integration...")

    # Load prediction model if exists
    model_path = Path(__file__).parent / "models" / "points_model.pkl"
    if model_path.exists():
        predictor.load_model(str(model_path))
        print("Loaded prediction model")

    print("API ready with all MCP tools!")


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": "2.0.0",
        "mcp_tools": "integrated",
        "auth_configured": check_auth_configured()
    }


# ============== AUTHENTICATION ENDPOINTS ==============
@app.post("/api/auth/verify", response_model=TokenResponse)
async def verify_code(request: AccessCodeRequest):
    """
    Verify access code and return JWT token.

    The access code is found on the portfolio owner's resume.
    Once verified, the returned token can be used to access protected features.
    """
    if not verify_access_code(request.code):
        raise HTTPException(
            status_code=401,
            detail="Invalid access code. Check the resume for the correct code!"
        )

    # Create JWT token with verified claim
    token = create_access_token({"sub": "portfolio_visitor", "verified": True})

    return TokenResponse(access_token=token)


@app.get("/api/auth/status")
async def auth_status():
    """Check if authentication is configured"""
    return {
        "auth_required": check_auth_configured(),
        "message": "Access code required for AI chat feature" if check_auth_configured() else "Auth not configured"
    }


# ============== MCP TOOL: get_all_players ==============
@app.get("/api/players")
async def get_all_players(
    position: Optional[str] = None,
    team: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    sort_by: Optional[str] = "points",
    limit: int = 50
):
    """
    Get all players with xG/xA and FBRef stats
    Equivalent to MCP tool: get_all_players
    """
    try:
        players, teams, data = await fetch_enhanced_players()
        if "error" in data:
            raise HTTPException(status_code=500, detail=data["error"])

        # Filter by position
        if position and position.upper() != "ALL":
            pos_id = POSITIONS_REV.get(position.upper())
            if pos_id:
                players = [p for p in players if p.get('element_type') == pos_id]

        # Filter by team
        if team:
            team_lower = team.lower()
            matching_teams = [
                t['id'] for t in teams.values()
                if team_lower in t.get('name', '').lower() or team_lower in t.get('short_name', '').lower()
            ]
            players = [p for p in players if p.get('team') in matching_teams]

        # Filter by price
        if min_price:
            players = [p for p in players if p.get('now_cost', 0) / 10 >= min_price]
        if max_price:
            players = [p for p in players if p.get('now_cost', 0) / 10 <= max_price]

        # Sort
        sort_key = {
            "points": lambda p: p.get('total_points', 0),
            "form": lambda p: float(p.get('form', 0) or 0),
            "value": lambda p: p.get('total_points', 0) / max(p.get('now_cost', 1), 1),
            "price": lambda p: p.get('now_cost', 0),
            "xG": lambda p: p.get('xG', 0),
            "xA": lambda p: p.get('xA', 0),
        }.get(sort_by, lambda p: p.get('total_points', 0))

        players = sorted(players, key=sort_key, reverse=True)[:limit]

        # Format output
        formatted = []
        for p in players:
            team_info = teams.get(p.get('team', 0), {})
            formatted.append({
                'id': p.get('id'),
                'name': f"{p.get('first_name', '')} {p.get('second_name', '')}".strip(),
                'web_name': p.get('web_name', ''),
                'team': team_info.get('short_name', ''),
                'team_name': team_info.get('name', ''),
                'position': POSITIONS.get(p.get('element_type', 0), ''),
                'price': p.get('now_cost', 0) / 10,
                'total_points': p.get('total_points', 0),
                'form': p.get('form', '0'),
                'points_per_game': p.get('points_per_game', '0'),
                'goals': p.get('goals_scored', 0),
                'assists': p.get('assists', 0),
                'clean_sheets': p.get('clean_sheets', 0),
                'bonus': p.get('bonus', 0),
                'minutes': p.get('minutes', 0),
                'ownership': p.get('selected_by_percent', '0'),
                # Understat xG/xA
                'xG': round(p.get('xG', 0), 2),
                'xA': round(p.get('xA', 0), 2),
                'npxG': round(p.get('npxG', 0), 2),
                'xG_per_90': round(p.get('xG_per_90', 0), 2),
                'xA_per_90': round(p.get('xA_per_90', 0), 2),
                'xGChain': round(p.get('xGChain', 0), 2),
                'xGBuildup': round(p.get('xGBuildup', 0), 2),
                'xG_overperformance': round(p.get('xG_overperformance', 0), 2),
                # FBRef defensive stats
                'tackles': p.get('tackles', 0),
                'tackles_won': p.get('tackles_won', 0),
                'interceptions': p.get('interceptions', 0),
                'blocks': p.get('blocks', 0),
                'clearances': p.get('clearances', 0),
                'def_contributions_per_90': round(p.get('def_contributions_per_90', 0), 2),
                'sca_per_90': round(p.get('sca_per_90', 0), 2),
                'gca_per_90': round(p.get('gca_per_90', 0), 2),
                # FPL DC points
                'fpl_dc_points': p.get('fpl_dc_points', 0),
                'status': p.get('status', 'a'),
                'news': p.get('news', '')
            })

        return {"players": formatted, "count": len(formatted)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== MCP TOOL: get_player_details ==============
@app.get("/api/player/{player_name}")
async def get_player_details(player_name: str):
    """
    Get detailed stats for a specific player including xG/xA and FBRef data
    Equivalent to MCP tool: get_player_details
    """
    try:
        players, teams, data = await fetch_enhanced_players()
        if "error" in data:
            raise HTTPException(status_code=500, detail=data["error"])

        # Find player
        search_lower = player_name.lower()
        search_words = search_lower.split()

        matching = []
        for p in players:
            player_text = f"{p.get('first_name', '')} {p.get('second_name', '')} {p.get('web_name', '')}".lower()

            if all(word in player_text for word in search_words):
                matching.append(p)
            elif any(word == p.get('web_name', '').lower() for word in search_words):
                matching.append(p)

        if not matching:
            raise HTTPException(status_code=404, detail=f"Player '{player_name}' not found")

        player = matching[0]
        team = teams.get(player.get('team', 0), {})

        # Get detailed history
        details = await make_fpl_request(f"element-summary/{player['id']}/")

        # Build response
        result = {
            'id': player.get('id'),
            'name': f"{player.get('first_name', '')} {player.get('second_name', '')}".strip(),
            'web_name': player.get('web_name', ''),
            'team': team.get('short_name', ''),
            'team_name': team.get('name', ''),
            'team_code': team.get('code', 0),  # For jersey images
            'element_type': player.get('element_type', 0),  # Position type (1=GK, 2=DEF, etc)
            'position': POSITIONS.get(player.get('element_type', 0), ''),
            'price': player.get('now_cost', 0) / 10,
            'now_cost': player.get('now_cost', 0),  # Raw price in tenths
            'ownership': player.get('selected_by_percent', '0'),

            # Season stats
            'season_stats': {
                'total_points': player.get('total_points', 0),
                'form': player.get('form', '0'),
                'points_per_game': player.get('points_per_game', '0'),
                'goals': player.get('goals_scored', 0),
                'assists': player.get('assists', 0),
                'clean_sheets': player.get('clean_sheets', 0),
                'bonus': player.get('bonus', 0),
                'minutes': player.get('minutes', 0),
            },

            # Understat xG/xA stats
            'advanced_stats': {
                'xG': round(player.get('xG', 0), 2),
                'xA': round(player.get('xA', 0), 2),
                'npxG': round(player.get('npxG', 0), 2),
                'xG_per_90': round(player.get('xG_per_90', 0), 2),
                'xA_per_90': round(player.get('xA_per_90', 0), 2),
                'npxG_per_90': round(player.get('npxG_per_90', 0), 2),
                'xGChain': round(player.get('xGChain', 0), 2),
                'xGBuildup': round(player.get('xGBuildup', 0), 2),
                'xGChain_per_90': round(player.get('xGChain_per_90', 0), 2),
                'xGBuildup_per_90': round(player.get('xGBuildup_per_90', 0), 2),
                'shots': player.get('shots', 0),
                'key_passes': player.get('key_passes', 0),
                'xG_overperformance': round(player.get('xG_overperformance', 0), 2),
                'npxG_overperformance': round(player.get('npxG_overperformance', 0), 2),
            },

            # FBRef defensive stats
            'defensive_stats': {
                'tackles': player.get('tackles', 0),
                'tackles_won': player.get('tackles_won', 0),
                'tackle_pct': round((player.get('tackles_won', 0) / max(player.get('tackles', 1), 1)) * 100, 1),
                'interceptions': player.get('interceptions', 0),
                'blocks': player.get('blocks', 0),
                'clearances': player.get('clearances', 0),
                'def_contributions_per_90': round(player.get('def_contributions_per_90', 0), 2),
                'fbref_recoveries': player.get('fbref_recoveries', 0),
                'fbref_recoveries_per_90': round(player.get('fbref_recoveries_per_90', 0), 2),
                'predicted_dc_per_90': round(player.get('predicted_dc_per_90', 0), 2),
                # FPL actual DC
                'fpl_dc_points': player.get('fpl_dc_points', 0),
                'fpl_cbi': player.get('fpl_cbi', 0),
                'fpl_tackles': player.get('fpl_tackles', 0),
                'fpl_recoveries': player.get('fpl_recoveries', 0),
            },

            # Progressive/Creative stats
            'progressive_stats': {
                'sca': player.get('sca', 0),
                'sca_per_90': round(player.get('sca_per_90', 0), 2),
                'gca': player.get('gca', 0),
                'gca_per_90': round(player.get('gca_per_90', 0), 2),
                'progressive_passes': player.get('progressive_passes', 0),
                'progressive_passes_per_90': round(player.get('progressive_passes_per_90', 0), 2),
                'progressive_carries': player.get('progressive_carries', 0),
                'progressive_carries_per_90': round(player.get('progressive_carries_per_90', 0), 2),
            },

            # Recent gameweeks
            'recent_gameweeks': [],

            # Upcoming fixtures
            'upcoming_fixtures': [],

            # Status
            'status': player.get('status', 'a'),
            'news': player.get('news', ''),
            'chance_of_playing': player.get('chance_of_playing_next_round'),
        }

        # Add recent gameweeks
        if details and 'history' in details:
            for gw in details['history'][-5:][::-1]:
                result['recent_gameweeks'].append({
                    'gameweek': gw.get('round', 0),
                    'points': gw.get('total_points', 0),
                    'minutes': gw.get('minutes', 0),
                    'goals': gw.get('goals_scored', 0),
                    'assists': gw.get('assists', 0),
                    'clean_sheet': gw.get('clean_sheets', 0),
                    'bonus': gw.get('bonus', 0),
                    'was_home': gw.get('was_home', False),
                })

        # Add upcoming fixtures
        if details and 'fixtures' in details:
            for fix in details['fixtures'][:5]:
                result['upcoming_fixtures'].append({
                    'gameweek': fix.get('event', 0),
                    'is_home': fix.get('is_home', False),
                    'difficulty': fix.get('difficulty', 3),
                })

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== MCP TOOL: get_fixtures ==============
@app.get("/api/fixtures")
async def get_fixtures(team: Optional[str] = None, gameweeks: int = 5):
    """
    Get upcoming fixtures with FDR
    Equivalent to MCP tool: get_fixtures
    """
    try:
        data = await make_fpl_request("bootstrap-static/")
        fixtures_data = await make_fpl_request("fixtures/")

        if "error" in data or "error" in fixtures_data:
            raise HTTPException(status_code=500, detail="Failed to fetch fixtures")

        teams = {t['id']: t for t in data.get('teams', [])}
        current_gw = next(
            (e['id'] for e in data['events'] if e.get('is_current')),
            1
        )

        # Filter fixtures
        upcoming = [
            f for f in fixtures_data
            if f.get('event') and current_gw <= f['event'] < current_gw + gameweeks
        ]

        # Filter by team if specified
        if team:
            team_lower = team.lower()
            team_ids = [
                t['id'] for t in teams.values()
                if team_lower in t.get('name', '').lower() or team_lower in t.get('short_name', '').lower()
            ]
            upcoming = [f for f in upcoming if f['team_h'] in team_ids or f['team_a'] in team_ids]

        # Format fixtures
        formatted = []
        for f in upcoming:
            home_team = teams.get(f['team_h'], {})
            away_team = teams.get(f['team_a'], {})
            formatted.append({
                'gameweek': f.get('event'),
                'home_team': home_team.get('short_name', ''),
                'away_team': away_team.get('short_name', ''),
                'home_difficulty': f.get('team_h_difficulty', 3),
                'away_difficulty': f.get('team_a_difficulty', 3),
            })

        return {"fixtures": formatted, "current_gameweek": current_gw}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== MCP TOOL: get_top_performers ==============
@app.get("/api/top-performers")
async def get_top_performers(
    metric: str = "total_points",
    position: str = "all",
    limit: int = 10
):
    """
    Get top performers by various metrics including xG/xA
    Equivalent to MCP tool: get_top_performers
    """
    try:
        players, teams, data = await fetch_enhanced_players()
        if "error" in data:
            raise HTTPException(status_code=500, detail=data["error"])

        # Filter by position
        if position.upper() != "ALL":
            pos_id = POSITIONS_REV.get(position.upper())
            if pos_id:
                players = [p for p in players if p.get('element_type') == pos_id]

        # Sort by metric
        metric_keys = {
            "total_points": lambda p: p.get('total_points', 0),
            "form": lambda p: float(p.get('form', 0) or 0),
            "value": lambda p: p.get('total_points', 0) / max(p.get('now_cost', 1), 1),
            "selected_by": lambda p: float(p.get('selected_by_percent', 0) or 0),
            "transfers_in": lambda p: p.get('transfers_in_event', 0),
            "bonus": lambda p: p.get('bonus', 0),
            "xG": lambda p: p.get('xG', 0),
            "xG_per_90": lambda p: p.get('xG_per_90', 0),
            "xA": lambda p: p.get('xA', 0),
            "xA_per_90": lambda p: p.get('xA_per_90', 0),
            "def_contributions_per_90": lambda p: p.get('def_contributions_per_90', 0),
            "sca_per_90": lambda p: p.get('sca_per_90', 0),
            "gca_per_90": lambda p: p.get('gca_per_90', 0),
            "progressive_passes_per_90": lambda p: p.get('progressive_passes_per_90', 0),
        }

        sort_key = metric_keys.get(metric, metric_keys["total_points"])
        top_players = sorted(players, key=sort_key, reverse=True)[:limit]

        # Format output
        formatted = []
        for i, p in enumerate(top_players, 1):
            team_info = teams.get(p.get('team', 0), {})
            formatted.append({
                'rank': i,
                'name': p.get('web_name', ''),
                'team': team_info.get('short_name', ''),
                'position': POSITIONS.get(p.get('element_type', 0), ''),
                'price': p.get('now_cost', 0) / 10,
                'metric_value': round(sort_key(p), 2),
                'total_points': p.get('total_points', 0),
                'form': p.get('form', '0'),
                'xG': round(p.get('xG', 0), 2),
                'xA': round(p.get('xA', 0), 2),
            })

        return {"performers": formatted, "metric": metric, "position": position}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== MCP TOOL: analyze_fixtures ==============
@app.get("/api/analyze-fixtures")
async def analyze_fixtures_endpoint(num_gameweeks: int = 5, team_filter: Optional[str] = None):
    """
    Analyze upcoming fixtures for teams
    Equivalent to MCP tool: analyze_fixtures
    """
    try:
        data = await make_fpl_request("bootstrap-static/")
        fixtures_data = await make_fpl_request("fixtures/")

        if "error" in data or "error" in fixtures_data:
            raise HTTPException(status_code=500, detail="Failed to fetch data")

        teams = {t['id']: t for t in data.get('teams', [])}
        current_gw = next(
            (e['id'] for e in data['events'] if e.get('is_current')),
            1
        )

        # Analyze fixtures
        analysis = fixture_analyzer.analyze_fixtures(
            fixtures_data, teams, current_gw, num_gameweeks
        )

        # Format results
        results = []
        for team_id, team_analysis in analysis.items():
            team_info = teams.get(team_id, {})

            if team_filter:
                team_name = team_info.get('name', '').lower()
                if team_filter.lower() not in team_name:
                    continue

            results.append({
                'team': team_info.get('short_name', ''),
                'team_name': team_info.get('name', ''),
                'fdr_avg': round(team_analysis.get('fdr_avg', 3), 2),
                'difficulty_score': round(team_analysis.get('difficulty_score', 1), 2),
                'num_fixtures': team_analysis.get('num_fixtures', 0),
                'rating': 'Easy' if team_analysis.get('fdr_avg', 3) <= 2.5 else 'Medium' if team_analysis.get('fdr_avg', 3) <= 3.5 else 'Hard'
            })

        # Sort by difficulty score (higher = easier)
        results.sort(key=lambda x: x['difficulty_score'], reverse=True)

        return {
            "analysis": results,
            "current_gameweek": current_gw,
            "num_gameweeks": num_gameweeks
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== MCP TOOL: suggest_chips_strategy ==============
@app.post("/api/chips-strategy")
async def suggest_chips_strategy(available_chips: List[str], num_gameweeks: int = 10):
    """
    Suggest optimal timing for FPL chips
    Equivalent to MCP tool: suggest_chips_strategy
    """
    try:
        data = await make_fpl_request("bootstrap-static/")
        fixtures_data = await make_fpl_request("fixtures/")

        if "error" in data or "error" in fixtures_data:
            raise HTTPException(status_code=500, detail="Failed to fetch data")

        teams = {t['id']: t for t in data.get('teams', [])}
        current_gw = next(
            (e['id'] for e in data['events'] if e.get('is_current')),
            1
        )

        # Get chip recommendations
        recommendations = chips_analyzer.analyze_chip_timing(
            fixtures_data, teams, current_gw, available_chips, num_gameweeks
        )

        return recommendations

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== MCP TOOL: get_my_team (user team) ==============
@app.get("/api/team/{team_id}")
async def get_user_team(team_id: int):
    """
    Get user's FPL team
    Equivalent to MCP tool: get_my_team
    """
    try:
        ssl_context = get_ssl_context()
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            # Fetch team info
            team_url = f"https://fantasy.premierleague.com/api/entry/{team_id}/"
            async with session.get(team_url) as resp:
                if resp.status == 404:
                    raise HTTPException(status_code=404, detail="Team not found")
                if resp.status != 200:
                    raise HTTPException(status_code=resp.status, detail="Failed to fetch team")
                team_info = await resp.json()

            # Get current gameweek
            gw_url = "https://fantasy.premierleague.com/api/bootstrap-static/"
            async with session.get(gw_url) as resp:
                bootstrap = await resp.json()

            current_gw = next(
                (e['id'] for e in bootstrap['events'] if e['is_current']),
                1
            )

            # Fetch team picks
            picks_url = f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{current_gw}/picks/"
            async with session.get(picks_url) as resp:
                if resp.status != 200:
                    picks_data = {"picks": []}
                else:
                    picks_data = await resp.json()

            # Map player IDs to full player data
            all_players = {p['id']: p for p in bootstrap['elements']}
            teams = {t['id']: t['short_name'] for t in bootstrap['teams']}

            players = []
            for pick in picks_data.get('picks', []):
                player_id = pick['element']
                player = all_players.get(player_id, {})

                last_gw_points = player.get('event_points', 0)

                players.append({
                    'id': player_id,
                    'name': f"{player.get('first_name', '')} {player.get('second_name', '')}".strip(),
                    'web_name': player.get('web_name', ''),
                    'team': teams.get(player.get('team', 0), ''),
                    'team_code': player.get('team_code', 0),
                    'position': player.get('element_type', 0),
                    'element_type': player.get('element_type', 0),
                    'now_cost': player.get('now_cost', 0),
                    'price': player.get('now_cost', 0),
                    'total_points': player.get('total_points', 0),
                    'last_gw_points': last_gw_points,
                    'form': player.get('form', '0'),
                    'selected_by_percent': player.get('selected_by_percent', '0'),
                    'is_captain': pick.get('is_captain', False),
                    'is_vice_captain': pick.get('is_vice_captain', False),
                    'multiplier': pick.get('multiplier', 1),
                    'is_bench': pick.get('position', 0) > 11,
                    'bench_order': pick.get('position', 0) - 11 if pick.get('position', 0) > 11 else 0,
                    'status': player.get('status', 'a'),
                    'chance_of_playing': player.get('chance_of_playing_next_round'),
                    'news': player.get('news', '')
                })

            return {
                'team_id': team_id,
                'manager_name': f"{team_info.get('player_first_name', '')} {team_info.get('player_last_name', '')}".strip(),
                'team_name': team_info.get('name', 'Unknown'),
                'total_points': team_info.get('summary_overall_points', 0),
                'overall_rank': team_info.get('summary_overall_rank', 0),
                'team_value': team_info.get('last_deadline_value', 1000),
                'bank': team_info.get('last_deadline_bank', 0),
                'gameweek': current_gw,
                'players': players,
            }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== BOT TEAM ENDPOINT ==============
# Bot's FPL team ID - hardcoded for the autonomous bot
BOT_TEAM_ID = int(os.getenv("BOT_TEAM_ID", "12777515"))

@app.get("/api/bot/team")
async def get_bot_team():
    """
    Get the bot's autonomous FPL team data.
    This is a public endpoint (no auth required) for displaying the bot's team.
    """
    try:
        ssl_context = get_ssl_context()
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            # Fetch team info
            team_url = f"https://fantasy.premierleague.com/api/entry/{BOT_TEAM_ID}/"
            async with session.get(team_url) as resp:
                if resp.status == 404:
                    raise HTTPException(status_code=404, detail="Bot team not found")
                if resp.status != 200:
                    raise HTTPException(status_code=resp.status, detail="Failed to fetch bot team")
                team_info = await resp.json()

            # Get bootstrap data (players, teams, events)
            gw_url = "https://fantasy.premierleague.com/api/bootstrap-static/"
            async with session.get(gw_url) as resp:
                bootstrap = await resp.json()

            current_gw = next(
                (e['id'] for e in bootstrap['events'] if e['is_current']),
                1
            )

            # Fetch team picks for current gameweek
            picks_url = f"https://fantasy.premierleague.com/api/entry/{BOT_TEAM_ID}/event/{current_gw}/picks/"
            async with session.get(picks_url) as resp:
                if resp.status != 200:
                    picks_data = {"picks": [], "entry_history": {}}
                else:
                    picks_data = await resp.json()

            # Fetch transfer history
            transfers_url = f"https://fantasy.premierleague.com/api/entry/{BOT_TEAM_ID}/transfers/"
            async with session.get(transfers_url) as resp:
                if resp.status == 200:
                    transfers_data = await resp.json()
                else:
                    transfers_data = []

            # Fetch chip history from entry history
            history_url = f"https://fantasy.premierleague.com/api/entry/{BOT_TEAM_ID}/history/"
            async with session.get(history_url) as resp:
                if resp.status == 200:
                    history_data = await resp.json()
                else:
                    history_data = {"chips": [], "current": []}

            # Map player IDs to full player data
            all_players = {p['id']: p for p in bootstrap['elements']}
            teams = {t['id']: t['short_name'] for t in bootstrap['teams']}

            # Build players list
            players = []
            for pick in picks_data.get('picks', []):
                player_id = pick['element']
                player = all_players.get(player_id, {})

                players.append({
                    'id': player_id,
                    'name': f"{player.get('first_name', '')} {player.get('second_name', '')}".strip(),
                    'web_name': player.get('web_name', ''),
                    'team': teams.get(player.get('team', 0), ''),
                    'team_code': player.get('team_code', 0),
                    'position': player.get('element_type', 0),
                    'element_type': player.get('element_type', 0),
                    'now_cost': player.get('now_cost', 0),
                    'price': player.get('now_cost', 0),
                    'total_points': player.get('total_points', 0),
                    'last_gw_points': player.get('event_points', 0),
                    'form': player.get('form', '0'),
                    'is_captain': pick.get('is_captain', False),
                    'is_vice_captain': pick.get('is_vice_captain', False),
                    'multiplier': pick.get('multiplier', 1),
                    'is_bench': pick.get('position', 0) > 11,
                    'bench_order': pick.get('position', 0) - 11 if pick.get('position', 0) > 11 else 0,
                    'status': player.get('status', 'a'),
                    'news': player.get('news', '')
                })

            # Process transfers (last 10)
            recent_transfers = []
            for transfer in transfers_data[:10]:
                player_in = all_players.get(transfer.get('element_in'), {})
                player_out = all_players.get(transfer.get('element_out'), {})
                recent_transfers.append({
                    'gameweek': transfer.get('event', 0),
                    'player_in': player_in.get('web_name', 'Unknown'),
                    'player_out': player_out.get('web_name', 'Unknown'),
                    'player_in_cost': transfer.get('element_in_cost', 0),
                    'player_out_cost': transfer.get('element_out_cost', 0)
                })

            # Process chip usage
            chips_used = history_data.get('chips', [])
            chips = {
                'wildcard1': {'used': False, 'gameweek': None},
                'wildcard2': {'used': False, 'gameweek': None},
                'freehit': {'used': False, 'gameweek': None},
                'benchboost': {'used': False, 'gameweek': None},
                'triplecaptain': {'used': False, 'gameweek': None}
            }
            for chip in chips_used:
                chip_name = chip.get('name', '').lower().replace(' ', '')
                if chip_name in chips:
                    chips[chip_name] = {'used': True, 'gameweek': chip.get('event')}
                elif chip_name == 'wildcard':
                    # First or second wildcard based on gameweek
                    if chip.get('event', 0) <= 19:
                        chips['wildcard1'] = {'used': True, 'gameweek': chip.get('event')}
                    else:
                        chips['wildcard2'] = {'used': True, 'gameweek': chip.get('event')}

            # Calculate stats
            entry_history = picks_data.get('entry_history', {})
            gw_history = history_data.get('current', [])

            total_points = team_info.get('summary_overall_points') or 0
            gw_points = entry_history.get('points', 0)
            overall_rank = team_info.get('summary_overall_rank')
            team_value = team_info.get('last_deadline_value', 1000)
            bank = team_info.get('last_deadline_bank', 0)

            # Calculate average points per gameweek
            gameweeks_played = len(gw_history)
            avg_points = round(total_points / gameweeks_played, 1) if gameweeks_played > 0 else 0

            # Transfers this gameweek
            transfers_this_gw = entry_history.get('event_transfers', 0)

            return {
                'gameweek': current_gw,
                'team': {
                    'team_id': BOT_TEAM_ID,
                    'team_name': team_info.get('name', 'Claude\'s XI'),
                    'manager_name': f"{team_info.get('player_first_name', '')} {team_info.get('player_last_name', '')}".strip(),
                    'total_points': total_points,
                    'gw_points': gw_points,
                    'overall_rank': overall_rank,
                    'team_value': team_value,
                    'bank': bank,
                    'avg_points_per_gw': avg_points,
                    'transfers_this_week': transfers_this_gw,
                    'gameweeks_played': gameweeks_played,
                    'players': players,
                    'transfers': recent_transfers,
                    'chips': chips
                }
            }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/bot/decision")
async def get_bot_decision(early: bool = False):
    """
    Get bot's autonomous decision for the current gameweek.

    Parameters:
    - early: If True, runs early decision mode (for price change monitoring)
             If False, runs final decision mode (before deadline)

    Returns:
    - Transfer recommendations with reasons
    - Chip strategy evaluation
    - Captain/Vice-captain selection
    - Price change risks for current squad
    - Top rising/falling players in the game
    """
    from bot_decision_maker import run_bot_decision

    try:
        result = await run_bot_decision(BOT_TEAM_ID, is_early_run=early)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/bot/price-changes")
async def get_price_changes():
    """
    Get players most likely to have price changes.

    First tries LiveFPL.net (most accurate - 99% rise, 98% fall accuracy).
    Falls back to FPL API transfer data if LiveFPL unavailable.

    Returns:
    - rising: Top 20 players most likely to rise in price
    - falling: Top 20 players most likely to fall in price
    - source: 'livefpl.net' or 'fpl_api'
    - accuracy: Prediction accuracy (if from LiveFPL)
    """
    from bot_decision_maker import BotDecisionMaker

    try:
        bot = BotDecisionMaker(BOT_TEAM_ID)
        await bot.initialize()

        # Try LiveFPL first, fall back to FPL API
        price_changes = await bot.analyze_price_changes_async()
        await bot.close()

        return {
            'rising': price_changes.get('rising', []),
            'falling': price_changes.get('falling', []),
            'source': price_changes.get('source', 'fpl_api'),
            'accuracy': price_changes.get('accuracy', None)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== CHAT ENDPOINT WITH ALL TOOLS ==============
@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, _: bool = Depends(verify_token)):
    """
    Chat with the FPL assistant using Anthropic Claude API.
    PROTECTED: Requires valid JWT token from access code verification.
    Has access to ALL MCP tools for comprehensive analysis.
    """
    try:
        message = request.message
        team_id = request.team_id
        user_context = request.context or {}
        history = request.history or []

        # === VERBOSE LOGGING ===
        print(f"\n{'='*60}")
        print(f"📝 CHAT REQUEST (Authenticated)")
        print(f"{'='*60}")
        print(f"Message: {message}")
        print(f"Team ID: {team_id}")
        print(f"User Context: {user_context}")
        print(f"History: {len(history)} previous messages")

        # Fetch team data if available
        team_data = None
        if team_id:
            try:
                team_data = await get_user_team(int(team_id))
                print(f"✅ Team loaded: {team_data.get('team_name', 'Unknown')} with {len(team_data.get('players', []))} players")
                print(f"   Bank: £{team_data.get('bank', 0)/10:.1f}m | Value: £{team_data.get('team_value', 0)/10:.1f}m")
            except Exception as e:
                print(f"❌ Failed to load team: {e}")

        # Get enhanced players with xG/xA and FBRef data
        players, teams, data = await fetch_enhanced_players()

        # Detect if asking about specific player
        player_details = await detect_player_query(message, players, teams)

        # Build comprehensive context with user's chip/transfer info AND team_id
        context = build_comprehensive_context(team_data, players, teams, player_details, user_context, team_id)

        print(f"\n📋 CONTEXT PREVIEW (first 500 chars):")
        print(context[:500])
        print(f"...")

        # Convert history to format for Anthropic
        conversation_history = [{"role": msg.role, "content": msg.content} for msg in history]

        # Use Anthropic Claude API with tool calling
        result = await query_anthropic(
            message=message,
            context=context,
            tools=FPL_TOOLS,
            execute_tool_func=execute_tool,
            players=players,
            teams=teams,
            team_data=team_data,
            history=conversation_history
        )

        # Unpack tuple result (response, tools_used, transfers)
        if isinstance(result, tuple):
            if len(result) == 3:
                response, tools_used, transfer_list = result
            else:
                response, tools_used = result
                transfer_list = []
        else:
            response, tools_used, transfer_list = result, [], []

        if not response:
            # Fallback to rule-based only if Anthropic fails
            print("⚠️ Anthropic returned no response, using fallback")
            if player_details:
                response = player_details
            else:
                response = await fallback_response(message.lower(), team_data, players, teams)

        # Convert transfer_list to TransferAction objects
        transfers = [
            TransferAction(
                player_out=t.get("player_out", ""),
                player_in=t.get("player_in", ""),
                reason=t.get("reason", "")
            )
            for t in transfer_list
        ]

        print(f"\n📤 RESPONSE (first 300 chars): {response[:300]}...")
        print(f"🔧 TOOLS USED: {tools_used}")
        print(f"🔄 TRANSFERS: {[f'{t.player_out} -> {t.player_in}' for t in transfers]}")
        print(f"{'='*60}\n")

        return ChatResponse(
            response=response,
            tools_used=tools_used,
            transfers=transfers,
            model="anthropic/claude-3.5-haiku"
        )

    except HTTPException:
        # Re-raise auth errors as-is
        raise
    except Exception as e:
        print(f"❌ CHAT ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def detect_player_query(message: str, players: List[Dict], teams: Dict) -> Optional[str]:
    """Detect if asking about a specific player and return their full stats"""
    message_lower = message.lower()

    # Check for player names in message
    for player in players:
        web_name = player.get('web_name', '').lower()
        last_name = player.get('second_name', '').lower()

        if len(web_name) > 3 and web_name in message_lower:
            return format_player_for_chat(player, teams)
        if len(last_name) > 3 and last_name in message_lower:
            return format_player_for_chat(player, teams)

    return None


def format_player_for_chat(player: Dict, teams: Dict) -> str:
    """Format full player details for chat context"""
    team = teams.get(player.get('team', 0), {})
    pos = POSITIONS.get(player.get('element_type', 0), 'UNK')

    lines = [
        f"**{player.get('first_name', '')} {player.get('second_name', '')}** ({team.get('short_name', '')})",
        f"Position: {pos} | Price: £{player.get('now_cost', 0)/10:.1f}m | Ownership: {player.get('selected_by_percent', 0)}%",
        "",
        "**Season Stats:**",
        f"Total Points: {player.get('total_points', 0)} | Form: {player.get('form', 0)} | PPG: {player.get('points_per_game', 0)}",
        f"Goals: {player.get('goals_scored', 0)} | Assists: {player.get('assists', 0)} | CS: {player.get('clean_sheets', 0)} | Bonus: {player.get('bonus', 0)}",
        "",
        "**Advanced Stats (Understat):**",
        f"xG: {player.get('xG', 0):.2f} ({player.get('xG_per_90', 0):.2f}/90)",
        f"xA: {player.get('xA', 0):.2f} ({player.get('xA_per_90', 0):.2f}/90)",
        f"npxG: {player.get('npxG', 0):.2f}",
        f"xG Chain: {player.get('xGChain', 0):.2f} | xG Buildup: {player.get('xGBuildup', 0):.2f}",
        f"Shots: {player.get('shots', 0)} | Key Passes: {player.get('key_passes', 0)}",
    ]

    # Add xG over/underperformance
    xg_overperf = player.get('xG_overperformance', 0)
    if xg_overperf > 0.5:
        lines.append(f"**Overperforming xG by {xg_overperf:.2f}** (scoring more than expected)")
    elif xg_overperf < -0.5:
        lines.append(f"**Underperforming xG by {abs(xg_overperf):.2f}** (due for more goals)")

    # Add defensive stats for DEF/MID
    if player.get('tackles', 0) > 0 or player.get('def_contributions_per_90', 0) > 0:
        lines.extend([
            "",
            "**Defensive Stats (FBRef):**",
            f"Tackles: {player.get('tackles', 0)} (Won: {player.get('tackles_won', 0)})",
            f"Interceptions: {player.get('interceptions', 0)} | Blocks: {player.get('blocks', 0)}",
            f"Clearances: {player.get('clearances', 0)} | Recoveries: {player.get('fbref_recoveries', 0)}",
            f"Predicted DC per 90: {player.get('predicted_dc_per_90', 0):.1f}",
        ])

        # FPL actual DC
        if player.get('fpl_dc_points', 0) > 0:
            lines.append(f"FPL DC Points (Actual): {player.get('fpl_dc_points', 0)}")

    # Creative stats
    if player.get('sca_per_90', 0) > 0:
        lines.extend([
            "",
            "**Creative Stats (FBRef):**",
            f"SCA per 90: {player.get('sca_per_90', 0):.2f} | GCA per 90: {player.get('gca_per_90', 0):.2f}",
            f"Progressive Passes per 90: {player.get('progressive_passes_per_90', 0):.2f}",
        ])

    # Status
    status = player.get('status', 'a')
    if status != 'a':
        status_text = {'i': 'INJURED', 'd': 'DOUBTFUL', 's': 'SUSPENDED'}.get(status, status)
        lines.append(f"\n**Status:** {status_text} - {player.get('news', '')}")

    return "\n".join(lines)


def build_comprehensive_context(team_data: Optional[Dict], players: List[Dict], teams: Dict, player_details: Optional[str], user_context: Optional[Dict] = None, team_id: str = None) -> str:
    """Build comprehensive context with all available data"""
    parts = []

    # Add team_id prominently so LLM knows to use team-specific tools
    if team_id:
        parts.append(f"**USER'S TEAM ID: {team_id}** (Use this for team-specific tools like suggest_captain, optimize_lineup)")
        parts.append("")

    # Add user's FPL resources (transfers and chips)
    if user_context:
        free_transfers = user_context.get('free_transfers', 1)
        available_chips = user_context.get('available_chips', [])
        active_chip = user_context.get('active_chip')
        transfers_made = user_context.get('transfers_made', [])

        parts.append("**User's FPL Resources:**")
        parts.append(f"Free Transfers Remaining: {free_transfers}")

        # Show transfers already made in theoretical lineup
        if transfers_made:
            parts.append(f"\n**TRANSFERS ALREADY MADE THIS SESSION ({len(transfers_made)}):**")
            for t in transfers_made:
                parts.append(f"  ❌ OUT: {t.get('out', 'Unknown')} → ✅ IN: {t.get('in', 'Unknown')}")
            parts.append("(These players are already in your theoretical squad - suggest OTHER transfers)")
            parts.append("")

        if available_chips:
            parts.append(f"Available Chips: {', '.join(available_chips)}")
        else:
            parts.append("Available Chips: None")

        if active_chip:
            chip_names = {
                'benchboost': 'Bench Boost',
                'triplecaptain': 'Triple Captain',
                'wildcard': 'Wildcard',
                'freehit': 'Free Hit'
            }
            parts.append(f"**ACTIVE CHIP THIS GW:** {chip_names.get(active_chip, active_chip)}")
            if active_chip in ['wildcard', 'freehit']:
                parts.append("(Unlimited transfers - no points cost)")
        parts.append("")

    # Add specific player if requested
    if player_details:
        parts.append(f"**PLAYER DETAILS REQUESTED:**\n{player_details}")
        parts.append("")

    # Add user's team
    if team_data:
        parts.append(f"**User's Team:** {team_data.get('team_name', 'Unknown')}")
        parts.append(f"Manager: {team_data.get('manager_name', 'Unknown')}")
        parts.append(f"Points: {team_data.get('total_points', 0)} | Rank: {team_data.get('overall_rank', 0):,}")
        parts.append(f"Bank: £{team_data.get('bank', 0)/10:.1f}m | Value: £{team_data.get('team_value', 1000)/10:.1f}m")
        parts.append("")

        parts.append("**Starting XI:**")
        starters = [p for p in team_data.get('players', []) if not p.get('is_bench')]
        for p in starters:
            cap = " (C)" if p.get('is_captain') else " (VC)" if p.get('is_vice_captain') else ""
            status = f" [{p.get('status').upper()}]" if p.get('status', 'a') != 'a' else ""
            parts.append(f"  {p.get('web_name')} ({p.get('team')}) - £{p.get('price', 0)/10:.1f}m | Form: {p.get('form')}{cap}{status}")

        parts.append("\n**Bench:**")
        bench = [p for p in team_data.get('players', []) if p.get('is_bench')]
        for p in bench:
            parts.append(f"  {p.get('web_name')} ({p.get('team')}) - £{p.get('price', 0)/10:.1f}m")
    else:
        parts.append("**No team loaded** - Enter FPL Team ID for personalized advice")

    # Add top form players with xG/xA
    parts.append("\n**Top Form Players (with xG/xA):**")
    for pos, pos_name in [(4, 'FWD'), (3, 'MID'), (2, 'DEF')]:
        pos_players = sorted(
            [p for p in players if p.get('element_type') == pos],
            key=lambda x: float(x.get('form', 0) or 0),
            reverse=True
        )[:3]

        for p in pos_players:
            team_name = teams.get(p.get('team', 0), {}).get('short_name', '?')
            parts.append(f"  {p.get('web_name')} ({team_name}) {pos_name} £{p.get('now_cost', 0)/10:.1f}m | Form: {p.get('form')} | xG: {p.get('xG', 0):.1f} | xA: {p.get('xA', 0):.1f}")

    return "\n".join(parts)


# ============== TOOL EXECUTION FUNCTIONS ==============
async def execute_tool(tool_name: str, args: Dict, players: List[Dict], teams: Dict, team_data: Optional[Dict]) -> str:
    """Execute a tool and return the result as a string - All 13 MCP tools supported"""
    print(f"Executing tool: {tool_name} with args: {args}")

    try:
        # === get_all_players - Filter/sort all players ===
        if tool_name == "get_all_players":
            position = args.get("position", "all")
            team_filter = args.get("team")
            max_price_val = args.get("max_price")
            min_price_val = args.get("min_price")
            sort_by = args.get("sort_by", "points")
            limit_val = args.get("limit", 20)
            limit = min(int(limit_val) if limit_val else 20, 50)
            return tool_get_all_players(players, teams, position, team_filter, min_price_val, max_price_val, sort_by, limit)

        # === get_player_details - Detailed stats for one player ===
        elif tool_name == "get_player_details":
            player_name = args.get("player_name", "")
            return await tool_get_player_details(player_name, players, teams)

        # === get_fixtures - Upcoming fixtures ===
        elif tool_name == "get_fixtures":
            team_filter = args.get("team")
            num_gws_val = args.get("num_gameweeks", 5)
            num_gws = min(int(num_gws_val) if num_gws_val else 5, 10)
            return await tool_get_fixtures(team_filter, num_gws)

        # === get_my_team - User's FPL team ===
        elif tool_name == "get_my_team":
            team_id_val = args.get("team_id")
            if not team_id_val:
                return "Error: team_id is required. Please provide your FPL team ID from fantasy.premierleague.com/entry/YOUR_ID/"
            team_id = int(team_id_val)
            gameweek_val = args.get("gameweek")
            gameweek = int(gameweek_val) if gameweek_val else None
            return await tool_get_my_team(team_id, gameweek, players, teams)

        # === get_top_players - Top performers by metric ===
        elif tool_name == "get_top_players":
            metric = args.get("metric", "total_points")
            position = args.get("position", "all")
            limit_val = args.get("limit", 10)
            limit = min(int(limit_val) if limit_val else 10, 20)
            return tool_get_top_players(players, teams, metric, position, limit)

        # === evaluate_transfer - Evaluate a specific transfer ===
        elif tool_name == "evaluate_transfer":
            player_out = args.get("player_out", "")
            player_in = args.get("player_in", "")
            free_transfers_val = args.get("free_transfers", 1)
            free_transfers = int(free_transfers_val) if free_transfers_val else 1
            return await tool_evaluate_transfer(player_out, player_in, free_transfers, players, teams)

        # === optimize_squad - Build optimal 15-player squad ===
        elif tool_name == "optimize_squad":
            budget_val = args.get("budget", 100.0)
            budget = float(budget_val) if budget_val else 100.0
            optimize_for = args.get("optimize_for", "fixtures")
            num_gws_val = args.get("num_gameweeks", 5)
            num_gws = int(num_gws_val) if num_gws_val else 5
            return await tool_optimize_squad(players, teams, budget, optimize_for, num_gws)

        # === analyze_team_fixtures - Fixture difficulty analysis ===
        elif tool_name == "analyze_team_fixtures":
            num_gws_val = args.get("num_gameweeks", 5)
            num_gws = min(int(num_gws_val) if num_gws_val else 5, 10)
            return await tool_analyze_fixtures(num_gws)

        # === optimize_lineup - Best starting 11 ===
        elif tool_name == "optimize_lineup":
            team_id_val = args.get("team_id")
            if not team_id_val:
                return "Error: team_id is required."
            team_id = int(team_id_val)
            gameweek_val = args.get("gameweek")
            gameweek = int(gameweek_val) if gameweek_val else None
            return await tool_optimize_lineup(team_id, gameweek, players, teams)

        # === suggest_captain - Captain recommendations ===
        elif tool_name == "suggest_captain":
            team_id_val = args.get("team_id")
            if not team_id_val:
                return "Error: team_id is required."
            team_id = int(team_id_val)
            gameweek_val = args.get("gameweek")
            gameweek = int(gameweek_val) if gameweek_val else None
            return await tool_suggest_captain(team_id, gameweek, players, teams)

        # === suggest_transfers - Transfer recommendations ===
        elif tool_name == "suggest_transfers":
            position = args.get("position", "any")
            max_price_val = args.get("max_price")
            min_price_val = args.get("min_price")
            max_price = float(max_price_val) if max_price_val else None
            min_price = float(min_price_val) if min_price_val else None
            return tool_suggest_transfers(players, teams, team_data, position, min_price, max_price)

        # === compare_players - Side-by-side comparison ===
        elif tool_name == "compare_players":
            player_names = args.get("player_names", [])
            return await tool_compare_players(player_names, players, teams)

        # === get_chip_strategy - Chip usage recommendations ===
        elif tool_name == "get_chip_strategy":
            available_chips = args.get("available_chips", [])
            return await tool_chip_strategy(available_chips)

        elif tool_name == "make_transfer":
            player_out = args.get("player_out", "")
            player_in = args.get("player_in", "")
            reason = args.get("reason", "")
            return await tool_make_transfer(player_out, player_in, reason, players, teams, team_data)

        else:
            return f"Unknown tool: {tool_name}"

    except Exception as e:
        print(f"Tool execution error: {e}")
        import traceback
        traceback.print_exc()
        return f"Error executing {tool_name}: {str(e)}"


async def tool_get_player_details(player_name: str, players: List[Dict], teams: Dict) -> str:
    """Get detailed player stats"""
    search = player_name.lower()

    for player in players:
        web_name = player.get('web_name', '').lower()
        full_name = f"{player.get('first_name', '')} {player.get('second_name', '')}".lower()

        if search in web_name or search in full_name or web_name in search:
            return format_player_for_chat(player, teams)

    return f"Player '{player_name}' not found. Try a different spelling or use their FPL web name."


def tool_get_top_players(players: List[Dict], teams: Dict, metric: str, position: str, limit: int) -> str:
    """Get top players by metric"""
    filtered = players

    # Filter by position
    if position.upper() != "ALL":
        pos_id = POSITIONS_REV.get(position.upper())
        if pos_id:
            filtered = [p for p in filtered if p.get('element_type') == pos_id]

    # Sort by metric
    metric_funcs = {
        "total_points": lambda p: p.get('total_points', 0),
        "form": lambda p: float(p.get('form', 0) or 0),
        "xG": lambda p: p.get('xG', 0),
        "xG_per_90": lambda p: p.get('xG_per_90', 0),
        "xA": lambda p: p.get('xA', 0),
        "xA_per_90": lambda p: p.get('xA_per_90', 0),
        "value": lambda p: p.get('total_points', 0) / max(p.get('now_cost', 1), 1),
        "def_contributions_per_90": lambda p: p.get('def_contributions_per_90', 0),
    }

    sort_func = metric_funcs.get(metric, metric_funcs["total_points"])
    top = sorted(filtered, key=sort_func, reverse=True)[:limit]

    lines = [f"**Top {limit} Players by {metric}**" + (f" ({position})" if position.upper() != "ALL" else "") + ":"]
    for i, p in enumerate(top, 1):
        team_name = teams.get(p.get('team', 0), {}).get('short_name', '?')
        pos = POSITIONS.get(p.get('element_type', 0), '?')
        value = sort_func(p)
        lines.append(f"{i}. **{p.get('web_name')}** ({team_name}, {pos}) - £{p.get('now_cost', 0)/10:.1f}m | {metric}: {value:.2f}")

    return "\n".join(lines)


async def tool_get_fixtures(team_filter: Optional[str], num_gws: int) -> str:
    """Get upcoming fixtures"""
    data = await make_fpl_request("bootstrap-static/")
    fixtures_data = await make_fpl_request("fixtures/")

    if "error" in data or "error" in fixtures_data:
        return "Failed to fetch fixtures data"

    teams_dict = {t['id']: t for t in data.get('teams', [])}
    current_gw = next((e['id'] for e in data['events'] if e.get('is_current')), 1)

    upcoming = [f for f in fixtures_data if f.get('event') and current_gw <= f['event'] < current_gw + num_gws]

    if team_filter:
        team_lower = team_filter.lower()
        team_ids = [t['id'] for t in teams_dict.values() if team_lower in t.get('name', '').lower() or team_lower in t.get('short_name', '').lower()]
        upcoming = [f for f in upcoming if f['team_h'] in team_ids or f['team_a'] in team_ids]

    lines = [f"**Upcoming Fixtures (GW{current_gw} - GW{current_gw + num_gws - 1})**" + (f" for {team_filter}" if team_filter else "") + ":"]

    by_gw = {}
    for f in upcoming:
        gw = f.get('event')
        if gw not in by_gw:
            by_gw[gw] = []
        home = teams_dict.get(f['team_h'], {}).get('short_name', '?')
        away = teams_dict.get(f['team_a'], {}).get('short_name', '?')
        by_gw[gw].append(f"{home} vs {away} (H:{f.get('team_h_difficulty', 3)}/A:{f.get('team_a_difficulty', 3)})")

    for gw in sorted(by_gw.keys()):
        lines.append(f"\n**GW{gw}:**")
        for match in by_gw[gw][:5]:  # Limit per GW
            lines.append(f"  {match}")

    return "\n".join(lines)


async def tool_analyze_fixtures(num_gws: int) -> str:
    """Analyze fixture difficulty for all teams"""
    data = await make_fpl_request("bootstrap-static/")
    fixtures_data = await make_fpl_request("fixtures/")

    if "error" in data or "error" in fixtures_data:
        return "Failed to fetch fixture data"

    teams_dict = {t['id']: t for t in data.get('teams', [])}
    current_gw = next((e['id'] for e in data['events'] if e.get('is_current')), 1)

    # Calculate average FDR for each team
    team_fdr = {}
    for team_id in teams_dict:
        fixtures = [f for f in fixtures_data if (f['team_h'] == team_id or f['team_a'] == team_id)
                   and f.get('event') and current_gw <= f['event'] < current_gw + num_gws]

        if fixtures:
            total_fdr = sum(f['team_a_difficulty'] if f['team_h'] == team_id else f['team_h_difficulty'] for f in fixtures)
            team_fdr[team_id] = total_fdr / len(fixtures)

    # Sort by easiest fixtures
    sorted_teams = sorted(team_fdr.items(), key=lambda x: x[1])

    lines = [f"**Fixture Difficulty Ranking (Next {num_gws} GWs)**:", "*(Lower = Easier)*"]
    for i, (team_id, avg_fdr) in enumerate(sorted_teams[:10], 1):
        team = teams_dict.get(team_id, {})
        rating = "Easy" if avg_fdr <= 2.5 else "Medium" if avg_fdr <= 3.5 else "Hard"
        lines.append(f"{i}. **{team.get('short_name', '?')}** - Avg FDR: {avg_fdr:.2f} ({rating})")

    return "\n".join(lines)


def tool_suggest_transfers(players: List[Dict], teams: Dict, team_data: Optional[Dict], position: str, min_price: Optional[float], max_price: Optional[float]) -> str:
    """Suggest transfers - identifies WHO to transfer OUT and WHO to bring IN with clear recommendations"""

    # Create players lookup by ID
    players_by_id = {p.get('id'): p for p in players}

    # Score function for player quality
    def player_score(p):
        form = float(p.get('form', 0) or 0)
        xg_90 = p.get('xG_per_90', 0) or 0
        xa_90 = p.get('xA_per_90', 0) or 0
        status_penalty = 0 if p.get('status', 'a') == 'a' else -10
        return form * 0.5 + (xg_90 + xa_90) * 3 + status_penalty

    lines = []

    # If user has a team loaded, analyze who to transfer OUT
    if team_data and team_data.get('players'):
        squad = team_data.get('players', [])
        bank = team_data.get('bank', 0) / 10  # Convert to millions

        lines.append(f"## Transfer Analysis for {team_data.get('team_name', 'Your Team')}")
        lines.append(f"**Bank:** £{bank:.1f}m | **Free Transfers:** Check your available transfers")
        lines.append("")

        # Find the weakest STARTING players (not bench)
        starters = [p for p in squad if not p.get('is_bench', False)]
        bench = [p for p in squad if p.get('is_bench', False)]

        squad_with_scores = []
        for p in starters:
            full_player = players_by_id.get(p.get('id'), p)
            score = player_score(full_player)
            squad_with_scores.append({
                **p,
                'score': score,
                'full_data': full_player,
                'is_starter': True
            })

        # Sort by score (lowest = weakest = should transfer out)
        weakest = sorted(squad_with_scores, key=lambda x: x['score'])

        # Find the single best transfer
        best_transfer = None
        best_gain = -999

        for p in weakest[:5]:  # Check top 5 weakest
            full = p.get('full_data', p)
            sell_price = p.get('price', full.get('now_cost', 0)) / 10
            budget = sell_price + bank
            pos_id = full.get('element_type')

            # Find best replacement
            replacements = [
                pl for pl in players
                if pl.get('element_type') == pos_id
                and pl.get('now_cost', 0) / 10 <= budget
                and pl.get('id') not in [sp.get('id') for sp in squad]
                and pl.get('status', 'a') == 'a'
            ]

            if replacements:
                best_rep = max(replacements, key=player_score)
                gain = player_score(best_rep) - p['score']
                if gain > best_gain:
                    best_gain = gain
                    best_transfer = {
                        'out': p,
                        'in': best_rep,
                        'gain': gain,
                        'budget': budget
                    }

        # Show the recommended transfer
        if best_transfer:
            out_p = best_transfer['out']
            in_p = best_transfer['in']
            out_full = out_p.get('full_data', out_p)
            out_team = out_p.get('team', teams.get(out_full.get('team', 0), {}).get('short_name', '?'))
            in_team = teams.get(in_p.get('team', 0), {}).get('short_name', '?')
            out_price = out_p.get('price', out_full.get('now_cost', 0)) / 10
            in_price = in_p.get('now_cost', 0) / 10

            lines.append("## 🎯 RECOMMENDED TRANSFER")
            lines.append(f"**OUT:** {out_p.get('web_name', '?')} ({out_team}) - £{out_price:.1f}m")
            lines.append(f"  Form: {out_full.get('form', '?')} | xG: {out_full.get('xG', 0):.2f} | xA: {out_full.get('xA', 0):.2f}")
            lines.append("")
            lines.append(f"**IN:** {in_p.get('web_name')} ({in_team}) - £{in_price:.1f}m")
            lines.append(f"  Form: {in_p.get('form')} | xG: {in_p.get('xG', 0):.2f} | xA: {in_p.get('xA', 0):.2f} | Pts: {in_p.get('total_points', 0)}")
            lines.append("")
            lines.append(f"**Why:** {out_p.get('web_name', '?')}'s form ({out_full.get('form', '?')}) is significantly lower than {in_p.get('web_name')}'s ({in_p.get('form')}). This transfer improves your expected points.")
            lines.append("")

        # Show other options
        lines.append("## Other Players to Consider Transferring OUT:")
        for i, p in enumerate(weakest[:3], 1):
            full = p.get('full_data', p)
            form = full.get('form', '?')
            status = full.get('status', 'a')
            status_icon = "" if status == 'a' else f" ⚠️ [{status.upper()}]"
            price = p.get('price', full.get('now_cost', 0)) / 10
            out_team = p.get('team', teams.get(full.get('team', 0), {}).get('short_name', '?'))

            lines.append(f"{i}. **{p.get('web_name', '?')}** ({out_team}) - £{price:.1f}m | Form: {form}{status_icon}")

            # Show top 2 replacements
            sell_price = price
            budget = sell_price + bank
            pos_id = full.get('element_type')

            replacements = [
                pl for pl in players
                if pl.get('element_type') == pos_id
                and pl.get('now_cost', 0) / 10 <= budget
                and pl.get('id') not in [sp.get('id') for sp in squad]
                and pl.get('status', 'a') == 'a'
            ]
            top_reps = sorted(replacements, key=player_score, reverse=True)[:2]

            if top_reps:
                for rep in top_reps:
                    rep_team = teams.get(rep.get('team', 0), {}).get('short_name', '?')
                    lines.append(f"   → {rep.get('web_name')} ({rep_team}) £{rep.get('now_cost', 0)/10:.1f}m | Form: {rep.get('form')} | xG: {rep.get('xG', 0):.1f}")

        lines.append("")

    else:
        lines.append("⚠️ No team loaded - showing general transfer targets")
        lines.append("")

    # Show general top targets if no team or as additional info
    filtered = [p for p in players if p.get('status', 'a') == 'a']

    if position.upper() not in ["ANY", "ALL"]:
        pos_id = POSITIONS_REV.get(position.upper())
        if pos_id:
            filtered = [p for p in filtered if p.get('element_type') == pos_id]

    if min_price:
        filtered = [p for p in filtered if p.get('now_cost', 0) / 10 >= float(min_price)]
    if max_price:
        filtered = [p for p in filtered if p.get('now_cost', 0) / 10 <= float(max_price)]

    if team_data:
        team_player_ids = {p.get('id') for p in team_data.get('players', [])}
        filtered = [p for p in filtered if p.get('id') not in team_player_ids]

    top = sorted(filtered, key=player_score, reverse=True)[:5]

    lines.append("## Top Transfer Targets" + (f" ({position})" if position.upper() not in ["ANY", "ALL"] else "") + ":")
    for i, p in enumerate(top, 1):
        team_name = teams.get(p.get('team', 0), {}).get('short_name', '?')
        pos = POSITIONS.get(p.get('element_type', 0), '?')
        lines.append(f"{i}. **{p.get('web_name')}** ({team_name}, {pos}) - £{p.get('now_cost', 0)/10:.1f}m | Form: {p.get('form')} | xG: {p.get('xG', 0):.1f}")

    return "\n".join(lines)


async def tool_compare_players(player_names: List[str], players: List[Dict], teams: Dict) -> str:
    """Compare multiple players"""
    found = []

    for name in player_names[:4]:  # Max 4 players
        search = name.lower()
        for p in players:
            web_name = p.get('web_name', '').lower()
            if search in web_name or web_name in search:
                found.append(p)
                break

    if len(found) < 2:
        return f"Could not find enough players to compare. Found: {[p.get('web_name') for p in found]}"

    lines = ["**Player Comparison:**", ""]

    # Header
    headers = ["Stat"] + [p.get('web_name', '?') for p in found]
    lines.append(" | ".join(headers))
    lines.append("-" * 60)

    # Stats
    stats = [
        ("Price", lambda p: f"£{p.get('now_cost', 0)/10:.1f}m"),
        ("Points", lambda p: str(p.get('total_points', 0))),
        ("Form", lambda p: str(p.get('form', '0'))),
        ("xG", lambda p: f"{p.get('xG', 0):.2f}"),
        ("xA", lambda p: f"{p.get('xA', 0):.2f}"),
        ("xG/90", lambda p: f"{p.get('xG_per_90', 0):.2f}"),
        ("Ownership", lambda p: f"{p.get('selected_by_percent', 0)}%"),
    ]

    for stat_name, stat_func in stats:
        row = [stat_name] + [stat_func(p) for p in found]
        lines.append(" | ".join(row))

    return "\n".join(lines)


async def tool_chip_strategy(available_chips: List[str]) -> str:
    """Get chip usage recommendations"""
    data = await make_fpl_request("bootstrap-static/")
    fixtures_data = await make_fpl_request("fixtures/")

    if "error" in data:
        return "Failed to fetch data for chip analysis"

    current_gw = next((e['id'] for e in data['events'] if e.get('is_current')), 1)

    # Find double gameweeks or blank gameweeks
    lines = [f"**Chip Strategy (Available: {', '.join(available_chips)})**:", ""]

    # Generic advice based on chips
    if 'benchboost' in available_chips:
        lines.append("**Bench Boost:** Best used in Double Gameweeks when all 15 players have 2 fixtures. Also good when you have a strong bench.")

    if 'triplecaptain' in available_chips:
        lines.append("**Triple Captain:** Save for a premium player (Haaland/Salah) in a Double Gameweek with favorable fixtures.")

    if 'wildcard' in available_chips:
        lines.append("**Wildcard:** Use before a favorable fixture swing or to prepare for Double/Blank Gameweeks.")

    if 'freehit' in available_chips:
        lines.append("**Free Hit:** Perfect for Blank Gameweeks when many teams don't play, or DGWs to maximize.")

    lines.append(f"\n*Current GW: {current_gw}*")

    return "\n".join(lines)


async def tool_make_transfer(player_out: str, player_in: str, reason: str, players: List[Dict], teams: Dict, team_data: Optional[Dict]) -> str:
    """
    Execute a transfer in the theoretical lineup.
    Returns confirmation message and transfer details for the frontend to apply.
    """
    # Find player_out in user's team
    out_player = None
    if team_data and team_data.get('players'):
        for p in team_data['players']:
            web_name = p.get('web_name', '').lower()
            name = p.get('name', '').lower()
            if player_out.lower() in web_name or player_out.lower() in name or web_name in player_out.lower():
                out_player = p
                break

    if not out_player:
        return f"Could not find '{player_out}' in your current team. Please check the spelling or use the player's FPL name."

    # Find player_in from all players
    in_player = None
    search = player_in.lower()
    for p in players:
        web_name = p.get('web_name', '').lower()
        full_name = f"{p.get('first_name', '')} {p.get('second_name', '')}".lower()
        if search in web_name or search in full_name or web_name in search:
            in_player = p
            break

    if not in_player:
        return f"Could not find '{player_in}' in the FPL database. Please check the spelling."

    # Get team names
    out_team = out_player.get('team', '')
    in_team = teams.get(in_player.get('team', 0), {}).get('short_name', '?')

    # Calculate prices
    out_price = out_player.get('price', out_player.get('now_cost', 0))
    in_price = in_player.get('now_cost', 0)
    price_diff = (in_price - out_price) / 10

    # Build response
    lines = [
        f"**Transfer Executed:**",
        f"OUT: {out_player.get('web_name')} ({out_team}) - £{out_price/10:.1f}m",
        f"IN: {in_player.get('web_name')} ({in_team}) - £{in_price/10:.1f}m",
        f"Price difference: {'+'if price_diff > 0 else ''}£{price_diff:.1f}m"
    ]

    if reason:
        lines.append(f"Reason: {reason}")

    # Add stats comparison
    lines.append(f"\n**Quick Stats:**")
    lines.append(f"• {in_player.get('web_name')}: Form {in_player.get('form', 0)}, Points {in_player.get('total_points', 0)}, xG {in_player.get('xG', 0):.1f}")

    lines.append(f"\n*The theoretical lineup on the left has been updated to show this transfer.*")

    return "\n".join(lines)


# ============== NEW TOOL FUNCTIONS (6 added) ==============

def tool_get_all_players(players: List[Dict], teams: Dict, position: str, team_filter: Optional[str],
                         min_price: Optional[float], max_price: Optional[float], sort_by: str, limit: int) -> str:
    """Get all players with filters and sorting"""
    filtered = players

    # Filter by position
    if position.upper() != "ALL":
        pos_id = POSITIONS_REV.get(position.upper())
        if pos_id:
            filtered = [p for p in filtered if p.get('element_type') == pos_id]

    # Filter by team
    if team_filter:
        team_lower = team_filter.lower()
        team_ids = [t_id for t_id, t in teams.items() if team_lower in t.get('name', '').lower() or team_lower in t.get('short_name', '').lower()]
        filtered = [p for p in filtered if p.get('team') in team_ids]

    # Filter by price
    if min_price:
        filtered = [p for p in filtered if p.get('now_cost', 0) / 10 >= float(min_price)]
    if max_price:
        filtered = [p for p in filtered if p.get('now_cost', 0) / 10 <= float(max_price)]

    # Sort
    sort_funcs = {
        "points": lambda p: p.get('total_points', 0),
        "form": lambda p: float(p.get('form', 0) or 0),
        "value": lambda p: p.get('total_points', 0) / max(p.get('now_cost', 1), 1),
        "price": lambda p: p.get('now_cost', 0)
    }
    sort_func = sort_funcs.get(sort_by, sort_funcs["points"])
    filtered = sorted(filtered, key=sort_func, reverse=True)[:limit]

    lines = [f"**Players** (pos={position}, sort={sort_by}, limit={limit}):"]
    for i, p in enumerate(filtered, 1):
        team_name = teams.get(p.get('team', 0), {}).get('short_name', '?')
        pos = POSITIONS.get(p.get('element_type', 0), '?')
        value = p.get('total_points', 0) / max(p.get('now_cost', 1) / 10, 0.1)
        xg_info = f" | xG: {p.get('xG', 0):.1f}" if p.get('xG', 0) > 0 else ""
        lines.append(f"{i}. {p.get('web_name')} ({team_name}, {pos}) - £{p.get('now_cost', 0)/10:.1f}m | Pts: {p.get('total_points', 0)} | Form: {p.get('form', 0)}{xg_info}")

    return "\n".join(lines)


async def tool_get_my_team(team_id: int, gameweek: Optional[int], players: List[Dict], teams: Dict) -> str:
    """Get user's FPL team details"""
    try:
        data = await make_fpl_request("bootstrap-static/")
        if "error" in data:
            return f"Error fetching data: {data['error']}"

        players_dict = {p['id']: p for p in data.get('elements', [])}
        events = data.get('events', [])
        current_gw = gameweek or next((e['id'] for e in events if e.get('is_current')), 1)

        team_data = await make_fpl_request(f"entry/{team_id}/")
        if "error" in team_data:
            return f"Team {team_id} not found. Check your FPL team ID."

        picks_data = await make_fpl_request(f"entry/{team_id}/event/{current_gw}/picks/")
        if "error" in picks_data:
            return f"Could not fetch picks for GW{current_gw}"

        manager = f"{team_data.get('player_first_name', '')} {team_data.get('player_last_name', '')}"
        lines = [
            f"**{team_data.get('name', 'Unknown Team')}**",
            f"Manager: {manager}",
            f"Overall Rank: {team_data.get('summary_overall_rank', 'N/A'):,}",
            f"Total Points: {team_data.get('summary_overall_points', 0)}",
            f"GW{current_gw} Points: {picks_data.get('entry_history', {}).get('points', 0)}",
            f"Team Value: £{team_data.get('last_deadline_value', 1000)/10:.1f}m",
            f"Bank: £{team_data.get('last_deadline_bank', 0)/10:.1f}m",
            "",
            "**Squad:**"
        ]

        picks = picks_data.get('picks', [])
        by_pos = {1: [], 2: [], 3: [], 4: []}
        for pick in picks:
            player = players_dict.get(pick['element'])
            if player:
                team = teams.get(player['team'], {})
                cap = " (C)" if pick.get('is_captain') else " (VC)" if pick.get('is_vice_captain') else ""
                by_pos[player['element_type']].append(f"{player['web_name']} ({team.get('short_name', '?')}) £{player['now_cost']/10:.1f}m{cap}")

        for pos_id, pos_name in POSITIONS.items():
            if by_pos[pos_id]:
                lines.append(f"\n**{pos_name}:** {', '.join(by_pos[pos_id])}")

        return "\n".join(lines)
    except Exception as e:
        return f"Error: {str(e)}"


async def tool_evaluate_transfer(player_out: str, player_in: str, free_transfers: int, players: List[Dict], teams: Dict) -> str:
    """Evaluate a specific transfer"""
    # Find players
    out_player = None
    in_player = None
    out_search = player_out.lower()
    in_search = player_in.lower()

    for p in players:
        web = p.get('web_name', '').lower()
        if out_search in web or web in out_search:
            out_player = p
        if in_search in web or web in in_search:
            in_player = p

    if not out_player:
        return f"Could not find player to transfer OUT: {player_out}"
    if not in_player:
        return f"Could not find player to transfer IN: {player_in}"

    out_team = teams.get(out_player['team'], {}).get('short_name', '?')
    in_team = teams.get(in_player['team'], {}).get('short_name', '?')

    # Calculate expected gain
    out_form = float(out_player.get('form', 0) or 0)
    in_form = float(in_player.get('form', 0) or 0)
    out_xg90 = out_player.get('xG_per_90', 0)
    in_xg90 = in_player.get('xG_per_90', 0)

    # Simple points prediction based on form and xG
    out_pred = out_form + out_xg90 * 2
    in_pred = in_form + in_xg90 * 2

    hit_cost = 0 if free_transfers > 0 else 4
    expected_gain = (in_pred - out_pred) - hit_cost

    cost_diff = (in_player['now_cost'] - out_player['now_cost']) / 10

    lines = [
        "**Transfer Evaluation:**",
        f"OUT: {out_player['web_name']} ({out_team}) - £{out_player['now_cost']/10:.1f}m | Form: {out_form} | xG/90: {out_xg90:.2f}",
        f"IN: {in_player['web_name']} ({in_team}) - £{in_player['now_cost']/10:.1f}m | Form: {in_form} | xG/90: {in_xg90:.2f}",
        "",
        f"**Cost:** {'+' if cost_diff > 0 else ''}{cost_diff:.1f}m",
        f"**Hit Cost:** {hit_cost} pts" + (" (using free transfer)" if free_transfers > 0 else " (taking a hit)"),
        f"**Expected Weekly Gain:** {expected_gain:.1f} pts",
        "",
        "**Recommendation:**"
    ]

    if expected_gain > 2:
        lines.append("🟢 **DO IT!** Significant expected gain")
    elif expected_gain > 0:
        lines.append("🟡 **CONSIDER IT** - Small positive gain")
    else:
        lines.append("🔴 **WAIT** - Negative expected return")

    return "\n".join(lines)


async def tool_optimize_squad(players: List[Dict], teams: Dict, budget: float, optimize_for: str, num_gws: int) -> str:
    """Build optimal squad - simplified version"""
    # Get current GW and fixtures
    data = await make_fpl_request("bootstrap-static/")
    current_gw = next((e['id'] for e in data.get('events', []) if e.get('is_current')), 1)

    # Score function based on optimization type
    def player_score(p):
        if optimize_for == "form":
            return float(p.get('form', 0) or 0)
        elif optimize_for == "value":
            return p.get('total_points', 0) / max(p.get('now_cost', 1) / 10, 0.1)
        elif optimize_for == "points":
            return p.get('total_points', 0)
        else:  # fixtures - use form as proxy
            return float(p.get('form', 0) or 0) + p.get('xG_per_90', 0) * 2

    # Simple greedy selection
    selected = {1: [], 2: [], 3: [], 4: []}  # GK, DEF, MID, FWD
    required = {1: 2, 2: 5, 3: 5, 4: 3}
    team_counts = {}
    total_cost = 0.0

    for pos_id in [4, 3, 2, 1]:  # FWD, MID, DEF, GK
        pos_players = sorted(
            [p for p in players if p.get('element_type') == pos_id],
            key=player_score,
            reverse=True
        )
        for p in pos_players:
            if len(selected[pos_id]) >= required[pos_id]:
                break
            cost = p.get('now_cost', 0) / 10
            team_id = p.get('team')
            if total_cost + cost > budget:
                continue
            if team_counts.get(team_id, 0) >= 3:
                continue
            selected[pos_id].append(p)
            total_cost += cost
            team_counts[team_id] = team_counts.get(team_id, 0) + 1

    # Format output
    lines = [
        f"**Optimal Squad (£{budget}m, {optimize_for} strategy)**",
        f"GW{current_gw} - GW{current_gw + num_gws - 1}",
        f"Total Cost: £{total_cost:.1f}m | Remaining: £{budget - total_cost:.1f}m",
        ""
    ]

    for pos_id, pos_name in [(4, 'FWD'), (3, 'MID'), (2, 'DEF'), (1, 'GK')]:
        lines.append(f"**{pos_name}:**")
        for p in selected[pos_id]:
            team = teams.get(p['team'], {}).get('short_name', '?')
            lines.append(f"  {p['web_name']} ({team}) - £{p['now_cost']/10:.1f}m | Form: {p.get('form', 0)}")

    return "\n".join(lines)


async def tool_optimize_lineup(team_id: int, gameweek: Optional[int], players: List[Dict], teams: Dict) -> str:
    """Select best starting 11 from user's squad"""
    try:
        data = await make_fpl_request("bootstrap-static/")
        players_dict = {p['id']: p for p in data.get('elements', [])}
        current_gw = gameweek or next((e['id'] for e in data.get('events', []) if e.get('is_current')), 1)

        picks_data = await make_fpl_request(f"entry/{team_id}/event/{current_gw}/picks/")
        if "error" in picks_data:
            return f"Could not fetch team {team_id} for GW{current_gw}"

        # Get squad players with scores
        squad = []
        for pick in picks_data.get('picks', []):
            player = players_dict.get(pick['element'])
            if player:
                form = float(player.get('form', 0) or 0)
                xg = player.get('xG_per_90', 0)
                score = form + xg * 2
                squad.append({**player, 'score': score})

        # Select best starting 11 maintaining formation rules
        by_pos = {1: [], 2: [], 3: [], 4: []}
        for p in squad:
            by_pos[p['element_type']].append(p)

        for pos_id in by_pos:
            by_pos[pos_id].sort(key=lambda x: x['score'], reverse=True)

        # Pick: 1 GK, 3-5 DEF, 2-5 MID, 1-3 FWD (total 11)
        starting = []
        starting.append(by_pos[1][0])  # Best GK
        starting.extend(by_pos[2][:3])  # Top 3 DEF
        starting.extend(by_pos[3][:4])  # Top 4 MID
        starting.extend(by_pos[4][:3])  # Top 3 FWD

        # Captain = highest scorer
        captain = max(starting, key=lambda x: x['score'])

        lines = [
            f"**Optimized Lineup GW{current_gw}**",
            f"Formation: 3-4-3",
            f"Captain: {captain['web_name']}",
            "",
            "**Starting XI:**"
        ]

        for p in starting:
            team = teams.get(p['team'], {}).get('short_name', '?')
            pos = POSITIONS.get(p['element_type'], '?')
            cap = " (C)" if p['id'] == captain['id'] else ""
            lines.append(f"  {pos} | {p['web_name']} ({team}) - Form: {p.get('form', 0)}{cap}")

        return "\n".join(lines)
    except Exception as e:
        return f"Error: {str(e)}"


async def tool_suggest_captain(team_id: int, gameweek: Optional[int], players: List[Dict], teams: Dict) -> str:
    """Suggest captain for user's team - uses enhanced player data with xG/xA from FBRef"""
    try:
        data = await make_fpl_request("bootstrap-static/")
        current_gw = gameweek or next((e['id'] for e in data.get('events', []) if e.get('is_current')), 1)

        # Create lookup from enhanced players (with xG/xA from FBRef)
        enhanced_dict = {p['id']: p for p in players}

        picks_data = await make_fpl_request(f"entry/{team_id}/event/{current_gw}/picks/")
        if "error" in picks_data:
            return f"Could not fetch team {team_id}"

        # Score each player for captaincy using ENHANCED data
        candidates = []
        for pick in picks_data.get('picks', []):
            player_id = pick['element']
            # Use enhanced player data (has xG/xA from FBRef)
            player = enhanced_dict.get(player_id)
            if player:
                form = float(player.get('form', 0) or 0)
                # Get xG/xA from enhanced data (FBRef fields)
                xg90 = float(player.get('npxG_per_90', 0) or player.get('xG_per_90', 0) or 0)
                xa90 = float(player.get('xA_per_90', 0) or 0)
                total_points = int(player.get('total_points', 0) or 0)
                # Premium bonus for expensive players
                premium_bonus = 1.5 if player.get('now_cost', 0) >= 100 else 0
                # Calculate captain score with xG/xA weighted heavily
                score = form * 1.5 + xg90 * 4 + xa90 * 3 + (total_points / 20) + premium_bonus
                candidates.append({
                    **player,
                    'captain_score': score,
                    'xg90': xg90,
                    'xa90': xa90
                })

        candidates.sort(key=lambda x: x['captain_score'], reverse=True)
        top3 = candidates[:3]

        lines = [f"**Captain Recommendations GW{current_gw}**", ""]
        for i, p in enumerate(top3, 1):
            team_name = teams.get(p['team'], {}).get('short_name', '?')
            form = p.get('form', 0)
            xg = p.get('xg90', 0)
            xa = p.get('xa90', 0)
            pts = p.get('total_points', 0)
            emoji = "👑" if i == 1 else "🥈" if i == 2 else "🥉"
            lines.append(f"{emoji} **{p['web_name']}** ({team_name})")
            lines.append(f"   Form: {form} | xG/90: {xg:.2f} | xA/90: {xa:.2f} | Total Pts: {pts}")
            lines.append(f"   Captain Score: {p['captain_score']:.1f}")
            lines.append("")

        return "\n".join(lines)
    except Exception as e:
        return f"Error: {str(e)}"


async def query_ollama(message: str, context: str, players: List[Dict] = None, teams: Dict = None, team_data: Optional[Dict] = None) -> tuple:
    """Query Ollama LLM with tool calling support. Returns (response, tools_used)"""
    tools_used = []  # Track which tools were called

    system_prompt = """You are an expert Fantasy Premier League (FPL) assistant. You have access to 13 tools that can fetch real-time FPL data.

CRITICAL INSTRUCTIONS:
1. ALWAYS use tools to get data - never make up stats
2. ALWAYS include the SPECIFIC details from tool outputs in your response
3. For transfer suggestions, you MUST state:
   - WHO to transfer OUT (player name, team, price, form)
   - WHO to transfer IN (player name, team, price, form)
   - WHY (comparing stats like form, xG, xA, fixtures)
4. Include actual numbers and stats from the tool output
5. Do NOT give generic responses - be SPECIFIC with data

Available tools:
- suggest_transfers: Get specific transfer recommendations (OUT → IN with reasoning)
- get_player_details: Detailed stats for a specific player
- get_fixtures: Upcoming fixtures with difficulty ratings
- get_my_team: User's FPL team details
- get_top_players: Top players by metric (form, xG, xA, points)
- evaluate_transfer: Compare specific player_out → player_in
- suggest_captain: Captain recommendations for user's team
- compare_players: Compare multiple players side by side
- get_chip_strategy: Chip usage recommendations
- analyze_team_fixtures: Team fixture difficulty rankings
- optimize_lineup: Best starting 11 from user's squad
- optimize_squad: Build optimal squad from scratch
- get_all_players: Filter/sort all players

RESPONSE FORMAT FOR TRANSFERS:
When suggesting transfers, structure your response like this:
"Based on your team analysis:

**RECOMMENDED TRANSFER:**
- **OUT:** [Player Name] ([Team]) - £X.Xm, Form: X.X
- **IN:** [Player Name] ([Team]) - £X.Xm, Form: X.X

**Why this transfer?**
[Explain using specific stats from the tool: form difference, xG/xA comparison, fixture advantage, etc.]"

Be specific and data-driven. Users want concrete recommendations with numbers, not vague advice."""

    try:
        async with aiohttp.ClientSession() as session:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Context about user's team:\n{context}\n\nUser question: {message}"}
            ]

            # First request - may trigger tool calls
            payload = {
                "model": "llama3.1",
                "messages": messages,
                "tools": FPL_TOOLS,
                "stream": False,
                "options": {"temperature": 0.7, "num_predict": 1500}
            }

            max_iterations = 5  # Increased to allow more tool calls
            iteration = 0
            called_tools = set()  # Track which tools have been called
            last_tool_result = None  # Store last tool result for fallback

            while iteration < max_iterations:
                iteration += 1
                print(f"Ollama request iteration {iteration}")

                async with session.post(
                    "http://localhost:11434/api/chat",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=90)
                ) as resp:
                    if resp.status != 200:
                        print(f"Ollama returned status {resp.status}")
                        return None

                    data = await resp.json()
                    response_message = data.get('message', {})

                    # Check if there are tool calls
                    tool_calls = response_message.get('tool_calls', [])

                    if not tool_calls:
                        # No more tool calls, return the content
                        content = response_message.get('content', '')
                        print(f"Ollama final response: {len(content)} chars")
                        print(f"🔧 Tools used: {tools_used}")
                        return (content, tools_used)

                    # Execute tool calls
                    messages.append(response_message)

                    for tool_call in tool_calls:
                        func = tool_call.get('function', {})
                        tool_name = func.get('name', '')
                        tool_args = func.get('arguments', {})

                        # Skip if we've already called this exact tool
                        tool_key = f"{tool_name}:{json.dumps(tool_args, sort_keys=True)}"
                        if tool_key in called_tools:
                            print(f"⚠️ Skipping duplicate tool call: {tool_name}")
                            # Add a message telling the LLM to respond
                            messages.append({
                                "role": "tool",
                                "content": "You already called this tool. Please provide your response to the user based on the data you received."
                            })
                            continue

                        called_tools.add(tool_key)
                        tools_used.append(tool_name)  # Track for response

                        # Execute the tool
                        result = await execute_tool(tool_name, tool_args, players or [], teams or {}, team_data)
                        last_tool_result = result  # Save for fallback

                        # Log tool output for debugging
                        print(f"\n📊 TOOL OUTPUT ({tool_name}):")
                        print(f"{result[:1000]}..." if len(result) > 1000 else result)
                        print(f"   Total length: {len(result)} chars\n")

                        # Add tool result to messages
                        messages.append({
                            "role": "tool",
                            "content": result
                        })

                    # Update payload for next iteration
                    payload["messages"] = messages

            print("Max iterations reached")
            print(f"🔧 Tools used: {tools_used}")
            # If we have tool results, return the last one instead of error
            if last_tool_result:
                print("Returning last tool result as fallback")
                return (last_tool_result, tools_used)
            return ("I apologize, but I'm having trouble processing this request. Please try again.", tools_used)

    except asyncio.TimeoutError:
        print("Ollama request timed out")
        return (None, tools_used)
    except Exception as e:
        print(f"Ollama error: {e}")
        import traceback
        traceback.print_exc()
        return (None, [])


async def fallback_response(message: str, team_data: Optional[Dict], players: List[Dict], teams: Dict) -> str:
    """Fallback responses when Ollama unavailable"""

    if 'captain' in message:
        if not team_data:
            return "Load your team first to get captain recommendations!"

        starters = [p for p in team_data.get('players', []) if not p.get('is_bench')]
        starters_sorted = sorted(starters, key=lambda p: float(p.get('form', 0) or 0), reverse=True)

        if starters_sorted:
            best = starters_sorted[0]
            return f"**Captain Pick:** {best.get('web_name')} ({best.get('team')})\nForm: {best.get('form')} | Last GW: {best.get('last_gw_points')} pts"
        return "No captain data available"

    elif 'transfer' in message:
        return "For transfer suggestions, I need Ollama running. Try asking about specific players or positions!"

    elif 'top' in message and ('xg' in message or 'form' in message):
        top = sorted(players, key=lambda p: p.get('xG', 0), reverse=True)[:5]
        lines = ["**Top xG Players:**"]
        for p in top:
            team = teams.get(p.get('team', 0), {}).get('short_name', '?')
            lines.append(f"{p.get('web_name')} ({team}) - xG: {p.get('xG', 0):.2f}")
        return "\n".join(lines)

    else:
        return """**FPL Optimizer with xG/xA & FBRef Data**

I can help with:
- **Player stats**: "Tell me about Salah" (includes xG, xA, DC stats)
- **Captain picks**: "Who should I captain?"
- **Top performers**: "Best xG per 90 forwards"
- **Fixtures**: "Analyze fixtures for next 5 GWs"
- **Team analysis**: Enter your Team ID first!

Start Ollama for full conversational AI:
```
ollama pull llama3.2
```"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
