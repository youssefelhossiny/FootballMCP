#!/usr/bin/env python3
"""
Autonomous gameweek decision — Claude tool-loop, structured output.

## Why this exists

There were two brains in this project and they shared nothing.

`bot_decision_maker.make_decision()` — the one that would actually run
unattended every gameweek — is hand-written arithmetic:

    captain score = (form * 3 + fixture_score) * position_weight   (:994)
    replacement   = max(form * 2 + (5 - avg_difficulty) * 1.5)     (:943)
    lineup_changes = []   # TODO: Implement lineup optimization    (:1105)

It contains **no reference** to `ml_predict_v2`, `points_model_v2.pkl`,
`search_player_news`, or `get_team_news`. So the retrained model that measured
+1.52 pts/pick over a form heuristic, and the news tool that caught FPL listing
Doku at 75% while the press had him out for weeks, were both invisible to the
autonomous path. They only ever ran in the chat and in `/api/bot/initial-squad`.

This module closes that gap the cheap way: instead of re-implementing judgment
in Python, it points the autonomous path at the tool-loop the chat already
uses. `api_server.execute_tool` is a plain async function with no FastAPI
request coupling, so it is callable headlessly as-is — all 18 tools, including
ML and live news, with no duplication.

## The division of labour (deliberate — do not "improve" this)

The LP optimizer stays deterministic. Constraint satisfaction (£100.0m, 3 per
club, valid formation) is provably optimal in PuLP and an LLM does it worse.
The agent owns only the **judgment** layer above it: reading team-news prose,
weighing "FPL says 75% but the press says out", captaincy risk, whether a hit
is worth taking. Deterministic code becomes the *tools*; the model decides.

## Why not just call query_anthropic()

Two reasons it is unsafe for unattended use:

1. It ends in `except Exception: return (None, [], [])`. In the chat that
   degrades to a rule-based fallback — which is exactly what hid a 404-ing
   retired model for months. At 2am with no human present, a swallowed failure
   becomes silence, and silence is indistinguishable from "no change needed".
   Here, failures raise `BotAgentError` and the caller downgrades to notify.
2. It returns prose. Prose cannot be fed to `fpl_auth.set_lineup` — that is how
   you get a wrong captain. This module forces a validated decision through a
   `submit_decision` tool instead.

## Safety

This module never writes to FPL. It returns a decision; `fpl_auth` (gated by
`FPL_BOT_MODE`, default `notify`) is the only thing that can submit one.
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional

try:
    from anthropic import Anthropic
except ImportError:  # pragma: no cover - import guard mirrors anthropic_chat
    Anthropic = None

AGENT_MODEL = os.getenv("ANTHROPIC_BOT_MODEL", os.getenv("ANTHROPIC_CHAT_MODEL", "claude-opus-5"))

# The agent gets more room than the chat: it must call news + ML + fixtures for
# a whole squad before deciding, and running out of iterations mid-deliberation
# is a failure, not a degraded answer.
MAX_ITERATIONS = int(os.getenv("BOT_AGENT_MAX_ITERATIONS", "24"))
MAX_TOKENS = int(os.getenv("BOT_AGENT_MAX_TOKENS", "8000"))


class BotAgentError(RuntimeError):
    """Raised when the agent cannot produce a decision. Never swallowed."""


# ---------------------------------------------------------------------------
# Decision shape
# ---------------------------------------------------------------------------

@dataclass
class TransferDecision:
    player_out_id: int
    player_out_name: str
    player_in_id: int
    player_in_name: str
    reason: str


@dataclass
class AgentDecision:
    """
    What the agent decided. Deliberately mirrors what `fpl_auth` consumes, so
    nothing has to re-parse prose on the write path.
    """
    gameweek: int
    run_type: str                      # "early" | "final"
    transfers: List[TransferDecision] = field(default_factory=list)
    captain_id: Optional[int] = None
    captain_name: str = ""
    vice_captain_id: Optional[int] = None
    vice_captain_name: str = ""
    # Element ids in FPL pick order: indices 0-10 start, 11-14 are the bench in
    # order. Empty means "no lineup change" — a legitimate outcome.
    lineup_order: List[int] = field(default_factory=list)
    chip: Optional[str] = None
    hit_taken: int = 0                 # points cost the agent accepted
    confidence: str = ""               # low | medium | high
    reasoning: str = ""
    availability_overrides: List[Dict] = field(default_factory=list)
    tools_used: List[str] = field(default_factory=list)
    # Token usage for the whole run, so cost is inspectable instead of a
    # surprise on the bill. `cache_read` should dominate `input` on a healthy
    # run; if it is 0 across iterations, caching silently broke.
    usage: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)

    def to_lineup_picks(self, squad_ids: List[int]) -> List[Dict]:
        """
        Convert to the 15 `{element, position, is_captain, is_vice_captain}`
        dicts `fpl_auth.set_lineup` wants.

        `squad_ids` is the post-transfer squad, used when the agent chose not to
        reorder — so an unchanged lineup still carries a captain change.
        """
        order = self.lineup_order or squad_ids
        if len(order) != 15:
            raise BotAgentError(
                f"Lineup needs exactly 15 elements, got {len(order)}. Refusing to build a payload."
            )
        if len(set(order)) != 15:
            raise BotAgentError("Lineup contains duplicate players. Refusing to build a payload.")
        if self.captain_id not in order:
            raise BotAgentError("Captain is not in the submitted squad.")
        if self.vice_captain_id not in order:
            raise BotAgentError("Vice-captain is not in the submitted squad.")
        if self.captain_id == self.vice_captain_id:
            raise BotAgentError("Captain and vice-captain are the same player.")
        return [
            {
                "element": element,
                "position": idx + 1,
                "is_captain": element == self.captain_id,
                "is_vice_captain": element == self.vice_captain_id,
            }
            for idx, element in enumerate(order)
        ]


# ---------------------------------------------------------------------------
# The submit_decision tool — how structure is enforced
# ---------------------------------------------------------------------------
# Rather than asking for JSON in prose and parsing it (brittle, and a malformed
# reply becomes a silent no-op), the decision is a *tool call*. The API
# validates it against this schema and the model retries on a mismatch.

SUBMIT_TOOL = {
    "name": "submit_decision",
    "description": (
        "Record your final decision for this gameweek. Call this exactly once, "
        "as your LAST action, after you have gathered evidence with the other tools. "
        "Do not call it before checking availability — a decision that ignores team news "
        "is worse than no decision."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "transfers": {
                "type": "array",
                "description": (
                    "Transfers to make. Empty list is a valid, often correct answer — "
                    "rolling a free transfer beats a marginal move."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "player_out_id": {"type": "integer", "description": "FPL element id to sell"},
                        "player_out_name": {"type": "string"},
                        "player_in_id": {"type": "integer", "description": "FPL element id to buy"},
                        "player_in_name": {"type": "string"},
                        "reason": {"type": "string", "description": "Why, citing the evidence you gathered"},
                    },
                    "required": ["player_out_id", "player_out_name", "player_in_id",
                                 "player_in_name", "reason"],
                },
            },
            "captain_id": {"type": "integer", "description": "FPL element id of the captain"},
            "captain_name": {"type": "string"},
            "vice_captain_id": {"type": "integer", "description": "Must differ from captain_id"},
            "vice_captain_name": {"type": "string"},
            "lineup_order": {
                "type": "array",
                "items": {"type": "integer"},
                "description": (
                    "All 15 element ids of the POST-transfer squad in FPL pick order: "
                    "first 11 start, last 4 are the bench in order. Omit entirely to leave "
                    "the current order untouched. Bench order is best-player-first."
                ),
            },
            "chip": {
                "type": "string",
                "enum": ["none", "wildcard", "freehit", "bboost", "3xc"],
                "description": "Chip to play, or 'none'.",
            },
            "hit_taken": {
                "type": "integer",
                "description": "Points hit you are accepting (0 if within free transfers).",
            },
            "confidence": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": (
                    "How much you trust this decision. Use 'low' honestly when sources "
                    "disagreed or news was thin — it gates whether the write happens."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": "Concise explanation a human can audit, naming the evidence used.",
            },
            "availability_overrides": {
                "type": "array",
                "description": (
                    "Players where live news CONTRADICTS FPL's chance_of_playing. This is the "
                    "point of the exercise — record every one you found, even if it did not "
                    "change your decision."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "player_name": {"type": "string"},
                        "fpl_chance": {"type": "integer", "description": "What FPL claims, 0-100"},
                        "verdict": {
                            "type": "string",
                            "enum": ["out", "doubtful", "likely_to_start", "starting"],
                            "description": "What the live sources actually indicate",
                        },
                        "source": {"type": "string", "description": "Where this came from"},
                    },
                    "required": ["player_name", "verdict", "source"],
                },
            },
        },
        "required": ["captain_id", "captain_name", "vice_captain_id", "vice_captain_name",
                     "confidence", "reasoning"],
    },
}


SYSTEM_PROMPT = """You are the autonomous decision-maker for a Fantasy Premier League team.

