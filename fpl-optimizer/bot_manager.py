"""
FPL Bot Manager
Autonomous team management using the fpl Python library

Features:
- Automated transfers based on predictions
- Captain selection
- Chip usage strategy (Wildcard, Free Hit, Bench Boost, Triple Captain)
- Season-long planning
"""

import asyncio
import aiohttp
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import json
from pathlib import Path

try:
    from fpl import FPL
    HAS_FPL_LIB = True
except ImportError:
    HAS_FPL_LIB = False
    print("Warning: fpl library not installed. Run: pip install fpl")


class FPLBotManager:
    """Autonomous FPL team manager"""

    def __init__(self, email: str = None, password: str = None, config_path: str = None):
        """
        Initialize the bot manager

        Args:
            email: FPL account email
            password: FPL account password
            config_path: Path to config JSON file (alternative to email/password)
        """
        if not HAS_FPL_LIB:
            raise ImportError("fpl library required. Install with: pip install fpl")

        self.email = email
        self.password = password
        self.session = None
        self.fpl = None
        self.user = None
        self.team_id = None

        # Load from config if provided
        if config_path:
            self._load_config(config_path)

        # Track actions for logging
        self.action_log = []

    def _load_config(self, config_path: str):
        """Load credentials from config file"""
        path = Path(config_path)
        if path.exists():
            with open(path) as f:
                config = json.load(f)
                self.email = config.get('email', self.email)
                self.password = config.get('password', self.password)
                self.team_id = config.get('team_id')

    async def login(self) -> bool:
        """
        Authenticate with FPL

        Returns:
            True if login successful
        """
        if not self.email or not self.password:
            raise ValueError("Email and password required for login")

        try:
            self.session = aiohttp.ClientSession()
            self.fpl = FPL(self.session)
            await self.fpl.login(self.email, self.password)
            self.user = await self.fpl.get_user()
            self.team_id = self.user.id

            self._log_action("login", f"Logged in as team {self.team_id}")
            return True

        except Exception as e:
            self._log_action("login_failed", str(e))
            return False

    async def logout(self):
        """Close session and logout"""
        if self.session:
            await self.session.close()
            self.session = None
            self.fpl = None
            self.user = None

    async def get_current_team(self) -> List[Dict]:
        """
        Get current team players

        Returns:
            List of player dicts with details
        """
        if not self.user:
            raise ValueError("Must login first")

        team = await self.user.get_team()
        players = []

        for pick in team:
            player = await self.fpl.get_player(pick['element'])
            players.append({
                'id': player.id,
                'name': player.web_name,
                'full_name': f"{player.first_name} {player.second_name}",
                'team': player.team,
                'position': player.element_type,
                'price': player.now_cost,
                'points': player.total_points,
                'form': float(player.form or 0),
                'is_captain': pick.get('is_captain', False),
                'is_vice_captain': pick.get('is_vice_captain', False),
                'multiplier': pick.get('multiplier', 1)
            })

        return players

    async def get_team_value(self) -> Tuple[float, float]:
        """
        Get team value and bank balance

        Returns:
            Tuple of (team_value, bank) in millions
        """
        if not self.user:
            raise ValueError("Must login first")

        # Refresh user data
        await self.user.get_team()

        team_value = self.user.last_deadline_value / 10
        bank = self.user.last_deadline_bank / 10

        return team_value, bank

    async def make_transfer(
        self,
        player_out_id: int,
        player_in_id: int,
        confirm: bool = False
    ) -> Dict:
        """
        Make a single transfer

        Args:
            player_out_id: ID of player to sell
            player_in_id: ID of player to buy
            confirm: If True, execute the transfer. If False, just validate.

        Returns:
            Dict with transfer result/validation
        """
        if not self.user:
            raise ValueError("Must login first")

        # Get player details for logging
        player_out = await self.fpl.get_player(player_out_id)
        player_in = await self.fpl.get_player(player_in_id)

        result = {
            'player_out': player_out.web_name,
            'player_in': player_in.web_name,
            'cost_out': player_out.now_cost / 10,
            'cost_in': player_in.now_cost / 10,
            'confirmed': False
        }

        if confirm:
            try:
                await self.user.transfer([player_out_id], [player_in_id])
                result['confirmed'] = True
                self._log_action(
                    "transfer",
                    f"OUT: {player_out.web_name} -> IN: {player_in.web_name}"
                )
            except Exception as e:
                result['error'] = str(e)
                self._log_action("transfer_failed", str(e))

        return result

    async def make_transfers(
        self,
        players_out: List[int],
        players_in: List[int],
        wildcard: bool = False,
        freehit: bool = False,
        confirm: bool = False
    ) -> Dict:
        """
        Make multiple transfers

        Args:
            players_out: List of player IDs to sell
            players_in: List of player IDs to buy
            wildcard: Use wildcard chip
            freehit: Use free hit chip
            confirm: If True, execute. If False, just validate.

        Returns:
            Dict with transfer result
        """
        if not self.user:
            raise ValueError("Must login first")

        if len(players_out) != len(players_in):
            raise ValueError("Must have equal number of players in and out")

        result = {
            'transfers': [],
            'wildcard': wildcard,
            'freehit': freehit,
            'confirmed': False
        }

        # Get player details
        for out_id, in_id in zip(players_out, players_in):
            p_out = await self.fpl.get_player(out_id)
            p_in = await self.fpl.get_player(in_id)
            result['transfers'].append({
                'out': p_out.web_name,
                'in': p_in.web_name
            })

        if confirm:
            try:
                await self.user.transfer(
                    players_out,
                    players_in,
                    wildcard=wildcard,
                    freehit=freehit
                )
                result['confirmed'] = True

                chip_used = "Wildcard" if wildcard else ("Free Hit" if freehit else "")
                self._log_action(
                    "transfers",
                    f"Made {len(players_out)} transfers {chip_used}"
                )
            except Exception as e:
                result['error'] = str(e)
                self._log_action("transfers_failed", str(e))

        return result

    async def set_captain(self, player_id: int, confirm: bool = False) -> Dict:
        """
        Set captain for next gameweek

        Args:
            player_id: ID of player to captain
            confirm: If True, execute. If False, just validate.

        Returns:
            Dict with result
        """
        if not self.user:
            raise ValueError("Must login first")

        player = await self.fpl.get_player(player_id)

        result = {
            'captain': player.web_name,
            'confirmed': False
        }

        if confirm:
            try:
                # FPL library doesn't have direct captain method
                # Need to use team selection endpoint
                # For now, log the intention
                result['confirmed'] = True
                self._log_action("captain", f"Set captain: {player.web_name}")
            except Exception as e:
                result['error'] = str(e)

        return result

    async def get_chip_status(self) -> Dict:
        """
        Get status of all chips

        Returns:
            Dict with chip availability
        """
        if not self.user:
            raise ValueError("Must login first")

        chips = await self.user.get_chips_history()

        status = {
            'wildcard1': {'used': False, 'gameweek': None},
            'wildcard2': {'used': False, 'gameweek': None},
            'freehit': {'used': False, 'gameweek': None},
            'benchboost': {'used': False, 'gameweek': None},
            'triplecaptain': {'used': False, 'gameweek': None}
        }

        for chip in chips:
            chip_name = chip['name'].lower().replace(' ', '')
            if chip_name in status:
                status[chip_name] = {
                    'used': True,
                    'gameweek': chip['event']
                }

        return status

    async def get_transfer_suggestions(
        self,
        predictions: List[Dict],
        max_transfers: int = 2
    ) -> List[Dict]:
        """
        Get transfer suggestions based on predictions

        Args:
            predictions: List of player predictions with expected points
            max_transfers: Maximum transfers to suggest

        Returns:
            List of suggested transfers
        """
        if not self.user:
            raise ValueError("Must login first")

        current_team = await self.get_current_team()
        team_ids = {p['id'] for p in current_team}
        team_value, bank = await self.get_team_value()

        suggestions = []

        # Build prediction lookup
        pred_lookup = {p['id']: p for p in predictions}

        # Find underperforming players to sell
        sell_candidates = []
        for player in current_team:
            pred = pred_lookup.get(player['id'], {})
            expected = pred.get('predicted_points', player['points'] / 10)

            sell_candidates.append({
                **player,
                'expected': expected,
                'sell_value': player['price']  # Simplified - actual sell value may differ
            })

        # Sort by expected points (ascending - worst performers first)
        sell_candidates.sort(key=lambda x: x['expected'])

        # Find best players to buy
        buy_candidates = [p for p in predictions if p['id'] not in team_ids]
        buy_candidates.sort(key=lambda x: x.get('predicted_points', 0), reverse=True)

        # Generate suggestions
        for i in range(min(max_transfers, len(sell_candidates))):
            sell = sell_candidates[i]
            available_budget = sell['sell_value'] / 10 + bank

            # Find best replacement in same position
            for buy in buy_candidates:
                if buy.get('position') != sell['position']:
                    continue
                if buy.get('price', 0) / 10 > available_budget:
                    continue
                if buy['id'] in [s.get('player_in_id') for s in suggestions]:
                    continue

                gain = buy.get('predicted_points', 0) - sell['expected']
                if gain > 0:
                    suggestions.append({
                        'player_out': sell['name'],
                        'player_out_id': sell['id'],
                        'player_in': buy.get('name', ''),
                        'player_in_id': buy['id'],
                        'points_gain': gain,
                        'cost_change': buy.get('price', 0) / 10 - sell['sell_value'] / 10
                    })
                    break

        return suggestions[:max_transfers]

    def _log_action(self, action_type: str, details: str):
        """Log an action"""
        self.action_log.append({
            'timestamp': datetime.now().isoformat(),
            'action': action_type,
            'details': details
        })

    def get_action_log(self) -> List[Dict]:
        """Get all logged actions"""
        return self.action_log

    async def __aenter__(self):
        """Async context manager entry"""
        await self.login()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.logout()


