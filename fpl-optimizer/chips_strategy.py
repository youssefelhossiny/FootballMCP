#!/usr/bin/env python3
"""
FPL Chips Strategy Analyzer
Recommends when to use Wildcard, Bench Boost, Triple Captain, Free Hit
"""

from typing import List, Dict, Tuple
import logging

logger = logging.getLogger(__name__)


class ChipsStrategyAnalyzer:
    """Analyzes when to use FPL chips for maximum benefit"""

    def __init__(self):
        self.chip_types = {
            'wildcard': 'Unlimited free transfers for one gameweek',
            'bench_boost': 'Points from all 15 players (inc. bench) count',
            'triple_captain': 'Captain points count 3x instead of 2x',
            'free_hit': 'Unlimited transfers for one GW, team reverts after'
        }

    def analyze_chips_strategy(
        self,
        available_chips: List[str],
        fixtures: List[Dict],
        teams: Dict,
        current_gw: int,
        num_gws: int = 10
    ) -> Dict:
        """
        Analyze optimal timing for chips

        Args:
            available_chips: List of chips still available
            fixtures: Upcoming fixtures
            teams: Team data
            current_gw: Current gameweek
            num_gws: Number of gameweeks to analyze ahead

        Returns:
            {
                'wildcard': {...},
                'bench_boost': {...},
                'triple_captain': {...},
                'free_hit': {...}
            }
        """
        analysis = {}

        # Identify double gameweeks and blank gameweeks
        dgws, bgws = self._identify_special_gameweeks(fixtures, current_gw, num_gws)

        # Analyze each chip
        if 'wildcard' in [c.lower() for c in available_chips]:
            analysis['wildcard'] = self._analyze_wildcard(fixtures, teams, current_gw, dgws, bgws, num_gws)

        if 'bench_boost' in [c.lower().replace('_', ' ') for c in available_chips] or \
           'bboost' in [c.lower() for c in available_chips]:
            analysis['bench_boost'] = self._analyze_bench_boost(fixtures, teams, current_gw, dgws, num_gws)

        if 'triple_captain' in [c.lower().replace('_', ' ') for c in available_chips] or \
           '3xc' in [c.lower() for c in available_chips]:
            analysis['triple_captain'] = self._analyze_triple_captain(fixtures, teams, current_gw, dgws, num_gws)

        if 'free_hit' in [c.lower().replace('_', ' ') for c in available_chips] or \
           'freehit' in [c.lower() for c in available_chips]:
            analysis['free_hit'] = self._analyze_free_hit(fixtures, teams, current_gw, bgws, dgws, num_gws)

        return analysis

    def _identify_special_gameweeks(
        self,
        fixtures: List[Dict],
        current_gw: int,
        num_gws: int
    ) -> Tuple[List[int], List[int]]:
        """Identify double gameweeks (DGW) and blank gameweeks (BGW)"""

        # Count fixtures per gameweek per team
        gw_fixtures = {}
        for gw in range(current_gw, current_gw + num_gws):
            gw_fixtures[gw] = set()

        for fixture in fixtures:
            gw = fixture.get('event')
            if gw and current_gw <= gw < current_gw + num_gws:
                gw_fixtures[gw].add(fixture['team_h'])
                gw_fixtures[gw].add(fixture['team_a'])

        # Identify DGWs (more than 20 teams playing means some have doubles)
        # and BGWs (fewer than 20 teams playing)
        dgws = []
        bgws = []

        for gw, teams in gw_fixtures.items():
            if len(teams) > 20:
                dgws.append(gw)
            elif len(teams) < 18:
                bgws.append(gw)

        return dgws, bgws

    def _analyze_wildcard(
        self,
        fixtures: List[Dict],
        teams: Dict,
        current_gw: int,
        dgws: List[int],
        bgws: List[int],
        num_gws: int
    ) -> Dict:
        """Recommend when to use Wildcard"""

        # Best times for wildcard:
        # 1. Before DGW to load up on doubles
        # 2. After BGW to rebuild
        # 3. When fixture swing happens (teams getting easy/hard runs)

        recommendations = []

        if dgws:
            first_dgw = min(dgws)
            recommendations.append({
                'gameweek': first_dgw - 1,
                'reason': f'Use before GW{first_dgw} Double Gameweek',
                'priority': 'HIGH',
                'benefit': 'Build team full of DGW players'
            })

        if bgws:
            first_bgw = min(bgws)
            recommendations.append({
                'gameweek': first_bgw + 1,
                'reason': f'Use after GW{first_bgw} Blank Gameweek',
                'priority': 'MEDIUM',
                'benefit': 'Rebuild team after blank'
            })

        # Default: use in next 2-3 weeks if team needs overhaul
        if not recommendations:
            recommendations.append({
                'gameweek': current_gw + 2,
                'reason': 'General squad overhaul',
                'priority': 'LOW',
                'benefit': 'Fix underperforming players and target good fixtures'
            })

        return {
            'available': True,
            'recommendations': recommendations,
            'best_gw': recommendations[0]['gameweek'] if recommendations else current_gw + 1
        }

    def _analyze_bench_boost(
        self,
        fixtures: List[Dict],
        teams: Dict,
        current_gw: int,
        dgws: List[int],
        num_gws: int
    ) -> Dict:
        """Recommend when to use Bench Boost"""

        # Best time: DGW when bench players also have doubles
        recommendations = []

        if dgws:
            for dgw in dgws:
                recommendations.append({
                    'gameweek': dgw,
                    'reason': f'Double Gameweek - bench players play twice',
                    'priority': 'HIGH',
                    'benefit': 'Maximize points from all 15 players'
                })

        if not recommendations:
            # If no DGW, use when bench has good fixtures
            recommendations.append({
                'gameweek': current_gw + 3,
                'reason': 'Good fixture run for bench-priced players',
                'priority': 'MEDIUM',
                'benefit': 'Extra points from budget bench options'
            })

        return {
            'available': True,
            'recommendations': recommendations,
            'best_gw': recommendations[0]['gameweek'] if recommendations else current_gw + 3,
            'tip': 'Only use if bench players are likely to play and have good fixtures'
        }

    def _analyze_triple_captain(
        self,
        fixtures: List[Dict],
        teams: Dict,
        current_gw: int,
        dgws: List[int],
        num_gws: int
    ) -> Dict:
        """Recommend when to use Triple Captain"""

        # Best time: DGW on premium captain option
        recommendations = []

        if dgws:
            for dgw in dgws:
                recommendations.append({
                    'gameweek': dgw,
                    'reason': 'Premium captain plays twice (DGW)',
                    'priority': 'VERY HIGH',
                    'benefit': '3x points on two games = potential 30+ points',
                    'target_players': 'Haaland, Salah, Son (whoever has DGW)'
                })

        if not recommendations:
            # Look for easy home fixtures for premium players
            recommendations.append({
                'gameweek': current_gw + 2,
                'reason': 'Premium player with easy home fixture',
                'priority': 'MEDIUM',
                'benefit': '3x points on likely high-scoring game'
            })

        return {
            'available': True,
            'recommendations': recommendations,
            'best_gw': recommendations[0]['gameweek'] if recommendations else current_gw + 2,
            'tip': 'Best used on DGW with Haaland/Salah type premium'
        }

    def _analyze_free_hit(
        self,
        fixtures: List[Dict],
        teams: Dict,
        current_gw: int,
        bgws: List[int],
        dgws: List[int],
        num_gws: int
    ) -> Dict:
        """Recommend when to use Free Hit"""

        # Best time: BGW when many teams don't play
        recommendations = []

        if bgws:
            for bgw in bgws:
                recommendations.append({
                    'gameweek': bgw,
                    'reason': 'Blank Gameweek - many teams not playing',
                    'priority': 'VERY HIGH',
                    'benefit': 'Build full team of playing teams for one week'
                })

        # Also good for one-week punts on DGW
        if dgws and not bgws:
            recommendations.append({
                'gameweek': dgws[0],
                'reason': 'One-week DGW team without permanent transfers',
                'priority': 'MEDIUM',
                'benefit': 'Full DGW team, reverts after'
            })

        if not recommendations:
            recommendations.append({
                'gameweek': current_gw + 4,
                'reason': 'Save for later BGW/DGW',
                'priority': 'LOW',
                'benefit': 'Flexibility for blank/double gameweeks'
            })

        return {
            'available': True,
            'recommendations': recommendations,
            'best_gw': recommendations[0]['gameweek'] if recommendations else None,
            'tip': 'Save for BGW (blank gameweek) when possible'
        }