No human is watching. Whatever you decide may be submitted to FPL automatically, so a
careless decision is not corrected by anyone downstream. Be conservative and evidence-led.

YOUR JOB — and only this:
The squad optimizer is deterministic code and is already provably optimal at constraint
satisfaction (budget, 3-per-club, formation). You do NOT redo its arithmetic. You own the
JUDGMENT it cannot do: reading team-news prose, resolving contradictions between sources,
judging captaincy risk, and deciding whether a move is worth a points hit.

THE ONE THING THAT MATTERS MOST:
FPL's own `chance_of_playing` is hand-updated and goes stale. It has listed a player at 75%
while the press had him out for weeks. The deterministic builder trusts that number, which is
exactly the blind spot you exist to cover. So:
- For EVERY player you are considering starting, captaining, or buying, and every player
  already in the XI who carries any doubt flag, verify availability against live sources.
- Use get_team_news and get_injury_report first (fast, cover everyone).
- Then use search_player_news for the handful where sources disagree or a partial doubt
  (25/50/75%) appears. It runs real web searches, so it is slow — use it on players you are
  actually deciding on, not for browsing.
- When live news contradicts FPL, TRUST THE LIVE NEWS and record it in availability_overrides.

HOW FPL AUTO-SUBSTITUTION CHANGES THE MATH (get this right — it is counter-intuitive):
If a starter plays 0 minutes, FPL automatically substitutes the first eligible bench player.
Therefore starting a doubtful player is FREE UPSIDE: you get his points if he plays, and an
auto-sub if he does not. NEVER bench a doubtful player to "protect" against a blank — that
only guarantees you lose his points. For the same reason, bench order is BEST-PLAYER-FIRST,
not worst-first. Only transfer a doubtful player out if he is genuinely ruled out for multiple
gameweeks AND the replacement is a clear upgrade.

