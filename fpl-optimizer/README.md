# FPL Optimizer MCP Server

> **Fantasy Premier League** optimization tools powered by the official FPL API

## 🎯 What This Server Does

Helps you dominate your Fantasy Premier League mini-league with:
- **Player Analysis** - Stats, prices, form, fixtures for all 600+ PL players
- **Team Optimization** - Build the best possible squad within £100m budget
- **Transfer Recommendations** - Smart suggestions for who to transfer in/out
- **Captain Picks** - Data-driven captain choices each gameweek
- **Fixture Analysis** - Upcoming difficulty for all teams

## 📊 Data Source

- **Official FPL API**: `https://fantasy.premierleague.com/api/`
- ✅ **Completely FREE** - No API key required
- ✅ **No rate limits** - Unlimited requests
- ✅ **Real-time data** - Updated instantly during matches

## 🛠️ Current Tools (Phase 1)

### 1. `get_all_players`
Get all Premier League players with filtering and sorting.

**Use Cases:**
- "Show me all midfielders under £8m"
- "List Arsenal players sorted by points"
- "Who are the best value defenders?"

**Filters:**
- Position: GK, DEF, MID, FWD
- Team: Any Premier League team
- Price range: Min/max price
- Sort: points, form, value, price

### 2. `get_player_details`
Deep dive into a specific player's stats and fixtures.

**Use Cases:**
- "Tell me about Erling Haaland"
- "Show me Salah's recent form"
- "What are Palmer's upcoming fixtures?"

**Shows:**
- Season totals (points, goals, assists, clean sheets)
- Last 5 gameweek performances
- Next 5 fixtures with difficulty ratings
- Ownership %, form, price

### 3. `get_fixtures` *(Coming Soon)*
Upcoming Premier League fixtures with FPL difficulty ratings.

### 4. `get_my_team` *(Coming Soon)*
View your current FPL squad (requires team ID).

### 5. `get_top_performers` *(Coming Soon)*
Top players by various metrics (points, form, value, ownership).

## 🚀 Quick Start

### 1. Test the FPL API

```bash
cd fpl-optimizer
python test_fpl_api.py
```

This will test all FPL API endpoints and show:
- ✅ Connection status
- 📊 Current gameweek
- 🏆 Top 5 players by points
- 💰 Most expensive players
- 📅 Upcoming fixtures

### 2. Run the MCP Server

```bash
python Server.py
```

### 3. Configure Your LLM Client

Add to your MCP client config (Claude Desktop, etc.):

```json
{
  "mcpServers": {
    "fpl-optimizer": {
      "command": "python",
      "args": ["/path/to/fpl-optimizer/Server.py"]
    }
  }
}
```

## 📝 Example Queries

**Player Research:**
```
"Show me all midfielders under £7.5m sorted by form"
"Tell me about Mohamed Salah's stats and upcoming fixtures"
"Who are the best value forwards?"
```

**Team Building:**
```
"Which defenders have the easiest fixtures in the next 5 gameweeks?"
"Show me high-scoring players under £10m"
"List Arsenal players sorted by points"
```

**Decision Making:**
```
"Should I buy Haaland or go for cheaper options?"
"Compare Salah vs Son for the next few weeks"
"Who's the best captain pick for this gameweek?"
```

## 🗂️ Project Structure

```
fpl-optimizer/
├── Server.py              # Main MCP server
├── test_fpl_api.py        # API testing script
├── requirements.txt       # Python dependencies
└── README.md             # This file
```

## 📦 Dependencies

```
mcp>=1.0.0
httpx>=0.27.0
```

Install with:
```bash
pip install -r requirements.txt
```

# Phase 2 Updates + Bug Fixes

## 🐛 Bugs Fixed

### 1. ✅ Fixed: Misleading Transfer Display
**Problem:** `get_my_team` showed "Free Transfers: 0" which was actually the number of transfers MADE in the gameweek, not the number of free transfers AVAILABLE.

**Solution:**
- Changed label to "Transfers Made This GW: X"
- Added clear warning: "⚠️ NOTE: API cannot show free transfers remaining"
- Prompts user to provide free transfer count when needed for advice

### 2. ✅ Fixed: Missing Chip Information
**Problem:** No way to track or use FPL chips (Wildcard, Free Hit, Bench Boost, Triple Captain) in transfer recommendations.

**Solution:**
- Added `available_chips` parameter to `suggest_transfers` tool
- Tool now asks user to provide chip status if giving transfer advice
- Chip strategy recommendations included in output

### 3. ✅ Improved: Structured Output Format
**Problem:** Perplexity (and other LLMs) were adding extensive commentary around raw MCP data.

