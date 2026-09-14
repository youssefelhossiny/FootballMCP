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
from anthropic_chat import query_anthropic, CHAT_MODEL

# Import existing modules - FULL MCP INTEGRATION
from enhanced_features import EnhancedDataCollector
from predict_points import FPLPointsPredictor
from data_sources.availability_filter import AvailabilityFilter
from data_sources.team_news_scraper import fetch_knocks_and_bans, fetch_ffscout_team_news
from data_sources.data_cache import DataCache
import ml_predict_v2
import fpl_auth
import player_news_search
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
# v1 predictor. Retained only for the FPLOptimizer/LP helpers that live in the
# same module; it serves NO predictions here — points projections now come from
# ml_predict_v2 (see /api/predictions and the get_ml_prediction tool). v1's
# model was trained on a synthetic label and is not loaded at startup.
predictor = FPLPointsPredictor()
availability_filter = AvailabilityFilter()
fixture_analyzer = FixtureAnalyzer()
enhanced_optimizer = EnhancedOptimizer()

# Two different bars, because buying a player and starting one you already own
# are different decisions with different downside.
#
# BUYING is stricter than starting — a squad slot is committed and can't be
# undone without a transfer hit. 50 keeps a genuinely useful band in play:
# FPL's flags are coarse (0/25/50/75/100), and a 50% flag on a strong player is
# often a knock that clears by kickoff, whereas 25% and below usually means a
# real absence. Combined with the model discounting by play probability, a 50%
# player has to be clearly better than the alternatives to actually get picked.
SQUAD_MIN_CHANCE = int(os.getenv("SQUAD_MIN_CHANCE", "50"))

# How long to wait for Understat/FBRef enrichment before serving plain FPL data.
# A cold FBRef scrape can take many minutes; no page should wait that long.
ENHANCE_TIMEOUT_SECONDS = float(os.getenv("ENHANCE_TIMEOUT_SECONDS", "25"))

