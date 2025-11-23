# FPL Optimizer - Current Capabilities

## 🎯 Overview
Complete FPL (Fantasy Premier League) optimization system with 12 tools for squad building, transfer analysis, fixture analysis, and chips strategy.

## ✅ What It Can Do NOW

### 1. **Build Optimal Squad from Scratch** 🏆
**Tool:** `optimize_squad_lp`

**Capabilities:**
- ✅ Generates mathematically optimal 15-player squad
- ✅ Uses **maximum budget** (£100m target, £99m minimum)
- ✅ Analyzes next **3-5 gameweeks** for fixture difficulty
- ✅ Identifies **starting 11** vs **bench players**
- ✅ **Smart bench strategy** - cheap enablers (£4.0-5.0m)
- ✅ **Budget maximization** - uses £99.5-100m
- ✅ Multiple optimization strategies: form, points, value, fixtures

**Example Usage:**
```
"Build me an optimal FPL squad"
"Create a squad optimized for the next 5 gameweeks"
"Build best team using maximum budget"
```

**Returns:**
- 15 players (2 GK, 5 DEF, 5 MID, 3 FWD)
- Starting 11 with formation (e.g., 4-5-1)
- Bench breakdown with costs
- Total cost (£99.5-100m)
- Expected points over next 5 gameweeks

---

### 2. **Fixture Analysis** 📅
**Tool:** `analyze_fixtures`

**Capabilities:**
- ✅ Analyzes upcoming fixtures (3-10 gameweeks)
- ✅ Calculates Fixture Difficulty Rating (FDR) per team
- ✅ Identifies teams with easy/hard runs
- ✅ Detects double gameweeks
- ✅ Team filtering available

**Example Usage:**
```
"Which teams have the easiest fixtures for the next 5 gameweeks?"
"Show me fixture difficulty for next 3 weeks"
"Analyze Arsenal's upcoming fixtures"
```

**Returns:**
- Top 5 easiest fixtures (teams to target)
- Bottom 5 hardest fixtures (teams to avoid)
- FDR ratings (1-5 scale with stars ⭐)
- Number of fixtures per team
- Double gameweek indicators

---

### 3. **Chips Strategy Recommendations** 🎴
**Tool:** `suggest_chips_strategy`

**Capabilities:**
- ✅ Analyzes when to use each chip type
- ✅ **Wildcard** timing (unlimited transfers)
- ✅ **Bench Boost** recommendations (bench scores)
- ✅ **Triple Captain** best gameweeks (3x points)
- ✅ **Free Hit** strategy (one-week team)
- ✅ Identifies double/blank gameweeks
- ✅ Priority ratings (VERY HIGH → LOW)

**Example Usage:**
```
"I have Wildcard and Bench Boost. When should I use them?"
"When is the best time to use Triple Captain?"
"Analyze my chips: Wildcard, Free Hit, Triple Captain"
```

**Returns:**
- Specific gameweek recommendations for each chip
- Priority level for each timing option
- Reasoning and expected benefit
- Multiple options ranked by priority

---

### 4. **Transfer Evaluation** 🔄
**Tool:** `evaluate_transfer`

**Capabilities:**
- ✅ Analyzes specific transfer (Player Out → Player In)
- ✅ ML-predicted points comparison
- ✅ Cost analysis (price difference)
- ✅ Hit cost calculation (-4 points if no free transfer)
- ✅ Expected points gain/loss
- ✅ Recommendation (DO IT / CONSIDER / WAIT)

**Example Usage:**
```
"Should I transfer out Haaland for Salah? I have 1 free transfer"
"Evaluate transfer: Player ID 123 out, Player ID 456 in"
```

**Returns:**
- OUT player: name, team, price, predicted points
- IN player: name, team, price, predicted points
- Price difference
- Hit cost (0 or -4 points)
- Expected gain/loss
- Color-coded recommendation

---

### 5. **Optimize Lineup (Starting 11)** 📐
**Tool:** `optimize_lineup`

**Capabilities:**
- ✅ Selects best starting 11 from your 15-player squad
- ✅ ML predictions for each player
- ✅ Formation optimization (3-4-3, 4-3-3, 4-4-2, 4-5-1, etc.)
- ✅ Captain & vice-captain recommendations
- ✅ Expected points calculation
- ✅ Bench order

**Example Usage:**
```
"Optimize my starting 11 for gameweek 13. My team ID is 8097506"
"Best lineup for this week, team 8097506"
```

**Returns:**
- Starting 11 players
- Formation
- Captain recommendation
- Vice-captain
- Expected total points
- Bench players

---

### 6. **Captain Recommendations** ⚡
**Tool:** `suggest_captain`

**Capabilities:**
- ✅ ML-based captain predictions
- ✅ Top 3 options ranked
- ✅ 2x points multiplier calculation
- ✅ Fixture-aware recommendations
- ✅ Form + fixtures considered

**Example Usage:**
```
"Who should I captain this week? Team ID 8097506"
"Best captain for gameweek 13, team 8097506"
```

**Returns:**
- Top 3 captain options
- Base predicted points
- Captain points (2x)
- Player team and fixtures

---