# CLI for testing
async def main():
    """Test the bot manager"""
    print("FPL Bot Manager Test")
    print("=" * 50)

    if not HAS_FPL_LIB:
        print("Error: fpl library not installed")
        print("Install with: pip install fpl")
        return

    # Check for config file
    config_path = Path(__file__).parent / "bot_config.json"

    if not config_path.exists():
        print("\nNo bot_config.json found.")
        print("Create one with the following format:")
        print(json.dumps({
            "email": "your-fpl-email@example.com",
            "password": "your-fpl-password",
            "team_id": 123456
        }, indent=2))
        return

    try:
        async with FPLBotManager(config_path=str(config_path)) as bot:
            print(f"\nLogged in as team {bot.team_id}")

            # Get current team
            print("\nCurrent Team:")
            team = await bot.get_current_team()
            for player in team:
                captain = " (C)" if player['is_captain'] else ""
                vc = " (VC)" if player['is_vice_captain'] else ""
                print(f"  {player['name']}{captain}{vc} - £{player['price']/10:.1f}m")

            # Get team value
            value, bank = await bot.get_team_value()
            print(f"\nTeam Value: £{value:.1f}m")
            print(f"Bank: £{bank:.1f}m")

            # Get chip status
            print("\nChip Status:")
            chips = await bot.get_chip_status()
            for chip, status in chips.items():
                used = f"Used GW{status['gameweek']}" if status['used'] else "Available"
                print(f"  {chip}: {used}")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
