#!/usr/bin/env python3
"""
FPL Linear Programming Squad Optimizer
Phase 2b: True optimal squad selection using PuLP
"""

from pulp import *
import pandas as pd
from typing import List, Dict, Tuple
import logging
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error
from sklearn.preprocessing import StandardScaler
import numpy as np
import joblib
import os
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


class FPLPointsPredictor:
    """Machine Learning model to predict player points"""

    def __init__(self, model_dir: str = "models"):
        """Initialize predictor with model directory at project root"""

        # Get project root (parent of fpl-optimizer/)
        project_root = Path(__file__).parent.parent

        self.model = None
        self.scaler = None
        # Use absolute path to models/ at project root
        self.model_dir = project_root / model_dir
        self.model_path = self.model_dir / "points_model.pkl"
        self.scaler_path = self.model_dir / "scaler.pkl"
        self.features_path = self.model_dir / "features.txt"
        self.importance_path = self.model_dir / "feature_importance.pkl"

        self.feature_columns = [
            'form', 'total_points', 'minutes', 'goals_scored', 'assists',
            'clean_sheets', 'goals_conceded', 'bonus', 'bps', 'influence',
            'creativity', 'threat', 'ict_index', 'now_cost', 'selected_by_percent',
            'element_type', 'team'
        ]

    def load_model(self):
        """Load trained model from disk"""

        if not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"Model not found at {self.model_path}. "
                f"Run: python fpl-optimizer/predict_points.py"
            )

        self.model = joblib.load(self.model_path)
        self.scaler = joblib.load(self.scaler_path)

        with open(self.features_path, 'r') as f:
            self.feature_columns = [line.strip() for line in f.readlines()]

        logger.info(f"✅ Model loaded from {self.model_path}")
        logger.info(f"   Features: {len(self.feature_columns)}")

    def prepare_features(self, players: List[Dict]) -> pd.DataFrame:
        """Convert player dicts to feature DataFrame"""

        features = []
        for p in players:
            row = {
                'form': float(p.get('form', 0)),
                'total_points': int(p.get('total_points', 0)),
                'minutes': int(p.get('minutes', 0)),
                'goals_scored': int(p.get('goals_scored', 0)),
                'assists': int(p.get('assists', 0)),
                'clean_sheets': int(p.get('clean_sheets', 0)),
                'goals_conceded': int(p.get('goals_conceded', 0)),
                'bonus': int(p.get('bonus', 0)),
                'bps': int(p.get('bps', 0)),
                'influence': float(p.get('influence', 0)),
                'creativity': float(p.get('creativity', 0)),
                'threat': float(p.get('threat', 0)),
                'ict_index': float(p.get('ict_index', 0)),
                'now_cost': int(p.get('now_cost', 0)) / 10,
                'selected_by_percent': float(p.get('selected_by_percent', 0)),
                'element_type': int(p.get('element_type', 1)),
                'team': int(p.get('team', 1))
            }
            features.append(row)

        return pd.DataFrame(features)

    def train(self, training_data_path: str = None):
        """Train model on historical data from soccer-stats/"""

        # Default to soccer-stats/training_data.csv at project root
        if training_data_path is None:
            project_root = Path(__file__).parent.parent
            training_data_path = project_root / "fpl-optimizer" / "training_data.csv"

        print(f"📂 Loading training data from {training_data_path}")

        if not os.path.exists(training_data_path):
            print(f"❌ Training data not found at {training_data_path}")
            print(f"   Expected location: soccer-stats/training_data.csv")
            print(f"   Make sure training data exists in soccer-stats/ directory")
            return None, None

        # Load training data
        df = pd.read_csv(training_data_path)
        print(f"✅ Loaded {len(df)} training samples")

        # Prepare features and target
        X = df[self.feature_columns]
        y = df['points_next_gw']

        # Scale features
        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)

        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X_scaled, y, test_size=0.2, random_state=42
        )

        # Train model
        print("🤖 Training Random Forest model...")
        self.model = RandomForestRegressor(
            n_estimators=200,
            max_depth=15,
            min_samples_split=5,
            random_state=42,
            n_jobs=-1
        )
        self.model.fit(X_train, y_train)

        # Evaluate
        train_pred = self.model.predict(X_train)
        test_pred = self.model.predict(X_test)

        train_mae = mean_absolute_error(y_train, train_pred)
        test_mae = mean_absolute_error(y_test, test_pred)

        print(f"✅ Training MAE: {train_mae:.2f} points")
        print(f"✅ Testing MAE: {test_mae:.2f} points")

        # Save models to project root models/ directory
        os.makedirs(self.model_dir, exist_ok=True)

        joblib.dump(self.model, self.model_path)
        print(f"💾 Model saved to {self.model_path}")

        joblib.dump(self.scaler, self.scaler_path)
        print(f"💾 Scaler saved to {self.scaler_path}")

        # Save feature names
        with open(self.features_path, 'w') as f:
            f.write('\n'.join(self.feature_columns))
        print(f"💾 Features saved to {self.features_path}")

        # Save feature importance
        feature_importance = pd.DataFrame({
            'feature': self.feature_columns,
            'importance': self.model.feature_importances_
        }).sort_values('importance', ascending=False)

        joblib.dump(feature_importance, self.importance_path)
        print(f"💾 Feature importance saved to {self.importance_path}")

        print(f"\n📊 Top 5 Most Important Features:")
        for idx, row in feature_importance.head().iterrows():
            print(f"   {row['feature']:<25} {row['importance']:.4f}")

        return train_mae, test_mae

    def predict(self, players: List[Dict]) -> Dict[int, float]:
        """Predict points for players"""

        if self.model is None:
            if os.path.exists(self.model_path):
                self.model = joblib.load(self.model_path)
                self.scaler = joblib.load(self.scaler_path)
            else:
                raise ValueError("Model not trained. Run train() first.")

        X = self.prepare_features(players)
        X_scaled = self.scaler.transform(X)
        predictions = self.model.predict(X_scaled)

        return {p['id']: pred for p, pred in zip(players, predictions)}


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


