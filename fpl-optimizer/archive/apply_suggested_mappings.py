#!/usr/bin/env python3
"""
Apply suggested player name mappings with review
"""
import json
from pathlib import Path


def apply_mappings():
    """Apply suggested mappings to manual_mappings.json"""

    print("=" * 80)
    print("APPLY SUGGESTED MAPPINGS")
    print("=" * 80)
    print()

    # Load suggestions
    suggestions_file = "suggested_mappings.json"
    if not Path(suggestions_file).exists():
        print(f"❌ No suggestions file found: {suggestions_file}")
        print("   Run: python3 find_unmatched_players.py first")
        return

    with open(suggestions_file, 'r') as f:
        suggestions = json.load(f)

    print(f"📋 Loaded {len(suggestions)} suggested mappings")
    print()

    # Load current manual mappings
    mappings_file = "player_mapping/manual_mappings.json"
    with open(mappings_file, 'r') as f:
        current_mappings = json.load(f)

    print(f"📊 Current manual mappings: {len(current_mappings)}")
    print()

    # Filter by confidence
    high_conf = [s for s in suggestions if s['confidence'] == 'MEDIUM']  # 70-74%
    medium_conf = [s for s in suggestions if s['confidence'] == 'LOW']   # 60-69%

    print(f"Suggestions breakdown:")
    print(f"  MEDIUM confidence (70-74%): {len(high_conf)}")
    print(f"  LOW confidence (60-69%): {len(medium_conf)}")
    print()

    # Strategy: Auto-apply MEDIUM confidence, review LOW
    print("=" * 80)
    print("STRATEGY")
    print("=" * 80)
    print()
    print("Auto-applying MEDIUM confidence mappings (70-74% match score)")
    print("These are highly likely to be correct matches")
    print()

    if not high_conf:
        print("✅ No MEDIUM confidence suggestions to apply")
        print()
    else:
        print(f"{'FPL Name':35} → {'Understat Name':35} {'Score':>6}")
        print("-" * 90)

        new_mappings = {}
        for s in high_conf:
            fpl_name = s['fpl_name']
            understat_name = s['understat_name']
            score = s['score']

            print(f"{fpl_name:35} → {understat_name:35} {score:5d}%")

            # Add to new mappings
            new_mappings[fpl_name] = understat_name

        print()
        print(f"📝 Ready to add {len(new_mappings)} new mappings")
        print()

        # Confirm
        response = input("Apply these mappings? (y/n): ").strip().lower()

        if response == 'y':
            # Merge with current mappings
            current_mappings.update(new_mappings)

            # Save
            with open(mappings_file, 'w') as f:
                json.dump(current_mappings, f, indent=2)

            print(f"✅ Added {len(new_mappings)} new mappings!")
            print(f"   Total mappings now: {len(current_mappings)}")
        else:
            print("❌ Cancelled - no changes made")

    print()
    print("=" * 80)
    print("LOW CONFIDENCE MAPPINGS (60-69%)")
    print("=" * 80)
    print()
    print(f"Found {len(medium_conf)} low-confidence suggestions")
    print("These require manual review - some may be incorrect")
    print()

    if medium_conf:
        print("Sample low-confidence suggestions:")
        for s in medium_conf[:10]:
            print(f"  {s['fpl_name']:30} → {s['understat_name']:30} ({s['score']}%)")

        print()
        print("💡 To review these:")
        print("   1. Check suggested_mappings.json")
        print("   2. Manually verify on Understat website")
        print("   3. Add correct mappings to player_mapping/manual_mappings.json")

    print()
    print("=" * 80)
    print("NEXT STEPS")
    print("=" * 80)
    print()
    print("Re-run the matcher to see improved match rate:")
    print("  python3 collect_fpl_training_data.py")
    print()


if __name__ == "__main__":
    apply_mappings()
