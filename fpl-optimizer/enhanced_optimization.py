#!/usr/bin/env python3
"""
Enhanced FPL Optimizer with Multi-Gameweek Analysis
Phase 2b Enhanced: Fixture-aware optimization with bench strategy
"""

from pulp import *
import pandas as pd
from typing import List, Dict, Tuple, Optional
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FixtureAnalyzer:
    """Analyzes fixtures for next 3-5 gameweeks"""

    def __init__(self):
        self.fdr_weights = {
            1: 2.0,   # Very easy
            2: 1.5,   # Easy
            3: 1.0,   # Medium
            4: 0.7,   # Hard
            5: 0.4    # Very hard
        }

    def analyze_fixtures(self, fixtures: List[Dict], teams: Dict, current_gw: int, num_gws: int = 5) -> Dict:
        """
        Analyze fixtures for next N gameweeks

        Returns:
            {
                team_id: {
                    'fixtures': [...],
                    'fdr_avg': float,
                    'difficulty_score': float,
                    'num_fixtures': int
                }
            }
        """
        analysis = {}

        # Filter fixtures for next N gameweeks
        upcoming_fixtures = [
            f for f in fixtures
            if f.get('event') and current_gw <= f['event'] < current_gw + num_gws
        ]

        # Analyze per team
        for team_id in teams.keys():
            team_fixtures = [
                f for f in upcoming_fixtures
                if f['team_h'] == team_id or f['team_a'] == team_id
            ]

            if not team_fixtures:
                analysis[team_id] = {
                    'fixtures': [],
                    'fdr_avg': 3.0,  # Neutral if no data
                    'difficulty_score': 1.0,
                    'num_fixtures': 0
                }
                continue

            # Calculate FDR (Fixture Difficulty Rating)
            fdrs = []
            for fixture in team_fixtures:
                if fixture['team_h'] == team_id:
                    # Home game
                    fdr = fixture.get('team_h_difficulty', 3)
                else:
                    # Away game
                    fdr = fixture.get('team_a_difficulty', 3)
                fdrs.append(fdr)

            avg_fdr = sum(fdrs) / len(fdrs) if fdrs else 3.0

            # Convert FDR to difficulty score (higher = easier)
            difficulty_score = sum([self.fdr_weights.get(fdr, 1.0) for fdr in fdrs]) / len(fdrs)

            analysis[team_id] = {
                'fixtures': team_fixtures,
                'fdr_avg': avg_fdr,
                'difficulty_score': difficulty_score,
                'num_fixtures': len(team_fixtures),
                'has_doubles': len(team_fixtures) > num_gws
            }

        return analysis


