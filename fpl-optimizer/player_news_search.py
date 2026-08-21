#!/usr/bin/env python3
"""
Live web search for player news — the escape hatch when structured feeds are wrong.

## Why this exists

FPL's `chance_of_playing_next_round` is coarse (0/25/50/75/100) and updated by
hand, so it goes stale. Concretely: FPL listed Doku at **75%** while press
reports had him **ruled out of the opener with a calf injury for several weeks**.
Every structured source we have — FPL's own flags, Knocks and Bans, FFScout —
either missed that or lagged it. A 50% or 75% flag is precisely the case where
the number alone can't be trusted and the actual reporting matters.

This uses Anthropic's **server-side web search**: the model runs the searches
itself, so there's no Google API key, no scraper to maintain, and nothing to
break when a site changes its markup.

Deliberately returns prose with sources rather than a parsed verdict. The whole
value is the nuance ("reported, not confirmed by the club", "expected back after
the international break") — collapsing that to a boolean would throw away the
reason the search was worth doing.
"""
import os
from typing import Dict, List, Optional

try:
    import anthropic
except ImportError:  # keep import-safe if the SDK is absent
    anthropic = None

# Search runs on the same model as the chat so behaviour stays consistent.
SEARCH_MODEL = os.getenv("ANTHROPIC_CHAT_MODEL", "claude-opus-5")

# Server-side web search. Requires Opus 4.6+/Sonnet 4.6+; the dated type is the
# current variant with dynamic filtering.
_WEB_SEARCH_TOOL = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": 4,
}

_PROMPT = """You are checking Premier League injury and availability news for Fantasy Premier League decisions.

You are given what THREE existing sources already say about each player. Your job
is to search the web and act as the tie-breaker across all of them.

For each player, report:
1. Fit, doubtful, or out for the upcoming gameweek?
2. If doubtful/out — the injury and expected return.
3. Is your evidence an official club statement, a manager's press conference, or
   a press report? Say which — they are not equally reliable.
4. **Do the sources DISAGREE?** Compare FPL's flag, Knocks and Bans, FFScout and
   what you found. Where they conflict, say so plainly and say which you'd trust
   and why (recency and provenance beat a stale number).

These sources genuinely do disagree in practice — one has been seen listing a
player at 25% while FPL had 75% and the press had him ruled out entirely. The
disagreement is the most valuable thing you can surface, so never smooth it over
into a single confident answer.

Existing source data:
{players}

Be concise: two or three sentences per player, and cite the source. If you can't
find recent news on someone, say so plainly rather than guessing. Prefer fewer,
well-targeted searches over exhausting the budget on one player."""


def available() -> bool:
    """Whether live search can run at all."""
    return anthropic is not None and bool(os.getenv("ANTHROPIC_API_KEY"))


def search_player_news(players: List[Dict], max_players: int = 6) -> Dict:
    """
    Look up live news for specific players.

    Args:
        players: dicts with at least `name`; `chance_of_playing` and `team`
            enrich the prompt so the model can spot a stale FPL flag.
        max_players: cap — each extra player means more searches and latency.

    Returns {"available": bool, "report": str, "players_checked": [...]}.
    Never raises: this is an advisory layer, so a failure must degrade to
    "no live news" rather than break the caller.
    """
    if not available():
        return {
            "available": False,
            "report": "Live news search unavailable (no ANTHROPIC_API_KEY or SDK).",
            "players_checked": [],
        }
    if not players:
        return {"available": True, "report": "No players supplied.", "players_checked": []}

    selected = players[:max_players]
    lines = []
    for p in selected:
        header = f"- {p.get('name', '?')}"
        if p.get("team"):
            header += f" ({p['team']})"
        lines.append(header)

        chance = p.get("chance_of_playing")
        fpl_bits = (f"{chance}% chance of playing"
                    if chance is not None else "no doubt listed")
        if p.get("news"):
            fpl_bits += f' — "{p["news"]}"'
        lines.append(f"    FPL:             {fpl_bits}")

        # Passed in by the caller so the model can cross-reference rather than
        # taking any single feed's word for it. "not listed" is itself a signal:
        # it means that source has nothing on the player, which conflicts with a
        # doubt elsewhere.
        lines.append(f"    Knocks and Bans: {p.get('knocks_and_bans') or 'not listed'}")
        lines.append(f"    FFScout:         {p.get('ffscout') or 'not listed'}")

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=SEARCH_MODEL,
            max_tokens=2000,
            tools=[_WEB_SEARCH_TOOL],
            messages=[{"role": "user",
                       "content": _PROMPT.format(players="\n".join(lines))}],
        )
        text = "\n".join(
            b.text.strip() for b in response.content
            if b.type == "text" and b.text.strip()
        )
        searches = sum(1 for b in response.content if b.type == "server_tool_use")
        return {
            "available": True,
            "report": text or "No usable response from the search.",
            "players_checked": [p.get("name") for p in selected],
            "searches_run": searches,
        }
    except Exception as e:
        return {
            "available": False,
            "report": f"Live news search failed: {e}",
            "players_checked": [p.get("name") for p in selected],
        }


