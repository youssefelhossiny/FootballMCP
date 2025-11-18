#!/usr/bin/env python3

import os
import asyncio
from datetime import datetime, timedelta
from typing import Any
import httpx
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import NotificationOptions, Server
import mcp.server.stdio
import joblib
import pandas as pd
from pathlib import Path

# ============================================
# ML PREDICTION HELPER FUNCTIONS
# Add these after your imports, before server = Server()
# ============================================

# Load ML models at startup
ML_MODELS = None


def load_ml_models():
    """Load trained ML models"""
    global ML_MODELS

    if ML_MODELS is not None:
        return ML_MODELS

    try:
        # Get the directory where Server.py is located
        script_dir = Path(__file__).parent
        models_dir = script_dir / "models"

        # Check if models directory exists
        if not models_dir.exists():
            print(f"ERROR: Models directory not found at {models_dir}")
            return None

        # Check if all required files exist
        required_files = [
            "result_classifier.pkl",
            "home_goals_predictor.pkl",
            "away_goals_predictor.pkl",
            "result_features.txt",
            "goals_features.txt"
        ]

        for file in required_files:
            if not (models_dir / file).exists():
                print(f"ERROR: Required file missing: {file}")
                return None

        result_model = joblib.load(models_dir / "result_classifier.pkl")
        home_goals_model = joblib.load(models_dir / "home_goals_predictor.pkl")
        away_goals_model = joblib.load(models_dir / "away_goals_predictor.pkl")

        with open(models_dir / "result_features.txt", "r") as f:
            result_features = [line.strip() for line in f.readlines()]

        with open(models_dir / "goals_features.txt", "r") as f:
            goals_features = [line.strip() for line in f.readlines()]

        ML_MODELS = {
            "result_model": result_model,
            "home_goals_model": home_goals_model,
            "away_goals_model": away_goals_model,
            "result_features": result_features,
            "goals_features": goals_features
        }

        print(f"✅ Successfully loaded ML models from {models_dir}")
        return ML_MODELS

    except Exception as e:
        print(f"ERROR loading ML models: {e}")
        import traceback
        traceback.print_exc()
        return None


async def calculate_team_stats(team_name, competition_code="PL"):
    """Calculate team statistics for ML prediction"""

    # Get team ID first
    teams_data = await make_api_request(f"competitions/{competition_code}/teams")

    if "teams" not in teams_data:
        return None

    team = None
    for t in teams_data["teams"]:
        if team_name.lower() in t["name"].lower():
            team = t
            break

    if not team:
        return None

    team_id = team["id"]

    # Get recent matches (last 5)
    matches_data = await make_api_request(f"teams/{team_id}/matches", {"limit": 5, "status": "FINISHED"})

    if "matches" not in matches_data or not matches_data["matches"]:
        # Return default values if no matches
        return {
            "team_name": team["name"],
            "goals_scored_avg": 1.5,
            "goals_conceded_avg": 1.5,
            "form": 0.5,
            "wins": 0,
            "draws": 0,
            "losses": 0
        }

    goals_scored = []
    goals_conceded = []
    points = 0
    wins = 0
    draws = 0
    losses = 0

    for match in matches_data["matches"][:5]:
        if match["status"] != "FINISHED":
            continue

        score = match.get("score", {}).get("fullTime", {})
        home_goals = score.get("home")
        away_goals = score.get("away")

        if home_goals is None or away_goals is None:
            continue

        # Check if this team was home or away
        if match["homeTeam"]["id"] == team_id:
            goals_scored.append(home_goals)
            goals_conceded.append(away_goals)

            if home_goals > away_goals:
                points += 3
                wins += 1
            elif home_goals == away_goals:
                points += 1
                draws += 1
            else:
                losses += 1
        else:
            goals_scored.append(away_goals)
            goals_conceded.append(home_goals)

            if away_goals > home_goals:
                points += 3
                wins += 1
            elif away_goals == home_goals:
                points += 1
                draws += 1
            else:
                losses += 1

    num_matches = len(goals_scored)

    if num_matches == 0:
        return {
            "team_name": team["name"],
            "goals_scored_avg": 1.5,
            "goals_conceded_avg": 1.5,
            "form": 0.5,
            "wins": 0,
            "draws": 0,
            "losses": 0
        }

    return {
        "team_name": team["name"],
        "goals_scored_avg": sum(goals_scored) / num_matches,
        "goals_conceded_avg": sum(goals_conceded) / num_matches,
        "form": points / (num_matches * 3),  # Normalized
        "wins": wins,
        "draws": draws,
        "losses": losses
    }


