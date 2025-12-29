"""
Anthropic Claude Integration for FPL Chatbot

This module replaces Ollama with Anthropic's Claude API for the chatbot feature.
Includes topic restriction to only allow FPL-related questions.
"""

import os
from typing import Dict, List, Optional, Any, Callable, Awaitable

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

# Allowed topics for the chatbot - must be FPL related
ALLOWED_TOPICS = [
    # FPL specific
    "fantasy premier league", "fpl", "fantasy football", "gameweek", "gw",
    "transfers", "transfer", "captain", "vice captain", "bench", "lineup",
    "wildcard", "free hit", "bench boost", "triple captain", "chips",
    "points", "bonus", "clean sheet", "assist", "goal",

    # Football/Soccer
    "premier league", "football", "soccer", "match", "fixture", "fixtures",
    "team", "player", "players", "squad", "formation",

    # Stats
    "xg", "expected goals", "xa", "expected assists", "form", "price",
    "value", "stats", "statistics", "performance", "ownership",
    "selected by", "transfers in", "transfers out",

    # Teams (Premier League)
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton",
    "chelsea", "crystal palace", "everton", "fulham", "ipswich",
    "leicester", "liverpool", "manchester city", "manchester united", "man city", "man utd",
    "newcastle", "nottingham forest", "southampton", "tottenham", "spurs",
    "west ham", "wolves", "wolverhampton",

    # Project related
    "this project", "portfolio", "how this works", "features", "what can you do",
    "help", "commands", "tools", "optimization", "optimizer", "predict", "prediction"
]

# Off-topic phrases that should be rejected
OFF_TOPIC_PHRASES = [
    "how far is", "what is the distance", "tell me about the",
    "calculate", "what year was", "where is", "who invented",
    "help me code", "write a function", "write code", "explain quantum",
    "what's the weather", "recipe for", "how to cook",
    "history of", "capital of", "population of",
    "translate", "meaning of life", "joke about",
    "write a poem", "write a story", "creative writing"
]

# System prompt for Claude
SYSTEM_PROMPT = """You are an expert Fantasy Premier League (FPL) assistant for a portfolio project.

STRICT TOPIC RESTRICTIONS:
You ONLY answer questions about:
1. Fantasy Premier League (FPL) - transfers, captains, chips, points, strategy
2. Premier League football - players, teams, fixtures, stats
3. This portfolio project - features, how it works, what tools are available

If asked about ANYTHING else (general knowledge, coding help, math, science, history, personal questions, etc.),
you MUST respond ONLY with:
"I'm specifically designed to help with FPL (Fantasy Premier League) questions and this portfolio project.
Please ask about players, transfers, captain picks, fixture analysis, or how to use this tool!"

NEVER:
- Answer questions about topics outside FPL/Premier League
- Pretend to be a general assistant
- Provide coding help (unless about this project's features)
- Answer math questions unrelated to FPL calculations
- Discuss news not related to Premier League

RESPONSE STYLE:
- Be specific and data-driven
- Include actual numbers and stats from tools
- For transfers, always specify WHO out, WHO in, and WHY
- Keep responses concise but informative

AVAILABLE TOOLS:
You have access to real FPL data through these tools:
- get_all_players: Filter/sort all players by position, price, form
- get_player_details: Deep stats for a specific player (xG, xA, defensive stats)
- get_fixtures: Upcoming fixtures with difficulty ratings
- get_my_team: User's FPL team details
- get_top_players: Top performers by metric
- evaluate_transfer: Compare specific transfers
- optimize_squad: Build optimal squad
- optimize_lineup: Best starting 11
- suggest_captain: Captain recommendations
- suggest_transfers: Transfer recommendations
- compare_players: Side-by-side comparison
- analyze_team_fixtures: Fixture difficulty rankings
- get_chip_strategy: Chip timing advice

Always use tools to get real data - never make up statistics!"""

# Response for off-topic questions
OFF_TOPIC_RESPONSE = (
    "I'm specifically designed to help with FPL (Fantasy Premier League) questions "
    "and this portfolio project. Please ask about players, transfers, captain picks, "
    "fixture analysis, or how to use this tool!"
)


def is_topic_allowed(message: str) -> bool:
    """
    Check if the message is about an allowed topic (FPL/Premier League).

    Returns True if the topic is allowed, False otherwise.
    """
    message_lower = message.lower()

    # First check for explicit off-topic indicators
    for phrase in OFF_TOPIC_PHRASES:
        if phrase in message_lower:
            # Double-check it's not actually FPL-related
            if not any(topic in message_lower for topic in ALLOWED_TOPICS):
                return False

    # Very short messages are usually greetings or simple queries - allow them
    if len(message_lower.split()) <= 3:
        return True

    # Check if any allowed topic is mentioned
    for topic in ALLOWED_TOPICS:
        if topic in message_lower:
            return True

    # Check for common FPL question patterns
    fpl_patterns = [
        "who should i", "should i transfer", "best captain",
        "who to captain", "best players", "top scorers",
        "cheap", "budget", "premium", "differential",
        "this week", "next week", "upcoming", "form"
    ]

    for pattern in fpl_patterns:
        if pattern in message_lower:
            return True

    # If no allowed topics found and message is substantial, likely off-topic
    # But give benefit of the doubt for shorter messages
    if len(message_lower.split()) > 8:
        return False

    return True


