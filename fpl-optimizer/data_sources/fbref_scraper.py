"""
FBRef Data Scraper
Fetches defensive, possession, and progressive stats from FBRef using soccerdata library

Key stats for FPL:
- Defensive: Tackles, Interceptions, Blocks, Clearances (for FPL defensive contribution points)
- Progressive: Progressive passes, carries, receptions (for midfielder value)
- Creation: SCA, GCA (shot/goal creating actions)
"""

import soccerdata as sd
import time
import pandas as pd
from typing import Dict, List, Optional
from pathlib import Path
try:
    from data_cache import DataCache
except ImportError:
    from data_sources.data_cache import DataCache


class FBRefScraper:
    """Fetch defensive and possession stats from FBRef"""

    def __init__(self, cache_dir: str = None):
        """
        Initialize the FBRef scraper

        Args:
            cache_dir: Directory for caching (default: same as understat cache)
        """
        self.fbref = None
        self.last_request_time = 0
        self.rate_limit_delay = 6.0  # FBRef requires 6 seconds between requests

        # Use same cache directory as other data sources
        if cache_dir is None:
            cache_dir = str(Path(__file__).parent.parent / "cache")
        self.cache = DataCache(cache_dir=cache_dir, ttl_hours=6)

    def _rate_limit(self):
        """Implement rate limiting (6 seconds for FBRef)"""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time

        if time_since_last_request < self.rate_limit_delay:
            sleep_time = self.rate_limit_delay - time_since_last_request
            print(f"   Rate limiting: waiting {sleep_time:.1f}s...")
            time.sleep(sleep_time)

        self.last_request_time = time.time()

    def _get_fbref_client(self, season: str = "2025-2026"):
        """Get or create FBRef client"""
        if self.fbref is None:
            self.fbref = sd.FBref(leagues="ENG-Premier League", seasons=season)
        return self.fbref

    def fetch_player_stats(self, season: str = "2025-2026", use_cache: bool = True) -> List[Dict]:
        """
        Fetch all player stats from FBRef (defensive, passing, possession)

        Args:
            season: Season in format "2024-2025"
            use_cache: Whether to use cached data if available

        Returns:
            List of player dictionaries with FBRef stats
        """
        cache_key = f"fbref_epl_{season.replace('-', '_')}"

        # Check cache first
        if use_cache:
            cached_data = self.cache.get(cache_key, format="json")
            if cached_data:
                return cached_data

        try:
            print(f"Fetching FBRef data for EPL {season}...")
            fbref = self._get_fbref_client(season)

            # Fetch different stat types
            print("   Fetching defensive stats...")
            self._rate_limit()
            defense_df = fbref.read_player_season_stats(stat_type="defense")

            print("   Fetching passing stats...")
            self._rate_limit()
            passing_df = fbref.read_player_season_stats(stat_type="passing")

            print("   Fetching possession stats...")
            self._rate_limit()
            possession_df = fbref.read_player_season_stats(stat_type="possession")

            print("   Fetching goal/shot creation stats...")
            self._rate_limit()
            gca_df = fbref.read_player_season_stats(stat_type="goal_shot_creation")

            print("   Fetching standard stats...")
            self._rate_limit()
            standard_df = fbref.read_player_season_stats(stat_type="standard")

            print("   Fetching miscellaneous stats (recoveries)...")
            self._rate_limit()
            misc_df = fbref.read_player_season_stats(stat_type="misc")

            # Process and merge data
            processed = self._process_stats(
                defense_df, passing_df, possession_df, gca_df, standard_df, misc_df
            )

            # Cache the results
            if processed:
                self.cache.set(cache_key, processed, format="json")

            print(f"Fetched {len(processed)} players from FBRef")
            return processed

        except Exception as e:
            print(f"Error fetching FBRef data: {e}")
            import traceback
            traceback.print_exc()
            return []

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