Buying and starting are different bars. Do not buy a player who is 50/50 to feature; DO start
one you already own, per the auto-sub logic above.

USING get_ml_prediction:
Predicted points for the next gameweek plus a start probability, trained on real per-gameweek
outcomes across three seasons. Its top picks historically averaged ~1.5 points more per pick
than a recent-form heuristic, so it is a genuinely useful RANKING signal — but it
under-predicts big hauls, so never quote its number as a precise forecast, and never let it
override clear injury news. It is one advisor among several.

PLAN OVER A HORIZON, NOT JUST THE NEXT DEADLINE:
Three different decisions have three different horizons, and confusing them is a classic error.
- **Captain and lineup: THIS gameweek only.** They reset every week, so future fixtures are
  irrelevant to them. Never captain someone for next week's fixture.
- **Transfers: the next 3-5 gameweeks.** A transfer persists, so a player with one good fixture
  followed by four hard ones is usually a bad buy. Call get_fixtures or analyze_team_fixtures
  (both look ahead 5 by default) before committing, and say in your reasoning what the incoming
  player's run actually looks like.
- **Chips: the whole horizon.** Only play one when the fixtures justify it now rather than later.

Watch for these specifically, since they only appear when you look forward:
- **Blanks and doubles.** A player with no fixture in the target gameweek scores nothing; a team
  playing twice is worth far more. Check the fixture list for teams missing from the target GW.
- **Fixture swings.** A team's run turning hard right after this week makes a transfer in bad
  value even if this week's fixture is easy — and makes a transfer OUT more attractive.
- **The ML prediction covers ONE gameweek only.** It is silent about the four after it, so never
  let it stand in for a fixture run. Pair it with the fixture tools.

USING get_squad_strategy — this is your FPL expertise, use it before transfers:
It returns the structural analysis the raw tools cannot: which teams are best placed for CLEAN
SHEETS (fixture softness combined with defensive strength), budget ROTATION PAIRS whose good
fixtures fall in different gameweeks, VALUE by points-per-million, xG BARGAINS and REGRESSION
RISKS. Reason with it; do not copy it.
- **Clean sheets need both a soft run AND a real defence.** A good defender facing a hard fixture
  is unlikely to keep one — that is exactly when his rotation partner should start instead.
- **Rotation pairs are how you cover a whole fixture run cheaply.** Two budget defenders from
  clubs whose easy fixtures alternate lets you field a good fixture every week for ~£8.5m.
