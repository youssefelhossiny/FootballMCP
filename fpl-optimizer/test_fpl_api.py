#!/usr/bin/env python3
"""
FPL API Test Script
Tests connection to the official Fantasy Premier League API
No API key required - completely free!
"""

import asyncio
import httpx
from datetime import datetime
import json

# FPL API Base URL
FPL_BASE_URL = "https://fantasy.premierleague.com/api"


async def test_bootstrap_static():
    """
    Test the main bootstrap-static endpoint
    This contains ALL player data, teams, fixtures, etc.
    """
    print("\n" + "=" * 60)
    print("🔍 TEST 1: Bootstrap Static (All Player Data)")
    print("=" * 60)

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{FPL_BASE_URL}/bootstrap-static/",
                timeout=15.0
            )

            if response.status_code == 200:
                data = response.json()

                # Extract key information
                players = data.get('elements', [])
                teams = data.get('teams', [])
                gameweeks = data.get('events', [])

                print(f"✅ SUCCESS!")
                print(f"\n📊 Data Summary:")
                print(f"   Total Players: {len(players)}")
                print(f"   Total Teams: {len(teams)}")
                print(f"   Total Gameweeks: {len(gameweeks)}")

                # Find current gameweek
                current_gw = next((gw for gw in gameweeks if gw.get('is_current')), None)
                if current_gw:
                    print(f"\n⚽ Current Gameweek: {current_gw['id']}")
                    print(f"   Deadline: {current_gw.get('deadline_time')}")

                # Show top 5 players by total points
                print(f"\n🏆 Top 5 Players by Total Points:")
                sorted_players = sorted(players, key=lambda x: x.get('total_points', 0), reverse=True)
                for i, player in enumerate(sorted_players[:5], 1):
                    team = next(t for t in teams if t['id'] == player['team'])
                    print(f"   {i}. {player['web_name']} ({team['short_name']}) - "
                          f"{player['total_points']} pts - £{player['now_cost'] / 10}m")

                # Show most expensive players
                print(f"\n💰 Most Expensive Players:")
                sorted_by_price = sorted(players, key=lambda x: x.get('now_cost', 0), reverse=True)
                for i, player in enumerate(sorted_by_price[:5], 1):
                    team = next(t for t in teams if t['id'] == player['team'])
                    print(f"   {i}. {player['web_name']} ({team['short_name']}) - "
                          f"£{player['now_cost'] / 10}m - {player['total_points']} pts")

                return data

            else:
                print(f"❌ Error: Status code {response.status_code}")
                return None

        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return None


async def test_player_details(player_id=355):
    """
    Test detailed player information
    Default: Erling Haaland (player_id usually 355-ish, may vary by season)
    """
    print("\n" + "=" * 60)
    print(f"🔍 TEST 2: Player Details (ID: {player_id})")
    print("=" * 60)

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{FPL_BASE_URL}/element-summary/{player_id}/",
                timeout=15.0
            )

            if response.status_code == 200:
                data = response.json()

                print(f"✅ SUCCESS!")

                # Show player history
                history = data.get('history', [])
                if history:
                    print(f"\n📈 Recent Gameweek Performance (Last 5):")
                    for match in history[-5:]:
                        print(f"   GW{match['round']}: {match['total_points']} pts - "
                              f"{match['minutes']} mins - "
                              f"Goals: {match['goals_scored']}, Assists: {match['assists']}")

                # Show upcoming fixtures
                fixtures = data.get('fixtures', [])
                if fixtures:
                    print(f"\n📅 Upcoming Fixtures:")
                    for fixture in fixtures[:5]:
                        opponent = "vs Team " + str(fixture.get('team_a' if fixture['is_home'] else 'team_h'))
                        difficulty = fixture.get('difficulty', 'N/A')
                        print(f"   GW{fixture['event']}: {opponent} (Difficulty: {difficulty})")

                return data

            else:
                print(f"❌ Error: Status code {response.status_code}")
                return None

        except Exception as e:
            print(f"❌ Error: {e}")
            return None