### 7. **Transfer Suggestions** 💡
**Tool:** `suggest_transfers`

**Capabilities:**
- ✅ Analyzes current squad weaknesses
- ✅ Suggests optimal transfers
- ✅ Considers free transfers available
- ✅ Factors in chips strategy
- ✅ Multi-gameweek planning
- ✅ Hit cost analysis

**Example Usage:**
```
"Suggest transfers for my team 8097506. I have 2 free transfers"
"Transfer recommendations, team 8097506, 1 FT, Wildcard available"
```

**Returns:**
- Priority transfers (most important first)
- Suggested replacements
- Expected points gain
- Whether to save or use transfers

---

### 8. **Get Player Stats** 👤
**Tool:** `get_player_details`

**Capabilities:**
- ✅ Detailed player statistics
- ✅ Recent performance
- ✅ Upcoming fixtures
- ✅ Form, points, price

**Example Usage:**
```
"Show me details for Erling Haaland"
"Stats for player ID 234"
```

---

### 9. **Filter All Players** 🔍
**Tool:** `get_all_players`

**Capabilities:**
- ✅ Filter by position (GK, DEF, MID, FWD)
- ✅ Filter by team
- ✅ Filter by price range
- ✅ Sort by points, form, value, price
- ✅ Top N results

**Example Usage:**
```
"Show me midfielders under £8m sorted by form"
"List Arsenal players"
"Best value defenders"
```

---

### 10. **Get Your Team** 📊
**Tool:** `get_my_team`

**Capabilities:**
- ✅ Shows current FPL team
- ✅ All 15 players
- ✅ Squad value
- ✅ Bank balance
- ✅ Overall rank
- ✅ Free transfers
- ✅ Available chips

**Example Usage:**
```
"Get my team, ID 8097506"
"Show my current FPL squad"
```

---

### 11. **Upcoming Fixtures** 📅
**Tool:** `get_fixtures`

**Capabilities:**
- ✅ Shows upcoming matches
- ✅ Fixture difficulty ratings
- ✅ Filter by days ahead
- ✅ Team-specific fixtures

**Example Usage:**
```
"Show fixtures for next 7 days"
"Liverpool's upcoming matches"
```

---

### 12. **Top Performers** 🌟
**Tool:** `get_top_performers`

**Capabilities:**
- ✅ Rank by: points, form, value, ownership, transfers, bonus
- ✅ Filter by position
- ✅ Top N players
- ✅ Current season stats

**Example Usage:**
```
"Top 10 players by points"
"Best value midfielders"
"Most transferred in players"
```

---

## 🎮 Key Features

### Multi-Gameweek Analysis
- All optimization considers **next 3-5 gameweeks** (configurable)
- Not just next week - strategic long-term planning
- Fixture difficulty weighted into decisions

### Maximum Budget Usage
- **Target:** £100m (use all available money)
- **Minimum:** £99m (only go lower if significantly better player)
- Smart allocation: premium starters + cheap bench

### Machine Learning Predictions
- **Model:** Random Forest with 200 estimators
- **Features:** 17 player stats (form, points, minutes, goals, assists, etc.)
- **Training:** Real FPL historical data
- **Accuracy:** ~2-3 points MAE (mean absolute error)

### Linear Programming Optimization
- Mathematically guaranteed optimal solution
- Handles all FPL constraints:
  - 2 GK, 5 DEF, 5 MID, 3 FWD
  - Max 3 players per team
  - Budget limits
  - Valid formations

### Smart Bench Strategy
- Identifies players who won't play much
- Allocates minimum budget to bench (£20-35m)
- Maximizes budget for starting 11 premium players
- Bench: 1 GK (£4.0-4.5m) + 3 outfield (£4.0-5.0m when possible)

---

## 📊 System Stats

- **Tools:** 12 total (6 Phase 1 + 6 Phase 2b)
- **Players analyzed:** 750+
- **Fixtures tracked:** 380+
- **Teams:** 20 Premier League teams
- **Optimization time:** 2-3 seconds
- **ML model size:** 2.4 MB
- **Training samples:** 163k+ player-gameweek combinations

---

## 🔧 Technical Details

### Architecture
```
User (Natural Language)
    ↓
Perplexity/LLM Client
    ↓
MCP Protocol
    ↓
FPL Optimizer Server (Python)
    ├── Phase 1 Tools (Basic data)
    ├── Phase 2b Tools (Advanced optimization)
    ├── Enhanced Optimizer (Fixture-aware LP)
    ├── ML Predictor (Random Forest)
    ├── Fixture Analyzer (FDR calculation)
    └── Chips Analyzer (Strategy recommendations)
    ↓
FPL API (Official Fantasy Premier League)
```

### Data Sources
- **Player stats:** Official FPL API
- **Fixtures:** Official FPL API
- **Historical data:** FPL API archives
- **Predictions:** ML model trained on FPL data

### Performance
- **Optimization:** O(n) with LP solver (CBC)
- **Predictions:** O(n) for n players
- **Fixture analysis:** O(f) for f fixtures
- **Total latency:** 2-5 seconds for full optimization

---

## 💬 Example Conversations

### Building a Squad
```
User: "Build me an optimal FPL squad for the next 5 gameweeks"