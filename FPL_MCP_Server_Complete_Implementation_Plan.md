# Fantasy Premier League MCP Server - Complete Plan

## 📋 FPL Rules Summary (2024/25 Season)

### Team Structure
- **15 players total**: 2 GK, 5 DEF, 5 MID, 3 FWD
- **£100m budget**
- **Max 3 players per club**
- **Starting 11**: Pick formation (3-4-3, 4-4-2, 4-3-3, etc.)
- **Captain**: Gets 2x points
- **Vice-Captain**: Gets 2x points if captain doesn't play

### Transfers & Chips
- **1 free transfer per week** (can save up to 5)
- **-4 points** for each additional transfer
- **Chips Available:**
  - Wildcard (2x per season) - Unlimited transfers
  - Triple Captain - Captain gets 3x points
  - Bench Boost - All 15 players score
  - Free Hit - One-week team reset
  - Mystery Chip (from Jan 2025)

### Point Scoring System

| Action | GK | DEF | MID | FWD |
|--------|----|----|-----|-----|
| **Playing 0-59 min** | 1 | 1 | 1 | 1 |
| **Playing 60+ min** | 2 | 2 | 2 | 2 |
| **Goal** | 10 | 6 | 5 | 4 |
| **Assist** | 3 | 3 | 3 | 3 |
| **Clean Sheet (60+ min)** | 4 | 4 | 1 | 0 |
| **Every 3 saves (GK only)** | 1 | - | - | - |
| **Penalty save** | 5 | - | - | - |
| **Every 2 goals conceded** | -1 | -1 | 0 | 0 |
| **Yellow card** | -1 | -1 | -1 | -1 |
| **Red card** | -3 | -3 | -3 | -3 |
| **Own goal** | -2 | -2 | -2 | -2 |
| **Penalty miss** | -2 | -2 | -2 | -2 |
| **Bonus (top 3 performers)** | 3/2/1 | 3/2/1 | 3/2/1 | 3/2/1 |

---

## 🎯 Your FPL Tool Requirements

### Core Features
1. **Optimal Team Selection** - Best 15 players within £100m budget
2. **Weekly Lineup Optimizer** - Best starting 11 from your squad
3. **Transfer Recommendations** - Who to transfer in/out
4. **Captain Picks** - Who to captain each week
5. **Fixture Analysis** - Upcoming difficulty
6. **Live Price Tracking** - Current player prices
7. **Points Projections** - Expected points next GW

---

## 🏗️ Architecture: Two MCP Servers

### **Option 1: Separate Servers (RECOMMENDED)** ⭐

**Server 1: Soccer Stats (Already Built)**
- Match predictions
- Team form analysis
- Head-to-head
- Live scores

**Server 2: FPL Optimizer (New)**
- Player data & prices
- Team optimization
- Transfer suggestions
- Points projections

**Why separate?**
- ✅ Clean separation of concerns
- ✅ Easier to maintain
- ✅ Can use both together or independently
- ✅ Different data sources (Football-Data.org vs FPL API)

**LLM connects to BOTH servers** and can use tools from either

### Option 2: Single Combined Server

Merge everything into one server

**Pros:** Simpler setup  
**Cons:** More complex code, harder to maintain

---

## 📊 Data Sources & APIs

### 1. **Official FPL API** (FREE, UNLIMITED) ⭐ PRIMARY

**Base URL:** `https://fantasy.premierleague.com/api/`

**Key Endpoints:**

```python
# All player data with prices, stats, points
GET /bootstrap-static/

# Detailed player info (fixtures, history)
GET /element-summary/{player_id}/

# Live gameweek data
GET /event/{gameweek_id}/live/

# Fixtures with difficulty ratings
GET /fixtures/

# Your team data (requires auth)
GET /entry/{team_id}/event/{gameweek_id}/picks/
```

**What You Get:**
- ✅ Live player prices
- ✅ Current points & form
- ✅ Fixture difficulty ratings (FDR)
- ✅ Ownership percentages
- ✅ Expected points (minutes, xG, xA)
- ✅ Injury/suspension status
- ✅ Bonus points

**Rate Limits:** None! Completely free and unlimited

### 2. **FBRef.com** (Advanced Stats)

**Use for:**
- xG (expected goals)
- xA (expected assists)
- Shots on target
- Key passes
- Defensive actions

