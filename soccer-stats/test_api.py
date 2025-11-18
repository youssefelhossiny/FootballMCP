import os
import asyncio
import httpx
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

API_KEY = os.getenv("FOOTBALL_DATA_API_KEY")
API_BASE_URL = "https://api.football-data.org/v4"


async def test_api_key():
    """Test if your Football-Data.org API key works"""

    print("🔑 Testing Football-Data.org API Key...")
    print(f"API Key: {API_KEY[:10]}..." if API_KEY else "❌ No API key found!")

    if not API_KEY or API_KEY == "your_api_key_here":
        print("\n❌ ERROR: Please set your FOOTBALL_DATA_API_KEY in the .env file")
        print("Get your key from: https://www.football-data.org/client/register")
        return

    headers = {
        "X-Auth-Token": API_KEY
    }

    print("\n📡 Making test requests to Football-Data.org API...\n")

    async with httpx.AsyncClient() as client:
        try:
            # Test 1: Get Premier League info
            print("Test 1: Checking Premier League competition info...")
            response = await client.get(
                f"{API_BASE_URL}/competitions/PL",
                headers=headers,
                timeout=10.0
            )

            if response.status_code == 200:
                data = response.json()
                season = data.get("currentSeason", {})
                print(f"✅ SUCCESS! Current Premier League Season:")
                print(f"   Start: {season.get('startDate')}")
                print(f"   End: {season.get('endDate')}")
                print(f"   Matchday: {season.get('currentMatchday')}")
            elif response.status_code == 403:
                print("❌ API Key is invalid or expired")
                print(f"Response: {response.text}")
                return
            else:
                print(f"❌ Error: Status code {response.status_code}")
                print(f"Response: {response.text}")
                return

            print("\n" + "=" * 50)

            # Test 2: Get standings
            print("\nTest 2: Fetching Premier League standings...")
            response = await client.get(
                f"{API_BASE_URL}/competitions/PL/standings",
                headers=headers,
                timeout=10.0
            )

            if response.status_code == 200:
                data = response.json()
                if "standings" in data and data["standings"]:
                    table = data["standings"][0]["table"][:5]
                    print("✅ SUCCESS! Top 5 teams:")
                    for team in table:
                        print(f"   {team['position']}. {team['team']['name']} - {team['points']} pts")
                else:
                    print("⚠️  API responded but no standings data")
            else:
                print(f"❌ Error: Status code {response.status_code}")
                return

            print("\n" + "=" * 50)

            # Test 3: Get upcoming matches
            print("\nTest 3: Fetching upcoming Premier League matches...")
            today = datetime.now().date().isoformat()

            response = await client.get(
                f"{API_BASE_URL}/competitions/PL/matches",
                headers=headers,
                params={"status": "SCHEDULED"},
                timeout=10.0
            )

            if response.status_code == 200:
                data = response.json()
                if "matches" in data and data["matches"]:
                    print(f"✅ SUCCESS! Next 3 fixtures:")
                    for match in data["matches"][:3]:
                        home = match["homeTeam"]["name"]
                        away = match["awayTeam"]["name"]
                        match_date = datetime.fromisoformat(match["utcDate"].replace("Z", "+00:00"))
                        print(f"   {match_date.strftime('%b %d, %H:%M')} - {home} vs {away}")
                else:
                    print("⚠️  No upcoming matches found (might be off-season)")
            else:
                print(f"❌ Error: Status code {response.status_code}")

            print("\n" + "=" * 50)

            # Test 4: Get top scorers
            print("\nTest 4: Fetching top scorers...")
            response = await client.get(
                f"{API_BASE_URL}/competitions/PL/scorers",
                headers=headers,
                params={"limit": 3},
                timeout=10.0
            )

            if response.status_code == 200:
                data = response.json()
                if "scorers" in data and data["scorers"]:
                    print("✅ SUCCESS! Top 3 scorers:")
                    for scorer in data["scorers"][:3]:
                        player = scorer["player"]["name"]
                        team = scorer["team"]["name"]
                        goals = scorer["goals"]
                        print(f"   {player} ({team}) - {goals} goals")
                else:
                    print("⚠️  No scorer data available")
            else:
                print(f"❌ Error: Status code {response.status_code}")

            print("\n" + "=" * 50)
            print("\n🎉 ALL TESTS COMPLETED SUCCESSFULLY!")
            print("✅ Your API key is working with CURRENT SEASON data!")
            print("💡 You're ready to use the MCP server!\n")

            # Print rate limit info
            remaining = response.headers.get('X-Requests-Available-Minute', 'unknown')
            print(f"📊 API Requests remaining this minute: {remaining}")
            print(f"ℹ️  Free tier: 10 requests/minute, no daily limit\n")

        except httpx.HTTPError as e:
            print(f"❌ Network error: {e}")
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_api_key())