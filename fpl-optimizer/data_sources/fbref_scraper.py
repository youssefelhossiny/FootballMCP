"""
FBRef Data Scraper
Fetches defensive, possession, and progressive stats from FBRef using soccerdata library

Key stats for FPL:
- Defensive: Tackles, Interceptions, Blocks, Clearances (for FPL defensive contribution points)
- Progressive: Progressive passes, carries, receptions (for midfielder value)
- Creation: SCA, GCA (shot/goal creating actions)

Also supports the EFL Championship as a prior-season baseline source for
promoted teams (soccerdata's built-in league list only covers the "big 5" +
internationals, so the Championship is registered via a custom league_dict.json
in soccerdata's config dir — see `_ensure_championship_league_registered`).
"""

import json
import os
import time
from pathlib import Path

import pandas as pd
from typing import Dict, List, Optional

try:
    from data_cache import DataCache
except ImportError:
    from data_sources.data_cache import DataCache


CHAMPIONSHIP_LEAGUE = "ENG-Championship"


def _ensure_championship_league_registered():
    """
    Register the EFL Championship with soccerdata so it can be passed as a
    `leagues=` value to `sd.FBref`. soccerdata only ships the "big 5" European
    leagues + internationals out of the box; anything else must be added via
    a user config file at `<soccerdata base dir>/config/league_dict.json`,
    which soccerdata merges into its LEAGUE_DICT **at import time** — so this
    must run before `import soccerdata`. Idempotent and self-healing so it
    works in fresh environments (e.g. Render) without manual setup.
    """
    base_dir = Path(os.environ.get("SOCCERDATA_DIR", Path.home() / "soccerdata"))
    config_dir = base_dir / "config"
    config_path = config_dir / "league_dict.json"

    existing = {}
    if config_path.exists():
        try:
            with open(config_path, 'r') as f:
                existing = json.load(f)
        except Exception:
            existing = {}

    if CHAMPIONSHIP_LEAGUE in existing:
        return

    existing[CHAMPIONSHIP_LEAGUE] = {
        "FBref": "EFL Championship",
        "season_start": "Aug",
        "season_end": "May",
    }

    config_dir.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w') as f:
        json.dump(existing, f, indent=2)


# Must run before `import soccerdata` — soccerdata builds its LEAGUE_DICT
# (merging in this config file) as a module-level side effect at import time.
_ensure_championship_league_registered()

import soccerdata as sd  # noqa: E402
from lxml import html as lxml_html, etree
from soccerdata.fbref import _parse_table, _fix_nation_col, _concat
from soccerdata._common import standardize_colnames


# soccerdata's read_player_season_stats() only whitelists a handful of
# stat_type values ('standard', 'keeper', 'shooting', 'playing_time', 'misc')
# — 'defense', 'passing', 'possession' and 'goal_shot_creation' were dropped
# from the library's supported list even though FBRef still serves these
# pages/tables at the same URLs. This replicates that method's internal
# fetch+parse chain (single-league branch) for the unsupported stat types,
# so tackles/interceptions/blocks/progressive-passing/SCA/GCA keep working.
EXTENDED_STAT_TYPES = {"defense", "passing", "possession", "goal_shot_creation"}

# Which output columns of _process_stats come from which upstream stat-type
# page. Used to report exactly which fields are zero-filled (not real) when a
# stat-type fetch fails, so a hollow cache can't be mistaken for real data.
# Note: def_contributions{,_per_90} is derived as tackles+interceptions+
# blocks+clearances, so it is corrupted if EITHER defense or passing fails.
_STAT_TYPE_COLUMNS = {
    "defense": (
        "tackles", "tackles_won", "tackle_pct", "interceptions",
        "tackles_plus_int", "blocks", "clearances", "errors",
        "def_contributions", "def_contributions_per_90",
    ),
    "passing": (
        "progressive_passes", "progressive_passes_per_90",
        "def_contributions", "def_contributions_per_90",
    ),
    "possession": (
        "progressive_carries", "progressive_receptions",
        "progressive_carries_per_90", "progressive_receptions_per_90",
        "touches", "touches_att_3rd",
    ),
    "goal_shot_creation": ("sca", "gca", "sca_per_90", "gca_per_90"),
    "misc": ("recoveries", "recoveries_per_90"),
}


