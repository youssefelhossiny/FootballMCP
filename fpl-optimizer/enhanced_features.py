"""
Enhanced Feature Pipeline
Merges FPL API data with Understat xG/xA data and FBRef defensive/progressive stats
for improved predictions

Phase 3: Understat integration (xG, xA, npxG, xGChain, xGBuildup)
Phase 4: FBRef integration (tackles, interceptions, blocks, clearances, progressive passes, SCA/GCA)
"""

import json
from typing import Dict, List, Optional, Tuple
from data_sources.understat_scraper import UnderstatScraper
from data_sources.fbref_scraper import FBRefScraper, CHAMPIONSHIP_LEAGUE
from data_sources.data_cache import DataCache
from player_mapping.name_matcher import PlayerNameMatcher, TEAM_MAPPING
from season_config import CURRENT_SEASON, PRIOR_SEASON, to_fbref, resolve_stats_season, display_label
import asyncio
from pathlib import Path


# FPL team IDs promoted into the EPL for 2026/27 (no prior EPL Understat/FBRef
# history — Championship data is the only available prior-season baseline).
# Understat has no Championship coverage at all, so these players only ever
# get an xG/xA baseline once they accrue real EPL minutes.
PROMOTED_TEAM_IDS = {7, 11, 12}  # Coventry City, Hull City, Ipswich Town


