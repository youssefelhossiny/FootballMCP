#!/usr/bin/env python3
"""
FPL Bot Decision Maker
Autonomous decision-making for FPL team management.

This module handles:
1. Weekly transfer decisions using ML predictions
2. Chip strategy evaluation (Wildcard, Free Hit, Bench Boost, Triple Captain)
3. Captain/Vice-Captain selection
4. Lineup optimization

The bot runs twice before each gameweek deadline:
1. Early run: When price changes are imminent for target players
2. Final run: Before deadline with latest injury/team news

Chip Strategy (2025/26 Season):
- Chips reset at GW19 - must use first batch before then
- Second batch available GW20-38
- Only ONE chip per gameweek

Sources:
- https://www.premierleague.com/en/news/4362085
- https://www.nevermanagealone.com/playerpicks/14801/fpl-chip-strategy
- https://www.fantasyfootballpundit.com/best-fpl-chip-strategy-2025-26-gw1-to-gw19/
"""

import asyncio
import aiohttp
import ssl
import certifi
import os
import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
import logging
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ChipType(Enum):
    WILDCARD = "wildcard"
    FREE_HIT = "freehit"
    BENCH_BOOST = "bboost"
    TRIPLE_CAPTAIN = "3xc"


@dataclass
class ChipRecommendation:
    chip: ChipType
    score: float  # 0-100, higher = more recommended
    reasons: List[str]
    should_play: bool


@dataclass
class TransferRecommendation:
    player_out_id: int
    player_out_name: str
    player_in_id: int
    player_in_name: str
    priority: int  # 1 = highest priority
    reasons: List[str]
    expected_points_gain: float
    price_change_risk: bool  # True if player price is about to change


@dataclass
class BotDecision:
    gameweek: int
    timestamp: datetime
    transfers: List[TransferRecommendation]
    chip_recommendation: Optional[ChipRecommendation]
    captain_id: int
    captain_name: str
    vice_captain_id: int
    vice_captain_name: str
    lineup_changes: List[Dict]  # Bench/starting changes
    reasoning: str
    price_changes: Dict  # Rising and falling players
    squad_price_risks: List[Dict]  # Price risks for current squad