**Access:** Web scraping (they don't have an official API)

### 3. **Understat.com** (xG Data)

**Use for:**
- Player xG and xA
- Team xG for/against
- Shot data

**Access:** Web scraping

---

## 🛠️ FPL MCP Server - Implementation Plan

### Phase 1: Data Collection Tools (Week 1)

**Tools to build:**

1. **`get_all_players`**
   - Returns all 600+ Premier League players
   - Includes: name, team, position, price, points, form
   - Filters: position, team, price range

2. **`get_player_details`**
   - Detailed stats for one player
   - Past gameweek scores
   - Upcoming fixtures with difficulty
   - Price changes
   - Ownership %

3. **`get_fixtures`**
   - Upcoming fixtures with FDR (Fixture Difficulty Rating)
   - Filter by team, gameweek range
   - Includes: home/away, blank/double gameweeks

4. **`get_my_team`**
   - User's current FPL team
   - Requires: team ID (from FPL website)
   - Shows: squad, budget, transfers available

5. **`get_top_performers`**
   - Top players by: points, form, value (points per £)
   - Filter by: position, price range

### Phase 2: Optimization Algorithms (Week 2)

6. **`optimize_squad`**
   - Uses **Linear Programming** (PuLP library)
   - Inputs: Budget, constraints
   - Outputs: Best 15 players maximizing expected points
   - Considers: form, fixtures, price

7. **`optimize_lineup`**
   - Best starting 11 from your 15 players
   - Inputs: Your squad, gameweek
   - Considers: fixtures, form, injuries
   - Suggests formation

8. **`suggest_captain`**
   - Best captain choice for the week
   - Factors: opponent difficulty, form, home/away

### Phase 3: Transfer Recommendations (Week 2)

9. **`suggest_transfers`**
   - Who to transfer in/out
   - Inputs: Current team, budget, # of free transfers
   - Considers: upcoming fixtures, form, price changes
   - Outputs: Priority transfers with reasoning

10. **`evaluate_transfer`**
    - Analyze a specific transfer you're considering
    - Shows: Points projection, fixture difficulty, value

### Phase 4: Advanced Analytics (Week 3)

11. **`predict_points`**
    - ML model to predict player points for next GW
    - Features: form, opponent, home/away, minutes, xG, xA
    - Uses: Random Forest Regressor

12. **`fixture_analysis`**
    - Deep dive into upcoming fixtures
    - Shows: difficulty trends, blank/double gameweeks
    - Suggests: When to use chips

13. **`differential_finder`**
    - Find low-ownership high-potential players
    - Great for climbing ranks

---

## 🧮 Optimization Algorithm Details

### Squad Optimization (Linear Programming)

**Objective Function:**  
Maximize: Σ (expected_points[i] × selected[i])

**Constraints:**
```python
1. Sum of prices ≤ £100m
2. Exactly 15 players
3. 2 GK, 5 DEF, 5 MID, 3 FWD
4. Max 3 players per club
5. selected[i] ∈ {0, 1}  # Binary decision variable
```

**Expected Points Calculation:**
```python
expected_points = (
    recent_form * 0.3 +
    fixture_difficulty_adjusted * 0.25 +
    xG_xA_prediction * 0.25 +
    minutes_likelihood * 0.2
)
```

### Transfer Optimization

**Priority Score:**
```python
transfer_priority = (
    points_gained +
    fixture_swing +
    price_change_risk -
    transfer_cost
)
```

**Decision Tree:**
1. Is player injured/suspended? → Transfer out (high priority)
2. Has player lost starting place? → Transfer out
3. Does replacement have better fixtures? → Consider
4. Is price about to drop? → Urgent transfer
5. Worth taking -4 hit? → Only if expected gain > 4pts

---

## 📦 Technology Stack

### Core Libraries
```python
# FPL Data
httpx              # API requests
pandas             # Data manipulation
numpy              # Calculations

# Optimization
pulp               # Linear programming
scipy              # Optimization algorithms

# ML Predictions
scikit-learn       # Random Forest models
xgboost            # Gradient boosting (optional)

# MCP
mcp                # MCP server framework

# Web Scraping (for FBRef/Understat)
beautifulsoup4     # HTML parsing
selenium           # Dynamic content
```

---

## 🚀 Quick Start Implementation

### Step 1: Set Up FPL MCP Server

```bash
# Create new directory
mkdir FPL-MCP
cd FPL-MCP

# Install dependencies
pip install mcp httpx pandas numpy pulp scikit-learn
```

### Step 2: Test FPL API Access

```python
import httpx

# Get all players
response = httpx.get("https://fantasy.premierleague.com/api/bootstrap-static/")
data = response.json()

# Extract players
players = data['elements']
print(f"Total players: {len(players)}")

# Show top 5 by points
sorted_players = sorted(players, key=lambda x: x['total_points'], reverse=True)
for p in sorted_players[:5]:
    print(f"{p['web_name']} - {p['total_points']} pts - £{p['now_cost']/10}m")
```

### Step 3: Build Basic Tools

Start with `get_all_players` and `get_player_details`

### Step 4: Add Optimization

Implement `optimize_squad` using PuLP

### Step 5: Connect to LLM

Configure Perplexity to use BOTH servers:
- Soccer Stats MCP (already have)
- FPL Optimizer MCP (new)

---

## 🎯 LLM Integration Strategy

### Config for Multiple Servers

**Perplexity/Claude Desktop Config:**
```json
{
  "mcpServers": {
    "soccer-stats": {
      "command": "python",
      "args": ["/path/to/soccer-server.py"],
      "env": {"FOOTBALL_DATA_API_KEY": "..."}
    },
    "fpl-optimizer": {
      "command": "python",
      "args": ["/path/to/fpl-server.py"]
    }
  }
}
```

**LLM can now use tools from BOTH servers!**

### Example Query Flow

**User:** "Give me the best FPL team for this gameweek"

**LLM thinks:**
1. Use `fpl-optimizer:get_fixtures` → Get upcoming fixtures
2. Use `soccer-stats:predict_match` → Get match predictions
3. Use `fpl-optimizer:get_all_players` → Get player data
4. Use `fpl-optimizer:optimize_squad` → Calculate best team
5. Respond with optimized 15-player squad

---

## 📊 Example Tool Responses

### `optimize_squad` Output

```
🏆 Optimal FPL Squad (£99.5m)

GOALKEEPERS (£9.0m):
  1. Alisson (£5.5m) - Liverpool
  2. Areola (£3.5m) - West Ham

DEFENDERS (£27.0m):
  3. Trent Alexander-Arnold (£7.0m) - Liverpool  ⭐ Captain Pick
  4. Gabriel (£6.0m) - Arsenal
  5. Saliba (£6.0m) - Arsenal
  6. Pedro Porro (£5.5m) - Tottenham
  7. Dalot (£4.5m) - Man United

MIDFIELDERS (£38.5m):
  8. Mohamed Salah (£13.0m) - Liverpool
  9. Cole Palmer (£10.5m) - Chelsea
  10. Bukayo Saka (£10.0m) - Arsenal
  11. Son Heung-Min (£9.5m) - Tottenham
  12. Bruno Fernandes (£8.5m) - Man United

FORWARDS (£25.0m):
  13. Erling Haaland (£15.0m) - Man City
  14. Alexander Isak (£8.5m) - Newcastle
  15. Mateta (£6.5m) - Crystal Palace

Total Value: £99.5m
Expected Points (Next 5 GWs): 387

💡 Key Picks:
  • Salah - Excellent fixtures, top form
  • Haaland - Essential captaincy option
  • Arsenal defense - 3 clean sheets in 5
```

### `suggest_transfers` Output

```
🔄 Transfer Recommendations (GW15)

Available: 2 free transfers | Bank: £0.5m

PRIORITY 1 (Do Now):
  OUT: Richarlison (£7.0m) - Injured, out 3+ weeks
  IN: Isak (£8.5m) - On fire, great fixtures

PRIORITY 2 (Consider):
  OUT: Trippier (£6.0m) - Rotation risk
  IN: Porro (£5.5m) - Nailed, attacking returns

Expected Points Gain: +8.5 pts over next 3 GWs
Worth the transfers: YES ✅

Alternative: Save transfer, roll over to next week
```

---

## 🎓 Machine Learning Model

### Features for Points Prediction

**Player Features:**
- Form (last 5 GW avg)
- Minutes per game
- xG per 90
- xA per 90
- Shots on target
- Key passes
- Clean sheet potential (defenders)

**Match Features:**
- Opponent FDR
- Home/away
- Team form
- Historical H2H

**Model:** Random Forest Regressor

**Target:** Points in next gameweek

**Accuracy Target:** MAE < 2.5 points

---

## 📅 Development Timeline

### Week 1: Foundation
- [ ] Set up FPL MCP server structure
- [ ] Implement data fetching tools (5 tools)
- [ ] Test API integration
- [ ] Connect to LLM

### Week 2: Optimization  
- [ ] Build squad optimizer (PuLP)
- [ ] Implement transfer suggestions
- [ ] Add captain recommendation
- [ ] Test with real scenarios

### Week 3: ML & Polish
- [ ] Train points prediction model
- [ ] Add fixture analysis
- [ ] Implement differential finder
- [ ] Write comprehensive tests

### Week 4: Integration
- [ ] Combine with Soccer Stats server
- [ ] Test multi-server LLM queries
- [ ] Create user guide
- [ ] Demo for hackathon!

---

## 🎯 Success Metrics

**Tool Performance:**
- Squad optimizer finds optimal team in <10 seconds
- Points predictions within 2.5 points MAE
- Transfer suggestions show positive ROI

**User Experience:**
- LLM understands complex FPL queries
- Clear, actionable recommendations
- Works with both MCP servers seamlessly

---

## 🚀 Getting Started (Next Steps)

1. **Test FPL API** - Run the test script I'll create
2. **Build basic tools** - Start with `get_all_players`
3. **Implement optimization** - PuLP for squad selection
4. **Train ML model** - Points prediction
5. **Deploy & test** - Connect to your LLM

**Want me to create the starter code for the FPL MCP server?** I can give you:
- Server structure
- Basic API integration
- First 3 tools working
- Optimization algorithm template

This will be an **amazing** hackathon project! 🏆