def annotate_with_scrapers(candidates: List[Dict], team_news: Dict) -> List[Dict]:
    """
    Attach what Knocks and Bans and FFScout say about each candidate.

    Without this the search only compares itself against FPL — one structured
    source — and can't do the three-way cross-reference that catches a feed being
    wrong. Matching is exact-name only, consistent with the squad builder: a
    substring rule previously paired "White" with "Gibbs-White".
    """
    kab_by_name = {}
    for entry in team_news.get("knocks_and_bans", []) or []:
        detail = entry.get("status", "unknown")
        if entry.get("injury_type"):
            detail += f" ({entry['injury_type']})"
        if entry.get("expected_return"):
            detail += f", est. return {entry['expected_return']}"
        kab_by_name[entry.get("name", "").strip().lower()] = detail

    ffs_by_name = {}
    for team in team_news.get("ffscout", []) or []:
        for group, label in (("out", "OUT"), ("doubts", "doubt"), ("banned", "banned")):
            for raw in team.get(group, []) or []:
                name = raw.split("(")[0].strip().lower()
                if name:
                    pct = raw[raw.find("(") + 1:raw.find(")")] if "(" in raw else ""
                    ffs_by_name[name] = f"{label} {pct}".strip()
        for raw in team.get("predicted_lineup", []) or []:
            name = raw.split("(")[0].strip().lower()
            if name and name not in ffs_by_name:
                ffs_by_name[name] = "in predicted XI"

    for candidate in candidates:
        keys = [
            (candidate.get("name") or "").strip().lower(),
            (candidate.get("web_name") or "").strip().lower(),
        ]
        for source, field in ((kab_by_name, "knocks_and_bans"), (ffs_by_name, "ffscout")):
            for key in keys:
                if key and key in source:
                    candidate[field] = source[key]
                    break
    return candidates


def flagged_players(all_players: List[Dict], teams: Optional[Dict] = None,
                    max_players: int = 6) -> List[Dict]:
    """
    Pick the players actually worth searching for: those with a partial doubt.

    A 100% player needs no check and a 0% player is already settled — it's the
    25/50/75 middle that's ambiguous and where a stale flag does damage. Sorted
    by descending chance so the most likely-to-feature (and therefore most
    decision-relevant) come first.
    """
    candidates = []
    for player in all_players:
        chance = player.get("chance_of_playing_next_round")
        if chance is None or chance <= 0 or chance >= 100:
            continue
        team_name = ""
        if teams:
            team_name = teams.get(player.get("team", 0), {}).get("short_name", "")
        candidates.append({
            "name": f"{player.get('first_name', '')} {player.get('second_name', '')}".strip()
                    or player.get("web_name", ""),
            "web_name": player.get("web_name", ""),
            "team": team_name,
            "chance_of_playing": chance,
            "news": player.get("news", ""),
            "id": player.get("id"),
        })
    candidates.sort(key=lambda p: p["chance_of_playing"], reverse=True)
    return candidates[:max_players]