def _wait_for_table_html(driver, url: str, marker: str, timeout: float = 40.0, poll: float = 2.0) -> str:
    """
    Navigate to `url` and poll the live page source until `marker` (e.g. the
    'div_stats_standard' comment id) actually appears, instead of trusting
    soccerdata's fixed 7s post-navigation sleep (`BaseSeleniumReader.
    _download_and_save`), which grabs `page_source` unconditionally after a
    flat delay and happily accepts FBRef's consent-banner/Cloudflare
    interstitial as "the page" if that overlay hasn't cleared yet in time.

    The interstitial is a cosmetic layer, not a replacement page — the real
    table sits in the DOM underneath it and typically appears within a few
    extra seconds. Polling for the actual marker (rather than a fixed sleep)
    is what makes that timing difference survivable.
    """
    driver.get(url)
    deadline = time.time() + timeout
    last_source = ""
    while time.time() < deadline:
        last_source = driver.page_source
        if marker in last_source:
            return last_source
        time.sleep(poll)
    return last_source


def _fetch_extended_player_stats(
    fbref_client, stat_type: str, max_attempts: int = 3, seasons: Optional[pd.DataFrame] = None
) -> pd.DataFrame:
    """
    Fetch a player-season-stats page FBRef still serves but soccerdata's
    read_player_season_stats() no longer whitelists. Mirrors that method's
    processing chain exactly (see soccerdata/fbref.py) for the single-league
    (non "Big 5 Combined") case, which is all this project ever selects,
    including soccerdata's own `_concat` (which moves the "Unnamed: ..."
    Player/Squad/league/season labels from level 1 to level 0 — required
    for set_index(["league","season","team","player"]) to resolve at all).

    FBRef intermittently serves a consent-banner interstitial instead of the
    real page even after soccerdata's internal retry; retried here since it
    self-resolves in practice (observed 3/4 stat types succeed first try).
    Retries drive the underlying Selenium session directly (`_wait_for_table_
    html`) to poll for the real table rather than re-triggering the same
    fixed-sleep race soccerdata's own `get()` would hit again.

    Args:
        seasons: pre-fetched fbref_client.read_seasons() result, so callers
            fetching multiple stat types don't repeat that (uncached) live
            page load once per stat type.
    """
    if seasons is None:
        seasons = fbref_client.read_seasons()

    # FBRef's URL path segment doesn't always match the stat_type name
    # (mirrors soccerdata.fbref.read_player_season_stats's own mapping).
    page = {"standard": "stats", "keeper": "keepers", "playing_time": "playingtime"}.get(
        stat_type, stat_type
    )

    frames = []
    for (lkey, skey), season in seasons.iterrows():
        filepath = fbref_client.data_dir / f"players_{lkey}_{skey}_{stat_type}.html"
        url = (
            "https://fbref.com"
            + "/".join(season.url.split("/")[:-1])
            + f"/{page}/"
            + season.url.split("/")[-1]
        )
        marker = f"div_stats_{stat_type}"

        html_table = None
        last_error = None
        last_page_text = ""
        for attempt in range(max_attempts):
            if attempt == 0:
                if filepath.exists():
                    filepath.unlink()
                reader = fbref_client.get(url, filepath)
                tree = lxml_html.parse(reader)
            else:
                # A plain retry through fbref_client.get() would hit the same
                # fixed-sleep race that failed last time — poll the real
                # driver instead so a slow-clearing interstitial has a chance
                # to resolve before we give up.
                page_source = _wait_for_table_html(fbref_client._driver, url, marker)
                last_page_text = page_source
                if not fbref_client.no_store:
                    filepath.parent.mkdir(parents=True, exist_ok=True)
                    filepath.write_text(page_source, encoding="utf-8")
                if os.environ.get("FBREF_DEBUG_DUMP"):
                    debug_path = Path(f"/tmp/fbref_debug_{stat_type}_attempt{attempt}.html")
                    debug_path.write_text(page_source, encoding="utf-8")
                    print(f"   [debug] dumped {len(page_source)} bytes to {debug_path}, marker present: {marker in page_source}")
                tree = lxml_html.fromstring(page_source)
            for elem in tree.xpath("//td[@data-stat='comp_level']//span"):
                elem.getparent().remove(elem)
            try:
                (el,) = tree.xpath(f"//comment()[contains(.,'{marker}')]")
                parser = etree.HTMLParser(recover=True)
                (html_table,) = etree.fromstring(el.text, parser).xpath(
                    f"//table[contains(@id, 'stats_{stat_type}')]"
                )
                break
            except ValueError as e:
                last_error = e
                html_table = None

        if html_table is None:
            # Distinguish "blocked" from "no such table". Conflating them is what
            # produced a wrong diagnosis in ROADMAP for weeks: the 2026/27 pages
            # were assumed to be anti-bot-blocked when in fact Selenium loads
            # them fine and they simply have NO stats table yet (no matches
            # played). A Cloudflare challenge leaves its own fingerprint in the
            # page; a missing table does not.
            page = (last_page_text or "").lower()
            blocked_markers = ("cf-mitigated", "just a moment", "challenge-platform",
                               "cf-chl", "attention required")
            looks_blocked = any(m in page for m in blocked_markers)
            if looks_blocked:
                detail = ("Cloudflare/anti-bot challenge did not clear — the page never "
                          "rendered. Retrying later may help.")
            else:
                detail = ("the page loaded but contains no "
                          f"'stats_{stat_type}' table — most likely this season has no "
                          "published data yet (no matches played). Retrying will NOT help "
                          "until FBRef publishes it.")
            raise RuntimeError(
                f"Could not load FBRef '{stat_type}' table after {max_attempts} attempts: "
                f"{detail} (last error: {last_error})"
            )

        df_table = _parse_table(html_table)
        df_table[("Unnamed: league", "league")] = lkey
        df_table[("Unnamed: season", "season")] = skey
        df_table = _fix_nation_col(df_table)
        frames.append(df_table)

    df = _concat(frames, key=["league", "season"])
    df = df[df.Player != "Player"]
    return (
        df.drop("Matches", axis=1, level=0)
        .drop("Rk", axis=1, level=0)
        .rename(columns={"Squad": "team"})
        .pipe(standardize_colnames, cols=["Player", "Nation", "Pos", "Age", "Born"])
        .set_index(["league", "season", "team", "player"])
        .sort_index()
    )


