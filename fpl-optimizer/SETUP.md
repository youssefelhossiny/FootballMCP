# FPL MCP Server - Setup Guide

## ✅ Phase 1 Complete: All 5 Data Tools Implemented!

### 🎉 What's Working

All 5 core data collection tools are now fully implemented:

1. ✅ **get_all_players** - Filter & sort all 600+ PL players
2. ✅ **get_player_details** - Deep dive into any player
3. ✅ **get_fixtures** - Upcoming matches with difficulty ratings
4. ✅ **get_my_team** - View your FPL squad (needs team ID)
5. ✅ **get_top_performers** - Top players by any metric

## 🚀 Quick Start (3 Steps)

### Step 1: Update Your Server.py

Replace your current `fpl-optimizer/Server.py` with the complete version from the artifact.

### Step 2: Test All Tools

```bash
cd fpl-optimizer
python test_tools.py
```

**Expected Output:**
```
⚽ FPL MCP Server - Tool Testing
============================================================

🔍 TEST 1: get_all_players
✅ Total players loaded: 623
✅ Midfielders under £8m: 145
🏆 Top 3 Midfielders under £8m:
   1. Bruno Fernandes (MUN) - £8.0m - 48 pts
   ...

🔍 TEST 2: get_player_details
✅ Found player: Salah (ID: 355)
✅ Retrieved 17 past gameweeks
✅ Retrieved 21 upcoming fixtures
...

📊 TEST SUMMARY
============================================================
✅ PASS: get_all_players
✅ PASS: get_player_details
✅ PASS: get_fixtures
✅ PASS: get_my_team
✅ PASS: get_top_performers

🎯 Results: 5/5 tests passed
🎉 ALL TESTS PASSED!
```

### Step 3: Configure Your MCP Client

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on Mac):

```json
{
  "mcpServers": {
    "fpl-optimizer": {
      "command": "python",
      "args": ["/absolute/path/to/FootballMCP/fpl-optimizer/Server.py"]
    }
  }
}
```

**Then restart Claude Desktop!**

## 🎮 Try These Queries

Once configured, try asking Claude:

### Player Research
```
"Show me all midfielders under £7.5m sorted by form"
"Tell me about Erling Haaland's stats and upcoming fixtures"
"Who are the best value defenders right now?"
```

### Fixture Analysis
```
"Which teams have the easiest fixtures in the next 5 gameweeks?"
"Show me Liverpool's upcoming matches"
"What's the fixture difficulty for Manchester City?"
```

### Top Performers
```
"Who are the top 10 scorers this season?"
"Show me the most in-form players"
"Which players have the best points per million value?"
```

### Team Management
```
"Show me my FPL team"
(You'll need your team ID: fantasy.premierleague.com/entry/YOUR_ID/)
```

## 📊 Tool Details

### 1. get_all_players

**Filters:**
- `position`: GK, DEF, MID, FWD, all
- `team`: Any Premier League team (partial match)
- `max_price`: e.g., 7.5 for £7.5m
- `min_price`: e.g., 5.0 for £5.0m
- `sort_by`: points, form, value, price
- `limit`: 1-100 players (default: 20)

**Example:**
```
"Show me all Arsenal defenders under £6m sorted by points"
```

### 2. get_player_details

**Shows:**
- Season totals (points, goals, assists, clean sheets)
- Last 5 gameweek performances
- Next 5 fixtures with difficulty (1-5)
- Ownership %, form, price

**Example:**
```
"Tell me about Cole Palmer"
```

### 3. get_fixtures

**Parameters:**
- `team`: Filter for specific team (optional)
- `gameweeks`: Number of GWs ahead (1-10, default: 5)

**Shows:**
- Fixture Difficulty Rating (FDR) for both teams
- Home/away fixtures
- Kickoff times

**Example:**
```
"Show me Manchester City's fixtures for the next 8 gameweeks"
```

### 4. get_my_team

**Requires:**
- `team_id`: Your FPL team ID from URL
- `gameweek`: Optional (defaults to current)

**Shows:**
- All 15 players grouped by position
- Captain/Vice-captain markers
- Team value, money in bank
- Free transfers available
- Overall rank and points

**Example:**
```
"Show me my team" (if you've set up team ID)
```

**Finding Your Team ID:**
1. Go to fantasy.premierleague.com
2. Log in and go to "Points"
3. Your URL will be: `fantasy.premierleague.com/entry/YOUR_ID/event/17`
4. The number after `/entry/` is your team ID

### 5. get_top_performers

**Metrics:**
- `total_points`: Season total
- `form`: Last 5 gameweeks average
- `value`: Points per £
- `selected_by`: Ownership %
- `transfers_in`: This gameweek
- `bonus`: Bonus points total

**Filters:**
- `position`: GK, DEF, MID, FWD, all
- `limit`: 1-50 players (default: 10)

**Examples:**
```
"Who are the top 20 players by total points?"
"Show me the most in-form forwards"
"Which defenders have the best value?"
```

## 🐛 Troubleshooting

### "Could not find team" error
- Make sure you're using YOUR team ID from the FPL website
- Team must be active for current season
- URL format: `fantasy.premierleague.com/entry/YOUR_ID/`

### "Player not found" error
- Try shorter names (e.g., "Haaland" not "Erling Haaland")
- Player names use partial matching
- Check spelling

### "No fixtures found"
- Make sure you're within the season dates
- Try increasing `gameweeks` parameter
- Check if team name is spelled correctly

### Server not connecting
1. Test the API first: `python test_fpl_api.py`
2. Check your Python version (3.8+)
3. Reinstall dependencies: `pip install -r requirements.txt`
4. Verify server path in MCP config

## 📁 Your File Structure

```
FootballMCP/
├── .env
├── .venv/
├── models/
├── README.md
│
├── soccer-stats/
│   └── ... (original server)
│
└── fpl-optimizer/
    ├── Server.py           ← Updated with all 5 tools
    ├── test_fpl_api.py     ← API connection test
    ├── test_tools.py       ← NEW: Test all tools
    ├── requirements.txt
    ├── README.md
    └── SETUP.md           ← This file
```

## 🎯 What's Next: Phase 2

With Phase 1 complete, we can now move to Phase 2:

### Optimization Tools (Coming Next)
1. **optimize_squad** - Build best 15-player team (Linear Programming)
2. **optimize_lineup** - Best starting 11 from your squad
3. **suggest_transfers** - Smart transfer recommendations
4. **suggest_captain** - Data-driven captain picks
5. **evaluate_transfer** - Analyze specific transfer options

### Advanced Features
- Machine learning for points prediction
- Expected points calculations
- Fixture difficulty trends
- Transfer hit analysis (-4 pts worth it?)

## 📚 Resources

- [FPL Official Site](https://fantasy.premierleague.com/)
- [FPL Rules](https://fantasy.premierleague.com/help/rules)
- [FPL API (Unofficial Docs)](https://medium.com/@frenzelts/fantasy-premier-league-api-endpoints-a-detailed-guide-acbd5598eb19)

## ✅ Verification Checklist

Before moving to Phase 2, verify:

- [ ] `test_fpl_api.py` passes all tests
- [ ] `test_tools.py` shows 5/5 tests passed
- [ ] MCP server starts without errors: `python Server.py`
- [ ] MCP client (Claude Desktop) connects successfully
- [ ] Can query player data through LLM
- [ ] Can view fixtures and top performers

Once all checked, you're ready for Phase 2: Optimization! 🚀