- **Overperforming xG is a WARNING, not a buy signal.** Goals already banked do not repeat unless
  the underlying numbers support them; that player's price is inflated by finishing luck.
  Underperforming on high xG+xA per 90 is the real bargain — the chances are there.
- **Spend on the pitch, not the bench.** Money not spent on the bench upgrades a starter. But the
  bench must still PLAY: a substitute who never features is not cover for an injury or a brutal
  fixture. Cheap AND playing, not just cheap.

TRANSFERS — the bar is high:
- Rolling a free transfer is often correct. An empty transfer list is a real answer, not a
  failure to decide.
- Only take a points hit when the expected gain clearly exceeds the cost. State the arithmetic.
- Never transfer purely on recent form; check fixtures and underlying numbers over the next
  3-5 gameweeks, not just the one you are deciding for.

CAPTAINCY:
Weigh fixture, minutes certainty and ceiling — for THIS gameweek's fixture only. Certainty of
starting matters more than a marginally higher projection — a captain who does not play costs
you double.

CONFIDENCE — report it honestly:
Your confidence value gates whether a write happens. Say 'low' when news was thin, sources
disagreed, or you could not verify a key player. Overstating confidence to seem decisive is
the single worst thing you can do here. Understating it is nearly free.

PROCESS:
1. Read the squad in the context below.
2. Call tools in PARALLEL where independent (team news + injuries + ML + fixtures +
   get_squad_strategy at once).
3. Follow up with search_player_news on genuinely uncertain players.
4. Decide, then call submit_decision EXACTLY ONCE as your final action.

Use real element ids from the context and tool results — never invent one. If you cannot
verify something important, lower your confidence and say so in your reasoning."""


def _build_agent_prompt(
    gameweek: int,
    run_type: str,
    context: str,
    free_transfers: int,
    available_chips: List[str],
) -> str:
    """The task message. Kept separate from the system prompt so the run-type
    gating is explicit and auditable rather than buried in a template."""
    if run_type == "early":
        timing = (
            "This is the EARLY run, shortly after the previous gameweek's matches and before "
            "tonight's price changes. Its ONLY purpose is to act on a transfer whose timing is "
            "price-sensitive — a player you were going to buy anyway who is about to rise, or "
            "one you were going to sell who is about to fall.\n"
            "- Do NOT set a captain or play a chip now. More team news arrives before the deadline "
            "and deciding early throws that information away.\n"
            "- If no transfer is BOTH merited on merit AND urgent on price, submit an empty "
            "transfer list. That is the expected outcome most weeks.\n"
            "- Still report captain_id/vice_captain_id as the CURRENT ones (unchanged) — they are "
            "required fields, and the final run will decide properly."
        )
    else:
        timing = (
            "This is the FINAL run, 1-2 hours before the deadline. This is the real decision: "
            "transfers, captain, vice-captain, bench order and chip all commit now. Press "
            "conferences have happened, so team news is at its most reliable — use it."
        )

    return f"""[TARGET GAMEWEEK] {gameweek} — the deadline you are deciding for. Captain and
lineup apply to GW{gameweek} alone. The fixture tools list GW{gameweek} first, then the
gameweeks after it, so use that forward run when judging transfers.
[RUN TYPE] {run_type}
[FREE TRANSFERS] {free_transfers}
[AVAILABLE CHIPS] {', '.join(available_chips) if available_chips else 'none'}

[TIMING RULES]
{timing}

[CURRENT SQUAD AND CONTEXT]
{context}

