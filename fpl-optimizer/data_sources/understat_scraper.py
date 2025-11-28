"""
Understat Data Scraper
Fetches xG, xA, and advanced shooting stats from Understat.com
"""

from understatapi import UnderstatClient
import time
import json
from typing import Dict, List, Optional
from datetime import datetime


class UnderstatScraper:
    """Fetch xG and xA data from Understat"""

    def __init__(self):
        """Initialize the Understat scraper"""
        self.client = None
        self.last_request_time = 0
        self.rate_limit_delay = 1.5  # seconds between requests

    def _rate_limit(self):
        """Implement rate limiting to be respectful of Understat"""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time

        if time_since_last_request < self.rate_limit_delay:
            sleep_time = self.rate_limit_delay - time_since_last_request
            time.sleep(sleep_time)

        self.last_request_time = time.time()

    def fetch_epl_players(self, season: str = "2024") -> List[Dict]:
        """
        Get all EPL players with xG/xA stats from Understat

        Args:
            season: Season year (e.g., "2024" for 2024/25 season)

        Returns:
            List of player dictionaries with xG, xA, shots, etc.
        """
        try:
            self._rate_limit()

            with UnderstatClient() as client:
                print(f"🔍 Fetching Understat data for EPL {season}...")

                # Fetch player data
                players = client.league(league="EPL").get_player_data(season=season)

                # Process into clean format
                processed = []
                for player in players:
                    # Calculate per-90 stats
                    minutes = int(player.get('time', 0))
                    games_played = max(minutes / 90, 0.1)  # Avoid division by zero

                    xG = float(player.get('xG', 0))
                    xA = float(player.get('xA', 0))
                    goals = int(player.get('goals', 0))
                    assists = int(player.get('assists', 0))
                    shots = int(player.get('shots', 0))

                    processed.append({
                        'name': player.get('player_name', ''),
                        'team': player.get('team_title', ''),
                        'position': player.get('position', ''),
                        'games': int(player.get('games', 0)),
                        'minutes': minutes,
                        'xG': xG,
                        'xA': xA,
                        'xG_per_90': round(xG / games_played, 2),
                        'xA_per_90': round(xA / games_played, 2),
                        'goals': goals,
                        'assists': assists,
                        'shots': shots,
                        'shots_on_target': int(player.get('shots_on_target', 0)),
                        'key_passes': int(player.get('key_passes', 0)),
                        'xG_overperformance': round(goals - xG, 2),
                        'xA_overperformance': round(assists - xA, 2),
                    })

                print(f"✅ Fetched {len(processed)} players from Understat")
                return processed

        except Exception as e:
            print(f"❌ Error fetching Understat data: {e}")
            print(f"   This may be due to network issues or Understat API changes")
            return []

    def get_player_by_name(self, player_name: str, players: List[Dict]) -> Optional[Dict]:
        """
        Find a specific player by exact name match

        Args:
            player_name: Player's full name
            players: List of Understat player dicts

        Returns:
            Player dict if found, None otherwise
        """
        for player in players:
            if player['name'].lower() == player_name.lower():
                return player
        return None

    def save_to_cache(self, data: List[Dict], filename: str = "understat_cache.json"):
        """
        Save Understat data to JSON cache file

        Args:
            data: List of player dictionaries
            filename: Cache filename
        """
        try:
            cache_data = {
                'timestamp': datetime.now().isoformat(),
                'season': '2024',
                'players': data
            }

            with open(filename, 'w') as f:
                json.dump(cache_data, f, indent=2)

            print(f"💾 Saved {len(data)} players to {filename}")

        except Exception as e:
            print(f"❌ Error saving cache: {e}")

    def load_from_cache(self, filename: str = "understat_cache.json") -> Optional[List[Dict]]:
        """
        Load Understat data from JSON cache file

        Args:
            filename: Cache filename

        Returns:
            List of player dicts if cache exists and is valid, None otherwise
        """
        try:
            with open(filename, 'r') as f:
                cache_data = json.load(f)

            # Check if cache is fresh (< 6 hours old)
            timestamp = datetime.fromisoformat(cache_data['timestamp'])
            age_hours = (datetime.now() - timestamp).total_seconds() / 3600

            if age_hours < 6:
                print(f"✅ Loaded {len(cache_data['players'])} players from cache (age: {age_hours:.1f}h)")
                return cache_data['players']
            else:
                print(f"⏰ Cache expired (age: {age_hours:.1f}h), needs refresh")
                return None

        except FileNotFoundError:
            print(f"📁 No cache file found at {filename}")
            return None
        except Exception as e:
            print(f"❌ Error loading cache: {e}")
            return None


# Standalone testing
if __name__ == "__main__":
    scraper = UnderstatScraper()

    # Try loading from cache first
    players = scraper.load_from_cache()

    # If no cache or expired, fetch fresh data
    if players is None:
        players = scraper.fetch_epl_players(season="2024")
        if players:
            scraper.save_to_cache(players)

    # Show sample data
    if players:
        print(f"\n📊 Sample Understat Data (top 5 by xG):")
        print("-" * 80)

        # Sort by xG
        top_xg = sorted(players, key=lambda p: p['xG'], reverse=True)[:5]

        for i, player in enumerate(top_xg, 1):
            print(f"{i}. {player['name']:20} ({player['team']:15}) - "
                  f"xG: {player['xG']:.2f}, xA: {player['xA']:.2f}, "
                  f"Shots: {player['shots']}, Minutes: {player['minutes']}")
