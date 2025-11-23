#!/usr/bin/env python3
"""
Diagnostic Test Suite for Phase 2b FPL Tools
Tests all tools as if the LLM is calling them
Captures errors and provides detailed diagnostics
"""

import asyncio
import sys
import traceback
from pathlib import Path

# Add fpl-optimizer to path
sys.path.insert(0, str(Path(__file__).parent))

print("="*70)
print("PHASE 2B DIAGNOSTIC TEST SUITE")
print("="*70)
print()

# Test 1: Check imports
print("TEST 1: Checking imports...")
print("-"*70)

try:
    from Server import (
        handle_call_tool,
        optimizer,
        enhanced_optimizer,
        fixture_analyzer,
        chips_analyzer,
        predictor,
        make_fpl_request
    )
    print("✅ All imports successful")
    print(f"   - optimizer: {type(optimizer)}")
    print(f"   - enhanced_optimizer: {type(enhanced_optimizer)}")
    print(f"   - fixture_analyzer: {type(fixture_analyzer)}")
    print(f"   - chips_analyzer: {type(chips_analyzer)}")
    print(f"   - predictor: {type(predictor)}")
except Exception as e:
    print(f"❌ Import failed: {e}")
    traceback.print_exc()
    sys.exit(1)

print()

# Test 2: Check predictor model
print("TEST 2: Checking predictor model...")
print("-"*70)

try:
    if predictor.model is None:
        print("⚠️  Predictor model is None")
        print("   Attempting to load model...")
        predictor.load_model()

    if predictor.model is not None:
        print("✅ Predictor model loaded successfully")
        print(f"   Model type: {type(predictor.model)}")
        print(f"   Scaler: {type(predictor.scaler)}")
    else:
        print("❌ Predictor model failed to load")
except Exception as e:
    print(f"❌ Predictor check failed: {e}")
    traceback.print_exc()

print()

# Test 3: Test API connectivity
print("TEST 3: Testing FPL API connectivity...")
print("-"*70)

async def test_api():
    try:
        # Test bootstrap
        print("Fetching bootstrap-static...")
        bootstrap = await make_fpl_request("bootstrap-static/")

        if "error" in bootstrap:
            print(f"❌ Bootstrap error: {bootstrap['error']}")
            return False

        players = bootstrap.get('elements', [])
        teams = bootstrap.get('teams', [])
        events = bootstrap.get('events', [])

        print(f"✅ Bootstrap successful:")
        print(f"   - Players: {len(players)}")
        print(f"   - Teams: {len(teams)}")
        print(f"   - Events: {len(events)}")

        # Test fixtures
        print("\nFetching fixtures...")
        fixtures = await make_fpl_request("fixtures/")

        if "error" in fixtures:
            print(f"❌ Fixtures error: {fixtures['error']}")
            return False

        if isinstance(fixtures, list):
            print(f"✅ Fixtures successful: {len(fixtures)} fixtures")
        else:
            print(f"⚠️  Unexpected fixtures format: {type(fixtures)}")

        return True

    except Exception as e:
        print(f"❌ API test failed: {e}")
        traceback.print_exc()
        return False

api_ok = asyncio.run(test_api())
print()

if not api_ok:
    print("❌ Cannot proceed - API connectivity failed")
    sys.exit(1)

# Test 4: Test optimize_squad_lp with different arguments
print("TEST 4: Testing optimize_squad_lp tool...")
print("-"*70)

async def test_optimize_squad_lp():
    test_cases = [
        ("No arguments (None)", None),
        ("Empty dict", {}),
        ("With defaults", {"budget": 100.0, "optimize_for": "fixtures"}),
        ("Custom budget", {"budget": 95.0, "optimize_for": "form", "target_spend": 94.0}),
    ]

    for test_name, args in test_cases:
        print(f"\nTest case: {test_name}")
        print(f"Arguments: {args}")

        try:
            result = await handle_call_tool("optimize_squad_lp", args)

            if result and len(result) > 0:
                text = result[0].text

                # Check for error markers
                if "❌" in text:
                    print(f"⚠️  Tool returned error:")
                    print(f"   {text[:200]}...")
                elif "🎯 OPTIMAL SQUAD" in text:
                    print(f"✅ Success! Squad generated")
                    # Extract key info
                    lines = text.split('\n')
                    for line in lines[:10]:  # First 10 lines
                        if any(x in line for x in ['Cost:', 'Remaining:', 'Expected Points:', 'Formation:']):
                            print(f"   {line.strip()}")
                else:
                    print(f"⚠️  Unexpected response format")
                    print(f"   First 200 chars: {text[:200]}")
            else:
                print(f"❌ No result returned")

        except Exception as e:
            print(f"❌ Exception raised: {e}")
            traceback.print_exc()

    return True

asyncio.run(test_optimize_squad_lp())
print()

# Test 5: Test analyze_fixtures
print("TEST 5: Testing analyze_fixtures tool...")
print("-"*70)

async def test_analyze_fixtures():
    test_cases = [
        ("Default arguments", None),
        ("Custom GWs", {"num_gameweeks": 3}),
        ("Team filter", {"team_filter": "Arsenal"}),
    ]

    for test_name, args in test_cases:
        print(f"\nTest case: {test_name}")
        print(f"Arguments: {args}")

        try:
            result = await handle_call_tool("analyze_fixtures", args)

            if result and len(result) > 0:
                text = result[0].text

                if "❌" in text:
                    print(f"⚠️  Tool returned error: {text[:150]}")
                elif "FIXTURE ANALYSIS" in text:
                    print(f"✅ Success! Fixtures analyzed")
                    lines = text.split('\n')
                    for line in lines[:8]:
                        print(f"   {line.strip()}")
                else:
                    print(f"⚠️  Unexpected format: {text[:150]}")
            else:
                print(f"❌ No result returned")

        except Exception as e:
            print(f"❌ Exception: {e}")
            traceback.print_exc()