class BotDecisionMaker:
    """
    Autonomous FPL decision maker.

    Runs before each gameweek deadline to:
    1. Evaluate current squad health (injuries, form, fixtures)
    2. Suggest transfers based on ML predictions
    3. Evaluate chip usage opportunities
    4. Select captain and optimize lineup
    """

    def __init__(self, team_id: int, email: str = None, password: str = None):
        self.team_id = team_id
        self.email = email or os.getenv("FPL_BOT_EMAIL")
        self.password = password or os.getenv("FPL_BOT_PASSWORD")
        self.session = None
        self.bootstrap_data = None
        self.team_data = None
        self.fixtures_data = None

        # Chip usage tracking
        self.chips_used = {
            'wildcard': {'used': False, 'gameweek': None},
            'freehit': {'used': False, 'gameweek': None},
            'bboost': {'used': False, 'gameweek': None},
            '3xc': {'used': False, 'gameweek': None}
        }

        # Price change tracking
        self.price_change_predictions = {}

    def get_ssl_context(self):
        """Get SSL context for HTTPS requests."""
        return ssl.create_default_context(cafile=certifi.where())

    async def initialize(self):
        """Initialize session and fetch required data."""
        ssl_context = self.get_ssl_context()
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        self.session = aiohttp.ClientSession(connector=connector)

        # Fetch bootstrap data (all players, teams, events)
        async with self.session.get("https://fantasy.premierleague.com/api/bootstrap-static/") as resp:
            self.bootstrap_data = await resp.json()

        # Fetch fixtures
        async with self.session.get("https://fantasy.premierleague.com/api/fixtures/") as resp:
            self.fixtures_data = await resp.json()

        # Fetch team data
        await self.fetch_team_data()

        logger.info(f"Bot initialized for team {self.team_id}")

    async def close(self):
        """Close the session."""
        if self.session:
            await self.session.close()

    async def fetch_team_data(self):
        """Fetch current team data including picks and history."""
        # Team info
        async with self.session.get(f"https://fantasy.premierleague.com/api/entry/{self.team_id}/") as resp:
            self.team_data = await resp.json()

        # Current GW picks
        current_gw = self.get_current_gameweek()
        async with self.session.get(f"https://fantasy.premierleague.com/api/entry/{self.team_id}/event/{current_gw}/picks/") as resp:
            if resp.status == 200:
                self.current_picks = await resp.json()
            else:
                self.current_picks = None

        # Transfer history
        async with self.session.get(f"https://fantasy.premierleague.com/api/entry/{self.team_id}/transfers/") as resp:
            self.transfers_history = await resp.json()

        # Chip history
        async with self.session.get(f"https://fantasy.premierleague.com/api/entry/{self.team_id}/history/") as resp:
            history = await resp.json()
            self._parse_chip_history(history.get('chips', []))

    def _parse_chip_history(self, chips: List[Dict]):
        """Parse which chips have been used."""
        for chip in chips:
            chip_name = chip.get('name')
            chip_gw = chip.get('event')
            if chip_name in self.chips_used:
                self.chips_used[chip_name] = {'used': True, 'gameweek': chip_gw}

    def get_current_gameweek(self) -> int:
        """Get the current gameweek number."""
        for event in self.bootstrap_data['events']:
            if event['is_current']:
                return event['id']
        return 1

    def get_next_gameweek(self) -> int:
        """Get the next gameweek number."""
        for event in self.bootstrap_data['events']:
            if event['is_next']:
                return event['id']
        return self.get_current_gameweek() + 1

    def get_gameweek_deadline(self, gw: int) -> datetime:
        """Get the deadline for a gameweek."""
        for event in self.bootstrap_data['events']:
            if event['id'] == gw:
                return datetime.fromisoformat(event['deadline_time'].replace('Z', '+00:00'))
        return None

    def get_player_by_id(self, player_id: int) -> Dict:
        """Get player data by ID."""
        for player in self.bootstrap_data['elements']:
            if player['id'] == player_id:
                return player
        return None

    def get_team_name(self, team_id: int) -> str:
        """Get team short name by ID."""
        for team in self.bootstrap_data['teams']:
            if team['id'] == team_id:
                return team['short_name']
        return "UNK"

    # ==================== PRICE CHANGE MONITORING ====================

    async def fetch_livefpl_predictions(self) -> Dict[str, List[Dict]]:
        """
        Fetch price change predictions from LiveFPL.net.

        LiveFPL is the most accurate price predictor (99% rise, 98% fall accuracy).
        Players with 100%+ progress are expected to rise tonight.
        Players with -100% or less are expected to fall tonight.

        Source: https://www.livefpl.net/prices
        """
        try:
            async with self.session.get(
                "https://www.livefpl.net/prices",
                headers={
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
                }
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"LiveFPL returned status {resp.status}, falling back to FPL API")
                    return None

                html = await resp.text()
                soup = BeautifulSoup(html, 'html.parser')

                rising = []
                falling = []

                # Find the main data table (index 4 - has 600+ rows with all players)
                tables = soup.find_all('table')
                data_table = None
                for table in tables:
                    rows = table.find_all('tr')
                    if len(rows) > 100:  # Main data table has 600+ rows
                        data_table = table
                        break

                if not data_table:
                    logger.warning("Could not find main price table on LiveFPL")
                    return None

                rows = data_table.find_all('tr')
                for row in rows[1:]:  # Skip header
                    cells = row.find_all('td')
                    if len(cells) < 5:
                        continue

                    try:
                        # Column 0: Player info (e.g., "GabrielDEF  £6.6Gabriel")
                        player_cell = cells[0].get_text(strip=True)

                        # Extract name - text before position indicator (GKP, DEF, MID, FWD)
                        # Handle accented names like Ødegaard, Gyökeres, L.Paquetá
                        name_match = re.match(r'^(.+?)(GKP|DEF|MID|FWD)', player_cell)
                        if name_match:
                            name = name_match.group(1).strip()
                        else:
                            # Fallback: take first word
                            name = player_cell.split()[0] if player_cell else "Unknown"

                        # Extract price from player cell (e.g., "£6.6")
                        price_match = re.search(r'£([\d.]+)', player_cell)
                        price = float(price_match.group(1)) if price_match else 0.0

                        # Column 2: Team
                        team = cells[2].get_text(strip=True) if len(cells) > 2 else ""

                        # Column 3: Progress Now (e.g., "74.37%")
                        progress_text = cells[3].get_text(strip=True) if len(cells) > 3 else "0%"
                        progress_match = re.search(r'(-?[\d.]+)%', progress_text)
                        progress = float(progress_match.group(1)) if progress_match else 0.0

                        # Column 4: Prediction + time estimate (e.g., "125.5%Tonight" or "22.93%>2 days")
                        prediction_cell = cells[4].get_text(strip=True) if len(cells) > 4 else "0%"
                        pred_match = re.search(r'(-?[\d.]+)%', prediction_cell)
                        prediction = float(pred_match.group(1)) if pred_match else 0.0

                        # Extract time estimate (e.g., "Tonight", ">2 days")
                        time_match = re.search(r'%(.+)$', prediction_cell)
                        time_estimate = time_match.group(1) if time_match else ""

                        player_data = {
                            'name': name,
                            'team': team,
                            'price': price,
                            'progress': progress,
                            'prediction': prediction,
                            'time_estimate': time_estimate,
                            'source': 'livefpl'
                        }

                        # Categorize by direction - rising players have positive prediction
                        if prediction >= 50:
                            player_data['risk_level'] = 'high' if prediction >= 100 else 'medium'
                            rising.append(player_data)
                        elif prediction <= -50:
                            player_data['risk_level'] = 'high' if prediction <= -100 else 'medium'
                            falling.append(player_data)

                    except (ValueError, IndexError) as e:
                        continue

                # Sort by prediction magnitude
                rising.sort(key=lambda x: x['prediction'], reverse=True)
                falling.sort(key=lambda x: x['prediction'])

                logger.info(f"LiveFPL: Found {len(rising)} rising, {len(falling)} falling players")

                return {
                    'rising': rising[:20],
                    'falling': falling[:20],
                    'source': 'livefpl.net',
                    'accuracy': {'rise': 99.0, 'fall': 98.0}
                }

        except Exception as e:
            logger.warning(f"Failed to fetch LiveFPL data: {e}")
            return None

    async def analyze_price_changes_async(self) -> Dict[str, List[Dict]]:
        """
        Analyze players at risk of price changes.

        First tries LiveFPL.net (most accurate - 99% rise, 98% fall).
        Falls back to FPL API transfer data if LiveFPL unavailable.
        """
        # Try LiveFPL first (most accurate)
        livefpl_data = await self.fetch_livefpl_predictions()
        if livefpl_data:
            self.price_change_predictions = livefpl_data
            return livefpl_data

        # Fallback to FPL API analysis
        logger.info("LiveFPL unavailable, using FPL API transfer data")
        return self.analyze_price_changes_from_api()

    def analyze_price_changes(self) -> Dict[str, List[Dict]]:
        """Synchronous wrapper - uses FPL API data only."""
        return self.analyze_price_changes_from_api()

    def analyze_price_changes_from_api(self) -> Dict[str, List[Dict]]:
        """
        Analyze players at risk of price changes using FPL API data.

        Uses FPL API data:
        - transfers_in_event: Transfers in this GW
        - transfers_out_event: Transfers out this GW
        - selected_by_percent: Overall ownership
        - cost_change_event: Price change already this GW

        Returns players likely to rise or fall based on transfer activity.
        """
        rising = []
        falling = []

        total_managers = self._estimate_total_managers()

        for player in self.bootstrap_data['elements']:
            player_id = player['id']
            name = player['web_name']
            team = self.get_team_name(player['team'])
            current_price = player['now_cost'] / 10
            transfers_in = player.get('transfers_in_event', 0)
            transfers_out = player.get('transfers_out_event', 0)
            selected_by = float(player.get('selected_by_percent', 0) or 0)
            cost_change_event = player.get('cost_change_event', 0)

            # Net transfers as percentage of total managers
            net_transfers = transfers_in - transfers_out
            net_transfer_pct = (net_transfers / total_managers * 100) if total_managers > 0 else 0

            # Price change thresholds (approximate - actual FPL algorithm is secret)
            # Generally need ~100k+ net transfers for a price change

            # Rising players
            if net_transfers > 80000:  # High threshold for price rise
                risk_level = "high" if net_transfers > 150000 else "medium"
                rising.append({
                    'id': player_id,
                    'name': name,
                    'team': team,
                    'price': current_price,
                    'net_transfers': net_transfers,
                    'net_transfer_pct': net_transfer_pct,
                    'transfers_in': transfers_in,
                    'risk_level': risk_level,
                    'already_changed': cost_change_event > 0
                })

            # Falling players
            elif net_transfers < -80000:  # Negative = more out than in
                risk_level = "high" if net_transfers < -150000 else "medium"
                falling.append({
                    'id': player_id,
                    'name': name,
                    'team': team,
                    'price': current_price,
                    'net_transfers': net_transfers,
                    'net_transfer_pct': net_transfer_pct,
                    'transfers_out': transfers_out,
                    'risk_level': risk_level,
                    'already_changed': cost_change_event < 0
                })

        # Sort by net transfer magnitude
        rising.sort(key=lambda x: x['net_transfers'], reverse=True)
        falling.sort(key=lambda x: x['net_transfers'])

        self.price_change_predictions = {
            'rising': rising[:20],  # Top 20 most likely to rise
            'falling': falling[:20]  # Top 20 most likely to fall
        }

        return self.price_change_predictions

    def _estimate_total_managers(self) -> int:
        """Estimate total active managers from event data."""
        for event in self.bootstrap_data['events']:
            if event.get('is_current'):
                return event.get('average_entry_score', 0) or 10000000  # Fallback
        return 10000000  # ~10M active managers as fallback

    def get_price_risk_for_player(self, player_id: int) -> Dict:
        """Get price change risk assessment for a specific player."""
        if not self.price_change_predictions:
            self.analyze_price_changes()

        for player in self.price_change_predictions.get('rising', []):
            if player['id'] == player_id:
                return {'direction': 'rising', **player}

        for player in self.price_change_predictions.get('falling', []):
            if player['id'] == player_id:
                return {'direction': 'falling', **player}

        return {'direction': 'stable', 'risk_level': 'low'}

    def get_squad_price_risks(self) -> List[Dict]:
        """Get price change risks for all players in current squad."""
        if not self.current_picks:
            return []

        if not self.price_change_predictions:
            self.analyze_price_changes()

        squad_risks = []
        for pick in self.current_picks.get('picks', []):
            player = self.get_player_by_id(pick['element'])
            if not player:
                continue

            risk = self.get_price_risk_for_player(pick['element'])
            if risk['direction'] != 'stable':
                squad_risks.append({
                    'player_id': pick['element'],
                    'name': player['web_name'],
                    'price': player['now_cost'] / 10,
                    'direction': risk['direction'],
                    'risk_level': risk.get('risk_level', 'low'),
                    'net_transfers': risk.get('net_transfers', 0)
                })

        return squad_risks

    # ==================== FIXTURE ANALYSIS ====================

    def get_fixtures_for_gameweek(self, gw: int) -> List[Dict]:
        """Get all fixtures for a gameweek."""
        return [f for f in self.fixtures_data if f.get('event') == gw]

    def get_team_fixtures(self, team_id: int, num_gws: int = 5) -> List[Dict]:
        """Get upcoming fixtures for a team."""
        current_gw = self.get_current_gameweek()
        team_fixtures = []

        for fixture in self.fixtures_data:
            gw = fixture.get('event')
            if gw and current_gw <= gw <= current_gw + num_gws:
                if fixture['team_h'] == team_id or fixture['team_a'] == team_id:
                    is_home = fixture['team_h'] == team_id
                    opponent = fixture['team_a'] if is_home else fixture['team_h']
                    team_fixtures.append({
                        'gameweek': gw,
                        'opponent': opponent,
                        'is_home': is_home,
                        'difficulty': fixture['team_h_difficulty'] if is_home else fixture['team_a_difficulty']
                    })

        return sorted(team_fixtures, key=lambda x: x['gameweek'])

    def is_double_gameweek(self, gw: int) -> Tuple[bool, List[int]]:
        """Check if gameweek is a DGW and return teams with double fixtures."""
        fixtures = self.get_fixtures_for_gameweek(gw)
        team_counts = {}

        for fixture in fixtures:
            team_counts[fixture['team_h']] = team_counts.get(fixture['team_h'], 0) + 1
            team_counts[fixture['team_a']] = team_counts.get(fixture['team_a'], 0) + 1

        dgw_teams = [team_id for team_id, count in team_counts.items() if count > 1]
        return len(dgw_teams) > 0, dgw_teams

    def is_blank_gameweek(self, gw: int) -> Tuple[bool, List[int]]:
        """Check if gameweek is a BGW and return teams without fixtures."""
        fixtures = self.get_fixtures_for_gameweek(gw)
        teams_playing = set()

        for fixture in fixtures:
            teams_playing.add(fixture['team_h'])
            teams_playing.add(fixture['team_a'])

        all_teams = {t['id'] for t in self.bootstrap_data['teams']}
        blank_teams = list(all_teams - teams_playing)

        return len(blank_teams) > 0, blank_teams

    # ==================== SQUAD HEALTH ANALYSIS ====================

    def analyze_squad_health(self) -> Dict:
        """Analyze current squad for injuries, suspensions, and form issues."""
        if not self.current_picks:
            return {'healthy': 0, 'doubtful': 0, 'injured': 0, 'suspended': 0, 'issues': []}

        health = {
            'healthy': 0,
            'doubtful': 0,
            'injured': 0,
            'suspended': 0,
            'poor_form': 0,
            'issues': []
        }

        for pick in self.current_picks.get('picks', []):
            player = self.get_player_by_id(pick['element'])
            if not player:
                continue

            status = player.get('status', 'a')
            form = float(player.get('form', 0) or 0)

            if status == 'a':
                health['healthy'] += 1
            elif status == 'd':
                health['doubtful'] += 1
                health['issues'].append({
                    'player': player['web_name'],
                    'issue': 'Doubtful',
                    'chance': player.get('chance_of_playing_next_round'),
                    'news': player.get('news', '')
                })
            elif status == 'i':
                health['injured'] += 1
                health['issues'].append({
                    'player': player['web_name'],
                    'issue': 'Injured',
                    'chance': 0,
                    'news': player.get('news', '')
                })
            elif status == 's':
                health['suspended'] += 1
                health['issues'].append({
                    'player': player['web_name'],
                    'issue': 'Suspended',
                    'chance': 0,
                    'news': player.get('news', '')
                })

            # Check form (below 3.0 is considered poor)
            if status == 'a' and form < 3.0:
                health['poor_form'] += 1
                health['issues'].append({
                    'player': player['web_name'],
                    'issue': 'Poor form',
                    'form': form
                })

        return health

    def count_players_without_fixture(self, gw: int) -> int:
        """Count how many squad players don't have a fixture in a GW."""
        _, blank_teams = self.is_blank_gameweek(gw)
        count = 0

        if not self.current_picks:
            return 0

        for pick in self.current_picks.get('picks', []):
            player = self.get_player_by_id(pick['element'])
            if player and player['team'] in blank_teams:
                count += 1

        return count

    # ==================== CHIP STRATEGY ====================

    def evaluate_chip_strategy(self) -> Optional[ChipRecommendation]:
        """
        Evaluate whether to play a chip this gameweek.

        Chip Strategy Logic:
        - WILDCARD: When squad needs major overhaul (3+ injuries, 5+ poor performers)
        - FREE HIT: During BGW or when many players injured for just 1 GW
        - BENCH BOOST: During DGW when bench players also have good fixtures
        - TRIPLE CAPTAIN: When premium player (Haaland) has easy home fixture in DGW
        """
        next_gw = self.get_next_gameweek()
        squad_health = self.analyze_squad_health()

        recommendations = []

        # Check remaining GWs until chip reset (GW19)
        gws_until_reset = max(0, 19 - next_gw) if next_gw <= 19 else max(0, 38 - next_gw)

        # ===== WILDCARD EVALUATION =====
        if not self.chips_used['wildcard']['used']:
            wc_score = 0
            wc_reasons = []

            injured_count = squad_health['injured'] + squad_health['suspended']
            poor_form_count = squad_health['poor_form']

            if injured_count >= 3:
                wc_score += 40
                wc_reasons.append(f"{injured_count} players unavailable (injured/suspended)")

            if poor_form_count >= 4:
                wc_score += 30
                wc_reasons.append(f"{poor_form_count} players in poor form")

            # Urgency bonus if chips reset soon
            if gws_until_reset <= 3 and wc_score > 0:
                wc_score += 20
                wc_reasons.append(f"Only {gws_until_reset} GWs until chip reset")

            if wc_score >= 50:
                recommendations.append(ChipRecommendation(
                    chip=ChipType.WILDCARD,
                    score=min(wc_score, 100),
                    reasons=wc_reasons,
                    should_play=True
                ))

        # ===== FREE HIT EVALUATION =====
        if not self.chips_used['freehit']['used']:
            fh_score = 0
            fh_reasons = []

            is_bgw, blank_teams = self.is_blank_gameweek(next_gw)
            players_without_fixture = self.count_players_without_fixture(next_gw)

            if is_bgw and players_without_fixture >= 3:
                fh_score += 50
                fh_reasons.append(f"Blank GW: {players_without_fixture} players without fixtures")

            # Short-term injuries (player back next week)
            short_term_injuries = sum(
                1 for issue in squad_health['issues']
                if issue.get('issue') == 'Injured' and 'expected back' in issue.get('news', '').lower()
            )
            if short_term_injuries >= 2:
                fh_score += 30
                fh_reasons.append(f"{short_term_injuries} players injured but returning soon")

            # Urgency bonus
            if gws_until_reset <= 2 and fh_score > 0:
                fh_score += 20
                fh_reasons.append(f"Only {gws_until_reset} GWs until chip reset")

            if fh_score >= 50:
                recommendations.append(ChipRecommendation(
                    chip=ChipType.FREE_HIT,
                    score=min(fh_score, 100),
                    reasons=fh_reasons,
                    should_play=True
                ))

        # ===== BENCH BOOST EVALUATION =====
        if not self.chips_used['bboost']['used']:
            bb_score = 0
            bb_reasons = []

            is_dgw, dgw_teams = self.is_double_gameweek(next_gw)

            if is_dgw:
                # Count bench players with DGW
                bench_dgw_count = 0
                if self.current_picks:
                    for pick in self.current_picks.get('picks', []):
                        if pick['position'] > 11:  # Bench player
                            player = self.get_player_by_id(pick['element'])
                            if player and player['team'] in dgw_teams:
                                bench_dgw_count += 1

                if bench_dgw_count >= 3:
                    bb_score += 60
                    bb_reasons.append(f"DGW: {bench_dgw_count} bench players with double fixtures")
                elif bench_dgw_count >= 2:
                    bb_score += 40
                    bb_reasons.append(f"DGW: {bench_dgw_count} bench players with double fixtures")

            # Check bench quality
            bench_total_form = 0
            if self.current_picks:
                for pick in self.current_picks.get('picks', []):
                    if pick['position'] > 11:
                        player = self.get_player_by_id(pick['element'])
                        if player:
                            bench_total_form += float(player.get('form', 0) or 0)

            if bench_total_form >= 15:  # Good bench form
                bb_score += 20
                bb_reasons.append(f"Strong bench form: {bench_total_form:.1f} combined")

            # Urgency bonus
            if gws_until_reset <= 2 and bb_score > 0:
                bb_score += 15
                bb_reasons.append(f"Only {gws_until_reset} GWs until chip reset")

            if bb_score >= 50:
                recommendations.append(ChipRecommendation(
                    chip=ChipType.BENCH_BOOST,
                    score=min(bb_score, 100),
                    reasons=bb_reasons,
                    should_play=True
                ))

        # ===== TRIPLE CAPTAIN EVALUATION =====
        if not self.chips_used['3xc']['used']:
            tc_score = 0
            tc_reasons = []

            is_dgw, dgw_teams = self.is_double_gameweek(next_gw)

            # Find best captain candidate
            best_captain = self._find_best_captain_for_tc(next_gw, dgw_teams if is_dgw else [])

            if best_captain:
                player = self.get_player_by_id(best_captain['id'])

                if is_dgw and player['team'] in dgw_teams:
                    tc_score += 50
                    tc_reasons.append(f"{player['web_name']} has DGW")

                # Check fixture difficulty
                fixtures = self.get_team_fixtures(player['team'], num_gws=1)
                if fixtures and all(f['difficulty'] <= 2 for f in fixtures):
                    tc_score += 30
                    tc_reasons.append(f"Easy fixture(s) for {player['web_name']}")

                # Premium player bonus (price >= 12.0m)
                if player['now_cost'] >= 120:
                    tc_score += 15
                    tc_reasons.append(f"Premium player (£{player['now_cost']/10:.1f}m)")

                # Home fixture bonus
                if fixtures and fixtures[0]['is_home']:
                    tc_score += 10
                    tc_reasons.append("Home fixture")

            # Urgency bonus
            if gws_until_reset <= 2 and tc_score > 0:
                tc_score += 15
                tc_reasons.append(f"Only {gws_until_reset} GWs until chip reset")

            if tc_score >= 60:
                recommendations.append(ChipRecommendation(
                    chip=ChipType.TRIPLE_CAPTAIN,
                    score=min(tc_score, 100),
                    reasons=tc_reasons,
                    should_play=True
                ))

        # Return highest scoring recommendation
        if recommendations:
            return max(recommendations, key=lambda x: x.score)

        return None

    def _find_best_captain_for_tc(self, gw: int, dgw_teams: List[int]) -> Optional[Dict]:
        """Find the best captain candidate for Triple Captain."""
        if not self.current_picks:
            return None

        candidates = []

        for pick in self.current_picks.get('picks', []):
            if pick['position'] <= 11:  # Starting players only
                player = self.get_player_by_id(pick['element'])
                if not player or player['status'] != 'a':
                    continue

                score = 0
                form = float(player.get('form', 0) or 0)

                # Form score
                score += form * 5

                # DGW bonus
                if player['team'] in dgw_teams:
                    score += 30

                # Position bonus (FWD > MID > DEF > GKP for TC)
                position_bonus = {4: 15, 3: 10, 2: 5, 1: 0}
                score += position_bonus.get(player['element_type'], 0)

                # xG/xA bonus from stats
                xg = float(player.get('expected_goals', 0) or 0)
                xa = float(player.get('expected_assists', 0) or 0)
                score += (xg + xa) * 3

                candidates.append({'id': player['id'], 'score': score})

        if candidates:
            return max(candidates, key=lambda x: x['score'])
        return None

    # ==================== TRANSFER DECISIONS ====================

    def evaluate_transfers(self, max_transfers: int = 2) -> List[TransferRecommendation]:
        """
        Evaluate and recommend transfers.

        Considers:
        - Player availability (injuries, suspensions)
        - Form and expected points
        - Fixtures
        - Price changes (falling players should be sold, rising targets should be bought)
        """
        if not self.current_picks:
            return []

        recommendations = []
        free_transfers = self.team_data.get('last_deadline_total_transfers', 1)
        bank = self.team_data.get('last_deadline_bank', 0) / 10  # Convert to millions

        # Analyze price changes first
        self.analyze_price_changes()
        squad_price_risks = self.get_squad_price_risks()

        # Get current squad
        current_squad = []
        for pick in self.current_picks.get('picks', []):
            player = self.get_player_by_id(pick['element'])
            if player:
                # Check if player is at price risk
                price_risk = self.get_price_risk_for_player(player['id'])
                current_squad.append({
                    'id': player['id'],
                    'name': player['web_name'],
                    'team': player['team'],
                    'position': player['element_type'],
                    'price': player['now_cost'] / 10,
                    'form': float(player.get('form', 0) or 0),
                    'status': player.get('status', 'a'),
                    'news': player.get('news', ''),
                    'is_starting': pick['position'] <= 11,
                    'price_falling': price_risk['direction'] == 'falling',
                    'price_risk_level': price_risk.get('risk_level', 'low')
                })

        # Find players to transfer out (injured, suspended, poor form, OR price falling)
        transfer_out_candidates = []
        for player in current_squad:
            priority = 0
            reasons = []

            if player['status'] in ['i', 'u']:  # Injured or unavailable
                priority = 1
                reasons.append(f"Injured/Unavailable: {player['news']}")
            elif player['status'] == 's':  # Suspended
                priority = 1
                reasons.append("Suspended")
            elif player['status'] == 'd' and player['is_starting']:  # Doubtful starter
                priority = 2
                reasons.append(f"Doubtful: {player['news']}")
            elif player['form'] < 2.0 and player['is_starting']:  # Very poor form
                priority = 3
                reasons.append(f"Very poor form ({player['form']:.1f})")

            # Add price falling as a reason (but lower priority unless combined with other issues)
            if player['price_falling'] and player['price_risk_level'] == 'high':
                if priority == 0:
                    priority = 4  # Lower priority for price-only transfers
                reasons.append(f"Price falling (high risk) - sell before price drop")

            if priority > 0:
                transfer_out_candidates.append({
                    **player,
                    'priority': priority,
                    'reasons': reasons
                })

        # Sort by priority
        transfer_out_candidates.sort(key=lambda x: x['priority'])

        # For each transfer out candidate, find best replacement
        for out_player in transfer_out_candidates[:max_transfers]:
            budget = out_player['price'] + bank

            # Find replacement (same position, within budget, good form)
            best_replacement = self._find_best_replacement(
                position=out_player['position'],
                budget=budget,
                exclude_teams=[p['team'] for p in current_squad],
                current_squad_ids=[p['id'] for p in current_squad]
            )

            if best_replacement:
                # Check if replacement is about to rise in price
                replacement_price_risk = self.get_price_risk_for_player(best_replacement['id'])
                price_change_risk = replacement_price_risk['direction'] == 'rising'

                reasons = out_player['reasons'] + [f"Replace with {best_replacement['web_name']} (form: {best_replacement['form']})"]
                if price_change_risk:
                    reasons.append(f"⚠️ {best_replacement['web_name']} price rising - buy soon!")

                recommendations.append(TransferRecommendation(
                    player_out_id=out_player['id'],
                    player_out_name=out_player['name'],
                    player_in_id=best_replacement['id'],
                    player_in_name=best_replacement['web_name'],
                    priority=out_player['priority'],
                    reasons=reasons,
                    expected_points_gain=float(best_replacement.get('form', 0) or 0) - out_player['form'],
                    price_change_risk=price_change_risk
                ))

        return recommendations

    def _find_best_replacement(
        self,
        position: int,
        budget: float,
        exclude_teams: List[int],
        current_squad_ids: List[int]
    ) -> Optional[Dict]:
        """Find the best replacement player for a position within budget."""
        candidates = []

        # Count teams in squad (max 3 per team)
        team_counts = {}
        for tid in exclude_teams:
            team_counts[tid] = team_counts.get(tid, 0) + 1

        for player in self.bootstrap_data['elements']:
            # Filter criteria
            if player['element_type'] != position:
                continue
            if player['id'] in current_squad_ids:
                continue
            if player['now_cost'] / 10 > budget:
                continue
            if player['status'] not in ['a', 'd']:  # Available or doubtful only
                continue
            if team_counts.get(player['team'], 0) >= 3:
                continue

            # Score based on form, xG, fixtures
            form = float(player.get('form', 0) or 0)
            if form < 3.0:  # Minimum form threshold
                continue

            # Get fixture difficulty
            fixtures = self.get_team_fixtures(player['team'], num_gws=3)
            avg_difficulty = sum(f['difficulty'] for f in fixtures) / len(fixtures) if fixtures else 3

            score = form * 2 + (5 - avg_difficulty) * 1.5

            candidates.append({
                **player,
                'score': score,
                'form': form
            })

        if candidates:
            return max(candidates, key=lambda x: x['score'])
        return None

    # ==================== CAPTAIN SELECTION ====================

    def select_captain(self) -> Tuple[int, int]:
        """Select captain and vice-captain based on form and fixtures."""
        if not self.current_picks:
            return None, None

        candidates = []
        next_gw = self.get_next_gameweek()

        for pick in self.current_picks.get('picks', []):
            if pick['position'] <= 11:  # Starting players only
                player = self.get_player_by_id(pick['element'])
                if not player or player['status'] != 'a':
                    continue

                form = float(player.get('form', 0) or 0)

                # Get fixture info
                fixtures = self.get_team_fixtures(player['team'], num_gws=1)
                fixture_score = 0
                if fixtures:
                    difficulty = fixtures[0]['difficulty']
                    is_home = fixtures[0]['is_home']
                    fixture_score = (5 - difficulty) * 2 + (2 if is_home else 0)

                # Position weight (FWD/MID preferred)
                position_weight = {4: 1.2, 3: 1.1, 2: 0.9, 1: 0.7}

                # Calculate captain score
                score = (form * 3 + fixture_score) * position_weight.get(player['element_type'], 1.0)

                # Premium player bonus
                if player['now_cost'] >= 100:
                    score *= 1.1

                candidates.append({
                    'id': player['id'],
                    'name': player['web_name'],
                    'score': score
                })

        # Sort by score
        candidates.sort(key=lambda x: x['score'], reverse=True)

        if len(candidates) >= 2:
            return candidates[0]['id'], candidates[1]['id']
        elif len(candidates) == 1:
            return candidates[0]['id'], candidates[0]['id']

        return None, None

    # ==================== MAIN DECISION FUNCTION ====================

    async def make_decision(self, is_early_run: bool = False) -> BotDecision:
        """
        Make all decisions for the gameweek.

        Args:
            is_early_run: True if this is the early run (for price changes),
                         False if this is the final run before deadline
        """
        next_gw = self.get_next_gameweek()

        logger.info(f"Making decisions for GW{next_gw} ({'early' if is_early_run else 'final'} run)")

        # Analyze squad health
        squad_health = self.analyze_squad_health()
        logger.info(f"Squad health: {squad_health['healthy']} healthy, {squad_health['injured']} injured")

        # Evaluate chip strategy
        chip_rec = self.evaluate_chip_strategy()
        if chip_rec:
            logger.info(f"Chip recommendation: {chip_rec.chip.value} (score: {chip_rec.score})")

        # Evaluate transfers
        transfers = self.evaluate_transfers(max_transfers=2 if is_early_run else 1)
        logger.info(f"Transfer recommendations: {len(transfers)}")

        # Select captain
        captain_id, vice_captain_id = self.select_captain()
        captain_name = self.get_player_by_id(captain_id)['web_name'] if captain_id else "Unknown"
        vice_captain_name = self.get_player_by_id(vice_captain_id)['web_name'] if vice_captain_id else "Unknown"
        logger.info(f"Captain: {captain_name}, Vice: {vice_captain_name}")

        # Analyze price changes (use async version to try LiveFPL first)
        price_changes = await self.analyze_price_changes_async()
        squad_price_risks = self.get_squad_price_risks()

        logger.info(f"Price changes: {len(price_changes.get('rising', []))} rising, {len(price_changes.get('falling', []))} falling")
        if squad_price_risks:
            logger.info(f"Squad price risks: {len(squad_price_risks)} players at risk")

        # Build reasoning
        reasoning_parts = []
        if squad_health['issues']:
            reasoning_parts.append(f"Squad issues: {len(squad_health['issues'])} players with concerns")
        if chip_rec and chip_rec.should_play:
            reasoning_parts.append(f"Recommend {chip_rec.chip.value}: {', '.join(chip_rec.reasons)}")
        if transfers:
            reasoning_parts.append(f"Transfers needed: {len(transfers)}")
        if squad_price_risks:
            falling_players = [p['name'] for p in squad_price_risks if p['direction'] == 'falling']
            if falling_players:
                reasoning_parts.append(f"Price falling: {', '.join(falling_players[:3])}")

        decision = BotDecision(
            gameweek=next_gw,
            timestamp=datetime.now(),
            transfers=transfers,
            chip_recommendation=chip_rec,
            captain_id=captain_id,
            captain_name=captain_name,
            vice_captain_id=vice_captain_id,
            vice_captain_name=vice_captain_name,
            lineup_changes=[],  # TODO: Implement lineup optimization
            reasoning="; ".join(reasoning_parts) if reasoning_parts else "No major changes needed",
            price_changes=price_changes,
            squad_price_risks=squad_price_risks
        )

        return decision

    def decision_to_dict(self, decision: BotDecision) -> Dict:
        """Convert decision to dictionary for JSON serialization."""
        return {
            'gameweek': decision.gameweek,
            'timestamp': decision.timestamp.isoformat(),
            'transfers': [
                {
                    'out': {'id': t.player_out_id, 'name': t.player_out_name},
                    'in': {'id': t.player_in_id, 'name': t.player_in_name},
                    'priority': t.priority,
                    'reasons': t.reasons,
                    'expected_points_gain': t.expected_points_gain,
                    'price_change_risk': t.price_change_risk
                }
                for t in decision.transfers
            ],
            'chip': {
                'type': decision.chip_recommendation.chip.value if decision.chip_recommendation else None,
                'score': decision.chip_recommendation.score if decision.chip_recommendation else 0,
                'reasons': decision.chip_recommendation.reasons if decision.chip_recommendation else [],
                'should_play': decision.chip_recommendation.should_play if decision.chip_recommendation else False
            },
            'captain': {'id': decision.captain_id, 'name': decision.captain_name},
            'vice_captain': {'id': decision.vice_captain_id, 'name': decision.vice_captain_name},
            'reasoning': decision.reasoning,
            'price_changes': {
                'rising': decision.price_changes.get('rising', [])[:10],  # Top 10
                'falling': decision.price_changes.get('falling', [])[:10]  # Top 10
            },
            'squad_price_risks': decision.squad_price_risks
        }


