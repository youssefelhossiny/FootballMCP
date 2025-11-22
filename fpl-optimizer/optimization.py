#!/usr/bin/env python3
"""
FPL Linear Programming Squad Optimizer
Phase 2b: True optimal squad selection using PuLP
"""

from pulp import *
import pandas as pd
from typing import List, Dict, Tuple
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FPLOptimizer:
    """
    Linear Programming based optimizer for FPL squad selection
    Guarantees mathematically optimal squad within constraints
    """

    # Squad constraints from FPL rules
    CONSTRAINTS = {
        "total_players": 15,
        "budget": 100.0,
        "max_per_team": 3,
        "positions": {
            1: ("GK", 2),  # Goalkeepers: exactly 2
            2: ("DEF", 5),  # Defenders: exactly 5
            3: ("MID", 5),  # Midfielders: exactly 5
            4: ("FWD", 3),  # Forwards: exactly 3
        }
    }

    def __init__(self):
        self.problem = None
        self.player_vars = {}
        self.last_solution = None

    def optimize_squad(
            self,
            players: List[Dict],
            budget: float = 100.0,
            optimize_for: str = "form"
    ) -> Tuple[List[Dict], str]:
        """
        Find optimal 15-player squad using Linear Programming

        Args:
            players: List of player dictionaries from FPL API
            budget: Budget constraint (default: £100m)
            optimize_for: Optimization metric - 'form', 'points', 'value', 'fixtures'

        Returns:
            (optimal_squad, status_message)
        """

        # Create new problem
        self.problem = LpProblem("FPL_Squad_Optimization", LpMaximize)

        # Create binary variables for each player (1 = select, 0 = don't select)
        self.player_vars = {}
        for player in players:
            player_id = player['id']
            self.player_vars[player_id] = LpVariable(
                f"player_{player_id}",
                cat='Binary'
            )

        # Calculate objective scores for each player
        scores = self._calculate_scores(players, optimize_for)

        # Objective: Maximize total score
        self.problem += lpSum(
            [scores[p['id']] * self.player_vars[p['id']] for p in players]
        ), "Total_Score"

        # Add constraints
        self._add_budget_constraint(players, budget)
        self._add_squad_size_constraint()
        self._add_position_constraints(players)
        self._add_team_constraint(players)

        # Solve
        logger.info("Solving Linear Programming problem...")
        self.problem.solve(PULP_CBC_CMD(msg=0))

        # Check solution status
        if LpStatus[self.problem.status] != "Optimal":
            logger.warning(f"Solution status: {LpStatus[self.problem.status]}")
            return [], f"Could not find optimal solution: {LpStatus[self.problem.status]}"

        # Extract solution
        optimal_squad = self._extract_solution(players)
        self.last_solution = optimal_squad

        return optimal_squad, "✅ Optimal squad found!"

    def optimize_lineup(
            self,
            squad_players: List[Dict],
            gameweek: int,
            fixtures: List[Dict] = None
    ) -> Dict:
        """
        Select best starting 11 from 15-player squad

        Args:
            squad_players: Your 15 selected players
            gameweek: Current gameweek
            fixtures: Upcoming fixtures (for FDR)

        Returns:
            {
                'starting_11': [...],
                'bench': [...],
                'formation': '4-3-3',
                'captain': player,
                'vice_captain': player,
                'reasoning': str
            }
        """

        if len(squad_players) != 15:
            return {
                'error': f"Expected 15 players, got {len(squad_players)}"
            }

        # Group by position
        by_position = {1: [], 2: [], 3: [], 4: []}
        for player in squad_players:
            by_position[player['element_type']].append(player)

        # Score players for this gameweek
        scores = {}
        for player in squad_players:
            score = self._calculate_player_gameweek_score(player, gameweek, fixtures)
            scores[player['id']] = score

        # Solve for best 11 using LP
        prob = LpProblem("FPL_Lineup", LpMaximize)
        player_vars = {p['id']: LpVariable(f"p_{p['id']}", cat='Binary') for p in squad_players}

        # Objective: Maximize score
        prob += lpSum([scores[p['id']] * player_vars[p['id']] for p in squad_players])

        # Constraints: 11 players
        prob += lpSum([player_vars[p['id']] for p in squad_players]) == 11

        # Position constraints for starting 11 (flexible formations)
        prob += lpSum([player_vars[p['id']] for p in by_position[1]]) == 1  # 1 GK
        prob += lpSum([player_vars[p['id']] for p in by_position[2]]) >= 3  # 3+ DEF
        prob += lpSum([player_vars[p['id']] for p in by_position[2]]) <= 5  # 5 max DEF
        prob += lpSum([player_vars[p['id']] for p in by_position[3]]) >= 2  # 2+ MID
        prob += lpSum([player_vars[p['id']] for p in by_position[3]]) <= 5  # 5 max MID
        prob += lpSum([player_vars[p['id']] for p in by_position[4]]) >= 1  # 1+ FWD
        prob += lpSum([player_vars[p['id']] for p in by_position[4]]) <= 3  # 3 max FWD

        prob.solve(PULP_CBC_CMD(msg=0))

        # Extract solution
        starting_11 = []
        bench = []

        for player in squad_players:
            if player_vars[player['id']].varValue == 1:
                starting_11.append(player)
            else:
                bench.append(player)

        # Recommend captain (highest scoring player)
        captain = max(starting_11, key=lambda p: scores[p['id']])
        vice_captain = max([p for p in starting_11 if p['id'] != captain['id']],
                           key=lambda p: scores[p['id']])

        # Determine formation
        def_count = len([p for p in starting_11 if p['element_type'] == 2])
        mid_count = len([p for p in starting_11 if p['element_type'] == 3])
        fwd_count = len([p for p in starting_11 if p['element_type'] == 4])
        formation = f"{def_count}-{mid_count}-{fwd_count}"

        return {
            'starting_11': starting_11,
            'bench': bench,
            'formation': formation,
            'captain': captain,
            'vice_captain': vice_captain,
            'expected_points': sum([scores[p['id']] for p in starting_11]),
            'reasoning': f"Formation {formation} with {captain['web_name']} as captain (expected {scores[captain['id']]:.1f} pts)"
        }

    def _calculate_scores(
            self,
            players: List[Dict],
            metric: str
    ) -> Dict[int, float]:
        """Calculate optimization score for each player"""

        scores = {}

        for player in players:
            if metric == "form":
                # Recent form (last 5 games)
                score = float(player.get('form', 0)) * 10

            elif metric == "points":
                # Total season points
                score = float(player.get('total_points', 0))

            elif metric == "value":
                # Points per £
                price = player.get('now_cost', 1) / 10
                points = float(player.get('total_points', 0))
                score = (points / price) if price > 0 else 0

            elif metric == "fixtures":
                # Form adjusted for fixture difficulty
                form = float(player.get('form', 0))
                # Would use FDR here if available
                score = form * 5

            else:
                score = 0

            scores[player['id']] = score

        return scores

    def _calculate_player_gameweek_score(
            self,
            player: Dict,
            gameweek: int,
            fixtures: List[Dict] = None
    ) -> float:
        """Calculate expected points for player in specific gameweek"""

        form = float(player.get('form', 0)) or 0

        # Base score from recent form
        score = form * 2

        # Bonus for good value
        price = player.get('now_cost', 1) / 10
        if price < 5.0:
            score += 2  # Budget players get bonus
        elif price > 10.0:
            score -= 0.5  # Expensive get penalty

        return score

    def _add_budget_constraint(self, players: List[Dict], budget: float):
        """Constraint: Total cost <= budget"""

        self.problem += lpSum(
            [(player['now_cost'] / 10) * self.player_vars[player['id']]
             for player in players]
        ) <= budget, "Budget_Constraint"

    def _add_squad_size_constraint(self):
        """Constraint: Exactly 15 players"""

        self.problem += lpSum(
            [self.player_vars[p_id] for p_id in self.player_vars]
        ) == 15, "Squad_Size_Constraint"

    def _add_position_constraints(self, players: List[Dict]):
        """Constraint: Correct number of players per position"""

        for pos_id, (pos_name, required_count) in self.CONSTRAINTS["positions"].items():
            pos_players = [p for p in players if p['element_type'] == pos_id]

            self.problem += lpSum(
                [self.player_vars[p['id']] for p in pos_players]
            ) == required_count, f"Position_{pos_name}_Constraint"

    def _add_team_constraint(self, players: List[Dict]):
        """Constraint: Max 3 players per club"""

        teams = {}
        for player in players:
            team_id = player['team']
            if team_id not in teams:
                teams[team_id] = []
            teams[team_id].append(player)

        for team_id, team_players in teams.items():
            self.problem += lpSum(
                [self.player_vars[p['id']] for p in team_players]
            ) <= 3, f"Team_{team_id}_Constraint"

    def _extract_solution(self, players: List[Dict]) -> List[Dict]:
        """Extract selected players from solution"""

        selected = []

        for player in players:
            if self.player_vars[player['id']].varValue == 1:
                selected.append(player)

        # Verify solution
        assert len(selected) == 15, f"Invalid solution: {len(selected)} players"

        return selected