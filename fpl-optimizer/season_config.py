"""
Season configuration — single source of truth for the active FPL season.

The FPL API (bootstrap-static) is always authoritative for *live* data
(players, prices, gameweeks). This module governs the season used for the
external advanced-stat sources (Understat, FBRef), which lag the FPL API:
at the start of a new season those sources return zero rows until real
matches have been played.

CURRENT_SEASON  — the live FPL season (Understat-style year, e.g. "2026" = 2026/27).
PRIOR_SEASON    — the last completed season, used as a baseline fallback
                  while the current season has no advanced-stat data yet.
"""

CURRENT_SEASON = "2026"   # 2026/27
PRIOR_SEASON = "2025"     # 2025/26


def display_label(understat_year: str = CURRENT_SEASON) -> str:
    """"2026" -> "2026/27" for UI/logging."""
    y = int(understat_year)
    return f"{y}/{str(y + 1)[-2:]}"


def to_fbref(understat_year: str) -> str:
    """"2026" -> "2026-2027" (FBRef season format)."""
    return f"{understat_year}-{int(understat_year) + 1}"


def resolve_stats_season(fetch_fn, use_cache: bool = True) -> tuple:
    """
    Auto-detect which season's advanced stats to use.

    Tries CURRENT_SEASON first; if the source returns no rows (typical
    pre-season / early-season), falls back to PRIOR_SEASON so profiles still
    show a meaningful baseline. Rolls forward automatically once the current
    season populates.

    Args:
        fetch_fn: callable(season_year: str, use_cache: bool) -> list
        use_cache: passed through to fetch_fn

    Returns:
        (season_year_used, players_list)
    """
    for season in (CURRENT_SEASON, PRIOR_SEASON):
        players = fetch_fn(season, use_cache)
        if players:
            if season != CURRENT_SEASON:
                print(
                    f"ℹ️  {display_label(CURRENT_SEASON)} advanced stats not yet "
                    f"available — using {display_label(season)} as baseline."
                )
            return season, players
    return CURRENT_SEASON, []