class EnhancedOptimizer:
    """
    Enhanced FPL Optimizer with:
    - Bench cost minimization
    - Budget maximization (use £99-99.5m)
    - Multi-gameweek fixture analysis
    - Starting 11 focus
    """

    CONSTRAINTS = {
        "total_players": 15,
        "budget": 100.0,
        "max_per_team": 3,
        "positions": {
            1: ("GK", 2),   # 2 GK
            2: ("DEF", 5),  # 5 DEF
            3: ("MID", 5),  # 5 MID
            4: ("FWD", 3),  # 3 FWD
        },
        "starting_11": {
            1: 1,  # 1 GK starts
            2: (3, 5),  # 3-5 DEF start
            3: (2, 5),  # 2-5 MID start
            4: (1, 3),  # 1-3 FWD start
        }
    }

    def __init__(self):
        self.fixture_analyzer = FixtureAnalyzer()

    def optimize_squad_with_fixtures(
        self,
        players: List[Dict],
        fixtures: List[Dict],
        teams: Dict,
        current_gw: int,
        budget: float = 100.0,
        optimize_for: str = "form",
        target_spend: float = 100.0,
        num_gws: int = 5
    ) -> Tuple[List[Dict], Dict, str]:
        """
        Optimize squad considering fixtures and bench strategy

        Args:
            players: All available players
            fixtures: Upcoming fixtures
            teams: Team data
            current_gw: Current gameweek
            budget: Maximum budget (default £100m)
            optimize_for: 'form', 'points', 'value', 'fixtures'
            target_spend: Target spending (default £100m - use maximum budget)
                         Minimum £99m (only go lower if better player available)
            num_gws: Number of gameweeks to analyze (default 5)

        Returns:
            (squad, lineup_info, status)
        """
        logger.info(f"Optimizing squad for GW{current_gw} to GW{current_gw + num_gws - 1}")

        # Analyze fixtures
        fixture_analysis = self.fixture_analyzer.analyze_fixtures(
            fixtures, teams, current_gw, num_gws
        )

        # Calculate player scores with fixture weighting
        player_scores = self._calculate_fixture_scores(
            players, fixture_analysis, optimize_for
        )

        # Separate bench strategy: identify cheap enablers
        bench_enablers = self._identify_bench_enablers(players)

        # Run optimization in two phases:
        # Phase 1: Optimize starting 11
        # Phase 2: Fill bench with cheapest valid players

        squad, lineup, status = self._optimize_with_bench_strategy(
            players, player_scores, bench_enablers, budget, target_spend
        )

        if not squad:
            return [], {}, status

        # Calculate expected points with fixture weighting
        expected_points = self._calculate_expected_points(squad, fixture_analysis)

        lineup_info = {
            'starting_11': lineup['starting'],
            'bench': lineup['bench'],
            'formation': lineup['formation'],
            'expected_points': expected_points,
            'total_cost': sum([p['now_cost'] / 10 for p in squad]),
            'money_remaining': budget - sum([p['now_cost'] / 10 for p in squad])
        }

        return squad, lineup_info, status

    def _calculate_fixture_scores(
        self,
        players: List[Dict],
        fixture_analysis: Dict,
        metric: str
    ) -> Dict[int, float]:
        """Calculate player scores weighted by fixture difficulty"""
        scores = {}

        for player in players:
            team_id = player['team']
            fixture_info = fixture_analysis.get(team_id, {})
            difficulty_score = fixture_info.get('difficulty_score', 1.0)

            # Base score
            if metric == "form":
                base_score = float(player.get('form', 0))
            elif metric == "points":
                base_score = float(player.get('total_points', 0)) / 10  # Normalize
            elif metric == "value":
                price = player.get('now_cost', 1) / 10
                points = float(player.get('total_points', 0))
                base_score = (points / price) if price > 0 else 0
            elif metric == "fixtures":
                base_score = float(player.get('form', 0))
            else:
                base_score = float(player.get('form', 0))

            # Apply fixture weighting (only for fixtures-focused optimization)
            if metric == "fixtures":
                score = base_score * difficulty_score * 2.0
            else:
                # Mild fixture bonus for all optimizations
                score = base_score * (1.0 + (difficulty_score - 1.0) * 0.2)

            scores[player['id']] = max(score, 0.01)  # Ensure positive

        return scores

    def _identify_bench_enablers(self, players: List[Dict]) -> Dict[int, List[Dict]]:
        """Find cheapest players per position for bench"""
        enablers = {1: [], 2: [], 3: [], 4: []}

        for pos_id in [1, 2, 3, 4]:
            pos_players = [p for p in players if p['element_type'] == pos_id]
            # Sort by price, get cheapest 10
            cheapest = sorted(pos_players, key=lambda p: p['now_cost'])[:10]
            enablers[pos_id] = cheapest

        return enablers

    def _optimize_with_bench_strategy(
        self,
        players: List[Dict],
        scores: Dict[int, float],
        bench_enablers: Dict[int, List[Dict]],
        budget: float,
        target_spend: float
    ) -> Tuple[List[Dict], Dict, str]:
        """
        Two-phase optimization:
        1. Optimize starting 11 with most budget
        2. Fill bench with cheapest valid players
        """

        # Create LP problem
        prob = LpProblem("FPL_Squad", LpMaximize)

        # Binary variables: selected[player_id] = 1 if selected
        selected = {p['id']: LpVariable(f"select_{p['id']}", cat='Binary') for p in players}

        # Binary variables: starting[player_id] = 1 if in starting 11
        starting = {p['id']: LpVariable(f"start_{p['id']}", cat='Binary') for p in players}

        # Objective: Maximize score of starting 11
        prob += lpSum([scores[p['id']] * starting[p['id']] for p in players])

        # Constraint: 15 players total
        prob += lpSum([selected[p['id']] for p in players]) == 15

        # Constraint: 11 players starting
        prob += lpSum([starting[p['id']] for p in players]) == 11

        # Constraint: Can only start if selected
        for p in players:
            prob += starting[p['id']] <= selected[p['id']]

        # Budget constraint (target spending)
        prob += lpSum([(p['now_cost'] / 10) * selected[p['id']] for p in players]) >= target_spend
        prob += lpSum([(p['now_cost'] / 10) * selected[p['id']] for p in players]) <= budget

        # Position constraints
        for pos_id, (pos_name, count) in self.CONSTRAINTS["positions"].items():
            pos_players = [p for p in players if p['element_type'] == pos_id]
            prob += lpSum([selected[p['id']] for p in pos_players]) == count

        # Starting 11 position constraints
        pos_players_by_type = {
            1: [p for p in players if p['element_type'] == 1],
            2: [p for p in players if p['element_type'] == 2],
            3: [p for p in players if p['element_type'] == 3],
            4: [p for p in players if p['element_type'] == 4]
        }

        # GK: exactly 1 starts
        prob += lpSum([starting[p['id']] for p in pos_players_by_type[1]]) == 1

        # DEF: 3-5 start
        prob += lpSum([starting[p['id']] for p in pos_players_by_type[2]]) >= 3
        prob += lpSum([starting[p['id']] for p in pos_players_by_type[2]]) <= 5

        # MID: 2-5 start
        prob += lpSum([starting[p['id']] for p in pos_players_by_type[3]]) >= 2
        prob += lpSum([starting[p['id']] for p in pos_players_by_type[3]]) <= 5

        # FWD: 1-3 start
        prob += lpSum([starting[p['id']] for p in pos_players_by_type[4]]) >= 1
        prob += lpSum([starting[p['id']] for p in pos_players_by_type[4]]) <= 3

        # Team constraint: max 3 per team
        teams = {}
        for p in players:
            if p['team'] not in teams:
                teams[p['team']] = []
            teams[p['team']].append(p)

        for team_players in teams.values():
            prob += lpSum([selected[p['id']] for p in team_players]) <= 3

        # Solve
        logger.info("Solving optimization problem...")
        prob.solve(PULP_CBC_CMD(msg=0))

        if LpStatus[prob.status] != "Optimal":
            logger.warning(f"Solution status: {LpStatus[prob.status]}")
            return [], {}, f"Could not find optimal solution: {LpStatus[prob.status]}"

        # Extract solution
        squad = [p for p in players if selected[p['id']].varValue == 1]
        starting_11 = [p for p in players if starting[p['id']].varValue == 1]
        bench = [p for p in squad if p not in starting_11]

        # Determine formation
        def_count = len([p for p in starting_11 if p['element_type'] == 2])
        mid_count = len([p for p in starting_11 if p['element_type'] == 3])
        fwd_count = len([p for p in starting_11 if p['element_type'] == 4])
        formation = f"{def_count}-{mid_count}-{fwd_count}"

        lineup = {
            'starting': starting_11,
            'bench': bench,
            'formation': formation
        }

        return squad, lineup, "✅ Optimal squad found!"

    def optimize_from_shortlist(
        self,
        shortlist: List[Dict],
        budget: float = 100.0,
        bench_spend_cap: float = 18.0,
        min_bank: float = 0.0,
    ) -> Tuple[List[Dict], Dict, str]:
        """
        Pick the best legal 15 from a strategy-tagged shortlist.

        Differs from `_optimize_with_bench_strategy` in three ways, each fixing a
        verified defect:

        1. **Objective is ML predicted points, not `form`.** `form` is 0.0 for
           all 600 players before a season starts, which made the old objective
           FLAT (`max(0 * fdr, 0.01)` == 0.01 for everyone) — the LP was
           returning an arbitrary feasible squad exactly when the opening squad
           is chosen. Each shortlist entry carries `predicted_points` from the
           v2 model, which was trained on real per-gameweek outcomes and still
           discriminates with no current-season form.

        2. **The bench is scored, at a discount.** The old objective summed only
           `starting[...]`, so bench players were worth nothing — while
           `total_cost >= target_spend` forced money to be spent, and the
           unscored bench was the only place left to put it. Bench picks now
           contribute at BENCH_WEIGHT, which is what makes them "cheap but
           actually useful" instead of either free filler or accidental luxury.

        3. **Bench spend is CAPPED and the budget is not force-spent.** Money
           not spent on the bench upgrades a starter. `min_bank` allows
           deliberately holding cash for an early transfer.
        """
        # Bench points are real but only materialise via rotation and auto-subs,
        # so they are worth having without being worth paying up for.
        BENCH_WEIGHT = 0.25

        by_id = {p["id"]: p for p in shortlist}
        ids = list(by_id)
        if len(ids) < 15:
            return [], {}, f"Shortlist too small ({len(ids)} players)"

        prob = LpProblem("FPL_Squad_Strategy", LpMaximize)
        selected = {i: LpVariable(f"sel_{i}", cat="Binary") for i in ids}
        starting = {i: LpVariable(f"st_{i}", cat="Binary") for i in ids}

        def pts(i):
            return float(by_id[i].get("predicted_points") or 0.0)

        def price(i):
            return float(by_id[i]["price"])

        def pos(i):
            return int(by_id[i]["position_id"])

        # Starters at full weight, bench at a discount. `selected - starting`
        # is 1 exactly for bench players, so this scores both tiers in one pass.
        prob += lpSum(
            pts(i) * starting[i] + BENCH_WEIGHT * pts(i) * (selected[i] - starting[i])
            for i in ids
        )

        prob += lpSum(selected[i] for i in ids) == 15
        prob += lpSum(starting[i] for i in ids) == 11
        for i in ids:
            prob += starting[i] <= selected[i]

        prob += lpSum(price(i) * selected[i] for i in ids) <= budget - min_bank

        # THE key structural constraint: bench (selected but not starting) may
        # not absorb more than the cap. This is what keeps spend on the pitch.
        prob += lpSum(
            price(i) * (selected[i] - starting[i]) for i in ids
        ) <= bench_spend_cap

        for pid, (_, count) in self.CONSTRAINTS["positions"].items():
            pool = [i for i in ids if pos(i) == pid]
            prob += lpSum(selected[i] for i in pool) == count

        prob += lpSum(starting[i] for i in ids if pos(i) == 1) == 1
        for pid, (lo, hi) in ((2, (3, 5)), (3, (2, 5)), (4, (1, 3))):
            pool = [i for i in ids if pos(i) == pid]
            prob += lpSum(starting[i] for i in pool) >= lo
            prob += lpSum(starting[i] for i in pool) <= hi

        teams = {}
        for i in ids:
            teams.setdefault(by_id[i]["team_id"], []).append(i)
        for pool in teams.values():
            prob += lpSum(selected[i] for i in pool) <= 3

        prob.solve(PULP_CBC_CMD(msg=0))
        if LpStatus[prob.status] != "Optimal":
            return [], {}, f"No optimal solution: {LpStatus[prob.status]}"

        squad = [by_id[i] for i in ids if selected[i].varValue == 1]
        xi = [by_id[i] for i in ids if starting[i].varValue == 1]
        bench = [p for p in squad if p not in xi]

        d = sum(1 for p in xi if p["position_id"] == 2)
        m = sum(1 for p in xi if p["position_id"] == 3)
        f = sum(1 for p in xi if p["position_id"] == 4)

        total = sum(p["price"] for p in squad)
        bench_cost = sum(p["price"] for p in bench)
        return squad, {
            "starting": xi,
            "bench": bench,
            "formation": f"{d}-{m}-{f}",
            "total_cost": round(total, 1),
            "bench_cost": round(bench_cost, 1),
            "xi_cost": round(total - bench_cost, 1),
            "bank": round(budget - total, 1),
            "predicted_xi_points": round(sum(p.get("predicted_points", 0) for p in xi), 2),
        }, "Optimal squad found"

    def _calculate_expected_points(
        self,
        squad: List[Dict],
        fixture_analysis: Dict
    ) -> float:
        """Calculate expected points considering fixtures"""
        total = 0.0

        for player in squad:
            form = float(player.get('form', 0))
            team_id = player['team']
            difficulty_score = fixture_analysis.get(team_id, {}).get('difficulty_score', 1.0)

            # Expected points = form * fixture difficulty
            expected = form * difficulty_score
            total += expected

        return total