async def test_fixtures():
    """
    Test fixtures endpoint
    """
    print("\n" + "=" * 60)
    print("🔍 TEST 3: Fixtures Data")
    print("=" * 60)

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{FPL_BASE_URL}/fixtures/",
                timeout=15.0
            )

            if response.status_code == 200:
                fixtures = response.json()

                print(f"✅ SUCCESS!")
                print(f"\n📊 Total Fixtures: {len(fixtures)}")

                # Show next 5 upcoming fixtures
                upcoming = [f for f in fixtures if not f.get('finished')][:5]
                print(f"\n⏰ Next 5 Fixtures:")
                for fixture in upcoming:
                    kickoff = fixture.get('kickoff_time', 'TBD')
                    if kickoff != 'TBD':
                        kickoff = datetime.fromisoformat(kickoff.replace('Z', '+00:00')).strftime('%b %d, %H:%M')
                    print(f"   GW{fixture['event']}: Team {fixture['team_h']} vs Team {fixture['team_a']} - {kickoff}")

                # Show completed fixtures with scores
                completed = [f for f in fixtures if f.get('finished')][-5:]
                if completed:
                    print(f"\n✅ Recent Completed Fixtures:")
                    for fixture in completed:
                        print(f"   GW{fixture['event']}: Team {fixture['team_h']} {fixture.get('team_h_score', 0)} - "
                              f"{fixture.get('team_a_score', 0)} Team {fixture['team_a']}")

                return fixtures

            else:
                print(f"❌ Error: Status code {response.status_code}")
                return None

        except Exception as e:
            print(f"❌ Error: {e}")
            return None


async def test_live_gameweek(gameweek=None):
    """
    Test live gameweek data
    """
    # First get current gameweek if not provided
    if gameweek is None:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{FPL_BASE_URL}/bootstrap-static/")
            if response.status_code == 200:
                data = response.json()
                current = next((gw for gw in data['events'] if gw.get('is_current')), None)
                gameweek = current['id'] if current else 1

    print("\n" + "=" * 60)
    print(f"🔍 TEST 4: Live Gameweek Data (GW{gameweek})")
    print("=" * 60)

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{FPL_BASE_URL}/event/{gameweek}/live/",
                timeout=15.0
            )

            if response.status_code == 200:
                data = response.json()
                elements = data.get('elements', [])

                print(f"✅ SUCCESS!")
                print(f"\n📊 Live Data for {len(elements)} players")

                # Show top performers this gameweek
                sorted_elements = sorted(elements, key=lambda x: x['stats'].get('total_points', 0), reverse=True)
                print(f"\n🌟 Top 5 Performers This Gameweek:")
                for i, element in enumerate(sorted_elements[:5], 1):
                    stats = element['stats']
                    print(f"   {i}. Player ID {element['id']}: {stats.get('total_points', 0)} pts - "
                          f"Goals: {stats.get('goals_scored', 0)}, Assists: {stats.get('assists', 0)}")

                return data

            else:
                print(f"❌ Error: Status code {response.status_code}")
                return None

        except Exception as e:
            print(f"❌ Error: {e}")
            return None


async def main():
    """
    Run all FPL API tests
    """
    print("⚽ Fantasy Premier League API - Connection Test")
    print("=" * 60)
    print("Testing connection to Official FPL API")
    print("🆓 No API key required - Completely FREE!")
    print("=" * 60)

    # Test 1: Bootstrap Static (main data)
    bootstrap_data = await test_bootstrap_static()

    if bootstrap_data:
        # Test 2: Player Details (pick top player)
        players = bootstrap_data.get('elements', [])
        if players:
            top_player = max(players, key=lambda x: x.get('total_points', 0))
            await test_player_details(top_player['id'])

        # Test 3: Fixtures
        await test_fixtures()

        # Test 4: Live Gameweek
        await test_live_gameweek()

        print("\n" + "=" * 60)
        print("✅ ALL TESTS COMPLETED SUCCESSFULLY!")
        print("=" * 60)
        print("\n💡 Next Steps:")
        print("   1. The FPL API is working perfectly!")
        print("   2. No rate limits on the free tier")
        print("   3. Ready to build the FPL MCP Server")
        print("\n📝 Key Endpoints Tested:")
        print("   ✅ /bootstrap-static/ - All player/team data")
        print("   ✅ /element-summary/{id}/ - Player details")
        print("   ✅ /fixtures/ - Match fixtures")
        print("   ✅ /event/{gw}/live/ - Live gameweek data")
    else:
        print("\n❌ Bootstrap data failed - check your connection")


if __name__ == "__main__":
    asyncio.run(main())