**Solution:**
- Updated all tool descriptions to specify "Returns STRUCTURED DATA ONLY - no commentary"
- Simplified output format with clear delimiters (pipes |)
- Removed emoji overuse in data sections
- Kept essential structure indicators only

---

## 🚀 Phase 2: New Tools Added

### Tool 6: `optimize_squad` ✅
**Status:** Initial implementation (Greedy algorithm)

**What it does:**
- Builds optimal 15-player squad within budget
- Respects all FPL constraints (2 GK, 5 DEF, 5 MID, 3 FWD, max 3 per team)
- Optimizes for: points, form, value, or fixtures
- Shows total cost and remaining budget

**Current Limitations:**
- Uses greedy algorithm (not true optimal)
- Full version will use Linear Programming (PuLP)

**Example Usage:**
```
"Build me the best FPL team optimized for form"
"Create an optimal squad with £98m budget"
```

### Tool 7: `suggest_transfers` ✅
**Status:** Initial implementation

**What it does:**
- Analyzes your current squad for weak spots
- Identifies players to transfer out (low form, injuries, price drops)
- Suggests replacements in same position
- Calculates hit cost (-4 points per extra transfer)
- Provides chip strategy recommendations

**Requires User Input:**
- Number of free transfers (0-5)
- Available chips (optional)

**Example Usage:**
```
"Suggest transfers for team 123456, I have 2 free transfers and wildcard available"
"Analyze my team for transfers, I have 1 free transfer, no chips"
```

**Transfer Priority Scoring:**
- 🔴 HIGH (50+ points): Injury risk, very low form
- 🟡 MEDIUM (30-50 points): Low form, price falling
- ✅ GOOD: No urgent transfers needed

---

## 📊 Updated Tool Descriptions

### Phase 1 Tools (All Fixed)

1. **get_all_players**
   - Now returns structured data with pipe delimiters
   - Clear column headers
   - No extra commentary

2. **get_player_details**
   - Structured sections: SEASON STATS, LAST 5 GAMEWEEKS, NEXT 5 FIXTURES
   - Clean data format
   - Essential info only

3. **get_fixtures**
   - Grouped by gameweek
   - FDR ratings clearly shown
   - No verbose descriptions

4. **get_my_team** ⚠️ IMPORTANT CHANGES
   - Shows "Transfers Made This GW" instead of misleading "Free Transfers"
   - Clear warning about API limitation
   - Prompts user for free transfer count when needed

5. **get_top_performers**
   - Structured ranking with chosen metric highlighted
   - Pipe-delimited data
   - Concise format

### Phase 2 Tools (New)

6. **optimize_squad** (NEW)
   - Greedy optimization (Phase 2a)
   - Returns full 15-player squad
   - Budget tracking
   - Note: Linear Programming version coming in Phase 2b

7. **suggest_transfers** (NEW)
   - Transfer analysis with priority scoring
   - Replacement suggestions
   - Hit cost calculator
   - Chip strategy advice
   - **REQUIRES user input for free transfers and chips**

---

## 🎯 How to Use New Features

### Scenario 1: Build a New Team
```
User: "Build me the best FPL team optimized for form with a £100m budget"

Server: Calls optimize_squad(budget=100.0, optimize_for="form")

Output:
OPTIMIZED FPL SQUAD
Strategy: FORM
Budget Used: £99.5m / £100.0m
Remaining: £0.5m

SQUAD (15 players):

GK (2):
  Ramsdale | ARS | £4.5m | 45pts | Form: 4.2
  Areola | WHU | £4.0m | 38pts | Form: 3.8

DEF (5):
  Saliba | ARS | £6.0m | 78pts | Form: 5.8
  ...
```

### Scenario 2: Get Transfer Advice
```
User: "Suggest transfers for my team (ID: 123456). I have 2 free transfers and a wildcard available."

Server: Calls suggest_transfers(team_id=123456, free_transfers=2, available_chips=["wildcard"])

Output:
TRANSFER RECOMMENDATIONS
Team: My FPL Team
Free Transfers: 2
Bank: £0.5m
Available Chips: wildcard

📊 ANALYSIS:

Found 3 players to consider transferring out:

TRANSFER 1:
OUT: Rashford (MUN) - £8.5m
Reasons: Low form (1.8), Price falling
Priority: 🟡 MEDIUM

🔄 Top 3 Replacements (MID):
  1. Palmer (CHE) - £11.0m - Form: 6.2
  2. Foden (MCI) - £9.0m - Form: 5.8
  3. Maddison (TOT) - £7.5m - Form: 5.2

...

💰 COST ANALYSIS:
Transfers recommended: 2
Free transfers used: 2
✅ No hits required!

🎴 CHIP STRATEGY:
💡 Consider WILDCARD if making 4+ changes
```