async def get_h2h_stats(team1_name, team2_name):
    """Get head-to-head statistics between two teams"""

    # For simplicity, return neutral H2H if we can't fetch
    # In production, you'd fetch actual H2H matches
    return {
        "home_wins": 2,
        "away_wins": 2,
        "draws": 1
    }


def predict_match_ml(home_stats, away_stats, h2h_stats, models):
    """Make ML prediction for a match"""

    if models is None:
        return None

    try:
        # Prepare result prediction features
        result_input = pd.DataFrame([{
            "home_goals_scored_avg": home_stats["goals_scored_avg"],
            "home_goals_conceded_avg": home_stats["goals_conceded_avg"],
            "home_form": home_stats["form"],
            "home_wins": home_stats["wins"],
            "home_draws": home_stats["draws"],
            "home_losses": home_stats["losses"],
            "away_goals_scored_avg": away_stats["goals_scored_avg"],
            "away_goals_conceded_avg": away_stats["goals_conceded_avg"],
            "away_form": away_stats["form"],
            "away_wins": away_stats["wins"],
            "away_draws": away_stats["draws"],
            "away_losses": away_stats["losses"],
            "h2h_home_wins": h2h_stats["home_wins"],
            "h2h_away_wins": h2h_stats["away_wins"],
            "h2h_draws": h2h_stats["draws"]
        }])

        # Prepare goals prediction features
        goals_input = pd.DataFrame([{
            "home_goals_scored_avg": home_stats["goals_scored_avg"],
            "home_goals_conceded_avg": home_stats["goals_conceded_avg"],
            "home_form": home_stats["form"],
            "away_goals_scored_avg": away_stats["goals_scored_avg"],
            "away_goals_conceded_avg": away_stats["goals_conceded_avg"],
            "away_form": away_stats["form"],
            "h2h_home_wins": h2h_stats["home_wins"],
            "h2h_away_wins": h2h_stats["away_wins"],
            "h2h_draws": h2h_stats["draws"]
        }])

        # Get predictions
        result_proba = models["result_model"].predict_proba(
            result_input[models["result_features"]]
        )[0]
        result_pred = models["result_model"].predict(
            result_input[models["result_features"]]
        )[0]

        home_goals_pred = models["home_goals_model"].predict(
            goals_input[models["goals_features"]]
        )[0]
        away_goals_pred = models["away_goals_model"].predict(
            goals_input[models["goals_features"]]
        )[0]

        # Map probabilities to labels
        classes = models["result_model"].classes_
        proba_dict = {cls: prob for cls, prob in zip(classes, result_proba)}

        return {
            "predicted_result": result_pred,
            "home_win_probability": proba_dict.get("HOME_WIN", 0),
            "draw_probability": proba_dict.get("DRAW", 0),
            "away_win_probability": proba_dict.get("AWAY_WIN", 0),
            "predicted_home_goals": round(home_goals_pred, 1),
            "predicted_away_goals": round(away_goals_pred, 1)
        }
    except Exception as e:
        print(f"Prediction error: {e}")
        return None

# API Configuration
API_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "your_api_key_here")
API_BASE_URL = "https://api.football-data.org/v4"

# Competition codes for Football-Data.org
PREMIER_LEAGUE_CODE = "PL"
CHAMPIONS_LEAGUE_CODE = "CL"