Work through your process now. Verify availability before deciding, then call
submit_decision exactly once."""


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------

async def run_agent_decision(
    gameweek: int,
    context: str,
    tools: List[Dict],
    execute_tool_func: Callable[..., Any],
    players: Optional[List[Dict]] = None,
    teams: Optional[Dict] = None,
    team_data: Optional[Dict] = None,
    run_type: str = "final",
    free_transfers: int = 1,
    available_chips: Optional[List[str]] = None,
    api_key: Optional[str] = None,
) -> AgentDecision:
    """
    Run the autonomous decision loop and return a validated decision.

    Takes the same `tools` / `execute_tool_func` the chat endpoint passes to
    `query_anthropic`, so the agent and the chat share one tool set by
    construction — they cannot drift apart.

    Raises `BotAgentError` on any failure. This is deliberate: the caller must
    downgrade to notify-only rather than proceed on a half-formed decision.
    """
    if Anthropic is None:
        raise BotAgentError("anthropic package not installed — cannot run the agent.")

    key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise BotAgentError("ANTHROPIC_API_KEY not set — cannot run the agent.")

    if run_type not in ("early", "final"):
        raise BotAgentError(f"run_type must be 'early' or 'final', got {run_type!r}")

    client = Anthropic(api_key=key)

    # Reuse the chat's OpenAI->Anthropic conversion so tool defs stay in one place.
    from anthropic_chat import convert_tools_to_anthropic_format

    agent_tools = convert_tools_to_anthropic_format(tools)
    # make_transfer only mutates the frontend's theoretical squad — meaningless
    # here, and an agent that "makes" a transfer via it would think it had acted.
    agent_tools = [t for t in agent_tools if t.get("name") != "make_transfer"]
    agent_tools.append(SUBMIT_TOOL)

    # Prompt caching. Render order is tools -> system -> messages, and the cache
    # is a PREFIX match, so a breakpoint on the last tool covers the whole tool
    # block, and one on the system prompt covers tools+system. Both are
    # byte-identical on every iteration of this loop, which makes them ~5,100
    # tokens of otherwise-repeated billing per call.
    #
    # This matters far more here than in the chat: an agentic loop resends the
    # entire history every turn, so input grows each iteration (measured on the
    # 2026-08-21 run: 6.3k tokens on call 1, 27.6k on call 9, ~145k total across
    # 9 calls — input was ~80% of the run's cost). Caching the stable prefix plus
    # the append-only history turns most of that into 0.1x reads.
    cached_tools = [dict(t) for t in agent_tools]
    cached_tools[-1] = {**cached_tools[-1], "cache_control": {"type": "ephemeral"}}
    agent_tools = cached_tools

    cached_system = [{
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},
    }]

    messages: List[Dict] = [{
        "role": "user",
        "content": _build_agent_prompt(
            gameweek, run_type, context, free_transfers, available_chips or []
        ),
    }]

    # Tracks what caching actually achieved, so a regression is visible rather
    # than assumed. Verified via usage.cache_read_input_tokens, not by faith.
    usage_totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}

    tools_used: List[str] = []
    submitted: Optional[Dict] = None

    for iteration in range(1, MAX_ITERATIONS + 1):
        try:
            response = client.messages.create(
                model=AGENT_MODEL,
                max_tokens=MAX_TOKENS,
                system=cached_system,
                tools=agent_tools,
                messages=messages,
            )
        except Exception as e:
            # Loud on purpose. A swallowed API error here is how the chat served
            # rule-based fallbacks against a retired model for months.
            raise BotAgentError(f"Anthropic API call failed on iteration {iteration}: {e}") from e

        u = getattr(response, "usage", None)
        if u is not None:
            usage_totals["input"] += getattr(u, "input_tokens", 0) or 0
            usage_totals["output"] += getattr(u, "output_tokens", 0) or 0
            usage_totals["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
            usage_totals["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        if not tool_use_blocks:
            if response.stop_reason == "max_tokens":
                raise BotAgentError(
                    f"Agent response truncated at {MAX_TOKENS} tokens without a decision."
                )
            text = " ".join(b.text for b in response.content if hasattr(b, "text"))
            raise BotAgentError(
                "Agent stopped without calling submit_decision. It said: "
                f"{text[:500] or '(nothing)'}"
            )

        tool_results = []
        for block in tool_use_blocks:
            if block.name == "submit_decision":
                submitted = block.input
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": "Decision recorded.",
                })
                continue

            tools_used.append(block.name)
            try:
                result = await execute_tool_func(
                    block.name, block.input, players or [], teams or {}, team_data
                )
            except Exception as e:
                # One failing tool must not kill the run — the agent can route
                # around it — but it must SEE the failure, not a plausible blank.
                result = f"TOOL ERROR ({block.name}): {e}. Do not treat this as 'no issues found'."
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result if isinstance(result, str) else json.dumps(result, default=str),
            })

        if submitted is not None:
            break

        messages.append({"role": "assistant", "content": response.content})

        # Roll a cache breakpoint onto the newest tool-result block and drop the
        # previous one. History here is append-only, so each turn's prefix is
        # exactly last turn's prefix plus new blocks — the next call reads all of
        # it at 0.1x instead of full price. Only the newest breakpoint is kept
        # because the request cap is 4; letting them accumulate would exceed it
        # (the older prefixes stay cached and are still hit by prefix match).
        for prior in messages[:-1]:
            content = prior.get("content")
            if isinstance(content, list):
                for blk in content:
                    if isinstance(blk, dict):
                        blk.pop("cache_control", None)
        if tool_results:
            tool_results[-1]["cache_control"] = {"type": "ephemeral"}
        messages.append({"role": "user", "content": tool_results})

    if submitted is None:
        raise BotAgentError(
            f"Agent did not submit a decision within {MAX_ITERATIONS} iterations."
        )

    return _build_decision(submitted, gameweek, run_type, tools_used, usage_totals)


def _build_decision(
    payload: Dict, gameweek: int, run_type: str, tools_used: List[str],
    usage: Optional[Dict[str, int]] = None,
) -> AgentDecision:
    """Validate the submitted payload into an AgentDecision.

    The API already enforced the schema; this catches the semantic errors it
    cannot — a captain equal to the vice, a wrong-length lineup, an early run
    trying to play a chip.
    """
    captain_id = payload.get("captain_id")
    vice_id = payload.get("vice_captain_id")
    if captain_id is None or vice_id is None:
        raise BotAgentError("Decision is missing a captain or vice-captain.")
    if captain_id == vice_id:
        raise BotAgentError(
            f"Captain and vice-captain are the same player (id {captain_id})."
        )

    lineup = payload.get("lineup_order") or []
    if lineup and len(lineup) != 15:
        raise BotAgentError(f"lineup_order must hold 15 ids or be omitted; got {len(lineup)}.")
    if lineup and len(set(lineup)) != len(lineup):
        raise BotAgentError("lineup_order contains duplicate players.")

    chip = payload.get("chip")
    if chip in ("none", "", None):
        chip = None

    transfers = []
    for t in payload.get("transfers") or []:
        if t.get("player_out_id") == t.get("player_in_id"):
            raise BotAgentError(
                f"Transfer buys and sells the same player (id {t.get('player_out_id')})."
            )
        transfers.append(TransferDecision(
            player_out_id=int(t["player_out_id"]),
            player_out_name=t.get("player_out_name", ""),
            player_in_id=int(t["player_in_id"]),
            player_in_name=t.get("player_in_name", ""),
            reason=t.get("reason", ""),
        ))

    out_ids = [t.player_out_id for t in transfers]
    in_ids = [t.player_in_id for t in transfers]
    if len(set(out_ids)) != len(out_ids):
        raise BotAgentError("The same player is sold twice in one decision.")
    if len(set(in_ids)) != len(in_ids):
        raise BotAgentError("The same player is bought twice in one decision.")

    if run_type == "early" and chip:
        # Not a model failure worth aborting for — the timing rule says chips
        # wait for the final run, so drop it and let the final run decide.
        chip = None

    return AgentDecision(
        gameweek=gameweek,
        run_type=run_type,
        transfers=transfers,
        captain_id=int(captain_id),
        captain_name=payload.get("captain_name", ""),
        vice_captain_id=int(vice_id),
        vice_captain_name=payload.get("vice_captain_name", ""),
        lineup_order=[int(x) for x in lineup],
        chip=chip,
        hit_taken=int(payload.get("hit_taken") or 0),
        confidence=payload.get("confidence", ""),
        reasoning=payload.get("reasoning", ""),
        availability_overrides=payload.get("availability_overrides") or [],
        tools_used=sorted(set(tools_used)),
        usage=usage or {},
    )


# ---------------------------------------------------------------------------
# CLI — run a decision by hand without the API server
# ---------------------------------------------------------------------------

async def _cli(team_id: int, run_type: str) -> Dict:
    """Wire the agent to the real tool set, exactly as the endpoint does."""
    import api_server

    team_data = await api_server.get_user_team(team_id)
    players, teams, _ = await api_server.fetch_enhanced_players()
    context = api_server.build_comprehensive_context(
        team_data, players, teams, None, None, str(team_id)
    )
    decision = await run_agent_decision(
        gameweek=team_data.get("gameweek", 0) + 1,
        context=context,
        tools=api_server.FPL_TOOLS,
        execute_tool_func=api_server.execute_tool,
        players=players,
        teams=teams,
        team_data=team_data,
        run_type=run_type,
    )
    return decision.to_dict()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Autonomous FPL agent decision")
    parser.add_argument("--team-id", type=int,
                        default=int(os.getenv("FPL_BOT_TEAM_ID", os.getenv("BOT_TEAM_ID", "12777515"))))
    parser.add_argument("--run-type", choices=["early", "final"], default="final")
    args = parser.parse_args()

    try:
        print(json.dumps(asyncio.run(_cli(args.team_id, args.run_type)), indent=2))
    except BotAgentError as exc:
        print(f"AGENT FAILED: {exc}")
        raise SystemExit(1)