if __name__ == "__main__":
    import asyncio
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    from Server import make_fpl_request


    async def test_predictor_and_optimizer():
        """Test both prediction and optimization"""

        # Step 1: Train prediction model
        print("=" * 60)
        print("STEP 1: Training Points Prediction Model")
        print("=" * 60)

        predictor = FPLPointsPredictor()
        train_mae, test_mae = predictor.train()

        if train_mae is None:
            print("\n❌ Training failed. Exiting...")
            return

        print("\n" + "=" * 60)
        print("STEP 2: Optimizing Squad")
        print("=" * 60)

        # Step 2: Fetch current players
        print("\nFetching FPL data...")
        data = await make_fpl_request("bootstrap-static/")

        if "error" in data:
            print(f"❌ Error: {data['error']}")
            return

        players = data.get('elements', [])
        print(f"✅ Loaded {len(players)} players\n")

        # Step 3: Optimize squad
        optimizer = FPLOptimizer()
        optimal_squad, status = optimizer.optimize_squad(
            players=players,
            budget=100.0,
            optimize_for="form"
        )

        print(status)
        print(f"\n📊 Optimal Squad ({len(optimal_squad)} players):")
        print(f"{'Name':<20} {'Team':<10} {'Pos':<5} {'Price':<8} {'Form':<6}")
        print("-" * 60)

        teams_dict = {t['id']: t for t in data.get('teams', [])}
        positions = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}

        total_cost = 0
        for p in sorted(optimal_squad, key=lambda x: (x['element_type'], -float(x.get('form', 0)))):
            team_name = teams_dict[p['team']]['short_name']
            pos = positions[p['element_type']]
            price = p['now_cost'] / 10
            total_cost += price
            form = p.get('form', 0)

            print(f"{p['web_name']:<20} {team_name:<10} {pos:<5} £{price:<7.1f} {form:<6}")

        print("-" * 60)
        print(f"Total Cost: £{total_cost:.1f}m / £100.0m")
        print(f"Remaining: £{100 - total_cost:.1f}m")


    asyncio.run(test_predictor_and_optimizer())