server = Server("soccer-stats")


async def make_api_request(endpoint: str, params: dict = None) -> dict:
    """Make a request to the Football-Data.org API"""
    headers = {
        "X-Auth-Token": API_KEY
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{API_BASE_URL}/{endpoint}",
                headers=headers,
                params=params,
                timeout=15.0
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e)}


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available tools with optimized descriptions"""
    return [
        types.Tool(
            name="get_live_matches",
            description=(
                "Get TODAY'S live match scores and schedules. "
                "Use this when the user asks about: "
                "- 'What games are on today?' "
                "- 'Any matches happening now?' "
                "- 'Live scores' "
                "- 'Today's fixtures' "
                "Shows: Live scores, finished matches, and upcoming kickoffs for today only."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "competition": {
                        "type": "string",
                        "enum": ["premier_league", "champions_league", "both"],
                        "description": "Which competition to check. Default: both",
                        "default": "both"
                    }
                }
            }
        ),
        types.Tool(
            name="get_fixtures",
            description=(
                "Get UPCOMING scheduled matches in the next 1-10 days. "
                "Use this when the user asks about: "
                "- 'Upcoming matches' "
                "- 'Next fixtures' "
                "- 'What games are coming up?' "
                "- 'Schedule for next week' "
                "Do NOT use for today's matches (use get_live_matches instead)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "competition": {
                        "type": "string",
                        "enum": ["premier_league", "champions_league", "both"],
                        "description": "Which competition",
                        "default": "both"
                    },
                    "days_ahead": {
                        "type": "number",
                        "description": "Number of days to look ahead (1-10). Default: 7 days",
                        "default": 7,
                        "minimum": 1,
                        "maximum": 10
                    }
                },
                "required": ["competition"]
            }
        ),
        types.Tool(
            name="get_standings",
            description=(
                "Get the CURRENT Premier League table with positions, points, and goal difference. "
                "Use this when the user asks about: "
                "- 'Premier League table' "
                "- 'Who's top of the league?' "
                "- 'League standings' "
                "- 'Where is [team] in the table?' "
                "Shows: Full league table from 1st to 20th place."
            ),
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        types.Tool(
            name="get_team_matches",
            description=(
                "Get recent PAST matches and upcoming FUTURE matches for a SPECIFIC team. "
                "Use this when the user asks about: "
                "- '[Team]'s recent matches' "
                "- 'How has [team] been doing?' "
                "- '[Team] fixtures' "
                "- 'Show me [team]'s schedule' "
                "Shows: Both completed matches (with scores) and scheduled matches (with dates)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "team_name": {
                        "type": "string",
                        "description": (
                            "Name of the team. Examples: 'Arsenal', 'Manchester City', 'Liverpool', 'Chelsea'. "
                            "Partial names work (e.g., 'City' will find Manchester City)"
                        )
                    },
                    "num_matches": {
                        "type": "number",
                        "description": "Number of matches to show (default: 5, max: 20)",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 20
                    }
                },
                "required": ["team_name"]
            }
        ),
        types.Tool(
            name="get_top_scorers",
            description=(
                "Get the TOP GOAL SCORERS in the Premier League this season. "
                "Use this when the user asks about: "
                "- 'Top scorers' "
                "- 'Who's leading the golden boot race?' "
                "- 'Who has the most goals?' "
                "- 'Best strikers this season' "
                "Shows: Player name, team, and total goals."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "number",
                        "description": "Number of top scorers to show (default: 10, max: 20)",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 20
                    }
                }
            }
        ),
        types.Tool(
            name="predict_match",
            description=(
                "Use MACHINE LEARNING to predict the outcome of a future match between two teams. "
                "Use this when the user asks about: "
                "- 'Who will win [Team A] vs [Team B]?' "
                "- 'Predict [match]' "
                "- 'What are the chances of [team] winning?' "
                "- 'Expected score for [match]' "
                "Provides: Win/draw/loss probabilities, expected goals, team form analysis, and confidence level. "
                "Based on: Recent form (last 5 matches), goals scored/conceded, and historical patterns."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "home_team": {
                        "type": "string",
                        "description": (
                            "Home team name (the team playing at their stadium). "
                            "Examples: 'Arsenal', 'Manchester United', 'Liverpool'"
                        )
                    },
                    "away_team": {
                        "type": "string",
                        "description": (
                            "Away team name (the visiting team). "
                            "Examples: 'Manchester City', 'Chelsea', 'Tottenham'"
                        )
                    }
                },
                "required": ["home_team", "away_team"]
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(
        name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool execution requests"""

    if name == "get_live_matches":
        competition = arguments.get("competition", "both")
        codes = []

        if competition in ["premier_league", "both"]:
            codes.append(PREMIER_LEAGUE_CODE)
        if competition in ["champions_league", "both"]:
            codes.append(CHAMPIONS_LEAGUE_CODE)

        today = datetime.now().date()
        results = []

        for code in codes:
            data = await make_api_request(
                f"competitions/{code}/matches",
                {"dateFrom": today.isoformat(), "dateTo": today.isoformat()}
            )

            if "matches" in data and data["matches"]:
                comp_name = "Premier League" if code == PREMIER_LEAGUE_CODE else "Champions League"
                results.append(f"\n⚽ {comp_name} - Today's Matches:")

                for match in data["matches"]:
                    home = match["homeTeam"]["name"]
                    away = match["awayTeam"]["name"]
                    status = match["status"]
                    score = match.get("score", {})

                    if status == "IN_PLAY" or status == "PAUSED":
                        home_score = score.get("fullTime", {}).get("home") or 0
                        away_score = score.get("fullTime", {}).get("away") or 0
                        results.append(f"  🔴 LIVE: {home} {home_score} - {away_score} {away}")
                    elif status == "FINISHED":
                        home_score = score.get("fullTime", {}).get("home")
                        away_score = score.get("fullTime", {}).get("away")
                        results.append(f"  ✅ FT: {home} {home_score} - {away_score} {away}")
                    else:
                        match_time = datetime.fromisoformat(match["utcDate"].replace("Z", "+00:00"))
                        results.append(f"  ⏰ {match_time.strftime('%H:%M')}: {home} vs {away}")

        if not results:
            return [types.TextContent(type="text", text="No matches scheduled for today.")]

        return [types.TextContent(type="text", text="\n".join(results))]

    elif name == "get_fixtures":
        competition = arguments.get("competition", "both")
        days_ahead = min(arguments.get("days_ahead", 7), 10)  # Max 10 days

        codes = []
        if competition in ["premier_league", "both"]:
            codes.append(PREMIER_LEAGUE_CODE)
        if competition in ["champions_league", "both"]:
            codes.append(CHAMPIONS_LEAGUE_CODE)

        today = datetime.now().date()
        end_date = today + timedelta(days=days_ahead)

        results = []
        for code in codes:
            data = await make_api_request(
                f"competitions/{code}/matches",
                {
                    "dateFrom": today.isoformat(),
                    "dateTo": end_date.isoformat(),
                    "status": "SCHEDULED"
                }
            )

            if "matches" in data and data["matches"]:
                comp_name = "Premier League" if code == PREMIER_LEAGUE_CODE else "Champions League"
                results.append(f"\n📅 {comp_name} - Upcoming Fixtures:")

                for match in data["matches"][:10]:  # Limit to 10 matches
                    home = match["homeTeam"]["name"]
                    away = match["awayTeam"]["name"]
                    match_date = datetime.fromisoformat(match["utcDate"].replace("Z", "+00:00"))
                    results.append(
                        f"  {match_date.strftime('%b %d, %H:%M')} - {home} vs {away}"
                    )

        if not results:
            return [types.TextContent(type="text", text="No upcoming fixtures found.")]

        return [types.TextContent(type="text", text="\n".join(results))]

    elif name == "get_standings":
        data = await make_api_request(f"competitions/{PREMIER_LEAGUE_CODE}/standings")

        if "standings" in data and data["standings"]:
            table = data["standings"][0]["table"]
            results = ["🏆 Premier League Standings (Current Season):\n"]

            for team in table:
                pos = team["position"]
                name = team["team"]["name"]
                points = team["points"]
                played = team["playedGames"]
                gd = team["goalDifference"]

                results.append(
                    f"{pos}. {name} - {points} pts ({played} played, GD: {gd:+d})"
                )

            return [types.TextContent(type="text", text="\n".join(results))]

        return [types.TextContent(type="text", text="Could not fetch standings.")]

    elif name == "get_team_matches":
        team_name = arguments["team_name"]
        num_matches = arguments.get("num_matches", 5)

        # Search for team in Premier League
        teams_data = await make_api_request(f"competitions/{PREMIER_LEAGUE_CODE}/teams")

        if "teams" not in teams_data:
            return [types.TextContent(type="text", text=f"Could not find team '{team_name}'.")]

        team = None
        for t in teams_data["teams"]:
            if team_name.lower() in t["name"].lower():
                team = t
                break

        if not team:
            return [types.TextContent(type="text", text=f"Team '{team_name}' not found in Premier League.")]

        team_id = team["id"]

        # Get team matches
        matches_data = await make_api_request(f"teams/{team_id}/matches")

        if "matches" in matches_data:
            results = [f"📊 Recent and Upcoming Matches for {team['name']}:\n"]

            for match in matches_data["matches"][:num_matches]:
                home = match["homeTeam"]["name"]
                away = match["awayTeam"]["name"]
                status = match["status"]
                match_date = datetime.fromisoformat(match["utcDate"].replace("Z", "+00:00"))

                if status == "FINISHED":
                    score = match.get("score", {}).get("fullTime", {})
                    home_score = score.get("home")
                    away_score = score.get("away")
                    results.append(
                        f"  {match_date.strftime('%b %d')}: {home} {home_score} - {away_score} {away}"
                    )
                else:
                    results.append(
                        f"  {match_date.strftime('%b %d, %H:%M')}: {home} vs {away}"
                    )

            return [types.TextContent(type="text", text="\n".join(results))]

        return [types.TextContent(type="text", text="Could not fetch team matches.")]

    elif name == "get_head_to_head":
        team1_id = arguments["team1_id"]
        team2_id = arguments["team2_id"]

        data = await make_api_request(
            f"matches",
            {
                "team1": team1_id,
                "team2": team2_id,
                "limit": 10
            }
        )

        if "matches" in data and data["matches"]:
            results = ["⚔️ Head-to-Head:\n"]

            for match in data["matches"]:
                if match["status"] == "FINISHED":
                    home = match["homeTeam"]["name"]
                    away = match["awayTeam"]["name"]
                    score = match.get("score", {}).get("fullTime", {})
                    home_score = score.get("home")
                    away_score = score.get("away")
                    match_date = datetime.fromisoformat(match["utcDate"].replace("Z", "+00:00"))

                    results.append(
                        f"  {match_date.strftime('%Y-%m-%d')}: {home} {home_score} - {away_score} {away}"
                    )

            if len(results) == 1:
                results.append("  No head-to-head matches found")

            return [types.TextContent(type="text", text="\n".join(results))]

        return [types.TextContent(type="text", text="Could not fetch head-to-head data.")]

    elif name == "get_team_id":
        team_name = arguments["team_name"]

        # Search in Premier League
        teams_data = await make_api_request(f"competitions/{PREMIER_LEAGUE_CODE}/teams")

        if "teams" in teams_data:
            results = [f"🔍 Search results for '{team_name}':\n"]

            for team in teams_data["teams"]:
                if team_name.lower() in team["name"].lower():
                    results.append(f"  {team['name']} - ID: {team['id']}")

            if len(results) == 1:
                results.append("  No teams found")

            return [types.TextContent(type="text", text="\n".join(results))]

        return [types.TextContent(type="text", text="Could not search for teams.")]

    elif name == "get_top_scorers":
        limit = arguments.get("limit", 10)

        data = await make_api_request(f"competitions/{PREMIER_LEAGUE_CODE}/scorers")

        if "scorers" in data:
            results = ["⚽ Premier League Top Scorers (Current Season):\n"]

            for i, scorer in enumerate(data["scorers"][:limit], 1):
                player = scorer["player"]["name"]
                team = scorer["team"]["name"]
                goals = scorer["goals"]

                results.append(f"{i}. {player} ({team}) - {goals} goals")

            return [types.TextContent(type="text", text="\n".join(results))]

        return [types.TextContent(type="text", text="Could not fetch top scorers.")]
    elif name == "predict_match":
        home_team = arguments["home_team"]
        away_team = arguments["away_team"]

        # Load ML models
        models = load_ml_models()

        if models is None:
            return [types.TextContent(
                type="text",
                text="❌ ML models not available. Please run:\n"
                     "   1. python collect_training_data.py\n"
                     "   2. python train_model.py"
            )]

        # Get team statistics
        home_stats = await calculate_team_stats(home_team)
        away_stats = await calculate_team_stats(away_team)

        if home_stats is None or away_stats is None:
            return [types.TextContent(
                type="text",
                text=f"❌ Could not find one or both teams in Premier League.\n"
                     f"   Home: {home_team}\n"
                     f"   Away: {away_team}"
            )]

        # Get head-to-head stats
        h2h_stats = await get_h2h_stats(home_team, away_team)

        # Make prediction
        prediction = predict_match_ml(home_stats, away_stats, h2h_stats, models)

        if prediction is None:
            return [types.TextContent(
                type="text",
                text="❌ Error making prediction. Check models are trained correctly."
            )]

        # Format output
        result_emoji = {
            "HOME_WIN": "🏠",
            "DRAW": "🤝",
            "AWAY_WIN": "✈️"
        }

        emoji = result_emoji.get(prediction["predicted_result"], "⚽")

        results = [
            f"🔮 ML Match Prediction\n",
            f"{'=' * 50}\n",
            f"{home_stats['team_name']} vs {away_stats['team_name']}\n",
            f"\n📊 Most Likely Result: {emoji} {prediction['predicted_result'].replace('_', ' ')}\n",
            f"\n🎯 Win Probabilities:",
            f"   Home Win ({home_stats['team_name']}): {prediction['home_win_probability']:.1%}",
            f"   Draw: {prediction['draw_probability']:.1%}",
            f"   Away Win ({away_stats['team_name']}): {prediction['away_win_probability']:.1%}",
            f"\n⚽ Expected Goals:",
            f"   {home_stats['team_name']}: {prediction['predicted_home_goals']} goals",
            f"   {away_stats['team_name']}: {prediction['predicted_away_goals']} goals",
            f"\n📈 Team Form (last 5 matches):",
            f"   {home_stats['team_name']}: {home_stats['form']:.1%} form ({home_stats['wins']}W {home_stats['draws']}D {home_stats['losses']}L)",
            f"   {away_stats['team_name']}: {away_stats['form']:.1%} form ({away_stats['wins']}W {away_stats['draws']}D {away_stats['losses']}L)",
            f"\n💡 Confidence: {'High' if max(prediction['home_win_probability'], prediction['draw_probability'], prediction['away_win_probability']) > 0.6 else 'Moderate' if max(prediction['home_win_probability'], prediction['draw_probability'], prediction['away_win_probability']) > 0.45 else 'Low'}"
        ]

        return [types.TextContent(type="text", text="\n".join(results))]
    else:
        raise ValueError(f"Unknown tool: {name}")


async def main():
    """Run the MCP server"""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="soccer-stats",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())