class EnhancedDataCollector:
    """Collect and merge FPL + Understat + FBRef data"""

    def __init__(self, cache_ttl_hours: int = 6):
        """
        Initialize enhanced data collector

        Args:
            cache_ttl_hours: Cache time-to-live in hours
        """
        # Get the directory where this file lives
        base_dir = Path(__file__).parent

        self.understat_scraper = UnderstatScraper()
        self.fbref_scraper = FBRefScraper(cache_dir=str(base_dir / "cache"))
        self.cache = DataCache(cache_dir=str(base_dir / "cache"), ttl_hours=cache_ttl_hours)
        mapping_dir = base_dir / "player_mapping"
        self.matcher = PlayerNameMatcher(
            manual_mappings_path=str(mapping_dir / "manual_mappings.json")
        )
        # FBRef needs its OWN overrides because the two sources spell the same
        # player differently, and one shared file cannot hold two targets for
        # one FPL name. Concretely: Understat calls him "Thiago" while FBRef
        # calls him "Igor Thiago"; pointing the shared mapping at the FBRef form
        # silently BREAKS the Understat match (verified — 'Igor Thiago' does not
        # exist in Understat's data at all). This matcher starts from the shared
        # file and layers FBRef-specific names on top.
        self.fbref_matcher = PlayerNameMatcher(
            manual_mappings_path=str(mapping_dir / "manual_mappings.json")
        )
        fbref_overrides = mapping_dir / "fbref_mappings.json"
        if fbref_overrides.exists():
            self.fbref_matcher.load_manual_mappings(str(fbref_overrides))

    def fetch_understat_data(self, season: str = CURRENT_SEASON, use_cache: bool = True) -> List[Dict]:
        """
        Fetch Understat data with caching

        Args:
            season: Season year (2025 = 2025/26 season)
            use_cache: Whether to use cached data if available

        Returns:
            List of Understat player dicts
        """
        cache_key = f"understat_epl_{season}"

        # Try cache first
        if use_cache:
            cached_data = self.cache.get(cache_key, format='json')
            if cached_data:
                return cached_data

        # Fetch fresh data
        print("📥 Fetching fresh Understat data...")
        players = self.understat_scraper.fetch_epl_players(season=season)

        # Cache it if successful
        if players:
            self.cache.set(cache_key, players, format='json')
            return players

        # FALLBACK: If fresh fetch failed, try to load stale cache
        print("⚠️ Fresh Understat fetch failed, trying stale cache...")
        stale_data = self.cache.get(cache_key, format='json', ignore_expiry=True)
        if stale_data:
            print(f"✅ Using stale Understat cache ({len(stale_data)} players)")
            return stale_data

        return []

    def fetch_fbref_data(self, season: str = None, use_cache: bool = True) -> List[Dict]:
        """
        Fetch FBRef defensive/progressive data with caching

        Args:
            season: Season in format "2024-2025"
            use_cache: Whether to use cached data if available

        Returns:
            List of FBRef player dicts with defensive/progressive stats
        """
        if season is None:
            season = to_fbref(CURRENT_SEASON)
        print("📥 Fetching FBRef data...")
        players = self.fbref_scraper.fetch_player_stats(season=season, use_cache=use_cache)
        return players

    def fetch_championship_fbref_data(self, season: str = None, use_cache: bool = True) -> List[Dict]:
        """
        Fetch prior-season Championship FBRef data — the baseline source for
        promoted-team players (see PROMOTED_TEAM_IDS) who have no EPL history.

        Args:
            season: Season in format "2025-2026". Defaults to the prior season.
            use_cache: Whether to use cached data if available

        Returns:
            List of FBRef player dicts (Championship), or [] if unavailable
        """
        if season is None:
            season = to_fbref(PRIOR_SEASON)
        print("📥 Fetching Championship FBRef data (promoted-team baseline)...")
        return self.fbref_scraper.fetch_player_stats(season=season, use_cache=use_cache, league=CHAMPIONSHIP_LEAGUE)

    def merge_player_data(
        self,
        fpl_player: Dict,
        understat_match: Optional[Dict],
        fbref_match: Optional[Dict] = None
    ) -> Dict:
        """
        Merge FPL player with Understat and FBRef data

        Data Sources:
        - FBRef: Used for PREDICTION (tackles, blocks, interceptions, clearances, recoveries per 90)
        - FPL: Used for ACTUAL DC points earned (validation/display only)

        Args:
            fpl_player: FPL player dict
            understat_match: Matched Understat player dict (or None)
            fbref_match: Matched FBRef player dict (or None)

        Returns:
            Enhanced player dict with all features
        """
        # Start with all FPL data
        enhanced = dict(fpl_player)

        # === FPL ACTUAL DC STATS (for validation/display) ===
        position = fpl_player.get('element_type', 3)
        minutes = int(fpl_player.get('minutes', 0) or 0)
        games_90 = max(minutes / 90, 0.1)

        # FPL actual defensive stats this season
        fpl_cbi = int(fpl_player.get('clearances_blocks_interceptions', 0) or 0)
        fpl_tackles = int(fpl_player.get('tackles', 0) or 0)
        fpl_recoveries = int(fpl_player.get('recoveries', 0) or 0)
        fpl_dc_points = int(fpl_player.get('defensive_contribution', 0) or 0)

        # Store actual FPL DC stats
        enhanced['fpl_cbi'] = fpl_cbi
        enhanced['fpl_tackles'] = fpl_tackles
        enhanced['fpl_recoveries'] = fpl_recoveries
        enhanced['fpl_dc_points'] = fpl_dc_points
        enhanced['fpl_recoveries_per_90'] = round(fpl_recoveries / games_90, 2) if games_90 > 0 else 0

        if understat_match:
            # Add core Understat features
            enhanced['xG'] = understat_match.get('xG', 0.0)
            enhanced['xA'] = understat_match.get('xA', 0.0)
            enhanced['npxG'] = understat_match.get('npxG', 0.0)
            enhanced['xGChain'] = understat_match.get('xGChain', 0.0)
            enhanced['xGBuildup'] = understat_match.get('xGBuildup', 0.0)

            # Per-90 stats
            enhanced['xG_per_90'] = understat_match.get('xG_per_90', 0.0)
            enhanced['xA_per_90'] = understat_match.get('xA_per_90', 0.0)
            enhanced['npxG_per_90'] = understat_match.get('npxG_per_90', 0.0)
            enhanced['xGChain_per_90'] = understat_match.get('xGChain_per_90', 0.0)
            enhanced['xGBuildup_per_90'] = understat_match.get('xGBuildup_per_90', 0.0)

            # Shooting and passing
            enhanced['shots'] = understat_match.get('shots', 0)
            enhanced['shots_on_target'] = understat_match.get('shots_on_target', 0)
            enhanced['key_passes'] = understat_match.get('key_passes', 0)

            # Over/underperformance
            enhanced['xG_overperformance'] = understat_match.get('xG_overperformance', 0.0)
            enhanced['xA_overperformance'] = understat_match.get('xA_overperformance', 0.0)
            enhanced['npxG_overperformance'] = understat_match.get('npxG_overperformance', 0.0)

            # Derived features
            enhanced['xG_xA_combined'] = enhanced['xG'] + enhanced['xA']
            enhanced['npxG_npxA_combined'] = enhanced['npxG'] + enhanced['xA']  # Non-penalty threat

            # Finishing quality (goals / xG, with safety checks)
            if enhanced['xG'] > 0:
                actual_goals = understat_match.get('goals', 0)
                enhanced['finishing_quality'] = round(actual_goals / enhanced['xG'], 2)
            else:
                enhanced['finishing_quality'] = 1.0  # Neutral

            # Non-penalty finishing quality
            if enhanced['npxG'] > 0:
                npg = understat_match.get('npg', 0)
                enhanced['np_finishing_quality'] = round(npg / enhanced['npxG'], 2)
            else:
                enhanced['np_finishing_quality'] = 1.0

        else:
            # No match - use position-based defaults
            position = fpl_player.get('element_type', 3)

            # Position defaults (conservative estimates)
            defaults = {
                1: {  # Goalkeepers
                    'xG': 0.0, 'xA': 0.0, 'npxG': 0.0, 'xGChain': 0.5, 'xGBuildup': 0.3,
                    'xG_per_90': 0.0, 'xA_per_90': 0.0, 'npxG_per_90': 0.0,
                    'xGChain_per_90': 0.05, 'xGBuildup_per_90': 0.03,
                    'shots': 0, 'shots_on_target': 0, 'key_passes': 0
                },
                2: {  # Defenders
                    'xG': 0.5, 'xA': 0.3, 'npxG': 0.4, 'xGChain': 2.0, 'xGBuildup': 1.5,
                    'xG_per_90': 0.08, 'xA_per_90': 0.05, 'npxG_per_90': 0.06,
                    'xGChain_per_90': 0.25, 'xGBuildup_per_90': 0.18,
                    'shots': 5, 'shots_on_target': 2, 'key_passes': 3
                },
                3: {  # Midfielders
                    'xG': 1.5, 'xA': 1.0, 'npxG': 1.2, 'xGChain': 5.0, 'xGBuildup': 3.5,
                    'xG_per_90': 0.15, 'xA_per_90': 0.10, 'npxG_per_90': 0.12,
                    'xGChain_per_90': 0.50, 'xGBuildup_per_90': 0.35,
                    'shots': 15, 'shots_on_target': 6, 'key_passes': 10
                },
                4: {  # Forwards
                    'xG': 3.0, 'xA': 0.8, 'npxG': 2.5, 'xGChain': 6.0, 'xGBuildup': 2.0,
                    'xG_per_90': 0.35, 'xA_per_90': 0.08, 'npxG_per_90': 0.30,
                    'xGChain_per_90': 0.60, 'xGBuildup_per_90': 0.20,
                    'shots': 25, 'shots_on_target': 12, 'key_passes': 5
                }
            }

            position_defaults = defaults.get(position, defaults[3])

            for key, value in position_defaults.items():
                enhanced[key] = value

            enhanced['xG_overperformance'] = 0.0
            enhanced['xA_overperformance'] = 0.0
            enhanced['npxG_overperformance'] = 0.0
            enhanced['xG_xA_combined'] = enhanced['xG'] + enhanced['xA']
            enhanced['npxG_npxA_combined'] = enhanced['npxG'] + enhanced['xA']
            enhanced['finishing_quality'] = 1.0
            enhanced['np_finishing_quality'] = 1.0

        # Add FBRef data (Phase 4)
        if fbref_match:
            # Defensive stats (critical for FPL defensive contribution points)
            enhanced['tackles'] = fbref_match.get('tackles', 0)
            enhanced['tackles_won'] = fbref_match.get('tackles_won', 0)
            enhanced['tackle_pct'] = fbref_match.get('tackle_pct', 0.0)
            enhanced['interceptions'] = fbref_match.get('interceptions', 0)
            enhanced['tackles_plus_int'] = fbref_match.get('tackles_plus_int', 0)
            enhanced['blocks'] = fbref_match.get('blocks', 0)
            enhanced['clearances'] = fbref_match.get('clearances', 0)
            enhanced['errors'] = fbref_match.get('errors', 0)

            # FPL Defensive Contribution calculation (base - without recoveries)
            enhanced['def_contributions'] = fbref_match.get('def_contributions', 0)
            enhanced['def_contributions_per_90'] = fbref_match.get('def_contributions_per_90', 0.0)

            # Progressive stats
            enhanced['progressive_passes'] = fbref_match.get('progressive_passes', 0)
            enhanced['progressive_carries'] = fbref_match.get('progressive_carries', 0)
            enhanced['progressive_receptions'] = fbref_match.get('progressive_receptions', 0)
            enhanced['progressive_passes_per_90'] = fbref_match.get('progressive_passes_per_90', 0.0)
            enhanced['progressive_carries_per_90'] = fbref_match.get('progressive_carries_per_90', 0.0)
            enhanced['progressive_receptions_per_90'] = fbref_match.get('progressive_receptions_per_90', 0.0)

            # Possession/Creation stats
            enhanced['touches'] = fbref_match.get('touches', 0)
            enhanced['touches_att_3rd'] = fbref_match.get('touches_att_3rd', 0)
            enhanced['sca'] = fbref_match.get('sca', 0)
            enhanced['gca'] = fbref_match.get('gca', 0)
            enhanced['sca_per_90'] = fbref_match.get('sca_per_90', 0.0)
            enhanced['gca_per_90'] = fbref_match.get('gca_per_90', 0.0)

            # Miscellaneous stats (recoveries critical for MID/FWD DC prediction)
            enhanced['fbref_recoveries'] = fbref_match.get('recoveries', 0)
            enhanced['fbref_recoveries_per_90'] = fbref_match.get('recoveries_per_90', 0.0)

            # === PREDICTED DC calculation using FBRef data ===
            # DEF: CBI + Tackles (no recoveries)
            # MID/FWD: CBI + Tackles + Recoveries
            base_dc_per_90 = enhanced['def_contributions_per_90']
            if position in [3, 4]:  # MID or FWD - add recoveries
                enhanced['predicted_dc_per_90'] = base_dc_per_90 + enhanced['fbref_recoveries_per_90']
            else:
                enhanced['predicted_dc_per_90'] = base_dc_per_90

            # Recalculate probability using predicted DC
            enhanced['def_contribution_prob'] = self._calc_def_contribution_prob(
                enhanced['predicted_dc_per_90'], position
            )
            enhanced['expected_def_points'] = round(enhanced['def_contribution_prob'] * 2, 2)

        else:
            # No FBRef match - use position-based defaults
            position = fpl_player.get('element_type', 3)

            fbref_defaults = {
                1: {  # Goalkeepers
                    'tackles': 0, 'tackles_won': 0, 'tackle_pct': 0.0,
                    'interceptions': 2, 'tackles_plus_int': 2, 'blocks': 5, 'clearances': 10, 'errors': 0,
                    'def_contributions': 17, 'def_contributions_per_90': 1.5,
                    'fbref_recoveries': 10, 'fbref_recoveries_per_90': 0.8,
                    'progressive_passes': 50, 'progressive_carries': 5, 'progressive_receptions': 0,
                    'progressive_passes_per_90': 4.0, 'progressive_carries_per_90': 0.4, 'progressive_receptions_per_90': 0.0,
                    'touches': 400, 'touches_att_3rd': 0, 'sca': 5, 'gca': 0, 'sca_per_90': 0.4, 'gca_per_90': 0.0
                },
                2: {  # Defenders - no recoveries in DC calculation
                    'tackles': 25, 'tackles_won': 15, 'tackle_pct': 60.0,
                    'interceptions': 20, 'tackles_plus_int': 45, 'blocks': 20, 'clearances': 50, 'errors': 1,
                    'def_contributions': 115, 'def_contributions_per_90': 8.0,
                    'fbref_recoveries': 60, 'fbref_recoveries_per_90': 4.5,
                    'progressive_passes': 80, 'progressive_carries': 30, 'progressive_receptions': 20,
                    'progressive_passes_per_90': 5.5, 'progressive_carries_per_90': 2.0, 'progressive_receptions_per_90': 1.4,
                    'touches': 800, 'touches_att_3rd': 50, 'sca': 20, 'gca': 2, 'sca_per_90': 1.4, 'gca_per_90': 0.14
                },
                3: {  # Midfielders - recoveries added to DC
                    'tackles': 30, 'tackles_won': 18, 'tackle_pct': 55.0,
                    'interceptions': 15, 'tackles_plus_int': 45, 'blocks': 15, 'clearances': 15, 'errors': 1,
                    'def_contributions': 75, 'def_contributions_per_90': 5.5,
                    'fbref_recoveries': 80, 'fbref_recoveries_per_90': 6.0,
                    'progressive_passes': 100, 'progressive_carries': 50, 'progressive_receptions': 60,
                    'progressive_passes_per_90': 7.0, 'progressive_carries_per_90': 3.5, 'progressive_receptions_per_90': 4.2,
                    'touches': 900, 'touches_att_3rd': 150, 'sca': 50, 'gca': 5, 'sca_per_90': 3.5, 'gca_per_90': 0.35
                },
                4: {  # Forwards - recoveries added to DC
                    'tackles': 10, 'tackles_won': 5, 'tackle_pct': 40.0,
                    'interceptions': 5, 'tackles_plus_int': 15, 'blocks': 5, 'clearances': 5, 'errors': 0,
                    'def_contributions': 25, 'def_contributions_per_90': 2.0,
                    'fbref_recoveries': 50, 'fbref_recoveries_per_90': 4.0,
                    'progressive_passes': 30, 'progressive_carries': 40, 'progressive_receptions': 80,
                    'progressive_passes_per_90': 2.5, 'progressive_carries_per_90': 3.3, 'progressive_receptions_per_90': 6.7,
                    'touches': 500, 'touches_att_3rd': 200, 'sca': 40, 'gca': 8, 'sca_per_90': 3.3, 'gca_per_90': 0.67
                }
            }

            pos_defaults = fbref_defaults.get(position, fbref_defaults[3])
            for key, value in pos_defaults.items():
                enhanced[key] = value

            # Calculate predicted DC (add recoveries for MID/FWD)
            base_dc_per_90 = enhanced['def_contributions_per_90']
            if position in [3, 4]:  # MID or FWD - add recoveries
                enhanced['predicted_dc_per_90'] = base_dc_per_90 + enhanced['fbref_recoveries_per_90']
            else:
                enhanced['predicted_dc_per_90'] = base_dc_per_90

            # Calculate defensive contribution probability using predicted DC
            enhanced['def_contribution_prob'] = self._calc_def_contribution_prob(
                enhanced['predicted_dc_per_90'], position
            )
            enhanced['expected_def_points'] = round(enhanced['def_contribution_prob'] * 2, 2)

        return enhanced

    def _calc_def_contribution_prob(self, def_per_90: float, position: int) -> float:
        """
        Calculate probability of earning FPL defensive contribution points

        FPL Rules (2025/26):
        - Defenders: 10 contributions = 2 pts
        - Midfielders/Forwards: 12 contributions = 2 pts
        - Max: 2 pts per match

        Args:
            def_per_90: Average defensive contributions per 90
            position: FPL position (1=GK, 2=DEF, 3=MID, 4=FWD)

        Returns:
            Probability (0-1) of earning the 2pt bonus per match
        """
        # Threshold based on position
        threshold = 10 if position == 2 else 12

        # Probability model based on how close to threshold
        if def_per_90 >= threshold:
            return 0.85  # High probability but not guaranteed
        elif def_per_90 >= threshold * 0.8:
            return 0.5  # Good chance
        elif def_per_90 >= threshold * 0.6:
            return 0.25  # Some chance
        elif def_per_90 >= threshold * 0.4:
            return 0.1  # Low chance
        else:
            return 0.02  # Very unlikely

    def collect_enhanced_data(
        self,
        fpl_players: List[Dict],
        season: str = None,
        use_cache: bool = True,
        match_threshold: int = 75
    ) -> Tuple[List[Dict], Dict]:
        """
        Collect and merge all player data (FPL + Understat + FBRef)

        Args:
            fpl_players: List of FPL player dicts
            season: Understat season year (e.g. "2026" = 2026/27). If None,
                auto-detects: uses the current season when advanced-stat data
                exists, otherwise falls back to the prior season as a baseline.
            use_cache: Whether to use cached data
            match_threshold: Name matching threshold (0-100)

        Returns:
            Tuple of (enhanced_players_list, stats_dict)
        """
        print("🚀 Starting enhanced data collection (Phase 4)...")

        # Resolve which season's advanced stats to use (auto-detect w/ fallback).
        # Understat and FBRef are resolved INDEPENDENTLY — they don't publish
        # on the same schedule (FBRef has been observed to have current-season
        # data while Understat is still empty), so locking FBRef to whatever
        # season Understat resolved to under-uses FBRef's freshest data.
        if season is None:
            understat_season, understat_players = resolve_stats_season(
                self.fetch_understat_data, use_cache=use_cache
            )
        else:
            understat_season = season
            understat_players = self.fetch_understat_data(season=season, use_cache=use_cache)

        def _fetch_fbref_for_year(year: str, use_cache: bool) -> List[Dict]:
            return self.fetch_fbref_data(season=to_fbref(year), use_cache=use_cache)

        if season is None:
            fbref_season, fbref_players = resolve_stats_season(
                _fetch_fbref_for_year, use_cache=use_cache
            )
        else:
            fbref_season = season
            fbref_players = _fetch_fbref_for_year(season, use_cache)

        print(
            f"📊 Advanced stats season — Understat: {display_label(understat_season)}, "
            f"FBRef: {display_label(fbref_season)}"
        )
        season = understat_season  # kept for the return-value contract below

        if not understat_players:
            print("⚠️  No Understat data available")
        if not fbref_players:
            print("⚠️  No FBRef data available")

        if not understat_players and not fbref_players:
            print("⚠️  No external data available, using FPL data only")
            enhanced = [self.merge_player_data(p, None, None) for p in fpl_players]
            return enhanced, {'match_rate': 0.0, 'total': len(fpl_players), 'matched': 0}

        # Match Understat players
        matched_understat = {}
        understat_unmatched = []
        understat_stats = {'matched': 0, 'total': len(fpl_players), 'match_rate': 0.0}
        if understat_players:
            print(f"🔗 Matching {len(fpl_players)} FPL players to {len(understat_players)} Understat players...")
            self.matcher.clear_log()
            matched_understat, understat_unmatched = self.matcher.match_all_players(
                fpl_players,
                understat_players,
                threshold=match_threshold
            )
            understat_stats = self.matcher.get_match_stats()

        # Match FBRef players using same fuzzy matching logic
        matched_fbref = {}
        fbref_unmatched = []
        if fbref_players:
            print(f"🔗 Matching {len(fpl_players)} FPL players to {len(fbref_players)} FBRef players...")
            # fbref_matcher, not matcher — FBRef spells some players
            # differently from Understat (see __init__).
            self.fbref_matcher.clear_log()
            matched_fbref, fbref_unmatched = self.fbref_matcher.match_all_players(
                fpl_players,
                fbref_players,
                threshold=match_threshold
            )

            # Promoted teams (Coventry/Hull/Ipswich) have zero EPL FBRef
            # history — retry their unmatched players against prior-season
            # Championship data instead, so they still get a defensive/
            # progressive-stats baseline rather than showing as invisible.
            promoted_unmatched = [
                p for p in fbref_unmatched if p.get('team') in PROMOTED_TEAM_IDS
            ]
            if promoted_unmatched:
                championship_players = self.fetch_championship_fbref_data(use_cache=use_cache)
                if championship_players:
                    print(
                        f"🔗 Retrying {len(promoted_unmatched)} promoted-team players against "
                        f"{len(championship_players)} Championship FBRef players..."
                    )
                    # Championship data is also FBRef, so it needs the FBRef
                    # spelling overrides too.
                    self.fbref_matcher.clear_log()
                    matched_championship, still_unmatched = self.fbref_matcher.match_all_players(
                        promoted_unmatched,
                        championship_players,
                        threshold=match_threshold
                    )
                    matched_fbref.update(matched_championship)
                    still_unmatched_ids = {p['id'] for p in still_unmatched}
                    fbref_unmatched = [
                        p for p in fbref_unmatched
                        if p.get('team') not in PROMOTED_TEAM_IDS or p['id'] in still_unmatched_ids
                    ]

        # Use Understat's stats as the headline match rate (kept for
        # backwards compatibility with callers reading stats['match_rate']),
        # but track both sources' unmatched lists explicitly rather than via
        # the matcher's shared mutable log (which gets overwritten above).
        stats = understat_stats

        # Show which players were matched
        if stats.get('methods'):
            print(f"\n📋 Understat match breakdown:")
            for method, count in stats.get('methods', {}).items():
                print(f"   {method}: {count}")

        # Merge data
        enhanced_players = []
        fbref_matched = len(matched_fbref)

        for fpl_player in fpl_players:
            fpl_id = fpl_player['id']
            understat_match = matched_understat.get(fpl_id)
            fbref_match = matched_fbref.get(fpl_id)

            enhanced = self.merge_player_data(fpl_player, understat_match, fbref_match)
            enhanced_players.append(enhanced)

        # Update stats with FBRef info
        stats['fbref_matched'] = fbref_matched
        stats['fbref_match_rate'] = round(fbref_matched / len(fpl_players) * 100, 1) if fpl_players else 0

        print(f"\n✅ Enhanced data collection complete!")
        print(f"   Understat: {stats['matched']}/{stats['total']} ({stats['match_rate']}%)")
        print(f"   FBRef: {fbref_matched}/{len(fpl_players)} ({stats['fbref_match_rate']}%)")

        if understat_unmatched:
            print(f"\n⚠️  Understat-unmatched players ({len(understat_unmatched)}):")
            for p in understat_unmatched[:10]:
                print(f"   - {p.get('first_name', '')} {p.get('second_name', '')}")
            if len(understat_unmatched) > 10:
                print(f"   ... and {len(understat_unmatched) - 10} more")

        self._write_unmatched_report(understat_unmatched, fbref_unmatched, stats, season)

        return enhanced_players, stats

    def _write_unmatched_report(
        self,
        understat_unmatched: List[Dict],
        fbref_unmatched: List[Dict],
        stats: Dict,
        season: str
    ):
        """
        Persist the list of FPL players that couldn't be matched to Understat
        and/or FBRef, so match-rate gaps are visible without re-running the
        pipeline with console output captured (previously console-print only).

        Written to cache/unmatched_players.json, overwritten on every run.
        """
        def _describe(p: Dict) -> Dict:
            return {
                'id': p.get('id'),
                'name': f"{p.get('first_name', '')} {p.get('second_name', '')}".strip(),
                'web_name': p.get('web_name', ''),
                'team': p.get('team'),
                'is_promoted_team': p.get('team') in PROMOTED_TEAM_IDS,
            }

        report = {
            'season': season,
            'total_fpl_players': stats.get('total', 0),
            'understat_match_rate': stats.get('match_rate', 0.0),
            'fbref_match_rate': stats.get('fbref_match_rate', 0.0),
            'understat_unmatched_count': len(understat_unmatched),
            'fbref_unmatched_count': len(fbref_unmatched),
            'understat_unmatched': [_describe(p) for p in understat_unmatched],
            'fbref_unmatched': [_describe(p) for p in fbref_unmatched],
        }

        try:
            self.cache.cache_dir.mkdir(parents=True, exist_ok=True)
            report_path = self.cache.cache_dir / "unmatched_players.json"
            with open(report_path, 'w') as f:
                json.dump(report, f, indent=2)
        except Exception as e:
            print(f"⚠️  Failed to write unmatched-players report: {e}")

    def get_enhanced_player(
        self,
        player_id: int,
        fpl_players: List[Dict],
        season: str = None
    ) -> Optional[Dict]:
        """
        Get a single enhanced player by FPL ID

        Args:
            player_id: FPL player ID
            fpl_players: List of all FPL players
            season: Understat season year (e.g. "2026"). If None, auto-detects
                current season with prior-season fallback.

        Returns:
            Enhanced player dict or None
        """
        # Find FPL player
        fpl_player = next((p for p in fpl_players if p['id'] == player_id), None)
        if not fpl_player:
            return None

        # Resolve season (auto-detect w/ fallback) and get Understat data
        auto_detect = season is None
        if auto_detect:
            season, understat_players = resolve_stats_season(self.fetch_understat_data)
        else:
            understat_players = self.fetch_understat_data(season=season)

        # Resolve FBRef's season independently — it doesn't publish on the
        # same schedule as Understat (see collect_enhanced_data for detail).
        if auto_detect:
            _, fbref_players = resolve_stats_season(
                lambda year, use_cache: self.fetch_fbref_data(season=to_fbref(year), use_cache=use_cache)
            )
        else:
            fbref_season = to_fbref(season) if len(season) == 4 else season
            fbref_players = self.fetch_fbref_data(season=fbref_season)

        # Match Understat
        understat_match = None
        if understat_players:
            understat_match = self.matcher.match_player(
                fpl_player,
                understat_players,
                team_id=fpl_player.get('team')
            )

        # Match FBRef using fuzzy matching
        fbref_match = None
        if fbref_players:
            fbref_match = self.fbref_matcher.match_player(
                fpl_player,
                fbref_players,
                team_id=fpl_player.get('team')
            )

        return self.merge_player_data(fpl_player, understat_match, fbref_match)


