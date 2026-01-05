"""
Player Name Matching
Matches FPL players to external data sources using fuzzy matching
"""

from thefuzz import fuzz, process
from typing import Dict, List, Optional, Tuple
import json
from pathlib import Path
import unicodedata


# Team name mapping between FPL and external sources
# Maps FPL team ID to a list of possible team names (Understat, FBRef)
# Updated for 2025/26 season (Burnley, Leeds, Sunderland promoted)
TEAM_MAPPING = {
    # FPL ID -> List of team name variations (Understat, FBRef, etc.)
    1: ["Arsenal"],
    2: ["Aston Villa"],
    3: ["Burnley"],
    4: ["Bournemouth"],
    5: ["Brentford"],
    6: ["Brighton"],
    7: ["Chelsea"],
    8: ["Crystal Palace"],
    9: ["Everton"],
    10: ["Fulham"],
    11: ["Leeds"],
    12: ["Liverpool"],
    13: ["Manchester City"],
    14: ["Manchester United", "Manchester Utd"],
    15: ["Newcastle United", "Newcastle Utd", "Newcastle"],
    16: ["Nottingham Forest", "Nott'ham Forest"],
    17: ["Sunderland"],
    18: ["Tottenham"],
    19: ["West Ham"],
    20: ["Wolverhampton Wanderers", "Wolves"],
}


def normalize_name(name: str) -> str:
    """
    Normalize player name for better matching
    - Removes accents (José → Jose, João → Joao)
    - Converts to lowercase
    - Strips extra whitespace

    Args:
        name: Player name to normalize

    Returns:
        Normalized name
    """
    # Remove accents using Unicode normalization
    # NFD = Canonical Decomposition (separates base character from accent)
    # Then filter out combining characters (the accents)
    nfd = unicodedata.normalize('NFD', name)
    without_accents = ''.join(char for char in nfd if unicodedata.category(char) != 'Mn')

    # Convert to lowercase and strip whitespace
    return without_accents.lower().strip()