# ==================== SCHEDULED RUNNER ====================

async def run_bot_decision(team_id: int, is_early_run: bool = False) -> Dict:
    """
    Run the bot decision maker.

    This should be called:
    1. Early run: When price changes are imminent (typically 24-48 hours before deadline)
    2. Final run: A few hours before the gameweek deadline
    """
    bot = BotDecisionMaker(team_id)

    try:
        await bot.initialize()
        decision = await bot.make_decision(is_early_run=is_early_run)
        result = bot.decision_to_dict(decision)

        # Log decision
        logger.info(f"Bot decision for GW{decision.gameweek}:")
        logger.info(f"  Transfers: {len(decision.transfers)}")
        logger.info(f"  Captain: {decision.captain_name}")
        logger.info(f"  Chip: {decision.chip_recommendation.chip.value if decision.chip_recommendation else 'None'}")

        return result

    finally:
        await bot.close()


# ==================== CLI ENTRY POINT ====================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="FPL Bot Decision Maker")
    parser.add_argument("--team-id", type=int, default=int(os.getenv("FPL_BOT_TEAM_ID", "12777515")),
                       help="FPL Team ID")
    parser.add_argument("--early", action="store_true",
                       help="Run as early decision (for price changes)")

    args = parser.parse_args()

    async def main():
        result = await run_bot_decision(args.team_id, is_early_run=args.early)
        print(json.dumps(result, indent=2))

    asyncio.run(main())