class FBRefScraper:
    """Fetch defensive and possession stats from FBRef"""

    def __init__(self, cache_dir: str = None):
        """
        Initialize the FBRef scraper

        Args:
            cache_dir: Directory for caching (default: same as understat cache)
        """
        self.fbref = None
        self._fbref_league = None
        self._fbref_season = None
        self.last_request_time = 0
        self.rate_limit_delay = 6.0  # FBRef requires 6 seconds between requests

        # Use same cache directory as other data sources
        if cache_dir is None:
            cache_dir = str(Path(__file__).parent.parent / "cache")
        self.cache = DataCache(cache_dir=cache_dir, ttl_hours=6)
        # Separate TTL for "this season isn't available" markers.
        #
        # Was 1 hour, which is far too aggressive: a retry costs ~11 MINUTES of
        # wall clock (5 stat types x 2-3 attempts x a 40s table-marker timeout,
        # measured) and, before a season's first matches are played, it CANNOT
        # succeed — FBRef has no player-stats table to serve until there are
        # stats. So the hourly retry was pure waste that repeatedly stalled
        # interactive tool calls.
        #
        # 12h keeps a newly-live season being picked up the same day while
        # making the stall rare. Override with FBREF_FAILURE_TTL_HOURS (set it
        # low around a season rollover if you want faster detection).
        self.failure_cache = DataCache(
            cache_dir=cache_dir,
            ttl_hours=float(os.getenv("FBREF_FAILURE_TTL_HOURS", "12")),
        )

    def _rate_limit(self):
        """Implement rate limiting (6 seconds for FBRef)"""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time

        if time_since_last_request < self.rate_limit_delay:
            sleep_time = self.rate_limit_delay - time_since_last_request
            print(f"   Rate limiting: waiting {sleep_time:.1f}s...")
            time.sleep(sleep_time)

        self.last_request_time = time.time()

    def _get_fbref_client(self, season: str = "2026-2027", league: str = "ENG-Premier League"):
        """Get or create FBRef client for the given league/season (rebuilds on change)"""
        if self.fbref is None or self._fbref_league != league or self._fbref_season != season:
            self.fbref = sd.FBref(leagues=league, seasons=season)
            self._fbref_league = league
            self._fbref_season = season
        return self.fbref

    def fetch_player_stats(
        self,
        season: str = "2026-2027",
        use_cache: bool = True,
        league: str = "ENG-Premier League",
    ) -> List[Dict]:
        """
        Fetch all player stats from FBRef (defensive, passing, possession)

        Args:
            season: Season in format "2024-2025"
            use_cache: Whether to use cached data if available
            league: soccerdata canonical league id, e.g. "ENG-Premier League"
                or "ENG-Championship" (see CHAMPIONSHIP_LEAGUE)

        Returns:
            List of player dictionaries with FBRef stats
        """
        league_slug = league.replace(" ", "_").replace("-", "_").lower()
        cache_key = f"fbref_{league_slug}_{season.replace('-', '_')}"
        failure_key = f"{cache_key}_unavailable"

        # Check cache first
        if use_cache:
            cached_data = self.cache.get(cache_key, format="json")
            if cached_data:
                return cached_data

            # Negative cache. A season FBRef hasn't published yet (or that its
            # anti-bot layer refuses) costs minutes to fail: Selenium starts,
            # every stat type retries, then we return []. `resolve_stats_season`
            # probes the current season on EVERY call, so without this each of
            # the ~7 tools that enhance player data paid that cost every time,
            # making them unusable interactively. Remember the failure briefly
            # and skip straight to the caller's fallback.
            if self.failure_cache.get(failure_key, format="json") is not None:
                print(
                    f"⏭️  Skipping FBRef {league} {season} — a recent fetch found "
                    f"no data (negative-cached; clear cache/{failure_key}.json to retry)"
                )
                return []

        try:
            print(f"Fetching FBRef data for {league} {season}...")
            fbref = self._get_fbref_client(season, league=league)

            # Fetch different stat types. defense/passing/possession/
            # goal_shot_creation are no longer in soccerdata's
            # read_player_season_stats() whitelist (dropped from the library,
            # though FBRef still serves these pages) — fetched via
            # _fetch_extended_player_stats, which replicates that method's
            # internal fetch+parse chain for the still-working URLs. Each is
            # fault-tolerant: FBRef intermittently serves a consent-banner
            # interstitial that won't clear even after retries, and losing
            # one stat type shouldn't fail the whole collection pass.
            extended_seasons = fbref.read_seasons()

            # Track which stat types actually failed. Without this, a failed
            # fetch degrades to an empty DataFrame, _process_stats fills the
            # affected columns with 0, and the result gets cached as if it
            # were real data — indistinguishable from "genuinely zero".
            # That silently poisoned the 2025/26 cache (0/551 rows nonzero
            # for tackles/blocks/clearances/progressive/sca/gca) and in turn
            # fed 22 constant features into the ML backtest.
            failed_stat_types: List[str] = []

            def _fetch_or_empty(label: str, stat_type: str) -> pd.DataFrame:
                print(f"   Fetching {label} stats...")
                self._rate_limit()
                try:
                    return _fetch_extended_player_stats(
                        fbref, stat_type, max_attempts=2, seasons=extended_seasons
                    )
                except RuntimeError as e:
                    print(f"   ⚠️  Could not load {label} stats, continuing without: {e}")
                    failed_stat_types.append(stat_type)
                    return pd.DataFrame()

            defense_df = _fetch_or_empty("defensive", "defense")
            passing_df = _fetch_or_empty("passing", "passing")
            possession_df = _fetch_or_empty("possession", "possession")
            gca_df = _fetch_or_empty("goal/shot creation", "goal_shot_creation")

            # standard/misc anchor _process_stats below (unlike the four
            # optional stat types above, an empty result here means an empty
            # player list) — worth the extra polling-retry attempts rather
            # than degrading silently.
            print("   Fetching standard stats...")
            self._rate_limit()
            standard_df = _fetch_extended_player_stats(
                fbref, "standard", max_attempts=3, seasons=extended_seasons
            )

            print("   Fetching miscellaneous stats (recoveries)...")
            self._rate_limit()
            misc_df = _fetch_extended_player_stats(
                fbref, "misc", max_attempts=3, seasons=extended_seasons
            )

            # Process and merge data
            processed = self._process_stats(
                defense_df, passing_df, possession_df, gca_df, standard_df, misc_df
            )

            # Stamp provenance so a partially-failed fetch is detectable
            # downstream instead of looking like real all-zero data. Any
            # consumer that cares (e.g. ML training) can check
            # `_incomplete_stat_types` and refuse to trust those columns.
            if failed_stat_types:
                affected = sorted(
                    col
                    for st in failed_stat_types
                    for col in _STAT_TYPE_COLUMNS.get(st, ())
                )
                print(
                    f"   ⚠️  INCOMPLETE FBRef data — {len(failed_stat_types)} stat "
                    f"type(s) failed ({', '.join(failed_stat_types)}); the "
                    f"following columns are zero-filled, NOT real: {', '.join(affected)}"
                )
                for player in processed:
                    player["_incomplete_stat_types"] = failed_stat_types

            # Cache the results
            if processed:
                self.cache.set(cache_key, processed, format="json")
            else:
                # Empty but no exception — the season parsed to nothing (not
                # yet published). Negative-cache so the next call is instant.
                self.failure_cache.set(failure_key, {"reason": "no rows returned"}, format="json")

            print(f"Fetched {len(processed)} players from FBRef")
            return processed

        except Exception as e:
            print(f"Error fetching FBRef data: {e}")
            import traceback
            traceback.print_exc()

            # FALLBACK: if the live scrape fails (e.g. upstream stat_type
            # changes, or early-season data not yet published), use the last
            # good cache even if expired, rather than returning nothing.
            stale_data = self.cache.get(cache_key, format="json", ignore_expiry=True)
            if stale_data:
                print(f"✅ Using stale FBRef cache ({len(stale_data)} players)")
                return stale_data

            self.failure_cache.set(failure_key, {"reason": str(e)[:200]}, format="json")
            return []

    def fetch_championship_stats(self, season: str = "2025-2026", use_cache: bool = True) -> List[Dict]:
        """
        Fetch Championship (2nd tier) player stats — used as a prior-season
        baseline for teams promoted into the EPL who have no EPL-level FBRef
        history yet (e.g. Coventry, Hull, Ipswich for 2026/27).

        Args:
            season: Season in format "2025-2026"
            use_cache: Whether to use cached data if available

        Returns:
            List of player dictionaries with FBRef stats
        """
        return self.fetch_player_stats(season=season, use_cache=use_cache, league=CHAMPIONSHIP_LEAGUE)

    def _process_stats(
        self,
        defense_df: pd.DataFrame,
        passing_df: pd.DataFrame,
        possession_df: pd.DataFrame,
        gca_df: pd.DataFrame,
        standard_df: pd.DataFrame,
        misc_df: pd.DataFrame = None
    ) -> List[Dict]:
        """
        Process and merge FBRef DataFrames into player dictionaries

        Args:
            defense_df: Defensive stats DataFrame
            passing_df: Passing stats DataFrame
            possession_df: Possession stats DataFrame
            gca_df: Goal/shot creation DataFrame
            standard_df: Standard stats DataFrame
            misc_df: Miscellaneous stats DataFrame (contains recoveries)

        Returns:
            List of player dictionaries with all stats
        """
        processed = []

        try:
            # Reset index to get player names as column
            defense_df = defense_df.reset_index()
            passing_df = passing_df.reset_index()
            possession_df = possession_df.reset_index()
            gca_df = gca_df.reset_index()
            standard_df = standard_df.reset_index()
            if misc_df is not None:
                misc_df = misc_df.reset_index()

            # Build lookup dicts for faster matching
            def build_lookup(df):
                lookup = {}
                for idx, row in df.iterrows():
                    player = self._get_tuple_value(row, ('player', ''))
                    team = self._get_tuple_value(row, ('team', ''))
                    if player:
                        key = f"{player.lower()}_{team.lower()}"
                        lookup[key] = row
                return lookup

            print("   Building player lookup tables...")
            defense_lookup = build_lookup(defense_df)
            passing_lookup = build_lookup(passing_df)
            possession_lookup = build_lookup(possession_df)
            gca_lookup = build_lookup(gca_df)
            misc_lookup = build_lookup(misc_df) if misc_df is not None else {}

            # Process each player from standard stats
            for idx, row in standard_df.iterrows():
                try:
                    # Extract player name and team using tuple access
                    player_name = self._get_tuple_value(row, ('player', ''))
                    team = self._get_tuple_value(row, ('team', ''))

                    # Skip if no player name
                    if not player_name or player_name == 'nan':
                        continue

                    # Get minutes played for per-90 calculations
                    minutes = self._get_tuple_value(row, ('Playing Time', 'Min'), default=0, as_float=True)
                    games_90 = max(minutes / 90, 0.1)  # Avoid division by zero

                    # Find matching rows in other dataframes
                    lookup_key = f"{player_name.lower()}_{team.lower()}"
                    def_row = defense_lookup.get(lookup_key)
                    pass_row = passing_lookup.get(lookup_key)
                    poss_row = possession_lookup.get(lookup_key)
                    gca_row = gca_lookup.get(lookup_key)
                    misc_row = misc_lookup.get(lookup_key)

                    # Extract defensive stats using proper MultiIndex tuple keys
                    tackles = self._get_tuple_value(def_row, ('Tackles', 'Tkl'), default=0, as_float=True)
                    tackles_won = self._get_tuple_value(def_row, ('Tackles', 'TklW'), default=0, as_float=True)
                    interceptions = self._get_tuple_value(def_row, ('Int', ''), default=0, as_float=True)
                    blocks = self._get_tuple_value(def_row, ('Blocks', 'Blocks'), default=0, as_float=True)
                    clearances = self._get_tuple_value(def_row, ('Clr', ''), default=0, as_float=True)
                    errors = self._get_tuple_value(def_row, ('Err', ''), default=0, as_float=True)
                    tkl_plus_int = self._get_tuple_value(def_row, ('Tkl+Int', ''), default=0, as_float=True)

                    # Tackle percentage
                    tackle_att = self._get_tuple_value(def_row, ('Challenges', 'Att'), default=0, as_float=True)
                    tackle_pct = self._get_tuple_value(def_row, ('Challenges', 'Tkl%'), default=0, as_float=True)

                    # Extract progressive stats from passing
                    progressive_passes = self._get_tuple_value(pass_row, ('PrgP', ''), default=0, as_float=True)
                    # Try alternate location
                    if progressive_passes == 0:
                        progressive_passes = self._get_tuple_value(pass_row, ('Unnamed: 28_level_0', 'PrgP'), default=0, as_float=True)

                    # Extract possession stats
                    touches = self._get_tuple_value(poss_row, ('Touches', 'Touches'), default=0, as_float=True)
                    touches_att_3rd = self._get_tuple_value(poss_row, ('Touches', 'Att 3rd'), default=0, as_float=True)
                    progressive_carries = self._get_tuple_value(poss_row, ('Carries', 'PrgC'), default=0, as_float=True)
                    progressive_receptions = self._get_tuple_value(poss_row, ('Receiving', 'PrgR'), default=0, as_float=True)

                    # Extract goal/shot creation stats
                    sca = self._get_tuple_value(gca_row, ('SCA', 'SCA'), default=0, as_float=True)
                    gca_val = self._get_tuple_value(gca_row, ('GCA', 'GCA'), default=0, as_float=True)

                    # Extract miscellaneous stats (recoveries for MID/FWD defensive contribution)
                    recoveries = self._get_tuple_value(misc_row, ('Performance', 'Recov'), default=0, as_float=True)
                    # Try alternate column name formats
                    if recoveries == 0:
                        recoveries = self._get_tuple_value(misc_row, ('Recov', ''), default=0, as_float=True)

                    # Calculate FPL defensive contribution sum (without recoveries - base stat)
                    # Recoveries are added separately for MID/FWD in enhanced_features.py
                    def_contributions = tackles + interceptions + blocks + clearances

                    player_stats = {
                        'name': player_name,
                        'team': team,
                        'minutes': minutes,

                        # Defensive stats (for FPL defensive contribution points)
                        'tackles': int(tackles),
                        'tackles_won': int(tackles_won),
                        'tackle_pct': round(tackle_pct, 1),
                        'interceptions': int(interceptions),
                        'tackles_plus_int': int(tkl_plus_int) if tkl_plus_int > 0 else int(tackles + interceptions),
                        'blocks': int(blocks),
                        'clearances': int(clearances),
                        'errors': int(errors),

                        # FPL Defensive Contribution calculation
                        'def_contributions': int(def_contributions),
                        'def_contributions_per_90': round(def_contributions / games_90, 2),

                        # Progressive stats
                        'progressive_passes': int(progressive_passes),
                        'progressive_carries': int(progressive_carries),
                        'progressive_receptions': int(progressive_receptions),
                        'progressive_passes_per_90': round(progressive_passes / games_90, 2),
                        'progressive_carries_per_90': round(progressive_carries / games_90, 2),
                        'progressive_receptions_per_90': round(progressive_receptions / games_90, 2),

                        # Possession/Creation stats
                        'touches': int(touches),
                        'touches_att_3rd': int(touches_att_3rd),
                        'sca': int(sca),
                        'gca': int(gca_val),
                        'sca_per_90': round(sca / games_90, 2),
                        'gca_per_90': round(gca_val / games_90, 2),

                        # Miscellaneous stats (recoveries critical for MID/FWD DC prediction)
                        'recoveries': int(recoveries),
                        'recoveries_per_90': round(recoveries / games_90, 2),
                    }

                    processed.append(player_stats)

                except Exception as e:
                    # Skip problematic rows
                    continue

            print(f"   Processed {len(processed)} players")
            return processed

        except Exception as e:
            print(f"Error processing FBRef stats: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _get_tuple_value(self, row, key, default=None, as_float=False):
        """
        Get value from row using tuple key (for MultiIndex columns)

        Args:
            row: DataFrame row (Series)
            key: Tuple key like ('Tackles', 'Tkl') or single column name
            default: Default value if not found
            as_float: Convert to float

        Returns:
            Value or default
        """
        if row is None:
            return default

        try:
            # Try tuple key first
            if isinstance(key, tuple) and key in row.index:
                val = row[key]
                if pd.notna(val):
                    return float(val) if as_float else val

            # Try string key
            if isinstance(key, str) and key in row.index:
                val = row[key]
                if pd.notna(val):
                    return float(val) if as_float else val

            # Try searching for partial match in MultiIndex
            if isinstance(key, tuple):
                for col in row.index:
                    if isinstance(col, tuple) and len(col) >= 2:
                        if col[0] == key[0] and col[1] == key[1]:
                            val = row[col]
                            if pd.notna(val):
                                return float(val) if as_float else val

            return default

        except Exception:
            return default

    def get_player_by_name(self, player_name: str, players: List[Dict]) -> Optional[Dict]:
        """
        Find a specific player by name

        Args:
            player_name: Player's name
            players: List of FBRef player dicts

        Returns:
            Player dict if found, None otherwise
        """
        for player in players:
            if player['name'].lower() == player_name.lower():
                return player
        return None

    def calculate_def_contribution_probability(
        self,
        def_contributions_per_90: float,
        position: int
    ) -> float:
        """
        Calculate probability of earning FPL defensive contribution points

        FPL Rules (2025/26):
        - Defenders: 10 contributions = 2 pts
        - Midfielders/Forwards: 12 contributions = 2 pts

        Args:
            def_contributions_per_90: Average defensive contributions per 90
            position: FPL position (1=GK, 2=DEF, 3=MID, 4=FWD)

        Returns:
            Probability (0-1) of earning the 2pt bonus
        """
        # Threshold based on position
        threshold = 10 if position == 2 else 12

        # Simple probability model based on how close to threshold
        # If avg is >= threshold, high probability
        # If avg is far below, low probability
        if def_contributions_per_90 >= threshold:
            return 0.85  # High probability but not guaranteed due to variance
        elif def_contributions_per_90 >= threshold * 0.8:
            return 0.5  # Good chance
        elif def_contributions_per_90 >= threshold * 0.6:
            return 0.25  # Some chance
        else:
            return 0.1  # Low chance


# Standalone testing
if __name__ == "__main__":
    scraper = FBRefScraper()

    # Fetch player stats
    players = scraper.fetch_player_stats(season="2025-2026", use_cache=False)

    if players:
        print(f"\nFBRef Data Sample (top 5 by tackles):")
        print("-" * 80)

        # Sort by tackles
        top_tackles = sorted(players, key=lambda p: p.get('tackles', 0), reverse=True)[:5]

        for i, player in enumerate(top_tackles, 1):
            print(f"{i}. {player['name']:25} ({player['team']:15})")
            print(f"   Defensive: Tkl={player.get('tackles', 0)} Int={player.get('interceptions', 0)} "
                  f"Blk={player.get('blocks', 0)} Clr={player.get('clearances', 0)}")
            print(f"   Recoveries: {player.get('recoveries', 0)} ({player.get('recoveries_per_90', 0):.1f}/90)")
            print(f"   Def Contributions/90: {player.get('def_contributions_per_90', 0):.1f}")
            print(f"   Progressive: PrgP={player.get('progressive_passes', 0)} "
                  f"PrgC={player.get('progressive_carries', 0)}")
            print(f"   Creation: SCA={player.get('sca', 0)} GCA={player.get('gca', 0)}")
            print()