### Scenario 3: Missing Free Transfer Info
```
User: "What transfers should I make?"

LLM: "I need some information to help you:
1. What's your FPL team ID? (Find it in your URL: fantasy.premierleague.com/entry/YOUR_ID/)
2. How many free transfers do you have? (0-5)
3. Do you have any chips available? (Wildcard, Free Hit, Bench Boost, Triple Captain)"

User provides: "Team ID 123456, 1 free transfer, no chips"

Server: Proceeds with analysis
```

---

## 🔄 Migration Guide

### If Updating from Phase 1:

1. **Replace Server.py** with new version
2. **Test the fixes:**
   ```bash
   cd fpl-optimizer
   python Server.py
   ```

3. **Verify new tools work:**
   - Try: "Build me an optimal FPL team"
   - Try: "Suggest transfers for team [YOUR_ID], 2 free transfers"

4. **Restart your MCP client** (Claude Desktop, etc.)

### Breaking Changes:
- ❌ None! All Phase 1 tools work the same way
- ✅ Only additions and fixes

---

## 🚧 Phase 2b - Coming Next

### Full Linear Programming Optimization
Currently `optimize_squad` uses a greedy algorithm. Phase 2b will add:

**Technologies:**
- **PuLP** - Linear programming library
- **scipy** - Optimization algorithms

**Improvements:**
- True mathematically optimal squad
- Consider fixture difficulty in optimization
- Multi-gameweek planning
- Transfer optimization (who to swap)

**New Tools:**
- `optimize_lineup` - Best starting 11 from your squad
- `suggest_captain` - Captain recommendation with expected points
- `evaluate_transfer` - Analyze specific transfer (A for B)
- ML-based points prediction

### Expected Points Model
- Train ML model on historical data
- Predict next gameweek points for each player
- Features: form, fixtures, opponent strength, home/away
- Use predictions in optimization

---

## 📝 Testing Checklist

Before using in production:

### Phase 1 Tests (All should pass)
- [ ] `get_all_players` returns structured data
- [ ] `get_player_details` shows correct player info
- [ ] `get_fixtures` displays FDR correctly
- [ ] `get_my_team` shows "Transfers Made" not "Free Transfers"
- [ ] Warning about API limitation is displayed
- [ ] `get_top_performers` ranks correctly

### Phase 2 Tests (New)
- [ ] `optimize_squad` returns 15 players
- [ ] Squad respects all constraints (2/5/5/3, max 3 per team)
- [ ] Budget calculation is correct
- [ ] `suggest_transfers` identifies weak players
- [ ] Replacement suggestions are in correct position
- [ ] Hit cost is calculated correctly
- [ ] Chip recommendations appear when chips available

---

## 🐛 Known Issues

### Current Limitations:

1. **optimize_squad** uses greedy algorithm
   - May not find true optimal solution
   - Fast but not perfect
   - Phase 2b will fix with Linear Programming

2. **suggest_transfers** needs user input
   - Cannot auto-detect free transfers from API
   - Cannot auto-detect chips from API
   - User must provide this info

3. **Fixture difficulty** in optimization is simplified
   - Currently uses player form only
   - Phase 2b will fetch and analyze actual fixtures

### Not Issues (Expected Behavior):

- ✅ LLM adds commentary around data - this is normal LLM behavior
- ✅ Output format is structured - LLM interprets for user
- ✅ User must provide free transfers - API limitation, not bug

---

## 💡 Tips for Best Results

### For Users:
1. **Know your team ID** - Keep it handy
2. **Track your free transfers** - API can't see this
3. **Note your chips** - Keep track of what you've used

### For LLM Integration:
1. **Let LLM add context** - Raw data is meant to be interpreted
2. **Trust structured format** - Pipe delimiters help LLM parse
3. **User prompts are okay** - LLM should ask for missing info

### For Development:
1. **Test with real team ID** - Use your actual FPL team
2. **Verify constraints** - Check squad totals (2/5/5/3)
3. **Monitor API calls** - FPL API is free but be respectful

---

## 📞 Support

**Questions about bugs?** Open an issue with:
- Tool name
- Input parameters
- Expected vs actual output

**Phase 2b requests?** Let us know which feature you want first:
- True optimal squad (Linear Programming)
- Captain recommendations
- Expected points prediction
- Transfer evaluation

---

**Version:** 0.2.0  
**Date:** December 2024  
**Status:** Phase 2a Complete ✅