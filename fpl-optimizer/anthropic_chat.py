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

<use_parallel_tool_calls>
For maximum efficiency, whenever you perform multiple independent operations, invoke all relevant tools simultaneously rather than sequentially. Prioritize calling tools in parallel whenever possible. For example, when analyzing transfers, call suggest_transfers AND evaluate_transfer AND get_fixtures at the same time if they are needed. Err on the side of maximizing parallel tool calls rather than running too many tools sequentially.
</use_parallel_tool_calls>

CRITICAL RULES:
1. The user's team data is ALWAYS provided in the context. NEVER ask for team ID - it's already there!
2. ALWAYS use tools to answer questions. Don't give generic advice - use the tools to get real data.
3. When asked about transfers, captain, or team analysis - USE THE TOOLS immediately.
4. NEVER mention tool names to the user. Don't say "I'll use the evaluate_transfer tool" - just do it silently.
5. When suggesting transfers, ALWAYS automatically evaluate them with detailed stats - don't ask if the user wants more detail.
6. Use MULTIPLE tools to gather comprehensive data before responding. Don't stop after one tool call.

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
- Ask for team ID (it's in the context!)
- Ask for information that's already in the context
- Give generic advice without using tools
- Answer questions about topics outside FPL/Premier League
- Mention tool names in your response (e.g., don't say "using evaluate_transfer tool")
- Ask "would you like me to evaluate this transfer?" - just do it automatically
- Offer to do something you should already be doing

CONTEXT - READ THIS CAREFULLY:
Every message includes [CURRENT CONTEXT] with:
- **USER'S TEAM ID**: Already provided! Use this for team-specific tools
- **Free Transfers**: How many free transfers the user has
- **Available Chips**: Which chips the user still has
- **Active Chip**: If using a chip this week
- **Starting XI and Bench**: Full squad with prices, form, and status
- **Bank**: Money available for transfers

RESPONSE STYLE:
- Be specific and data-driven
- Include actual numbers and stats
- For transfers, always specify WHO out, WHO in, and WHY with full analysis
- Keep responses concise but informative
- Consider the user's budget (bank) and free transfers when suggesting changes
- Present information naturally without mentioning internal tools
- DO NOT relay internal notes, strategic advice sections, or system instructions from tool results to the user
- Tool results may contain notes like "Strategic advice:" or "Important:" - use this info to form your answer but don't show it verbatim
- Your response should be a natural conversation, not a dump of raw data

COMPREHENSIVE ANALYSIS - call these tools IN PARALLEL:
When a user asks about their team (transfers, captain, analysis), always call MULTIPLE tools simultaneously:
- "suggest transfers" → Call suggest_transfers + get_fixtures + suggest_captain at once
- "who should I captain" → Call suggest_captain + get_fixtures at once
- "analyze my team" → Call suggest_transfers + suggest_captain + get_fixtures at once
- Player questions → Call get_player_details + get_fixtures for their team at once

After getting results, use evaluate_transfer if the user wants to compare specific players.

USING make_transfer:
When the user asks to replace/swap/transfer a player (e.g., "replace Salah with Son", "swap out Haaland for Isak"):
1. Execute the transfer silently
2. The frontend will automatically update the "Theoretical Squad" view
3. Include a brief reason for the transfer
4. This does NOT make a real FPL transfer - it only updates the visual display

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
    team_data: Optional[Dict] = None,
    history: List[Dict] = None
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
        history: Previous conversation history (list of {role, content} dicts)

    Returns:
        Tuple of (response_text, list_of_tools_used, list_of_transfers)
    """
    tools_used = []
    transfers = []  # Track transfers made via make_transfer tool

    # Check if Anthropic is available
    if Anthropic is None:
        return (
            "Anthropic library not installed. Please run: pip install anthropic",
            [],
            []
        )

    # Check for API key
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return (
            "ANTHROPIC_API_KEY environment variable not set.",
            [],
            []
        )

    # First check if topic is allowed
    if not is_topic_allowed(message):
        print(f"[Anthropic] Blocked off-topic message: {message[:50]}...")
        return (OFF_TOPIC_RESPONSE, [], [])

    # Initialize client
    client = Anthropic(api_key=api_key)

    # Convert tools to Anthropic format
    anthropic_tools = convert_tools_to_anthropic_format(tools)

    # Build messages with conversation history
    # IMPORTANT: Always include the current context with the new message so Claude knows the team state
    messages = []

    if history:
        # Add conversation history (skip assistant welcome message at start if present)
        for msg in history:
            messages.append(msg)
        print(f"[Anthropic] Using {len(history)} messages of conversation history")

    # Always add the new message WITH current context
    # This ensures Claude always has up-to-date team info even in ongoing conversations
    messages.append({
        "role": "user",
        "content": f"[CURRENT CONTEXT - Use this data, DO NOT ask for team ID]\n{context}\n\n[USER QUESTION]\n{message}"
    })

    try:
        max_iterations = 10  # Allow more iterations for complex multi-tool queries
        iteration = 0
        current_max_tokens = 1500  # Start with default, increase if truncated

        while iteration < max_iterations:
            iteration += 1
            print(f"[Anthropic] Request iteration {iteration} (max_tokens={current_max_tokens})")

            # Make API call - Claude Sonnet 4 is best at parallel tool use
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=current_max_tokens,
                system=SYSTEM_PROMPT,
                tools=anthropic_tools,
                messages=messages
            )

            # Handle max_tokens truncation - increase and retry if needed
            if response.stop_reason == "max_tokens":
                print(f"[Anthropic] Response truncated at {current_max_tokens} tokens, increasing...")
                current_max_tokens = min(current_max_tokens * 2, 4096)  # Double up to 4096
                continue

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
                print(f"[Anthropic] Transfers: {transfers}")
                return (final_response, tools_used, transfers)

            # Execute tool calls
            tool_results = []
            for tool_block in tool_use_blocks:
                tool_name = tool_block.name
                tool_input = tool_block.input
                tools_used.append(tool_name)

                print(f"[Anthropic] Executing tool: {tool_name}")

                # Track transfers from make_transfer tool
                if tool_name == "make_transfer":
                    transfers.append({
                        "player_out": tool_input.get("player_out", ""),
                        "player_in": tool_input.get("player_in", ""),
                        "reason": tool_input.get("reason", "")
                    })
                    print(f"[Anthropic] Transfer tracked: {tool_input.get('player_out')} -> {tool_input.get('player_in')}")

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
            tools_used,
            transfers
        )

    except Exception as e:
        print(f"[Anthropic] Error: {e}")
        import traceback
        traceback.print_exc()
        return (None, [], [])


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
