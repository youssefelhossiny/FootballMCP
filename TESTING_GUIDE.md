# Testing Your FPL MCP Server with xG/xA Features

## 🎯 Quick Start

Your MCP server now includes **enhanced predictions with Understat xG/xA data**!

### Match Rate: **57.5%** (434/755 players)
- Active players (90+ min): ~100% matched
- Premium attackers: ~90% matched with xG/xA stats

---

## 🚀 How to Test the MCP Server

### Step 1: Start the MCP Server

```bash
cd /Users/youssefelhossiny/Documents/GitHub/Football-MCP
python3 fpl-optimizer/Server.py
```

The server will:
- ✅ Load the ML model with 27 features (17 FPL + 8 Understat + 2 derived)
- ✅ Load 166 manual player name mappings
- ✅ Cache Understat data (6-hour TTL)
- ✅ Expose 12 FPL optimization tools

### Step 2: Connect Your MCP Client

In Claude Desktop, the server should auto-connect via your MCP settings.

**MCP Settings Location:**
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

**Expected Config:**
```json
{
  "mcpServers": {
    "fpl-optimizer": {
      "command": "python3",
      "args": [
        "/Users/youssefelhossiny/Documents/GitHub/Football-MCP/fpl-optimizer/Server.py"
      ]
    }
  }
}
```

---

## 🧪 Test Cases to Try

### Test 1: Check Enhanced Player Predictions
**What it tests:** ML predictions using xG/xA features

**Try asking Claude:**
```
"Show me the top 10 forwards with the highest predicted points for next gameweek"
```

**What to look for:**
- Players should show predicted points
- Premium attackers (Haaland, Salah, etc.) should have xG/xA data
- Predictions should consider form + xG + fixtures

---

### Test 2: Build Optimal Squad with xG/xA
**What it tests:** Squad optimization using enhanced features

**Try asking Claude:**
```
"Build me an optimal FPL squad for the next 5 gameweeks using maximum budget"
```

**What to look for:**
- 15 players (2 GK, 5 DEF, 5 MID, 3 FWD)
- Budget: £99.5-100m
- Starting 11 identified
- Premium players with high xG (Haaland, Salah, Palmer, Isak)
- Fixture analysis included

---

### Test 3: Transfer Suggestions with Advanced Stats
**What it tests:** Transfer recommendations using xG/xA insights

**Try asking Claude:**
```
"I have 2 free transfers. Suggest transfers for players underperforming their xG"
```

**What to look for:**
- Identifies players with negative xG_overperformance (unlucky)
- Suggests transfers based on xG_per_90 and upcoming fixtures
- Considers budget constraints

---

### Test 4: Check Specific Player xG/xA Stats
**What it tests:** Player details with Understat data

**Try asking Claude:**
```
"Show me detailed stats for Erling Haaland including his xG and xA"
```

**What to look for:**
- Basic FPL stats (points, form, price)
- **Enhanced stats:** xG, xA, xG_per_90, xA_per_90
- **Advanced metrics:** xG_overperformance, shots, key_passes
- Fixture difficulty for next 3-5 gameweeks

---

### Test 5: Fixture Analysis with xG Context
**What it tests:** Fixture difficulty + player xG analysis

**Try asking Claude:**
```
"Which teams have the best fixtures in the next 5 gameweeks, and which high-xG players should I target from those teams?"
```

**What to look for:**
- Teams with average FDR < 3.0
- Players from those teams with xG_per_90 > 0.5
- Transfer targets combining fixtures + xG

---

### Test 6: Value Picks Based on xG
**What it tests:** Finding undervalued players using xG

**Try asking Claude:**
```
"Find me midfielders under £7m with high xG per 90 minutes"
```

**What to look for:**
- Price filtering working
- xG_per_90 sorting
- Value picks (high xG, low ownership, good price)

---

### Test 7: Chips Strategy with Enhanced Data
**What it tests:** Wildcard/Bench Boost timing using xG insights