# STARTING is permissive. Once a player is in the squad the transfer cost is
# already sunk, so the only question is bench-or-start — and any chance of
# playing beats a guaranteed zero, because FPL auto-substitutes if he doesn't
# appear. So a player who'd never be bought at 50% is still worth starting at
# 50% if he's already owned. Anything above zero qualifies.
START_MIN_CHANCE = int(os.getenv("START_MIN_CHANCE", "1"))
chips_analyzer = ChipsStrategyAnalyzer()
# Short TTL: these sources claim near-real-time updates, so a stale multi-hour
# cache (like the 6h default) would defeat the point of using them over FPL's
# own slower-updating bootstrap-static news field.
team_news_cache = DataCache(cache_dir=str(Path(__file__).parent / "cache"), ttl_hours=0.25)

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
            "name": "search_player_news",
            "description": "Search the live web for the latest injury/availability news on specific players, and cross-reference it against FPL's own flag, Knocks and Bans, and Fantasy Football Scout. Use this whenever a player shows a PARTIAL doubt (25/50/75%) or the structured sources disagree — those flags are coarse and hand-updated, so they go stale. Real example: FPL listed a player at 75% while FFScout said 25% and the press had a third answer. Slower than the other tools (it runs real web searches), so use it for a handful of players you're actually deciding on, not for browsing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Players to check, e.g. ['Doku','Bruno G.']. Max 6."
                    }
                },
                "required": ["player_names"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_squad_strategy",
            "description": "Get FPL squad-construction STRATEGY analysis for the upcoming gameweeks: which teams are best placed to keep CLEAN SHEETS (fixture softness combined with FPL's own defensive-strength ratings), budget-defender ROTATION PAIRS whose good fixtures fall in different gameweeks (so one of the pair always has a favourable game), VALUE picks by points-per-million, xG BARGAINS (players scoring below their expected goals on high underlying threat — the chances are there and finishing tends to correct), and REGRESSION RISKS (players scoring well above xG, whose price is inflated by finishing luck that will not repeat). Use this when deciding transfers, planning a wildcard, or judging whether a player is genuinely good value rather than just in form. This is strategic context to reason WITH, not a squad to copy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "num_gameweeks": {
                        "type": "integer",
                        "description": "How many gameweeks ahead to analyse (default 5, max 10). Transfers should be judged over 3-5."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_ml_prediction",
            "description": "Get machine-learning predicted points for the NEXT gameweek, plus the probability each player actually starts (60+ minutes). Trained on real historical per-gameweek outcomes across three seasons. Use this as ONE input among several when advising on transfers, captaincy or lineups — it is a useful ranking signal (its top picks historically averaged ~1.5 more points per pick than a recent-form heuristic) but it deliberately under-predicts big hauls, so treat it as 'who is likely to do well', not 'exactly how many points'. Always weigh it against injury/team news and fixtures rather than following it blindly. Pass player_names to score specific players (this fetches their real gameweek history for a more accurate answer), or omit to get the top-ranked players overall.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific players to predict (e.g. ['Haaland','Saka']). More accurate than the ranked list, as it uses each player's real per-gameweek history."
                    },
                    "position": {
                        "type": "string",
                        "enum": ["all", "GK", "DEF", "MID", "FWD"],
                        "description": "Restrict the ranked list to one position (ignored when player_names is given)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "How many players to return in the ranked list (default 10, max 30)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_team_news",
            "description": "Get fast, near-real-time team news from third-party FPL sources (Knocks and Bans + Fantasy Football Scout) — faster-updating than FPL's own official injury data, which can lag actual announcements by a day or more. Returns predicted starting lineups, rotation-risk/doubt/out/banned players per team, and injury status with expected return dates. Use this instead of (or alongside) get_injury_report when the user wants the most current team news, or asks 'who's likely to start' / 'is X going to play' / 'any team news on Y'. Can filter to one team.",
            "parameters": {
                "type": "object",
                "properties": {
                    "team": {
                        "type": "string",
                        "description": "Filter to one team's news (optional, e.g., 'Arsenal', 'Liverpool')"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_injury_report",
            "description": "Get a report of injured, suspended, and doubtful Premier League players, based on FPL's official status/news/chance-of-playing data. Use this before recommending transfers, captains, or lineups so injury risk is factored in — a doubtful or injured player shouldn't be started or captained even if their underlying stats look good. Can filter to a specific team.",
            "parameters": {
                "type": "object",
                "properties": {
                    "team": {
                        "type": "string",
                        "description": "Filter to one team's players (optional, e.g., 'Arsenal', 'Liverpool')"
                    }
                },
                "required": []
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


def planning_gameweek(events: List[Dict]) -> int:
    """
    The gameweek that forward-looking advice should START from — the next
    unplayed one, not the one already in progress.

    `is_current` is the wrong anchor for planning. Mid-season it points at the
    gameweek whose matches are being played right now, so a 5-gameweek fixture
    window built from it leads with a gameweek nobody can still transfer for:
    the first slot is wasted and the real forward view is only 4 deep. Before a
    season's first deadline `is_current` is absent entirely, and a `, 1` fallback
    silently hides the bug (it happens to equal the target in GW1 only).

    Prefers `is_next`, then the first unfinished event, then `is_current`, and
    only then 1 — so it degrades toward "something sane" rather than "GW1".
    """
    for key in ("is_next",):
        gw = next((e["id"] for e in events if e.get(key)), None)
        if gw is not None:
            return gw
    gw = next((e["id"] for e in events if not e.get("finished")), None)
    if gw is not None:
        return gw
    return next((e["id"] for e in events if e.get("is_current")), 1)


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

    # Enhance with xG/xA and FBRef stats.
    #
    # Run in a worker THREAD, not on the event loop. `enhance_players_with_
    # understat` is fully synchronous and can drive a Selenium scrape that takes
    # minutes when a cache expires; calling it directly froze the whole server —
    # every request (players, chat, analytics) hung until the scrape finished,
    # which looked to the user like three separate features being broken.
    # A thread keeps the API responsive while the scrape proceeds.
    try:
        enhanced_players, match_stats = await asyncio.wait_for(
            asyncio.to_thread(enhance_players_with_understat, players),
            timeout=ENHANCE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        # Degrade to plain FPL data rather than hanging the request. FPL's own
        # fields now include expected_goals/assists, so this is still usable.
        print(f"⚠️  enhanced stats timed out after {ENHANCE_TIMEOUT_SECONDS}s — "
              "serving base FPL data (which includes native xG/xA)")
        enhanced_players = players

    return enhanced_players, teams, data


async def fetch_team_news(use_cache: bool = True) -> Dict:
    """
    Fetch fast third-party injury + predicted-lineup news (Knocks and Bans +
    FFScout team news), cached for team_news_cache's TTL (15 min) since these
    sources update roughly in real time — no point re-scraping on every call.
    """
    cache_key = "team_news"
    if use_cache:
        cached = team_news_cache.get(cache_key, format="json")
        if cached:
            return cached

    ssl_context = get_ssl_context()
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            knocks_and_bans, ffscout = await asyncio.gather(
                fetch_knocks_and_bans(session),
                fetch_ffscout_team_news(session),
            )
        except Exception as e:
            print(f"Warning: Failed to fetch team news: {e}")
            knocks_and_bans, ffscout = [], []

    result = {"knocks_and_bans": knocks_and_bans, "ffscout": ffscout}
    if knocks_and_bans or ffscout:
        team_news_cache.set(cache_key, result, format="json")
    return result


# ============== DATA MATCHING REPORT ==============
@app.get("/api/data/match-report")
async def get_match_report(team: Optional[int] = None):
    """
    Per-source (Understat/FBRef) player match rate + unmatched player list.

    A player unmatched across sources has no advanced xG/xA/defensive stats,
    so this tracks how close matching is to ~100% coverage. Triggers a fresh
    enhanced-data collection pass (same pipeline as /api/players) so the
    report always reflects the current cache/season state.

    Args:
        team: optional FPL team ID to filter the unmatched lists to one team
            (e.g. 7/11/12 for the promoted teams Coventry/Hull/Ipswich)
    """
    try:
        players, teams, data = await fetch_enhanced_players()
        if "error" in data:
            raise HTTPException(status_code=500, detail=data["error"])

        report_path = Path(__file__).parent / "cache" / "unmatched_players.json"
        if not report_path.exists():
            raise HTTPException(
                status_code=404,
                detail="No match report available yet — run a data collection pass first"
            )

        with open(report_path, 'r') as f:
            report = json.load(f)

        def _enrich(p: Dict) -> Dict:
            team_info = teams.get(p.get('team', 0), {})
            return {
                **p,
                'team_name': team_info.get('name', ''),
                'team_short_name': team_info.get('short_name', ''),
            }

        understat_unmatched = [_enrich(p) for p in report.get('understat_unmatched', [])]
        fbref_unmatched = [_enrich(p) for p in report.get('fbref_unmatched', [])]

        if team is not None:
            understat_unmatched = [p for p in understat_unmatched if p.get('team') == team]
            fbref_unmatched = [p for p in fbref_unmatched if p.get('team') == team]

        return {
            "season": report.get('season'),
            "total_fpl_players": report.get('total_fpl_players', 0),
            "understat_match_rate": report.get('understat_match_rate', 0.0),
            "fbref_match_rate": report.get('fbref_match_rate', 0.0),
            "understat_unmatched_count": len(understat_unmatched),
            "fbref_unmatched_count": len(fbref_unmatched),
            "understat_unmatched": understat_unmatched,
            "fbref_unmatched": fbref_unmatched,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== ML PREDICTIONS (v2) ==============
async def fetch_player_histories(player_ids: List[int], max_concurrent: int = 8) -> Dict[int, List[Dict]]:
    """
    Fetch per-GW history for specific players from element-summary.

    The v2 model's features are rolling means over prior gameweeks, so this is
    what enables the accurate serving path. One request per player, so it's
    only worth doing for a shortlist (a squad, a comparison set) — never for
    all ~600 players on a chat request. Concurrency is capped to stay polite
    to the FPL API; failures degrade to no-history (season-total fallback)
    rather than failing the whole request.
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def one(pid: int):
        async with semaphore:
            data = await make_fpl_request(f"element-summary/{pid}/")
            if isinstance(data, dict) and "error" not in data:
                return pid, data.get("history", []) or []
            return pid, []

    results = await asyncio.gather(*(one(p) for p in player_ids), return_exceptions=True)
    out: Dict[int, List[Dict]] = {}
    for item in results:
        if isinstance(item, tuple):
            pid, history = item
            if history:
                out[pid] = history
    return out


async def predict_for_players(players: List[Dict], with_history: bool = False) -> Dict[int, Dict]:
    """Run the v2 model over `players`, optionally pulling real per-GW history first."""
    histories = {}
    if with_history and players:
        histories = await fetch_player_histories([p["id"] for p in players])
    return ml_predict_v2.predict_points(players, histories)


@app.get("/api/predictions")
async def get_predictions(
    limit: int = 20,
    position: Optional[str] = None,
    team: Optional[int] = None,
    with_history: bool = False,
):
    """
    Next-gameweek predicted points from the v2 model.

    Args:
        limit: how many players to return (ranked by prediction, max 100)
        position: GK/DEF/MID/FWD filter
        team: FPL team id filter
        with_history: fetch real per-GW history for the returned shortlist,
            giving the accurate rolling-window prediction instead of the
            season-total fallback. Costs one FPL request per player, so it
            runs AFTER filtering/ranking, not before.
    """
    try:
        info = ml_predict_v2.model_info()
        if not info["available"]:
            raise HTTPException(status_code=503, detail="v2 points model not available on this deploy")

        data = await make_fpl_request("bootstrap-static/")
        if "error" in data:
            raise HTTPException(status_code=500, detail=data["error"])

        players = data.get("elements", [])
        teams = {t["id"]: t for t in data.get("teams", [])}

        if position:
            wanted = POSITIONS_REV.get(position.upper())
            if wanted:
                players = [p for p in players if p.get("element_type") == wanted]
        if team is not None:
            players = [p for p in players if p.get("team") == team]

        preds = ml_predict_v2.predict_points(players)
        ranked = sorted(players, key=lambda p: preds.get(p["id"], {}).get("predicted_points", 0), reverse=True)
        shortlist = ranked[:max(1, min(limit, 100))]

        # Re-predict the shortlist with real history for a better answer.
        if with_history:
            better = await predict_for_players(shortlist, with_history=True)
            preds.update(better)
            shortlist = sorted(shortlist, key=lambda p: preds[p["id"]]["predicted_points"], reverse=True)

        return {
            "model": info,
            "count": len(shortlist),
            "predictions": [
                {
                    "id": p["id"],
                    "web_name": p.get("web_name"),
                    "team": teams.get(p.get("team", 0), {}).get("short_name", ""),
                    "position": POSITIONS.get(p.get("element_type", 0), ""),
                    "price": p.get("now_cost", 0) / 10,
                    **preds.get(p["id"], {}),
                }
                for p in shortlist
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== OPTIMAL SQUADS (wildcard / free hit) ==============
async def build_optimal_squad(strategy: str, budget: float, num_gws: int) -> Dict:
    """
    Build an optimal £100m squad and shape it for WeeklyPicksPage.jsx.

    The response contract is dictated by the existing frontend, which had been
    calling /api/optimal/{wildcard,freehit} against routes that never existed.
    Two easy-to-get-wrong details, both matched deliberately:
      * `player.price` and `total_cost` are read as TENTHS (the JSX divides
        each by 10), even though the optimizer works in millions.
      * `player.position` must be the NUMERIC element_type — getPositionShort()
        maps {1:GK,2:DEF,3:MID,4:FWD} and renders '?' for a string.

    Wildcard optimizes over a multi-gameweek fixture horizon; free hit uses a
    single gameweek, since it's a one-week squad.
    """
    data = await make_fpl_request("bootstrap-static/")
    fixtures_data = await make_fpl_request("fixtures/")
    if "error" in data:
        raise HTTPException(status_code=502, detail=f"FPL API error: {data['error']}")
    if isinstance(fixtures_data, dict) and "error" in fixtures_data:
        raise HTTPException(status_code=502, detail=f"FPL fixtures error: {fixtures_data['error']}")

    all_players = data.get("elements", [])
    teams = {t["id"]: t for t in data.get("teams", [])}
    current_gw = next((e["id"] for e in data.get("events", []) if e.get("is_next")), None) \
        or next((e["id"] for e in data.get("events", []) if e.get("is_current")), 1)

    # Selection bar. `filter_available_players` already drops anyone FPL marks
    # injured / suspended / unavailable / not-in-squad outright.
    #
    # The threshold here is a genuine trade-off. Too low and you spend money on
    # players who may not feature; too high and you exclude an elite player on a
    # temporary doubt — a 50%-chance Haaland is still worth owning, because FPL
    # auto-subs mean starting him costs nothing if he sits out. SQUAD_MIN_CHANCE
    # is the compromise: keep clear doubts out of an opening squad you're
    # committing for the whole gameweek, while not demanding perfect health.
    # Whether such a player then STARTS is a separate decision (see start_rank).
    available = availability_filter.filter_available_players(
        all_players, min_chance=SQUAD_MIN_CHANCE
    )

    # Cross-check against third-party team news, which carries signal FPL's own
    # data does not: a fully fit player who simply isn't in his club's predicted
    # XI (rotation risk). Without this the optimizer happily picked players the
    # bookmakers' own lineups had on the bench. Advisory only — if the scrape
    # fails the squad is still built, just without this filter.
    excluded_by_news: Dict[str, str] = {}
    rotation_risk_ids: set = set()
    try:
        news = await fetch_team_news()

        # Two DISTINCT signals, deliberately not merged:
        #   unavailable   -> out / banned / injured. Never select.
        #   rotation_risk -> fit per FPL but not in his club's predicted XI.
        #                    Selectable, but must never START or be captain.
        # Collapsing these into one set would either bench genuinely-out
        # players (pointless — they can't play at all) or start players the
        # club's own lineup has on the bench.
        unavailable = set()
        rotation_flagged = set()

        for entry in news.get("knocks_and_bans", []):
            status = str(entry.get("status", "")).lower()
            if "out" in status or "doubt" in status:
                unavailable.add(entry["name"].strip().lower())

        for team_news in news.get("ffscout", []):
            for group in ("out", "banned"):
                for raw in team_news.get(group, []):
                    name = raw.split("(")[0].strip().lower()
                    if name:
                        unavailable.add(name)
            # A doubt is not an "out" — keep them selectable but bench-only.
            for raw in team_news.get("doubts", []):
                name = raw.split("(")[0].strip().lower()
                if name:
                    rotation_flagged.add(name)
            # Fully fit but missing from the predicted XI = rotation risk.
            predicted = {
                p.split("(")[0].strip().lower()
                for p in team_news.get("predicted_lineup", [])
            }
            team_news["_predicted_names"] = predicted

        flagged = unavailable

        def news_flagged(player: Dict) -> Optional[str]:
            """
            Match a flagged news name to an FPL player.

            Deliberately EXACT-match only. A substring rule was tried first and
            was badly wrong in both directions — it matched "White" to
            "morgan gibbs-white", "Anthony" to "anthony gordon" and "Silva" to
            "josh dasilva", wrongly excluding 68 fully-fit players. Excluding a
            good player is as damaging as picking an injured one, so ambiguity
            resolves to "keep". FPL's own status flag is the safety net for
            genuine injuries; this filter only adds rotation signal it can be
            confident about.
            """
            web = (player.get("web_name") or "").strip().lower()
            second = (player.get("second_name") or "").strip().lower()
            full = f"{player.get('first_name','')} {player.get('second_name','')}".strip().lower()
            for candidate in (full, second, web):
                if candidate and candidate in flagged:
                    return candidate
            return None

        def matches(player: Dict, names: set) -> Optional[str]:
            """Exact-match only — see news_flagged for why substrings are unsafe."""
            web = (player.get("web_name") or "").strip().lower()
            second = (player.get("second_name") or "").strip().lower()
            full = f"{player.get('first_name','')} {player.get('second_name','')}".strip().lower()
            for candidate in (full, second, web):
                if candidate and candidate in names:
                    return candidate
            return None

        kept = []
        for player in available:
            hit = news_flagged(player)
            if hit:
                excluded_by_news[player.get("web_name", "?")] = hit
                continue
            kept.append(player)
            # Selectable but bench-only: an explicit doubt in the news.
            if matches(player, rotation_flagged):
                rotation_risk_ids.add(player["id"])
        if kept:
            available = kept
    except Exception as e:
        print(f"⚠️  Team-news cross-check unavailable, continuing without it: {e}")

    # The optimizer scores every strategy off `player['form']`
    # (enhanced_optimization._calculate_fixture_scores). Pre-season, FPL resets
    # form to 0.0 for ALL players — verified: 0/599 nonzero — so every score
    # floors to 0.01 and the "optimal" squad is arbitrary and identical for
    # every strategy. Seed `form` with the v2 model's predicted points so the
    # optimizer has real signal to rank on. In-season, when FPL publishes real
    # form again, that is used as-is and this is a no-op.
    predictions = ml_predict_v2.predict_points(available)

    # Two-pass prediction. Pass 1 (above) is cheap and covers everyone. Pass 2
    # re-scores only realistic candidates using their REAL per-gameweek history,
    # which is the model's accurate path — one FPL request per player, so it
    # would be ~486 requests if applied to the whole pool.
    #
    # Without this the squad builder silently used season-total rates forever,
    # while the get_ml_prediction MCP tool used real form — so the two would
    # disagree once the season started. Pre-season this is a no-op (history is
    # empty for everyone), and it starts contributing automatically at GW2.
    if predictions:
        shortlist = sorted(
            available,
            key=lambda p: predictions.get(p["id"], {}).get("predicted_points", 0),
            reverse=True,
        )[:60]
        if any(int(p.get("minutes", 0) or 0) > 0 for p in shortlist):
            try:
                refined = await predict_for_players(shortlist, with_history=True)
                # Only accept refinements that actually used history; otherwise
                # keep pass 1 rather than overwrite good data with a fallback.
                for pid, better in refined.items():
                    if better.get("basis") == "history":
                        predictions[pid] = better
            except Exception as e:
                print(f"⚠️  History-based refinement unavailable, using season rates: {e}")

    if predictions and not any(float(p.get("form") or 0) for p in available):
        available = [
            {**p, "form": predictions.get(p["id"], {}).get("predicted_points", 0.0)}
            for p in available
        ]

    squad, lineup_info, status = enhanced_optimizer.optimize_squad_with_fixtures(
        players=available,
        fixtures=fixtures_data,
        teams=teams,
        current_gw=current_gw,
        budget=budget,
        optimize_for="fixtures" if strategy == "wildcard" else "form",
        target_spend=budget,
        num_gws=num_gws,
    )
    if not squad:
        raise HTTPException(status_code=422, detail=f"Could not build a squad: {status}")

    preds = predictions

    next_fixture = {}
    for fixture in (fixtures_data or []):
        if fixture.get("event") != current_gw:
            continue
        for side, opp_side, diff_key in (("team_h", "team_a", "team_h_difficulty"),
                                         ("team_a", "team_h", "team_a_difficulty")):
            next_fixture.setdefault(fixture[side], {
                "opponent": teams.get(fixture[opp_side], {}).get("short_name", "?"),
                "difficulty": fixture.get(diff_key, 3),
            })

    # Choose the XI explicitly rather than trusting the LP's own split.
    #
    # The LP selects the 15 and splits XI/bench in a single solve, optimising
    # squad value — so it has no notion of "this player is fit enough to own but
    # not to start". Selecting the 15 and picking who plays are different
    # decisions with different bars, so the XI is decided here: rank by
    # (not rotation-risk, predicted points) and fill a legal formation.
    def start_rank(player: Dict) -> tuple:
        """
        Rank by expected value, with one hard gate.

        A player with a genuine ZERO chance of playing sorts last: he is not a
        gamble, he is a certainty of nothing, and starting him wastes a slot an
        auto-sub could have filled. Anything above zero ranks normally — FPL
        auto-substitutes, so a doubtful player in the XI risks nothing (points
        if he plays, auto-sub if not) while benching him forfeits his points
        outright. That's why rotation risk does NOT demote a player here, even
        though it does affect captaincy.

        `predicted_points` already embeds play probability (the model multiplies
        P(plays) by points-if-plays), so it is the right primary key.
        """
        chance = player.get("chance_of_playing_next_round")
        playable = 1 if (chance is None or chance >= START_MIN_CHANCE) else 0
        pred = preds.get(player["id"], {}).get("predicted_points", 0)
        prob = preds.get(player["id"], {}).get("play_probability") or 0
        return (playable, pred, prob)

    by_position: Dict[int, List[Dict]] = {1: [], 2: [], 3: [], 4: []}
    for player in squad:
        by_position.setdefault(player.get("element_type", 3), []).append(player)
    for bucket in by_position.values():
        bucket.sort(key=start_rank, reverse=True)

    # Minimum legal shape, then fill the remaining slots with the best left.
    starters = (by_position[1][:1] + by_position[2][:3]
                + by_position[3][:2] + by_position[4][:1])
    chosen = {p["id"] for p in starters}
    remaining = sorted(
        [p for p in squad if p["id"] not in chosen and p.get("element_type") != 1],
        key=start_rank, reverse=True,
    )
    # Respect FPL's per-position maxima while topping up to 11.
    caps = {2: 5, 3: 5, 4: 3}
    counts = {pos: len([p for p in starters if p.get("element_type") == pos]) for pos in (1, 2, 3, 4)}
    for player in remaining:
        if len(starters) >= 11:
            break
        pos = player.get("element_type")
        if counts.get(pos, 0) < caps.get(pos, 0):
            starters.append(player)
            counts[pos] = counts.get(pos, 0) + 1

    starting_ids = {p["id"] for p in starters}

    # Captain must be a STARTER, and here rotation risk IS worth avoiding —
    # unlike the XI decision above. If the captain doesn't play the armband
    # passes to the vice, so it isn't a wipeout, but you lose the doubling on
    # your best pick. Prefer a nailed starter; fall back to the full XI only if
    # every starter is flagged.
    captain_pool = [p for p in starters if p["id"] not in rotation_risk_ids] or starters
    captain = max(
        captain_pool,
        key=lambda p: preds.get(p["id"], {}).get("predicted_points", 0),
        default=None,
    )

    # Report FPL's real form, never the seeded value above, so the UI's Form
    # column stays truthful even when the optimizer ran on predictions.
    real_form = {p["id"]: p.get("form", "0") for p in all_players}

    def shape(player: Dict) -> Dict:
        fixture = next_fixture.get(player.get("team"), {})
        prediction = preds.get(player["id"], {})
        return {
            "id": player["id"],
            "name": player.get("web_name", ""),
            "team": teams.get(player.get("team", 0), {}).get("short_name", ""),
            "position": player.get("element_type"),          # numeric — see docstring
            "price": player.get("now_cost", 0),              # tenths — see docstring
            "form": real_form.get(player["id"], "0"),
            "predicted_points": prediction.get("predicted_points", 0.0),
            "play_probability": prediction.get("play_probability"),
            "next_opponent": fixture.get("opponent", "TBC"),
            "fixture_difficulty": fixture.get("difficulty", 3),
            "is_captain": bool(captain and player["id"] == captain["id"]),
            "is_starting": player["id"] in starting_ids,
            "ownership": float(player.get("selected_by_percent", 0) or 0),
        }

    players_out = [shape(p) for p in squad]
    difficulties = [p["fixture_difficulty"] for p in players_out if p["fixture_difficulty"]]

    return {
        "strategy": strategy,
        "gameweek": current_gw,
        "formation": lineup_info.get("formation"),
        "status": status,
        # Sum of ML predictions across the starting XI — what the UI labels
        # "Predicted Points". The optimizer's own expected_points uses a
        # different (heuristic) scale, so mixing them would be misleading.
        "predicted_points": round(sum(p["predicted_points"] for p in players_out if p["is_starting"]), 1),
        "total_cost": sum(p["price"] for p in players_out),   # tenths
        "avg_fixture_difficulty": round(sum(difficulties) / len(difficulties), 2) if difficulties else None,
        "players": players_out,
        "differentials": sorted(
            [p for p in players_out if p["ownership"] < 5.0],
            key=lambda p: p["predicted_points"], reverse=True,
        )[:6],
        "model": ml_predict_v2.model_info(),
        # Auditable: who team news removed from consideration, and why.
        "excluded_by_team_news": excluded_by_news,
    }


@app.get("/api/optimal/wildcard")
async def get_optimal_wildcard(budget: float = 100.0, num_gameweeks: int = 5):
    """Best £100m squad for a Wildcard — optimized across a multi-GW fixture horizon."""
    try:
        return await build_optimal_squad("wildcard", budget, max(1, min(num_gameweeks, 10)))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/optimal/freehit")
async def get_optimal_freehit(budget: float = 100.0):
    """Best £100m squad for a Free Hit — single gameweek only."""
    try:
        return await build_optimal_squad("freehit", budget, 1)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== INJURY REPORT ==============
@app.get("/api/injuries")
async def get_injuries(team: Optional[int] = None):
    """
    Injured/suspended/doubtful player report, from FPL's own status/news/
    chance-of-playing fields (no external source — always live).

    Args:
        team: optional FPL team ID to filter to one team
    """
    try:
        data = await make_fpl_request("bootstrap-static/")
        if "error" in data:
            raise HTTPException(status_code=500, detail=data["error"])

        players = data.get('elements', [])
        teams = {t['id']: t for t in data.get('teams', [])}

        if team is not None:
            players = [p for p in players if p.get('team') == team]

        report = availability_filter.get_injury_report(players)

        def _enrich(p: Dict) -> Dict:
            team_info = teams.get(p.get('team', 0), {})
            return {
                **p,
                'team_name': team_info.get('name', ''),
                'team_short_name': team_info.get('short_name', ''),
            }

        return {
            category: [_enrich(p) for p in entries]
            for category, entries in report.items()
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== TEAM NEWS (fast third-party source) ==============
@app.get("/api/team-news")
async def get_team_news_endpoint(team: Optional[str] = None):
    """
    Fast, near-real-time team news from Knocks and Bans (injury/suspension
    status) + Fantasy Football Scout (predicted lineups, rotation risk) —
    both update faster than FPL's own bootstrap-static news field. Cached
    15 min server-side.

    Args:
        team: optional team name substring to filter FFScout's per-team
            lineup/out/doubts/banned lists (Knocks and Bans entries aren't
            team-tagged, so that list is always returned in full)
    """
    try:
        news = await fetch_team_news()
        ffscout = news.get("ffscout", [])
        if team:
            team_lower = team.lower()
            ffscout = [t for t in ffscout if team_lower in t['team'].lower()]

        return {
            "knocks_and_bans": news.get("knocks_and_bans", []),
            "ffscout": ffscout,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# In-process bot scheduler, set at startup. None when disabled (the default) or
# when apscheduler is unavailable — /api/bot/schedule reports which.
_bot_scheduler = None


@app.on_event("startup")
async def startup_event():
    """Initialize models and fetch initial data"""
    print("Starting FPL Optimizer API v2.0 with full MCP integration...")

    # v2 points model (two-stage hurdle, trained on real per-GW outcomes).
    # Two bugs previously lived here: the path pointed at fpl-optimizer/models/
    # while the models actually live at repo-root models/, and load_model() was
    # called with an argument despite taking none — so v1 never loaded at all
    # and the TypeError never even surfaced.
    info = ml_predict_v2.model_info()
    if info["available"]:
        print(f"Loaded points model {info['version']} "
              f"({info['n_features']} features, {info['architecture']})")
    else:
        print(f"⚠️  No v2 points model at {info['path']} — "
              "predictions unavailable (run: python ml_train.py)")

    # Autonomous bot scheduling. Disabled by default: on Render's free tier the
    # service is spun down when idle, and a spun-down process cannot fire a job —
    # so an in-process scheduler there would advertise a bot that is not actually
    # watching the deadline. The supported production path is an external cron
    # hitting POST /api/bot/run, which wakes the service by calling it.
    global _bot_scheduler
    try:
        import bot_scheduler as _bs

        _bot_scheduler = _bs.BotScheduler(run_agent_and_maybe_submit)
        outcome = await _bot_scheduler.start()
        if outcome.get("started"):
            print(f"Bot scheduler started: {outcome.get('runs')}")
        else:
            print(f"Bot scheduler not started — {outcome.get('reason')}")
    except Exception as e:
        # Never let scheduling break API startup; the endpoints still work.
        print(f"⚠️  Bot scheduler unavailable: {e}")

    print("API ready with all MCP tools!")


@app.on_event("shutdown")
async def shutdown_event():
    """Stop the bot scheduler so a reload doesn't leave a job firing twice."""
    if _bot_scheduler is not None:
        _bot_scheduler.shutdown()


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": "2.0.0",
        "mcp_tools": "integrated",
        "auth_configured": check_auth_configured(),
        "points_model": ml_predict_v2.model_info(),
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
@app.get("/api/analytics/{team_id}")
async def get_team_analytics(team_id: int, league_id: Optional[int] = None):
    """
    Season analytics for one manager: gameweek-by-gameweek history, how each
    week compares to the manager's own average and to the global average, and
    where they sit in their mini-leagues.

    Built for the "My Team" analytics view. Everything comes from FPL's own
    endpoints, so there is no scraping and no staleness beyond FPL's own.
    """
    try:
        ssl_context = get_ssl_context()
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            base = "https://fantasy.premierleague.com/api"

            async def fetch(url):
                async with session.get(url) as r:
                    return await r.json() if r.status == 200 else None

            entry, history, bootstrap = await asyncio.gather(
                fetch(f"{base}/entry/{team_id}/"),
                fetch(f"{base}/entry/{team_id}/history/"),
                fetch(f"{base}/bootstrap-static/"),
            )

        if not entry or not history:
            raise HTTPException(status_code=404, detail=f"Team {team_id} not found")

        current = history.get("current", []) or []
        chips_used = history.get("chips", []) or []

        # FPL publishes the global average score per gameweek on the event
        # object, which is the fairest "how did I do this week" benchmark —
        # a 60 is good in a low-scoring week and poor in a high-scoring one.
        events = {e["id"]: e for e in (bootstrap or {}).get("events", [])}

        # Player names for "most captained", so the world-context panel can show
        # who everyone else backed rather than an opaque element id.
        elements = {e["id"]: e.get("web_name") for e in (bootstrap or {}).get("elements", [])}

        gameweeks = []
        for row in current:
            gw = row["event"]
            ev = events.get(gw, {})
            avg = ev.get("average_entry_score") or 0
            highest = ev.get("highest_score") or 0
            pts = row.get("points", 0)
            gameweeks.append({
                "gameweek": gw,
                "points": pts,
                "average": avg,
                "highest": highest,
                "vs_average": pts - avg,
                # Share of the top score — shows how close to a perfect week you got.
                "pct_of_best": round(pts / highest * 100) if highest else None,
                # FPL's own per-gameweek world percentile (1 = best).
                "percentile": row.get("percentile_rank"),
                "most_captained": elements.get(ev.get("most_captained")),
                "chip_plays": {c["chip_name"]: c["num_played"]
                               for c in (ev.get("chip_plays") or [])},
                "managers_ranked": ev.get("ranked_count"),
                "total_points": row.get("total_points", 0),
                "overall_rank": row.get("overall_rank"),
                "gw_rank": row.get("rank"),
                "bench_points": row.get("points_on_bench", 0),
                "transfers": row.get("event_transfers", 0),
                "transfer_cost": row.get("event_transfers_cost", 0),
                "value": round((row.get("value") or 0) / 10, 1),
                "bank": round((row.get("bank") or 0) / 10, 1),
                "chip": next((c["name"] for c in chips_used if c.get("event") == gw), None),
            })

        played = len(gameweeks)
        pts_list = [g["points"] for g in gameweeks]
        best = max(gameweeks, key=lambda g: g["points"]) if gameweeks else None
        worst = min(gameweeks, key=lambda g: g["points"]) if gameweeks else None

        # Rank movement across the season so far. Negative delta = improving,
        # since a LOWER overall rank is better.
        ranks = [g["overall_rank"] for g in gameweeks if g["overall_rank"]]
        rank_change = (ranks[0] - ranks[-1]) if len(ranks) >= 2 else 0

        summary = {
            "team_name": entry.get("name"),
            "manager": f"{entry.get('player_first_name','')} {entry.get('player_last_name','')}".strip(),
            "total_points": entry.get("summary_overall_points") or 0,
            "overall_rank": entry.get("summary_overall_rank"),
            "gameweeks_played": played,
            "average_score": round(sum(pts_list) / played, 1) if played else 0,
            "best_gw": {"gameweek": best["gameweek"], "points": best["points"]} if best else None,
            "worst_gw": {"gameweek": worst["gameweek"], "points": worst["points"]} if worst else None,
            "total_bench_points": sum(g["bench_points"] for g in gameweeks),
            "total_transfer_cost": sum(g["transfer_cost"] for g in gameweeks),
            "beat_average_count": sum(1 for g in gameweeks if g["vs_average"] > 0),
            "rank_change": rank_change,
            "squad_value": round((entry.get("last_deadline_value") or 1000) / 10, 1),
            "bank": round((entry.get("last_deadline_bank") or 0) / 10, 1),
            "chips_used": [{"name": c["name"], "gameweek": c.get("event")} for c in chips_used],
            # Where you sit among everyone playing, not just your mini-leagues.
            "world_percentile": (
                round(entry.get("summary_overall_rank") / total_managers * 100, 1)
                if (total_managers := (bootstrap or {}).get("total_players"))
                and entry.get("summary_overall_rank") else None
            ),
            "total_managers": (bootstrap or {}).get("total_players"),
            "best_percentile_gw": (
                min((g for g in gameweeks if g.get("percentile")),
                    key=lambda g: g["percentile"], default=None)
            ),
        }

        # Prior seasons, so a manager can see whether this year is actually
        # going better or worse than their own history — the comparison most
        # dashboards omit.
        past_seasons = [
            {
                "season": p.get("season_name"),
                "total_points": p.get("total_points"),
                "rank": p.get("rank"),
                "rank_percentage": p.get("rank_percentage"),
            }
            for p in (history.get("past", []) or [])
        ]

        leagues = [
            {
                "id": l["id"],
                "name": l["name"],
                "rank": l.get("entry_rank"),
                "last_rank": l.get("entry_last_rank"),
                # Positive = moved up the table this week.
                "movement": ((l.get("entry_last_rank") or 0) - (l.get("entry_rank") or 0))
                            if l.get("entry_last_rank") and l.get("entry_rank") else 0,
            }
            for l in (entry.get("leagues", {}) or {}).get("classic", [])
        ]

        return {
            "summary": summary,
            "gameweeks": gameweeks,
            "leagues": leagues,
            "past_seasons": past_seasons,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analytics/{team_id}/league/{league_id}")
async def get_league_comparison(team_id: int, league_id: int):
    """
    How this manager compares to the other members of one mini-league.

    Returns the standings plus percentile placement and the gap to the leader,
    which is the context a bare rank number does not give you.
    """
    try:
        ssl_context = get_ssl_context()
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            url = f"https://fantasy.premierleague.com/api/leagues-classic/{league_id}/standings/"
            async with session.get(url) as r:
                if r.status != 200:
                    raise HTTPException(status_code=r.status, detail="League not found")
                data = await r.json()

        results = (data.get("standings", {}) or {}).get("results", []) or []
        me = next((e for e in results if e.get("entry") == team_id), None)

        # In a large league the manager is not on page 1, so `me` stays None and
        # every personal stat comes back empty (observed: rank ~78,000 against a
        # 50-row page, with FPL reporting has_next=True and no rank_count).
        # Paging to find them would take ~1,500 requests, so instead read the
        # manager's own standing from their entry — FPL already publishes their
        # rank in every league they are in, which is exact and costs one call.
        my_league_rank = None
        if me is None:
            async with aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=get_ssl_context())
            ) as session:
                async with session.get(
                    f"https://fantasy.premierleague.com/api/entry/{team_id}/"
                ) as r:
                    entry = await r.json() if r.status == 200 else {}
            for l in (entry.get("leagues", {}) or {}).get("classic", []):
                if l.get("id") == league_id:
                    my_league_rank = l.get("entry_rank")
                    me = {
                        "rank": l.get("entry_rank"),
                        "last_rank": l.get("entry_last_rank"),
                        "total": entry.get("summary_overall_points"),
                        "event_total": entry.get("summary_event_points"),
                        "entry": team_id,
                    }
                    break

        totals = [e["total"] for e in results]

        stats = None
        if results:
            leader = results[0]
            stats = {
                "members_shown": len(results),
                "leader_total": leader["total"],
                # NOTE: this is the average of the VISIBLE PAGE (the top ~50),
                # not of the whole league — FPL pages standings and publishes no
                # league-wide average. Comparing a mid-table manager against it
                # is comparing them to the leaders, so the UI labels it "top 50
                # average" rather than "league average".
                "top50_average": round(sum(totals) / len(totals), 1),
                "league_average": round(sum(totals) / len(totals), 1),
                "top_score_this_gw": max((e.get("event_total") or 0) for e in results),
                "average_this_gw": round(
                    sum((e.get("event_total") or 0) for e in results) / len(results), 1
                ),
            }
            if me:
                total_members = (data.get("league", {}) or {}).get("rank_count")
                my_rank = me.get("rank")
                stats.update({
                    "my_rank": my_rank,
                    "my_total": me["total"],
                    "my_gw_points": me.get("event_total"),
                    "points_behind_leader": leader["total"] - me["total"],
                    "vs_top50_average": round(me["total"] - stats["top50_average"], 1),
                    "total_members": total_members,
                    # Percentile from the manager's TRUE rank when the league
                    # size is known, rather than from the visible page — the
                    # page-1 version reported "top 0%" for someone ranked 78,000th.
                    "percentile": (
                        round((1 - (my_rank - 1) / total_members) * 100)
                        if total_members and my_rank else None
                    ),
                })

        return {
            "league": {
                "id": league_id,
                "name": (data.get("league", {}) or {}).get("name"),
            },
            "stats": stats,
            "standings": [
                {
                    "rank": e.get("rank"),
                    "last_rank": e.get("last_rank"),
                    "entry": e.get("entry"),
                    "entry_name": e.get("entry_name"),
                    "player_name": e.get("player_name"),
                    "total": e.get("total"),
                    "event_total": e.get("event_total"),
                    "is_me": e.get("entry") == team_id,
                }
                for e in results[:50]
            ],
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
# The bot's own FPL entry id. The historical default below DOES NOT EXIST —
# verified live: GET /api/entry/12777515/ returns 404, so every bot endpoint
# that resolves a squad has been failing with a confusing "Team not found"
# rather than saying the id was never configured. Set BOT_TEAM_ID in .env
# (your team id is in the URL at fantasy.premierleague.com/entry/<ID>/).
BOT_TEAM_ID = int(os.getenv("BOT_TEAM_ID", "12777515"))
BOT_TEAM_ID_CONFIGURED = bool(os.getenv("BOT_TEAM_ID"))


def require_bot_team_id() -> int:
    """Fail with an actionable message instead of a bare 404 from FPL."""
    if not BOT_TEAM_ID_CONFIGURED:
        raise HTTPException(
            status_code=503,
            detail=(
                "BOT_TEAM_ID is not configured, and the built-in default "
                f"({BOT_TEAM_ID}) is not a real FPL team. Set BOT_TEAM_ID in .env "
                "to the bot's entry id (see fantasy.premierleague.com/entry/<ID>/)."
            ),
        )
    return BOT_TEAM_ID

@app.get("/api/bot/auth-status")
async def get_bot_auth_status():
    """
    Whether authenticated FPL writes are possible, and in which mode.

    Read-only and never throws — the point is to diagnose auth without
    attempting a write.
    """
    return fpl_auth.auth_status()


@app.get("/api/bot/initial-squad")
async def get_bot_initial_squad(budget: float = 100.0, num_gameweeks: int = 5):
    """
    Build a full 15-player opening squad for review — read-only, submits nothing.

    Reuses build_optimal_squad (EnhancedOptimizer + AvailabilityFilter + the v2
    points model) and adds what you need to actually enter a squad by hand:
    bench order, a vice-captain, and a per-pick justification.

    Deliberately read-only. FPL has no documented endpoint for submitting a
    first 15-player squad (transfers and lineup do have documented endpoints,
    initial squad creation does not), so this produces a squad for a human to
    apply rather than pretending it can submit one.
    """
    try:
        squad = await build_optimal_squad("wildcard", budget, max(1, min(num_gameweeks, 10)))
        players = squad["players"]

        starting = [p for p in players if p["is_starting"]]
        bench = [p for p in players if not p["is_starting"]]

        # Bench order: GK always sits at bench slot 1 (FPL convention — the
        # backup keeper can only replace the keeper), then the rest by
        # descending prediction so the likeliest scorer comes on first.
        bench_gks = [p for p in bench if p["position"] == 1]
        # Best player first, purely by expected points.
        #
        # FPL walks the bench IN ORDER — if bench 1 didn't play it tries bench 2,
        # then 3. So there is no cost to putting a doubtful-but-better player
        # first: if he plays you get the better score, and if he doesn't the next
        # man is used automatically. Sorting by play probability instead would
        # spend your best substitute slot on a lesser player for no gain.
        bench_outfield = sorted(
            [p for p in bench if p["position"] != 1],
            key=lambda p: p["predicted_points"], reverse=True,
        )
        ordered_bench = bench_gks + bench_outfield

        # Vice-captain: best predicted starter who isn't the captain. Guards
        # against the captain being a late withdrawal.
        captain = next((p for p in players if p["is_captain"]), None)
        vice = next(
            (p for p in sorted(starting, key=lambda p: p["predicted_points"], reverse=True)
             if not captain or p["id"] != captain["id"]),
            None,
        )

        def justify(p: Dict) -> str:
            bits = [f"{p['predicted_points']} pred pts"]
            if p.get("play_probability") is not None:
                bits.append(f"{int(p['play_probability'] * 100)}% to start")
            if p.get("next_opponent"):
                bits.append(f"vs {p['next_opponent']} (FDR {p['fixture_difficulty']})")
            if p["ownership"] < 5.0:
                bits.append(f"differential, {p['ownership']:.1f}% owned")
            return " · ".join(bits)

        return {
            "gameweek": squad["gameweek"],
            "formation": squad["formation"],
            "total_cost": squad["total_cost"],
            "total_cost_m": round(squad["total_cost"] / 10, 1),
            "budget_remaining_m": round(budget - squad["total_cost"] / 10, 1),
            "predicted_points": squad["predicted_points"],
            "avg_fixture_difficulty": squad["avg_fixture_difficulty"],
            "captain": {"id": captain["id"], "name": captain["name"]} if captain else None,
            "vice_captain": {"id": vice["id"], "name": vice["name"]} if vice else None,
            "starting_xi": [
                {**p, "justification": justify(p)}
                for p in sorted(starting, key=lambda p: (p["position"], -p["predicted_points"]))
            ],
            "bench": [
                {**p, "bench_order": i + 1, "justification": justify(p)}
                for i, p in enumerate(ordered_bench)
            ],
            "model": squad["model"],
            "submission": {
                "automated": False,
                "reason": (
                    "FPL publishes no documented endpoint for creating an initial 15-player "
                    "squad, so this must be entered manually in the FPL app or site."
                ),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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


async def _fetch_entry_history(session, team_id):
    """Return the FPL entry/{id}/history 'current' array (per-GW), or [] on failure."""
    url = f"https://fantasy.premierleague.com/api/entry/{team_id}/history/"
    async with session.get(url) as resp:
        if resp.status != 200:
            return []
        data = await resp.json()
        return data.get("current", [])


@app.get("/api/history")
@app.get("/api/history/{team_id}")
async def get_history(team_id: Optional[int] = None):
    """
    Per-gameweek season history for the Stats page.

    Proxies FPL entry/{id}/history/ for both the user's team (if team_id given)
    and the bot, and pulls the gameweek field average from bootstrap-static's
    events[].average_entry_score. Returns series aligned by gameweek:

        { gw, user, bot, avg, rankUser, rankBot, bench }

    When no team_id is supplied, `user` mirrors the field average so the Stats
    page still renders a meaningful "you vs bot vs world" view.
    """
    try:
        ssl_context = get_ssl_context()
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            # Field average per finished gameweek
            gw_url = "https://fantasy.premierleague.com/api/bootstrap-static/"
            async with session.get(gw_url) as resp:
                bootstrap = await resp.json()
            avg_by_gw = {
                e["id"]: (e.get("average_entry_score") or 0)
                for e in bootstrap["events"]
                if e.get("finished")
            }

            bot_hist = await _fetch_entry_history(session, BOT_TEAM_ID)
            user_hist = await _fetch_entry_history(session, team_id) if team_id else []

            # Anchor the series on the gameweeks the bot has actually played,
            # intersected with finished GWs that have a field average.
            gws = sorted(
                g["event"] for g in bot_hist if g["event"] in avg_by_gw
            ) if bot_hist else sorted(avg_by_gw.keys())

            if not gws:
                raise HTTPException(status_code=503, detail="No gameweek history available yet")

            bot_by_gw = {g["event"]: g for g in bot_hist}
            user_by_gw = {g["event"]: g for g in user_hist}

            def points(by_gw, gw):
                return (by_gw.get(gw) or {}).get("points", 0)

            def rank(by_gw, gw):
                return (by_gw.get(gw) or {}).get("overall_rank") or 0

            gw_list = list(gws)
            avg = [avg_by_gw.get(gw, 0) for gw in gw_list]
            bot = [points(bot_by_gw, gw) for gw in gw_list]
            rank_bot = [rank(bot_by_gw, gw) for gw in gw_list]

            if team_id and user_hist:
                user = [points(user_by_gw, gw) for gw in gw_list]
                rank_user = [rank(user_by_gw, gw) for gw in gw_list]
                bench = [(user_by_gw.get(gw) or {}).get("points_on_bench", 0) for gw in gw_list]
            else:
                # No user team loaded — fall back to the field average line.
                user = list(avg)
                rank_user = list(rank_bot)
                bench = [0 for _ in gw_list]

            return {
                "gw": gw_list,
                "user": user,
                "bot": bot,
                "avg": avg,
                "rankUser": rank_user,
                "rankBot": rank_bot,
                "bench": bench,
                "has_user": bool(team_id and user_hist),
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
async def get_price_changes(limit: int = 20):
    """
    Players closest to a price rise or fall, from **FPL's own official data**.

    Previously this scraped LiveFPL and, failing that, guessed from raw transfer
    counts — both of which were estimates of something FPL now publishes
    directly:

      price_change_percent      progress toward a change; +100 triggers a rise,
                                -100 a fall
      price_change_projections  per-day projections, each with a `likelihood`
                                from -5 (near-certain fall) to +5 (near-certain
                                rise)
      price_change_hourly_rate  current rate of movement

    Using the official numbers removes a scraping dependency, a LiveFPL
    outage path, and the BOT_TEAM_ID requirement (the old version built a whole
    BotDecisionMaker just to read prices, so it 503'd when no bot team was set).

    Response keys are unchanged (`rising`/`falling`/`source`), so existing
    consumers keep working; each player now also carries `progress_percent`,
    `likelihood` and `confidence`.
    """
    try:
        data = await make_fpl_request("bootstrap-static/")
        if "error" in data:
            raise HTTPException(status_code=502, detail=f"FPL API error: {data['error']}")

        limit = min(max(int(limit or 20), 1), 50)
        teams = {t["id"]: t.get("short_name", "?") for t in data.get("teams", [])}

        def progress(p) -> float:
            try:
                return float(p.get("price_change_percent") or 0)
            except (TypeError, ValueError):
                return 0.0

        candidates = [
            p for p in data.get("elements", [])
            if p.get("price_change_percent") is not None
        ]
        if not candidates:
            # FPL blanks these fields outside its daily calculation window.
            return {"rising": [], "falling": [], "source": "fpl_official",
                    "note": "FPL is not publishing price-change progress right now."}

        # Likelihood is signed (-5 falling .. +5 rising); magnitude is confidence.
        CONFIDENCE = {5: "near-certain", 4: "very likely", 3: "likely",
                      2: "possible", 1: "outside chance", 0: "unclear"}

        def shape(p) -> Dict:
            proj = (p.get("price_change_projections") or [{}])[0]
            like = proj.get("likelihood")
            pct = progress(p)
            t_in = p.get("transfers_in_event", 0) or 0
            t_out = p.get("transfers_out_event", 0) or 0
            return {
                "id": p.get("id"),
                "name": p.get("web_name"),
                "team": teams.get(p.get("team"), "?"),
                "price": round((p.get("now_cost") or 0) / 10, 1),
                "progress_percent": round(pct, 1),
                "likelihood": like,
                "confidence": CONFIDENCE.get(abs(like) if like is not None else 0, "unclear"),
                "hourly_rate": p.get("price_change_hourly_rate"),
                "net_transfers": t_in - t_out,
                "transfers_in": t_in,
                "transfers_out": t_out,
                # Kept for compatibility with the previous LiveFPL shape.
                "risk_level": "high" if abs(pct) >= 75 else "medium" if abs(pct) >= 50 else "low",
                "already_changed": (p.get("cost_change_event") or 0) != 0,
            }

        rising = [shape(p) for p in sorted(candidates, key=progress, reverse=True)[:limit]]
        falling = [shape(p) for p in sorted(candidates, key=progress)[:limit]]

        return {
            "rising": rising,
            "falling": falling,
            "source": "fpl_official",
            "explanation": (
                "progress_percent is FPL's own progress toward a price change "
                "(+100 rises, -100 falls). Timing signal only — never a reason "
                "to buy a player you would not otherwise want."
            ),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def run_agent_and_maybe_submit(run_type: str = "final", submit: bool = False) -> Dict:
    """
    One autonomous decision, optionally written to FPL.

    Shared by `GET /api/bot/agent-decision` (manual/inspection) and
    `POST /api/bot/run` (scheduler/external cron) so the two paths cannot drift.

    Raises `BotAgentError` when no decision could be made — the caller decides
    whether that becomes a 503 or a recorded failed run. It must never be
    flattened into an empty decision, which would read as "no changes needed".
    """
    from bot_agent import run_agent_decision, BotAgentError
    import bot_scheduler

    early = run_type == "early"
    bot_team_id = require_bot_team_id()

    # Take the target gameweek from FPL's `is_next` event, NOT from
    # `get_user_team`'s gameweek + 1. That field comes from `is_current`, which
    # is empty before a season's first deadline and falls back to 1 — so +1 gave
    # GW2 while the deadline actually being played was GW1 (verified live on
    # 2026-08-21). Submitting transfers against the wrong event id is not a
    # cosmetic error: it targets the wrong gameweek entirely. `bot_scheduler`
    # already resolves this correctly and is the single source of truth.
    schedule = await bot_scheduler.get_gameweek_schedule()
    target_gw = schedule.get("next_gameweek")
    if target_gw is None:
        raise BotAgentError(
            "FPL reports no upcoming gameweek (season over, or bootstrap-static "
            "unavailable). Refusing to guess a gameweek for a write."
        )

    team_data = await get_user_team(bot_team_id)
    players, teams, _data = await fetch_enhanced_players()
    context = build_comprehensive_context(
        team_data, players, teams, None, None, str(bot_team_id)
    )

    decision = await run_agent_decision(
        gameweek=target_gw,
        context=context,
        tools=FPL_TOOLS,
        execute_tool_func=execute_tool,
        players=players,
        teams=teams,
        team_data=team_data,
        run_type=run_type,
    )

    result = {"decision": decision.to_dict(), "submitted": False}

    if not submit:
        return result

    import fpl_auth

    if decision.confidence == "low":
        result["submit_skipped"] = (
            "Agent reported low confidence — not submitting. Review by hand."
        )
        return result

    try:
        squad_ids = [p["id"] for p in team_data.get("players", [])]
        writes = {}
        squad_chip = decision.chip in ("wildcard", "freehit")

        if decision.transfers:
            prices = fpl_auth.get_squad_selling_prices(bot_team_id)
            player_costs = {p["id"]: p.get("now_cost") for p in players}
            payload = []
            for t in decision.transfers:
                priced = prices.get(t.player_out_id)
                if not priced:
                    raise fpl_auth.FPLAuthError(
                        f"No selling price for {t.player_out_name} "
                        f"(id {t.player_out_id}) — is he in the squad?"
                    )
                cost_in = player_costs.get(t.player_in_id)
                if cost_in is None:
                    raise fpl_auth.FPLAuthError(
                        f"No current price for {t.player_in_name} (id {t.player_in_id})."
                    )
                payload.append({
                    "element_out": t.player_out_id,
                    "element_in": t.player_in_id,
                    # What the sold player is worth (half of any rise, per
                    # get_squad_selling_prices) vs what the bought player costs
                    # right now. FPL's field name for the incoming side is
                    # `purchase_price`, so `now_cost` is the correct value here.
                    "selling_price": priced["selling_price"],
                    "purchase_price": cost_in,
                })
            writes["transfers"] = fpl_auth.make_transfers(
                bot_team_id, decision.gameweek, payload,
                wildcard=decision.chip == "wildcard",
                freehit=decision.chip == "freehit",
            )
            # Post-transfer squad, so the lineup payload reflects the new players.
            for t in decision.transfers:
                if t.player_out_id in squad_ids:
                    squad_ids[squad_ids.index(t.player_out_id)] = t.player_in_id
        elif squad_chip:
            # A wildcard/freehit is activated by the TRANSFER endpoint, not the
            # lineup one. Previously this branch didn't exist, so a chip decided
            # with an empty transfer list was silently dropped: make_transfers
            # was skipped, and set_lineup only forwards bboost/3xc. Refuse
            # instead of pretending the chip was played.
            raise fpl_auth.FPLAuthError(
                f"Agent chose {decision.chip} but submitted no transfers. That chip is "
                "activated through the transfer endpoint, so there is nothing to play it "
                "on. Not submitting — re-run, or apply it by hand."
            )

        if not early:
            lineup_chip = decision.chip if decision.chip in ("bboost", "3xc") else None
            writes["lineup"] = fpl_auth.set_lineup(
                bot_team_id, decision.to_lineup_picks(squad_ids), chip=lineup_chip
            )

        result["submitted"] = True
        result["writes"] = writes
        result["mode"] = fpl_auth.bot_mode()
    except (fpl_auth.FPLAuthError, BotAgentError) as e:
        # Decision is still valuable even if the write failed — return it with
        # the error rather than 500ing and losing the analysis.
        result["submit_error"] = str(e)
        result["mode"] = fpl_auth.bot_mode()

    return result


@app.get("/api/strategy/squad")
async def strategy_squad(budget: float = 100.0, num_gameweeks: int = 5,
                         bench_cap: float = None, min_bank: float = 0.0):
    """
    Strategy-driven squad build (two-stage), replacing the flat-objective LP.

    Stage 1 — `fpl_strategy` does the FPL THINKING: builds a fixture-anchored
    shortlist tagged premium/core/value/rotation/bench, scores clean-sheet
    outlook per team (fixture softness x FPL's own defensive-strength ratings),
    finds budget-defender ROTATION PAIRS whose good fixtures fall in different
    gameweeks, and surfaces value picks, xG-underperforming bargains and
    overperforming regression risks.

    Stage 2 — the LP assembles the best legal 15 FROM THAT SHORTLIST, maximising
    v2-model predicted points with the bench scored at a discount and its spend
    capped, so money stays on the pitch instead of being force-spent.

    Why this exists: the previous builder optimised `form`, which is 0.0 for all
    600 players pre-season, so its objective was flat and the squad was an
    arbitrary feasible solution. It also never referenced the ML model.
    """
    import fpl_strategy
    from enhanced_optimization import EnhancedOptimizer

    data = await make_fpl_request("bootstrap-static/")
    fixtures_data = await make_fpl_request("fixtures/")
    if "error" in data:
        raise HTTPException(status_code=502, detail=f"FPL API error: {data['error']}")

    teams = {t["id"]: t for t in data.get("teams", [])}
    start_gw = planning_gameweek(data.get("events", []))
    num_gws = max(1, min(num_gameweeks, 10))

    # Availability first — an unavailable player should never reach the shortlist.
    available = availability_filter.filter_available_players(
        data.get("elements", []), min_chance=SQUAD_MIN_CHANCE
    )

    # Enhanced players carry the Understat xG fields the value analysis needs.
    try:
        enriched, _t, _d = await fetch_enhanced_players()
        by_id = {p["id"]: p for p in enriched}
        available = [{**p, **{k: v for k, v in by_id.get(p["id"], {}).items()
                              if k.startswith(("xG", "xA", "npxG", "threat"))}}
                     for p in available]
    except Exception as e:
        print(f"strategy: enhanced stats unavailable ({e}); value analysis degrades to points/£m")

    runs = fpl_strategy.build_fixture_runs(fixtures_data, teams, start_gw, num_gws)

    # v2 model predictions — this is what replaces `form` as the ranking signal.
    raw = ml_predict_v2.predict_points(available)
    if not raw:
        # Refuse rather than silently reverting to a form-based objective, which
        # is flat pre-season and produced the arbitrary squad this replaces.
        raise HTTPException(
            status_code=503,
            detail="v2 model unavailable — refusing to fall back to a flat `form` objective.",
        )
    predictions = {
        pid: {
            "predicted_points": v.get("predicted_points", 0.0),
            "start_prob": v.get("play_probability", 0.0),
        }
        for pid, v in raw.items()
    }

    shortlist, meta = fpl_strategy.build_shortlist(
        available, teams, runs, predictions
    )
    if len(shortlist) < 15:
        raise HTTPException(status_code=503, detail="Shortlist too small to build a squad")

    lp_rows = [{
        "id": t.player_id, "name": t.name, "price": t.price,
        "position_id": t.position, "team_id": t.team, "team": t.team_short,
        "predicted_points": t.predicted_points, "start_prob": t.start_prob,
        "role": t.role, "reasons": t.reasons,
        "points_per_million": t.points_per_million, "xg_signal": t.xg_signal,
        "good_fixture_gws": t.good_fixture_gws,
    } for t in shortlist]

    squad, lineup, status = EnhancedOptimizer().optimize_from_shortlist(
        lp_rows, budget=budget,
        bench_spend_cap=bench_cap if bench_cap is not None else fpl_strategy.BENCH_SPEND_CAP,
        min_bank=min_bank,
    )
    if not squad:
        raise HTTPException(status_code=503, detail=status)

    return {
        "gameweek": start_gw,
        "horizon_gameweeks": num_gws,
        "formation": lineup["formation"],
        "total_cost": lineup["total_cost"],
        "xi_cost": lineup["xi_cost"],
        "bench_cost": lineup["bench_cost"],
        "bank": lineup["bank"],
        "predicted_xi_points": lineup["predicted_xi_points"],
        "starting_xi": sorted(lineup["starting"],
                              key=lambda p: (p["position_id"], -p["predicted_points"])),
        "bench": sorted(lineup["bench"], key=lambda p: (p["position_id"] != 1,
                                                       -p["predicted_points"])),
        "strategy": meta,
        "model": ml_predict_v2.model_info(),
    }


@app.get("/api/bot/agent-decision")
async def get_bot_agent_decision(early: bool = False, submit: bool = False):
    """
    Autonomous gameweek decision made by the Claude tool-loop (Task 6).

    Differs from /api/bot/decision, which runs `bot_decision_maker`'s hand-written
    arithmetic (`form * 3 + fixture_score`) and references neither the retrained
    v2 model nor any live news source. This endpoint runs the same tool set the
    chat uses — ML predictions, third-party team news, live web search — and the
    model owns the judgment while the LP optimizer keeps owning the constraints.

    Parameters:
    - early: early run (price-timing transfers only, no captain/chip) vs final run
    - submit: also write the decision to FPL via fpl_auth. Still gated by
      FPL_BOT_MODE (default `notify` writes nothing), and refused on a low-confidence
      decision — an unverified call should never reach a real team.
    """
    from bot_agent import BotAgentError

    try:
        return await run_agent_and_maybe_submit(
            run_type="early" if early else "final", submit=submit
        )
    except BotAgentError as e:
        # 503 so a caller can distinguish a failed run from a valid empty decision.
        raise HTTPException(status_code=503, detail=f"Agent could not decide: {e}")


@app.post("/api/bot/run")
async def trigger_bot_run(
    run_type: Optional[str] = None,
    force: bool = False,
    submit: bool = True,
    _: bool = Depends(verify_token),
):
    """
    Trigger a scheduled bot run. **This is the production path on Render's free
    tier**, where an in-process scheduler cannot be trusted — a dozing service is
    not running, so APScheduler is not late, it is absent. An external cron
    hitting this endpoint wakes the service by the act of calling it.

    Authenticated (same JWT as /api/chat) so a public URL can't drive the bot.

    Parameters:
    - run_type: 'early' or 'final'. Omit to auto-detect what is due now, which is
      what a periodic cron should do.
    - force: run even if this gameweek's run already completed.
    - submit: write the decision (still gated by FPL_BOT_MODE, default notify).

    Never 500s on an agent failure: the failure is recorded and returned, so a
    cron's logs show what happened rather than a silent nothing.
    """
    import bot_scheduler

    if run_type is None:
        due = await bot_scheduler.due_runs()
        if not due:
            schedule = await bot_scheduler.get_gameweek_schedule()
            return {
                "ran": False,
                "reason": "Nothing due now.",
                "next_gameweek": schedule.get("next_gameweek"),
                "deadline": schedule["deadline"].isoformat() if schedule.get("deadline") else None,
            }
        # Final wins if somehow both are due — it is the one that must not be missed.
        run_type = "final" if "final" in due else due[0]
    elif run_type not in ("early", "final"):
        raise HTTPException(status_code=400, detail="run_type must be 'early' or 'final'")

    outcome = await bot_scheduler.execute_run(
        run_type, run_agent_and_maybe_submit, force=force, submit=submit
    )
    return {"ran": outcome.get("ok", False), **outcome}


@app.get("/api/bot/schedule")
async def get_bot_schedule():
    """
    Upcoming deadline, planned run times, what's due now, and recent run history.
    Read-only — safe to poll, and the fastest way to see whether the bot is
    actually watching the deadline or just configured to look like it is.
    """
    import bot_scheduler

    schedule = await bot_scheduler.get_gameweek_schedule()
    planned = {}
    if schedule.get("deadline"):
        planned = {
            k: v.isoformat()
            for k, v in bot_scheduler.compute_run_times(
                schedule["deadline"], schedule.get("previous_deadline")
            ).items()
        }

    return {
        "next_gameweek": schedule.get("next_gameweek"),
        "deadline": schedule["deadline"].isoformat() if schedule.get("deadline") else None,
        "planned_runs": planned,
        "due_now": await bot_scheduler.due_runs(),
        "in_process_scheduler": _bot_scheduler.status() if _bot_scheduler else {"running": False},
        "recent_runs": bot_scheduler.run_history(10),
        "bot_mode": __import__("fpl_auth").bot_mode(),
    }


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

        # Unpack (response, tools_used, transfers, failure_reason)
        failure_reason = None
        if isinstance(result, tuple):
            if len(result) == 4:
                response, tools_used, transfer_list, failure_reason = result
            elif len(result) == 3:
                response, tools_used, transfer_list = result
            else:
                response, tools_used = result
                transfer_list = []
        else:
            response, tools_used, transfer_list = result, [], []

        if not response:
            # The AI failed. Say so.
            #
            # This used to silently serve a rule-based answer, which looked like
            # a real reply — a canned "Captain Pick: X / Form: Y" with NO tool
            # calls. That is how a retired, 404-ing model went unnoticed for
            # months, and it hid an out-of-credit account here too. The heuristic
            # answer is still shown (it is better than nothing), but it is now
            # clearly labelled as a fallback with the actual cause.
            print(f"⚠️ AI unavailable: {failure_reason or 'no response'}")
            heuristic = player_details or await fallback_response(
                message.lower(), team_data, players, teams
            )
            reason = failure_reason or "The AI assistant did not return a response."
            response = (
                f"⚠️ **AI assistant unavailable** — {reason}\n\n"
                f"Showing a basic non-AI answer instead:\n\n{heuristic}"
            )

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
            model=CHAT_MODEL
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

        # === get_injury_report - Injured/suspended/doubtful players ===
        elif tool_name == "get_injury_report":
            team_filter = args.get("team")
            return tool_get_injury_report(players, teams, team_filter)

        # === get_team_news - Fast third-party injury + lineup news ===
        elif tool_name == "get_team_news":
            team_filter = args.get("team")
            return await tool_get_team_news(team_filter)

        # === search_player_news - live web cross-reference ===
        elif tool_name == "search_player_news":
            names = args.get("player_names") or []
            return await tool_search_player_news(names, players, teams)

        # === get_ml_prediction - v2 model predicted points ===
        elif tool_name == "get_squad_strategy":
            n = args.get("num_gameweeks", 5)
            return await tool_squad_strategy(min(max(int(n or 5), 1), 10))

        elif tool_name == "get_ml_prediction":
            names = args.get("player_names") or []
            position = args.get("position", "all")
            limit_val = args.get("limit", 10)
            limit = min(int(limit_val) if limit_val else 10, 30)
            return await tool_get_ml_prediction(names, position, limit, players, teams)

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


async def tool_squad_strategy(num_gws: int) -> str:
    """
    Strategy analysis as prose the agent can reason over.

    Deliberately returns the ANALYSIS, not a squad. The agent's job is judgment —
    weighing a clean-sheet target against team news, deciding whether a
    regression risk is still worth owning — so handing it a finished squad would
    replace the reasoning this tool exists to inform.
    """
    import fpl_strategy

    data = await make_fpl_request("bootstrap-static/")
    fixtures_data = await make_fpl_request("fixtures/")
    if "error" in data:
        return f"Could not load FPL data: {data['error']}"

    teams = {t["id"]: t for t in data.get("teams", [])}
    start_gw = planning_gameweek(data.get("events", []))
    available = availability_filter.filter_available_players(
        data.get("elements", []), min_chance=SQUAD_MIN_CHANCE
    )

    # Understat xG fields power the bargain/regression analysis.
    try:
        enriched, _t, _d = await fetch_enhanced_players()
        by_id = {p["id"]: p for p in enriched}
        available = [{**p, **{k: v for k, v in by_id.get(p["id"], {}).items()
                              if k.startswith(("xG", "xA", "npxG"))}}
                     for p in available]
    except Exception:
        pass  # value analysis degrades to points/£m; still useful

    raw = ml_predict_v2.predict_points(available)
    if not raw:
        return "Strategy analysis unavailable: the points model could not be loaded."
    preds = {pid: {"predicted_points": v.get("predicted_points", 0.0),
                   "start_prob": v.get("play_probability", 0.0)}
             for pid, v in raw.items()}

    runs = fpl_strategy.build_fixture_runs(fixtures_data, teams, start_gw, num_gws)
    _shortlist, meta = fpl_strategy.build_shortlist(available, teams, runs, preds)

    out = [f"**Squad strategy — GW{start_gw} to GW{start_gw + num_gws - 1}**", ""]

    out.append("**Best clean-sheet outlook** (fixture softness x defensive strength):")
    for t in meta["clean_sheet_teams"][:6]:
        out.append(f"  {t['team']}: score {t['cs_score']}, avg FDR {t['avg_fdr']}")
    out.append("  A strong defence with a hard run still concedes — pair these with team news.")
    out.append("")

    if meta["rotation_pairs"]:
        out.append("**Budget rotation pairs** (complementary fixtures — start whichever has the better game):")
        for pr in meta["rotation_pairs"][:4]:
            out.append(
                f"  {pr['players'][0]} ({pr['teams'][0]}) + {pr['players'][1]} "
                f"({pr['teams'][1]}) £{pr['combined_price']}m — good fixtures cover "
                f"GW{pr['covered_gameweeks']}, overlap GW{pr['overlap_gameweeks'] or 'none'}"
            )
        out.append("")

    if meta["value_picks"]:
        out.append("**Best value** (points per £m, cheap and playing):")
        for v in meta["value_picks"][:6]:
            out.append(f"  {v['name']} ({v['team']}) {v['position']} £{v['price']}m — "
                       f"{v['points_per_million']} pts/£m, {v['start_prob']:.0%} to start")
        out.append("")

    if meta["underperforming_bargains"]:
        out.append("**xG bargains** (scoring BELOW expected on real chances — tends to correct):")
        for v in meta["underperforming_bargains"][:5]:
            note = next((r for r in v["reasons"] if "BELOW xG" in r), "")
            out.append(f"  {v['name']} ({v['team']}) £{v['price']}m — {note}")
        out.append("")

    if meta["regression_risks"]:
        out.append("**Regression risks** (scoring ABOVE xG — price inflated by finishing luck):")
        for v in meta["regression_risks"][:5]:
            note = next((r for r in v["reasons"] if "above xG" in r), "")
            out.append(f"  {v['name']} ({v['team']}) £{v['price']}m — {note}")
        out.append("")

    br = meta["budget_rules"]
    out.append(
        f"**Budget principle:** keep bench spend under ~£{br['bench_spend_cap']}m, and require "
        f"bench players to be >={br['bench_min_start_prob']:.0%} likely to start — a substitute who "
        "never plays is not cover. Money saved on the bench upgrades a starter."
    )
    return "\n".join(out)


async def tool_get_fixtures(team_filter: Optional[str], num_gws: int) -> str:
    """Get upcoming fixtures"""
    data = await make_fpl_request("bootstrap-static/")
    fixtures_data = await make_fpl_request("fixtures/")

    if "error" in data or "error" in fixtures_data:
        return "Failed to fetch fixtures data"

    teams_dict = {t['id']: t for t in data.get('teams', [])}
    # Planning window starts at the NEXT unplayed gameweek. Anchoring on
    # is_current would lead the list with a gameweek already being played,
    # wasting the first slot and shortening the real forward view by one.
    current_gw = planning_gameweek(data['events'])

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
    # Forward-looking advice plans from the next unplayed gameweek (see planning_gameweek).
    current_gw = planning_gameweek(data['events'])

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


def tool_get_injury_report(players: List[Dict], teams: Dict, team_filter: Optional[str] = None) -> str:
    """Get injured/suspended/doubtful player report"""
    filtered_players = players
    if team_filter:
        team_lower = team_filter.lower()
        team_ids = [t['id'] for t in teams.values() if team_lower in t.get('name', '').lower() or team_lower in t.get('short_name', '').lower()]
        filtered_players = [p for p in players if p.get('team') in team_ids]

    report = availability_filter.get_injury_report(filtered_players)

    lines = [f"**Injury Report**" + (f" for {team_filter}" if team_filter else "") + ":"]

    section_labels = [
        ("injured", "🔴 Injured"),
        ("suspended", "🟠 Suspended"),
        ("doubtful", "🟡 Doubtful"),
    ]
    any_concerns = False
    for key, label in section_labels:
        entries = report.get(key, [])
        if not entries:
            continue
        any_concerns = True
        lines.append(f"\n**{label}** ({len(entries)}):")
        for p in entries[:20]:
            team_name = teams.get(p.get('team', 0), {}).get('short_name', '?')
            chance = p.get('chance')
            chance_str = f"{chance}% chance" if chance is not None else "no % given"
            news = p.get('news') or "no details"
            lines.append(f"  {p.get('web_name')} ({team_name}) - {chance_str} - {news}")
        if len(entries) > 20:
            lines.append(f"  ... and {len(entries) - 20} more")

    if not any_concerns:
        lines.append("\nNo injury/suspension/doubt concerns found" + (f" for {team_filter}" if team_filter else "") + ".")

    return "\n".join(lines)


async def tool_search_player_news(player_names: List[str], players: List[Dict], teams: Dict) -> str:
    """Live web search for player news, cross-referenced against all three feeds."""
    if not player_names:
        return "Give me at least one player name to check."
    if not player_news_search.available():
        return ("Live news search isn't configured on this deployment. "
                "get_team_news and get_injury_report still work.")

    selected = []
    for wanted in player_names[:6]:
        needle = wanted.strip().lower()
        for p in players:
            web = (p.get("web_name") or "").lower()
            if needle == web or needle in web or web in needle:
                selected.append(p)
                break
    if not selected:
        return f"Couldn't find any of those players: {', '.join(player_names)}"

    candidates = [{
        "name": f"{p.get('first_name','')} {p.get('second_name','')}".strip() or p.get("web_name"),
        "web_name": p.get("web_name"),
        "team": teams.get(p.get("team", 0), {}).get("short_name", ""),
        "chance_of_playing": p.get("chance_of_playing_next_round"),
        "news": p.get("news", ""),
        "id": p.get("id"),
    } for p in selected]

    # Feed the scrapers in so the model arbitrates between all three sources
    # rather than only against FPL — that comparison is the point of the tool.
    try:
        candidates = player_news_search.annotate_with_scrapers(candidates, await fetch_team_news())
    except Exception as e:
        print(f"⚠️  Could not attach scraper data to news search: {e}")

    result = await asyncio.to_thread(player_news_search.search_player_news, candidates)

    lines = ["**Live player news (web + all structured sources)**", ""]
    for c in candidates:
        lines.append(
            f"  {c['name']} ({c['team']}) — FPL: "
            f"{str(c['chance_of_playing']) + '%' if c['chance_of_playing'] is not None else 'no doubt'}"
            f" | Knocks and Bans: {c.get('knocks_and_bans', 'not listed')}"
            f" | FFScout: {c.get('ffscout', 'not listed')}"
        )
    lines.append("")
    lines.append(result.get("report", "No report."))
    return "\n".join(lines)


async def tool_get_team_news(team_filter: Optional[str] = None) -> str:
    """Get fast third-party team news (Knocks and Bans + FFScout)"""
    news = await fetch_team_news()
    knocks_and_bans = news.get("knocks_and_bans", [])
    ffscout = news.get("ffscout", [])

    if not knocks_and_bans and not ffscout:
        return "Team news sources are temporarily unavailable — fall back to get_injury_report for FPL's own data."

    lines = ["**Team News (third-party, faster-updating than FPL's own data)**"]

    if ffscout:
        teams_to_show = ffscout
        if team_filter:
            team_lower = team_filter.lower()
            teams_to_show = [t for t in ffscout if team_lower in t['team'].lower()]
        for t in teams_to_show:
            lines.append(f"\n**{t['team']}**" + (f" (updated: {t['last_updated']})" if t.get('last_updated') else "") + ":")
            if t['predicted_lineup']:
                lines.append(f"  Predicted XI: {', '.join(t['predicted_lineup'])}")
            if t['out']:
                lines.append(f"  Out: {', '.join(t['out'])}")
            if t['doubts']:
                lines.append(f"  Doubts: {', '.join(t['doubts'])}")
            if t['banned']:
                lines.append(f"  Banned: {', '.join(t['banned'])}")

    if knocks_and_bans:
        entries_to_show = knocks_and_bans
        if team_filter:
            # Knocks and Bans entries aren't team-tagged, so this source is
            # skipped when filtering by team — FFScout above already covers
            # the per-team Out/Doubts/Banned lists.
            entries_to_show = []
        if entries_to_show:
            lines.append(f"\n**Injury/Suspension Status (all teams, {len(entries_to_show)} entries)**:")
            for e in entries_to_show[:30]:
                detail = e['injury_type'] or "no details"
                return_str = f", est. return {e['expected_return']}" if e.get('expected_return') else ""
                lines.append(f"  {e['name']} - {e['status']} - {detail}{return_str}")
            if len(entries_to_show) > 30:
                lines.append(f"  ... and {len(entries_to_show) - 30} more")

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


async def tool_get_ml_prediction(
    player_names: List[str],
    position: str,
    limit: int,
    players: List[Dict],
    teams: Dict,
) -> str:
    """v2 model predicted points, either for named players or as a ranked list."""
    info = ml_predict_v2.model_info()
    if not info["available"]:
        return ("The ML prediction model isn't available on this deployment, so I can't give "
                "model-based projections. Other signals (form, fixtures, team news) still work.")

    if player_names:
        selected = []
        for name in player_names[:10]:
            search = name.lower()
            for p in players:
                web_name = p.get("web_name", "").lower()
                if search in web_name or web_name in search:
                    selected.append(p)
                    break
        if not selected:
            return f"Could not find any of those players: {', '.join(player_names)}"
        # Named players get the accurate path: real per-GW history.
        preds = await predict_for_players(selected, with_history=True)
        header = "**Predicted points (next gameweek)**"
    else:
        pool = players
        if position and position != "all":
            wanted = POSITIONS_REV.get(position.upper())
            if wanted:
                pool = [p for p in pool if p.get("element_type") == wanted]
        preds = ml_predict_v2.predict_points(pool)
        selected = sorted(pool, key=lambda p: preds.get(p["id"], {}).get("predicted_points", 0),
                          reverse=True)[:limit]
        header = f"**Top {len(selected)} by predicted points (next gameweek)**"
        if position and position != "all":
            header += f" — {position.upper()}"

    lines = [header, ""]
    for p in selected:
        r = preds.get(p["id"])
        if not r:
            continue
        team_name = teams.get(p.get("team", 0), {}).get("short_name", "?")
        lines.append(
            f"  {p.get('web_name')} ({team_name}, £{p.get('now_cost',0)/10:.1f}m): "
            f"**{r['predicted_points']} pts** — {int(r['play_probability']*100)}% likely to start, "
            f"{r['points_if_plays']} pts if they do (confidence: {r['confidence']})"
        )

    if any(preds.get(p["id"], {}).get("basis") == "season_totals" for p in selected):
        lines.append("")
        lines.append("_Note: no gameweek history exists yet this season, so these are estimated from "
                     "last season's per-game rates and cannot reflect current form — treat as rough._")

    lines.append("")
    lines.append("_This model ranks who's likely to do well; it deliberately under-predicts big hauls, "
                 "so use it alongside fixtures and team news rather than on its own._")
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

    # Forward-looking advice plans from the next unplayed gameweek (see planning_gameweek).
    current_gw = planning_gameweek(data['events'])

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
