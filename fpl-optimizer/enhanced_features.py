"""
Enhanced Feature Pipeline
Merges FPL API data with Understat xG/xA data for improved predictions
"""

from typing import Dict, List, Optional, Tuple
from data_sources.understat_scraper import UnderstatScraper
from data_sources.data_cache import DataCache
from player_mapping.name_matcher import PlayerNameMatcher
import asyncio
from pathlib import Path


class EnhancedDataCollector:
    """Collect and merge FPL + Understat data"""

    def __init__(self, cache_ttl_hours: int = 6):
        """
        Initialize enhanced data collector

        Args:
            cache_ttl_hours: Cache time-to-live in hours
        """
        # Get the directory where this file lives
        base_dir = Path(__file__).parent

        self.understat_scraper = UnderstatScraper()
        self.cache = DataCache(cache_dir=str(base_dir / "cache"), ttl_hours=cache_ttl_hours)
        self.matcher = PlayerNameMatcher(
            manual_mappings_path=str(base_dir / "player_mapping" / "manual_mappings.json")
        )

    def fetch_understat_data(self, season: str = "2025", use_cache: bool = True) -> List[Dict]:
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

        # Cache it
        if players:
            self.cache.set(cache_key, players, format='json')

        return players

    def merge_player_data(
        self,
        fpl_player: Dict,
        understat_match: Optional[Dict]
    ) -> Dict:
        """
        Merge FPL player with Understat data

        Args:
            fpl_player: FPL player dict
            understat_match: Matched Understat player dict (or None)

        Returns:
            Enhanced player dict with all features
        """
        # Start with all FPL data
        enhanced = dict(fpl_player)

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

        return enhanced

    def collect_enhanced_data(
        self,
        fpl_players: List[Dict],
        season: str = "2025",
        use_cache: bool = True,
        match_threshold: int = 75
    ) -> Tuple[List[Dict], Dict]:
        """
        Collect and merge all player data

        Args:
            fpl_players: List of FPL player dicts
            season: Understat season (2025 = 2025/26 season)
            use_cache: Whether to use cached Understat data
            match_threshold: Name matching threshold (0-100)

        Returns:
            Tuple of (enhanced_players_list, stats_dict)
        """
        print("🚀 Starting enhanced data collection...")

        # Fetch Understat data
        understat_players = self.fetch_understat_data(season=season, use_cache=use_cache)

        if not understat_players:
            print("⚠️  No Understat data available, using FPL data only")
            # Return FPL players with default Understat values
            enhanced = [self.merge_player_data(p, None) for p in fpl_players]
            return enhanced, {'match_rate': 0.0, 'total': len(fpl_players), 'matched': 0}

        # Match players
        print(f"🔗 Matching {len(fpl_players)} FPL players to {len(understat_players)} Understat players...")
        self.matcher.clear_log()
        matched, unmatched = self.matcher.match_all_players(
            fpl_players,
            understat_players,
            threshold=match_threshold
        )

        # Get match statistics (moved up before using it)
        stats = self.matcher.get_match_stats()

        # Show which players were matched
        print(f"\n📋 Matched players breakdown:")
        for method, count in stats.get('methods', {}).items():
            print(f"   {method}: {count}")

        # Merge data
        enhanced_players = []
        for fpl_player in fpl_players:
            fpl_id = fpl_player['id']
            understat_match = matched.get(fpl_id)

            enhanced = self.merge_player_data(fpl_player, understat_match)
            enhanced_players.append(enhanced)

        print(f"✅ Enhanced data collection complete!")
        print(f"   Matched: {stats['matched']}/{stats['total']} ({stats['match_rate']}%)")
        print(f"   Methods: {stats.get('methods', {})}")

        if stats['unmatched'] > 0:
            print(f"\n⚠️  Unmatched players ({stats['unmatched']}):")
            for name in self.matcher.get_unmatched_players()[:10]:  # Show first 10
                print(f"   - {name}")
            if stats['unmatched'] > 10:
                print(f"   ... and {stats['unmatched'] - 10} more")

        return enhanced_players, stats

    def get_enhanced_player(
        self,
        player_id: int,
        fpl_players: List[Dict],
        season: str = "2025"
    ) -> Optional[Dict]:
        """
        Get a single enhanced player by FPL ID

        Args:
            player_id: FPL player ID
            fpl_players: List of all FPL players
            season: Understat season (2025 = 2025/26 season)

        Returns:
            Enhanced player dict or None
        """
        # Find FPL player
        fpl_player = next((p for p in fpl_players if p['id'] == player_id), None)
        if not fpl_player:
            return None

        # Get Understat data
        understat_players = self.fetch_understat_data(season=season)
        if not understat_players:
            return self.merge_player_data(fpl_player, None)

        # Match and merge
        understat_match = self.matcher.match_player(
            fpl_player,
            understat_players,
            team_id=fpl_player.get('team')
        )

        return self.merge_player_data(fpl_player, understat_match)


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
            season="2024",
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
