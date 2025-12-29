"""
Availability Filter
Filters players based on injury/availability status from FPL API

FPL API provides:
- chance_of_playing_next_round (0-100%)
- chance_of_playing_this_round (0-100%)
- status: a=available, d=doubtful, i=injured, s=suspended, u=unavailable, n=not_in_squad
- news: injury description text
- news_added: timestamp of when news was added
"""

from typing import Dict, List, Optional
from datetime import datetime


class AvailabilityFilter:
    """Filter and analyze player availability for FPL"""

    STATUS_MAP = {
        'a': 'available',
        'd': 'doubtful',
        'i': 'injured',
        's': 'suspended',
        'u': 'unavailable',
        'n': 'not_in_squad'
    }

    # Status codes that mean player definitely won't play
    UNAVAILABLE_STATUSES = {'i', 's', 'u', 'n'}

    def __init__(self, min_chance_default: int = 75):
        """
        Initialize the availability filter

        Args:
            min_chance_default: Default minimum chance of playing (0-100)
        """
        self.min_chance_default = min_chance_default

    def is_likely_to_play(self, player: Dict, min_chance: int = None) -> bool:
        """
        Check if a player is likely to play next gameweek

        Args:
            player: Player dict from FPL API
            min_chance: Minimum chance threshold (uses default if None)

        Returns:
            True if player is likely to play
        """
        if min_chance is None:
            min_chance = self.min_chance_default

        status = player.get('status', 'a')

        # Definitely unavailable
        if status in self.UNAVAILABLE_STATUSES:
            return False

        # Check chance of playing
        chance = player.get('chance_of_playing_next_round')

        # None means no injury news (100% available)
        if chance is None:
            return True

        return chance >= min_chance

    def filter_available_players(
        self,
        players: List[Dict],
        min_chance: int = None
    ) -> List[Dict]:
        """
        Filter players to only those likely to play

        Args:
            players: List of player dicts
            min_chance: Minimum chance threshold

        Returns:
            List of available players
        """
        return [p for p in players if self.is_likely_to_play(p, min_chance)]

    def get_availability_info(self, player: Dict) -> Dict:
        """
        Get detailed availability information for a player

        Args:
            player: Player dict from FPL API

        Returns:
            Dict with availability details
        """
        status_code = player.get('status', 'a')
        chance_next = player.get('chance_of_playing_next_round')
        chance_this = player.get('chance_of_playing_this_round')
        news = player.get('news', '')
        news_added = player.get('news_added')

        # Parse news_added timestamp if present
        news_date = None
        if news_added:
            try:
                news_date = datetime.fromisoformat(news_added.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                pass

        return {
            'status': self.STATUS_MAP.get(status_code, 'unknown'),
            'status_code': status_code,
            'chance_next_round': chance_next if chance_next is not None else 100,
            'chance_this_round': chance_this if chance_this is not None else 100,
            'news': news,
            'news_date': news_date.isoformat() if news_date else None,
            'is_available': status_code not in self.UNAVAILABLE_STATUSES,
            'has_doubt': status_code == 'd' or (chance_next is not None and chance_next < 100)
        }

    def get_injury_report(self, players: List[Dict]) -> Dict:
        """
        Generate an injury report for all players

        Args:
            players: List of player dicts

        Returns:
            Dict with categorized players by status
        """
        report = {
            'injured': [],
            'suspended': [],
            'doubtful': [],
            'available': []
        }

        for player in players:
            info = self.get_availability_info(player)
            name = f"{player.get('first_name', '')} {player.get('second_name', '')}".strip()

            entry = {
                'id': player.get('id'),
                'name': name,
                'web_name': player.get('web_name', ''),
                'team': player.get('team'),
                'chance': info['chance_next_round'],
                'news': info['news']
            }

            status = info['status']
            if status == 'injured':
                report['injured'].append(entry)
            elif status == 'suspended':
                report['suspended'].append(entry)
            elif status == 'doubtful' or info['has_doubt']:
                report['doubtful'].append(entry)
            else:
                report['available'].append(entry)

        return report

    def get_transfer_risks(
        self,
        team_players: List[Dict],
        all_players: List[Dict]
    ) -> List[Dict]:
        """
        Identify players in a team that are at risk of not playing

        Args:
            team_players: List of player IDs in user's team
            all_players: List of all players from FPL API

        Returns:
            List of at-risk players with recommendations
        """
        # Build lookup dict
        player_lookup = {p['id']: p for p in all_players}

        risks = []
        for player_id in team_players:
            player = player_lookup.get(player_id)
            if not player:
                continue

            info = self.get_availability_info(player)

            # Only flag if there's actual doubt
            if not info['is_available'] or info['has_doubt']:
                name = f"{player.get('first_name', '')} {player.get('second_name', '')}".strip()

                risks.append({
                    'id': player_id,
                    'name': name,
                    'web_name': player.get('web_name', ''),
                    'status': info['status'],
                    'chance': info['chance_next_round'],
                    'news': info['news'],
                    'should_transfer': info['chance_next_round'] < 50 or not info['is_available'],
                    'priority': self._calculate_risk_priority(info)
                })

        # Sort by priority (highest first)
        risks.sort(key=lambda x: x['priority'], reverse=True)
        return risks

    def _calculate_risk_priority(self, info: Dict) -> int:
        """Calculate priority score for transfer risk (higher = more urgent)"""
        score = 0

        if not info['is_available']:
            score += 100  # Definitely out

        if info['status'] == 'suspended':
            score += 50  # Suspensions are certain

        # Lower chance = higher priority
        chance = info['chance_next_round']
        if chance == 0:
            score += 80
        elif chance <= 25:
            score += 60
        elif chance <= 50:
            score += 40
        elif chance <= 75:
            score += 20

        return score


# Testing
if __name__ == "__main__":
    # Test with sample data
    filter = AvailabilityFilter()

    sample_players = [
        {
            'id': 1,
            'first_name': 'Mohamed',
            'second_name': 'Salah',
            'web_name': 'Salah',
            'team': 12,
            'status': 'a',
            'chance_of_playing_next_round': None,
            'news': ''
        },
        {
            'id': 2,
            'first_name': 'Diogo',
            'second_name': 'Jota',
            'web_name': 'Jota',
            'team': 12,
            'status': 'd',
            'chance_of_playing_next_round': 50,
            'news': 'Knee injury - 50% chance of playing'
        },
        {
            'id': 3,
            'first_name': 'Gabriel',
            'second_name': 'Jesus',
            'web_name': 'Jesus',
            'team': 1,
            'status': 'i',
            'chance_of_playing_next_round': 0,
            'news': 'ACL injury - expected return March'
        }
    ]

    print("Availability Filter Test")
    print("=" * 50)

    # Test filtering
    available = filter.filter_available_players(sample_players)
    print(f"\nAvailable players: {len(available)}")
    for p in available:
        print(f"  - {p['web_name']}")

    # Test individual info
    print("\nPlayer availability details:")
    for player in sample_players:
        info = filter.get_availability_info(player)
        print(f"\n{player['web_name']}:")
        print(f"  Status: {info['status']}")
        print(f"  Chance: {info['chance_next_round']}%")
        print(f"  News: {info['news'] or 'No news'}")
        print(f"  Likely to play: {filter.is_likely_to_play(player)}")

    # Test injury report
    print("\nInjury Report:")
    report = filter.get_injury_report(sample_players)
    for category, players in report.items():
        if players:
            print(f"\n{category.upper()}:")
            for p in players:
                print(f"  - {p['web_name']}: {p['news'] or 'No details'}")