def convert_tools_to_anthropic_format(tools: List[Dict]) -> List[Dict]:
    """
    Convert OpenAI-style tool definitions to Anthropic format.
    """
    anthropic_tools = []

    for tool in tools:
        func = tool.get("function", {})
        anthropic_tools.append({
            "name": func.get("name"),
            "description": func.get("description"),
            "input_schema": func.get("parameters", {"type": "object", "properties": {}})
        })

    return anthropic_tools


async def query_anthropic(
    message: str,
    context: str,
    tools: List[Dict],
    execute_tool_func: Callable[[str, Dict, List[Dict], Dict, Optional[Dict]], Awaitable[str]],
    players: List[Dict] = None,
    teams: Dict = None,
    team_data: Optional[Dict] = None
) -> tuple:
    """
    Query Anthropic Claude with tool calling support.

    Args:
        message: User's message
        context: Context about user's team
        tools: List of tool definitions (OpenAI format)
        execute_tool_func: Async function to execute tools
        players: List of player data
        teams: Dict of team data
        team_data: User's team data (optional)

    Returns:
        Tuple of (response_text, list_of_tools_used)
    """
    tools_used = []

    # Check if Anthropic is available
    if Anthropic is None:
        return (
            "Anthropic library not installed. Please run: pip install anthropic",
            []
        )

    # Check for API key
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return (
            "ANTHROPIC_API_KEY environment variable not set.",
            []
        )

    # First check if topic is allowed
    if not is_topic_allowed(message):
        print(f"[Anthropic] Blocked off-topic message: {message[:50]}...")
        return (OFF_TOPIC_RESPONSE, [])

    # Initialize client
    client = Anthropic(api_key=api_key)

    # Convert tools to Anthropic format
    anthropic_tools = convert_tools_to_anthropic_format(tools)

    # Build messages
    messages = [
        {
            "role": "user",
            "content": f"Context about user's team:\n{context}\n\nUser question: {message}"
        }
    ]

    try:
        max_iterations = 5
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            print(f"[Anthropic] Request iteration {iteration}")

            # Make API call
            response = client.messages.create(
                model="claude-3-haiku-20240307",  # Fast and cheap
                max_tokens=1500,
                system=SYSTEM_PROMPT,
                tools=anthropic_tools,
                messages=messages
            )

            # Check for tool use
            tool_use_blocks = [
                block for block in response.content
                if block.type == "tool_use"
            ]

            # If no tool calls, extract text response
            if not tool_use_blocks:
                text_blocks = [
                    block.text for block in response.content
                    if hasattr(block, 'text')
                ]
                final_response = "\n".join(text_blocks)
                print(f"[Anthropic] Final response: {len(final_response)} chars")
                print(f"[Anthropic] Tools used: {tools_used}")
                return (final_response, tools_used)

            # Execute tool calls
            tool_results = []
            for tool_block in tool_use_blocks:
                tool_name = tool_block.name
                tool_input = tool_block.input
                tools_used.append(tool_name)

                print(f"[Anthropic] Executing tool: {tool_name}")

                # Execute the tool
                result = await execute_tool_func(
                    tool_name,
                    tool_input,
                    players or [],
                    teams or {},
                    team_data
                )

                # Log tool output
                print(f"[Anthropic] Tool {tool_name} returned {len(result)} chars")

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": result
                })

            # Add assistant response and tool results to messages
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        # Max iterations reached
        print("[Anthropic] Max iterations reached")
        return (
            "I apologize, but I had trouble processing that request. Please try again with a simpler question.",
            tools_used
        )

    except Exception as e:
        print(f"[Anthropic] Error: {e}")
        import traceback
        traceback.print_exc()
        return (None, [])


# For testing topic filtering
if __name__ == "__main__":
    test_messages = [
        "Who should I captain this week?",  # Allowed
        "Best midfielders under 8m?",  # Allowed
        "How far is the sun from earth?",  # Blocked
        "Write me a Python function",  # Blocked
        "What's Salah's form?",  # Allowed
        "Tell me a joke",  # Blocked
        "Arsenal fixtures",  # Allowed
        "What is the meaning of life?",  # Blocked
    ]

    print("Topic Filter Test:")
    print("-" * 50)
    for msg in test_messages:
        allowed = is_topic_allowed(msg)
        status = "ALLOWED" if allowed else "BLOCKED"
        print(f"[{status}] {msg}")