# Testing
if __name__ == "__main__":
    import httpx
    import asyncio

    async def test_enhanced_data():
        # Fetch FPL data
        print("Fetching FPL data...")
        async with httpx.AsyncClient() as client:
            response = await client.get("https://fantasy.premierleague.com/api/bootstrap-static/")
            bootstrap = response.json()

        fpl_players = bootstrap['elements'][:50]  # Test with first 50 players

        # Collect enhanced data
        collector = EnhancedDataCollector(cache_ttl_hours=6)
        enhanced_players, stats = collector.collect_enhanced_data(
            fpl_players,
            season="2025",
            use_cache=True
        )

        # Show sample enhanced data
        print(f"\n📊 Sample Enhanced Players:")
        print("-" * 100)

        # Find some high xG players
        sorted_by_xg = sorted(enhanced_players, key=lambda p: p.get('xG', 0), reverse=True)[:5]

        for i, player in enumerate(sorted_by_xg, 1):
            name = f"{player.get('first_name', '')} {player.get('second_name', '')}"
            print(f"{i}. {name:25} - "
                  f"xG: {player.get('xG', 0):.2f}, "
                  f"xA: {player.get('xA', 0):.2f}, "
                  f"Shots: {player.get('shots', 0):3d}, "
                  f"Finishing: {player.get('finishing_quality', 1.0):.2f}")

        print(f"\n✅ Test complete!")

    # Run test
    asyncio.run(test_enhanced_data())