**Try asking Claude:**
```
"When should I use my Wildcard? Show me the best gameweeks based on fixture difficulty and high-xG player availability"
```

**What to look for:**
- Gameweek recommendations (3-5 GW window)
- Fixture analysis for multiple teams
- Players with high xG and good fixtures

---

## 📊 Available Tools (12 Total)

### Core Tools (Phase 1)
1. **get_all_players** - All players with stats, prices, points
2. **get_player_details** - Detailed stats including xG/xA
3. **get_fixtures** - Fixtures with difficulty ratings
4. **get_my_team** - Your FPL team
5. **get_top_performers** - Top players by metric

### Optimization Tools (Phase 2)
6. **optimize_squad_lp** - Linear programming optimizer (basic)
7. **optimize_squad** - Enhanced optimizer with fixtures
8. **suggest_transfers** - Transfer recommendations
9. **optimize_starting_11** - Best starting lineup
10. **analyze_fixtures_multi** - Multi-gameweek fixture analysis
11. **recommend_captain** - Captain picks with xG insights
12. **recommend_chips_strategy** - Wildcard/Bench Boost timing

---

## 🔍 What's Different with xG/xA?

### Before (Basic FPL Stats Only):
```
Player: Mohamed Salah
Price: £13.0m
Form: 7.2
Total Points: 84
```

### After (With Understat xG/xA):
```
Player: Mohamed Salah
Price: £13.0m
Form: 7.2
Total Points: 84
xG: 8.45 (Expected Goals)
xA: 3.21 (Expected Assists)
xG_per_90: 0.89 (Elite level)
xG_overperformance: +2.55 (Overperforming - 11 goals vs 8.45 xG)
Shots: 42
Key Passes: 28
```

### ML Model Features (27 Total):
**FPL Features (17):**
- form, total_points, points_per_game, minutes, goals_scored, assists
- clean_sheets, goals_conceded, bonus, bps, influence, creativity
- threat, ict_index, now_cost, selected_by_percent, element_type, team

**Understat Features (8):**
- xG, xA, xG_per_90, xA_per_90
- shots, shots_on_target, key_passes, xG_overperformance

**Derived Features (2):**
- xG_xA_combined (total expected output)
- finishing_quality (goals vs xG ratio)

---

## ✅ Expected Behavior

### Predictions Should:
- Use xG_per_90 as 2nd most important feature (after form)
- Identify value picks (high xG, low price)
- Spot overperformers (positive xG_overperformance)
- Spot underperformers (negative xG_overperformance - due for goals)

### Optimizations Should:
- Prioritize high xG attackers
- Consider fixture difficulty + xG together
- Build balanced squads with xG coverage across positions

---

## 🐛 Troubleshooting

### Model Not Loading?
```bash
cd fpl-optimizer
python3 predict_points.py  # Train the model first
```

### Understat Data Not Fresh?
- Cache TTL: 6 hours
- Delete cache: `rm -rf fpl-optimizer/cache/`
- Data will re-fetch automatically

### Player Names Not Matching?
- 57.5% match rate is normal
- Unmatched players get position-based defaults (DEF: xG=0.1, MID: xG=0.2, FWD: xG=0.3)
- Active players (90+ min) should be ~100% matched

---

## 📈 Success Metrics

**Good Test Results:**
- ✅ Model loads successfully
- ✅ Predictions include xG/xA data for premium players
- ✅ Haaland/Salah show xG_per_90 > 0.8
- ✅ Squad optimization suggests high-xG attackers
- ✅ Transfer suggestions consider xG underperformance
- ✅ Captain recommendations prioritize fixtures + xG

---

## 🎯 Next Steps

After testing, you can:

1. **Add more manual mappings** - Get to 60%+ match rate
2. **Tune the model** - Adjust feature weights
3. **Add more features** - Minutes per game, recent form trends
4. **Build a dashboard** - Visualize xG vs actual goals
5. **Add live gameweek updates** - Fetch live scores during matches

---

**Ready to test!** 🚀

Ask Claude to use any of the 12 FPL tools and see your enhanced predictions in action.