class PlayerNameMatcher:
    """Match FPL players to external data sources"""

    def __init__(self, manual_mappings_path: Optional[str] = None):
        """
        Initialize matcher

        Args:
            manual_mappings_path: Path to JSON file with manual name mappings
        """
        self.manual_mappings = {}
        self.match_log = []  # Track matching results for debugging

        if manual_mappings_path:
            self.load_manual_mappings(manual_mappings_path)

    def load_manual_mappings(self, path: str):
        """
        Load manual name mappings from JSON file

        Args:
            path: Path to JSON file
        """
        try:
            with open(path, 'r') as f:
                self.manual_mappings = json.load(f)
            # Note: Removed print() - it corrupts MCP stdout JSON protocol
        except FileNotFoundError:
            pass  # Silent - no mappings file is OK
        except Exception as e:
            import sys
            print(f"Error loading manual mappings: {e}", file=sys.stderr)

    def save_manual_mappings(self, path: str):
        """
        Save current manual mappings to JSON file

        Args:
            path: Path to save JSON file
        """
        try:
            with open(path, 'w') as f:
                json.dump(self.manual_mappings, f, indent=2)
            print(f"💾 Saved {len(self.manual_mappings)} manual mappings to {path}")
        except Exception as e:
            print(f"❌ Error saving manual mappings: {e}")

    def match_player(
        self,
        fpl_player: Dict,
        external_players: List[Dict],
        team_id: Optional[int] = None,
        threshold: int = 85
    ) -> Optional[Dict]:
        """
        Match a single FPL player to external data source

        Args:
            fpl_player: FPL player dict with 'first_name', 'second_name', 'web_name'
            external_players: List of external player dicts with 'name', 'team'
            team_id: FPL team ID for team-based filtering
            threshold: Minimum similarity score (0-100) to accept match

        Returns:
            Matched external player dict or None
        """
        # Build FPL player name variations
        first_name = fpl_player.get('first_name', '')
        second_name = fpl_player.get('second_name', '')
        web_name = fpl_player.get('web_name', '')

        fpl_full_name = f"{first_name} {second_name}".strip()

        # Check manual mappings first
        if fpl_full_name in self.manual_mappings:
            manual_name = self.manual_mappings[fpl_full_name]
            for ext_player in external_players:
                if ext_player['name'] == manual_name:
                    self._log_match(fpl_full_name, manual_name, 100, 'manual')
                    return ext_player

        # Filter external players by team if team_id provided
        candidates = external_players
        if team_id and team_id in TEAM_MAPPING:
            team_names = TEAM_MAPPING[team_id]  # Now a list of possible names
            candidates = [p for p in external_players if p.get('team') in team_names]

            if not candidates:
                # Fallback to all players if team filtering yields no results
                candidates = external_players

        # Try exact match first (case-insensitive)
        for candidate in candidates:
            if candidate['name'].lower() == fpl_full_name.lower():
                self._log_match(fpl_full_name, candidate['name'], 100, 'exact')
                return candidate

        # Try normalized exact match (accent-insensitive)
        fpl_normalized = normalize_name(fpl_full_name)
        for candidate in candidates:
            candidate_normalized = normalize_name(candidate['name'])
            if candidate_normalized == fpl_normalized:
                self._log_match(fpl_full_name, candidate['name'], 100, 'exact_normalized')
                return candidate

        # Fuzzy matching with normalized names
        candidate_names = [p['name'] for p in candidates]
        candidate_names_normalized = [normalize_name(p['name']) for p in candidates]

        # Try full name match (normalized)
        match = process.extractOne(
            fpl_normalized,
            candidate_names_normalized,
            scorer=fuzz.token_sort_ratio
        )

        if match and match[1] >= threshold:
            # Find the matching player by index (match[0] is the normalized name)
            matched_idx = candidate_names_normalized.index(match[0])
            matched_candidate = candidates[matched_idx]
            self._log_match(fpl_full_name, matched_candidate['name'], match[1], 'fuzzy_full_normalized')
            return matched_candidate

        # Try web_name match (e.g., "Salah" instead of "Mohamed Salah")
        if web_name:
            web_normalized = normalize_name(web_name)
            match = process.extractOne(
                web_normalized,
                candidate_names_normalized,
                scorer=fuzz.token_sort_ratio
            )

            if match and match[1] >= threshold:
                matched_idx = candidate_names_normalized.index(match[0])
                matched_candidate = candidates[matched_idx]
                self._log_match(fpl_full_name, matched_candidate['name'], match[1], 'fuzzy_web_normalized')
                return matched_candidate

        # No match found
        self._log_match(fpl_full_name, None, 0, 'no_match')
        return None

    def match_all_players(
        self,
        fpl_players: List[Dict],
        external_players: List[Dict],
        threshold: int = 85
    ) -> Tuple[Dict[int, Dict], List[Dict]]:
        """
        Match all FPL players to external data source

        Args:
            fpl_players: List of FPL player dicts
            external_players: List of external player dicts
            threshold: Minimum similarity score

        Returns:
            Tuple of (matched_dict, unmatched_list)
            - matched_dict: {fpl_player_id: external_player_dict}
            - unmatched_list: List of FPL players that couldn't be matched
        """
        matched = {}
        unmatched = []

        for fpl_player in fpl_players:
            fpl_id = fpl_player['id']
            team_id = fpl_player.get('team')

            external_match = self.match_player(
                fpl_player,
                external_players,
                team_id=team_id,
                threshold=threshold
            )

            if external_match:
                matched[fpl_id] = external_match
            else:
                unmatched.append(fpl_player)

        return matched, unmatched

    def _log_match(self, fpl_name: str, external_name: Optional[str], score: int, method: str):
        """Log match result for debugging"""
        self.match_log.append({
            'fpl_name': fpl_name,
            'external_name': external_name,
            'score': score,
            'method': method
        })

    def get_match_stats(self) -> Dict:
        """
        Get statistics about matching results

        Returns:
            Dict with match statistics
        """
        if not self.match_log:
            return {
                'total': 0,
                'matched': 0,
                'unmatched': 0,
                'match_rate': 0.0
            }

        total = len(self.match_log)
        matched = sum(1 for m in self.match_log if m['external_name'] is not None)
        unmatched = total - matched

        methods = {}
        for log in self.match_log:
            method = log['method']
            methods[method] = methods.get(method, 0) + 1

        return {
            'total': total,
            'matched': matched,
            'unmatched': unmatched,
            'match_rate': round((matched / total * 100), 2) if total > 0 else 0.0,
            'methods': methods
        }

    def get_unmatched_players(self) -> List[str]:
        """
        Get list of FPL player names that couldn't be matched

        Returns:
            List of unmatched player names
        """
        return [
            log['fpl_name']
            for log in self.match_log
            if log['external_name'] is None
        ]

    def clear_log(self):
        """Clear the match log"""
        self.match_log = []


# Testing
if __name__ == "__main__":
    # Test matching
    matcher = PlayerNameMatcher()

    # Sample FPL players
    fpl_players = [
        {
            'id': 1,
            'first_name': 'Mohamed',
            'second_name': 'Salah',
            'web_name': 'Salah',
            'team': 12  # Liverpool
        },
        {
            'id': 2,
            'first_name': 'Erling',
            'second_name': 'Haaland',
            'web_name': 'Haaland',
            'team': 13  # Man City
        },
        {
            'id': 3,
            'first_name': 'Gabriel',
            'second_name': 'Magalhães',
            'web_name': 'Gabriel',
            'team': 1  # Arsenal
        }
    ]

    # Sample Understat players
    understat_players = [
        {'name': 'Mohamed Salah', 'team': 'Liverpool', 'xG': 15.2},
        {'name': 'Erling Haaland', 'team': 'Manchester City', 'xG': 18.7},
        {'name': 'Gabriel Magalhaes', 'team': 'Arsenal', 'xG': 2.1}
    ]

    # Match all
    matched, unmatched = matcher.match_all_players(fpl_players, understat_players)

    print("Matched players:")
    for fpl_id, ext_player in matched.items():
        print(f"  FPL ID {fpl_id} -> {ext_player['name']} (xG: {ext_player['xG']})")

    print(f"\nUnmatched players: {len(unmatched)}")
    for player in unmatched:
        print(f"  - {player['first_name']} {player['second_name']}")

    # Show stats
    stats = matcher.get_match_stats()
    print(f"\nMatch Statistics:")
    print(f"  Total: {stats['total']}")
    print(f"  Matched: {stats['matched']}")
    print(f"  Match rate: {stats['match_rate']}%")
    print(f"  Methods: {stats['methods']}")