asyncio.run(test_analyze_fixtures())
print()

# Test 6: Test suggest_chips_strategy
print("TEST 6: Testing suggest_chips_strategy tool...")
print("-"*70)

async def test_chips_strategy():
    test_cases = [
        ("Wildcard only", {"available_chips": ["Wildcard"]}),
        ("Multiple chips", {"available_chips": ["Wildcard", "Bench Boost", "Triple Captain"]}),
        ("All chips", {"available_chips": ["Wildcard", "Free Hit", "Bench Boost", "Triple Captain"]}),
    ]

    for test_name, args in test_cases:
        print(f"\nTest case: {test_name}")
        print(f"Arguments: {args}")

        try:
            result = await handle_call_tool("suggest_chips_strategy", args)

            if result and len(result) > 0:
                text = result[0].text

                if "❌" in text:
                    print(f"⚠️  Tool returned error: {text[:150]}")
                elif "CHIPS STRATEGY" in text:
                    print(f"✅ Success! Chips analyzed")
                    lines = text.split('\n')
                    for line in lines[:10]:
                        if line.strip():
                            print(f"   {line.strip()}")
                else:
                    print(f"⚠️  Unexpected format: {text[:150]}")
            else:
                print(f"❌ No result returned")

        except Exception as e:
            print(f"❌ Exception: {e}")
            traceback.print_exc()

asyncio.run(test_chips_strategy())
print()

# Test 7: Test predictor directly
print("TEST 7: Testing predictor directly...")
print("-"*70)

async def test_predictor():
    try:
        # Get some real player data
        bootstrap = await make_fpl_request("bootstrap-static/")
        players = bootstrap.get('elements', [])[:10]  # First 10 players

        print(f"Testing with {len(players)} players...")

        # Test predict method
        predictions = predictor.predict(players)
        print(f"✅ predict() returned {len(predictions)} predictions")
        print(f"   Sample: {list(predictions.items())[:3]}")

        # Test predict_player_points wrapper
        if players:
            test_player = players[0]
            single_pred = predictor.predict_player_points(test_player, {}, {})
            print(f"✅ predict_player_points() returned: {single_pred:.2f}")
            print(f"   Player: {test_player['web_name']}")

        return True

    except Exception as e:
        print(f"❌ Predictor test failed: {e}")
        traceback.print_exc()
        return False

asyncio.run(test_predictor())
print()

# Test 8: Check enhanced optimizer directly
print("TEST 8: Testing enhanced optimizer directly...")
print("-"*70)

async def test_enhanced_optimizer():
    try:
        bootstrap = await make_fpl_request("bootstrap-static/")
        fixtures = await make_fpl_request("fixtures/")

        players = bootstrap.get('elements', [])
        teams = {t['id']: t for t in bootstrap.get('teams', [])}
        events = bootstrap.get('events', [])
        current_gw = next((e['id'] for e in events if e.get('is_current')), 1)

        print(f"Running enhanced optimizer...")
        print(f"  Players: {len(players)}")
        print(f"  Fixtures: {len(fixtures) if isinstance(fixtures, list) else 'N/A'}")
        print(f"  Current GW: {current_gw}")

        squad, lineup_info, status = enhanced_optimizer.optimize_squad_with_fixtures(
            players=players,
            fixtures=fixtures if isinstance(fixtures, list) else [],
            teams=teams,
            current_gw=current_gw,
            budget=100.0,
            optimize_for='fixtures',
            target_spend=99.0,
            num_gws=5
        )

        print(f"\n{status}")

        if squad:
            print(f"✅ Enhanced optimizer works!")
            print(f"   Squad size: {len(squad)}")
            print(f"   Total cost: £{lineup_info['total_cost']:.1f}m")
            print(f"   Remaining: £{lineup_info['money_remaining']:.1f}m")
            print(f"   Formation: {lineup_info['formation']}")
            print(f"   Expected points: {lineup_info['expected_points']:.1f}")
            return True
        else:
            print(f"❌ Enhanced optimizer failed: {status}")
            return False

    except Exception as e:
        print(f"❌ Enhanced optimizer test failed: {e}")
        traceback.print_exc()
        return False

asyncio.run(test_enhanced_optimizer())
print()

# Final Summary
print("="*70)
print("DIAGNOSTIC SUMMARY")
print("="*70)
print()
print("If all tests passed ✅, the tools should work when LLM calls them.")
print("If tests failed ❌, check the error messages above for the root cause.")
print()
print("Common issues:")
print("  1. Predictor model not loaded → Run: python fpl-optimizer/predict_points.py")
print("  2. API connectivity issues → Check internet connection")
print("  3. Import errors → Check file structure and dependencies")
print("  4. Fixture data format issues → Check FPL API response format")
print()
print("Next steps:")
print("  - If optimize_squad_lp fails: Check enhanced_optimization.py")
print("  - If predictor fails: Check models/ directory has .pkl files")
print("  - If API fails: Check FPL API status")
print("="*70)
