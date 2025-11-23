# FPL Optimizer - Phase 3 Roadmap

## 🎯 Current Status

**Phase 2b: COMPLETE ✅**
- 12 fully functional tools
- Enhanced optimization with fixture analysis
- ML-based predictions
- Chips strategy recommendations
- Multi-gameweek planning (3-5 GWs)
- Maximum budget usage (£100m target)

---

## 🚀 Phase 3: Planned Enhancements

### 1. **Enhanced Transfer Analysis** 📊
**Priority:** HIGH

**Current State:**
- `suggest_transfers` tool exists but needs multi-gameweek upgrade
- Currently analyzes single gameweek

**Planned Improvements:**
- Analyze transfers over next 3-5 gameweeks (not just next GW)
- Consider fixture swings (easy run ending, hard run starting)
- Factor in price changes and player trends
- Multi-transfer planning (use 2 FTs optimally)
- Transfer hits vs waiting analysis

**Implementation:**
```python
# Enhanced suggest_transfers
- Use FixtureAnalyzer for multi-GW fixture scoring
- Compare current player's 5-GW projection vs replacement
- Account for transfer timing (GW13 vs GW14 vs GW15)
- Suggest "transfer chains" (GW13: A→B, GW14: C→D)
```

**Expected Benefit:**
- Better long-term transfer decisions
- Avoid kneejerk reactions
- Plan ahead for fixture swings

---

### 2. **Fixture-Aware ML Model** 🤖
**Priority:** MEDIUM

**Current State:**
- ML model uses 17 player features (form, points, minutes, etc.)
- Fixture difficulty NOT included in training

**Planned Improvements:**
- Add fixture features to training data:
  - Opponent FDR (1-5)
  - Home/Away indicator
  - Opponent defensive strength
  - Opponent clean sheet probability
- Retrain model with fixture-aware features
- Improve prediction accuracy

**Implementation:**
```python
# New features for ML model
features = [
    # Existing 17 features...
    'opponent_fdr',           # NEW
    'is_home',                # NEW
    'opponent_goals_conceded', # NEW
    'opponent_clean_sheets'    # NEW
]
```

**Expected Benefit:**
- 10-15% improvement in prediction accuracy
- Better captain recommendations
- More accurate lineup optimization

---

### 3. **Rotation Risk Analysis** ⚠️
**Priority:** MEDIUM

**Current State:**
- Squad optimization picks best players by predicted points
- Doesn't account for rotation/rest risk

**Planned Improvements:**
- Detect high-rotation-risk players:
  - Playing midweek Champions League
  - Manager rotation patterns
  - Minutes played recently (fatigue)
  - Injury-prone status
- Add "rotation risk score" (0-1)
- Penalize high-risk players in optimization

**Implementation:**
```python
# Rotation risk factors
def calculate_rotation_risk(player):
    risk = 0.0

    # Champions League teams
    if team_in_europe(player['team']):
        risk += 0.2

    # Recent minutes > 270 (3 full games)
    if player['minutes'] > 270:
        risk += 0.15

    # Manager rotation tendency
    risk += get_manager_rotation_score(player['team'])

    return min(risk, 1.0)
```

**Expected Benefit:**
- Avoid players likely to be benched/subbed early
- More reliable starting 11
- Better bench planning

---

### 4. **Differential Finder** 🎯
**Priority:** LOW

**Current State:**
- Optimization focuses on pure points maximization
- Doesn't consider ownership %

**Planned Improvements:**
- Tool to find "differential" players:
  - Low ownership (< 10%)
  - High predicted points
  - Good fixtures
- Help managers gain rank with unique picks
- Risk/reward analysis

**Example Usage:**
```
"Find me differential players with <5% ownership and good fixtures"
"Show me captaincy differentials for GW13"
```

**Returns:**
- Top 10 differentials by position
- Ownership %
- Predicted points
- Potential rank gain if successful

---

### 5. **Wildcard Squad Builder** 🎴
**Priority:** MEDIUM

**Current State:**
- `optimize_squad_lp` builds squad from scratch
- Doesn't consider existing team value

**Planned Improvements:**
- Special wildcard mode:
  - Use current squad value (not £100m)
  - Account for player price changes
  - Show ITB (in the bank) after wildcard
- Multi-GW wildcard timing optimizer
- "Wildcard now vs GW later" comparison

**Implementation:**
```python
def optimize_wildcard_squad(
    current_team_id: str,
    team_value: float,  # e.g., £102.5m from price rises
    target_gw: int = None
):
    # Use team_value instead of £100m
    # Analyze fixtures from target_gw onwards
    # Return optimized wildcard squad
```

---

### 6. **Bench Boost Optimizer** 🚀
**Priority:** LOW

**Current State:**
- `suggest_chips_strategy` recommends when to use Bench Boost
- Doesn't optimize squad for Bench Boost

**Planned Improvements:**
- Tool to build "Bench Boost squad":
  - 15 playing players (no £4.0 fodder)
  - All 15 with good fixtures that GW
  - Maximize total 15-player points
- Free Hit + Bench Boost combo analysis

**Example Usage:**
```
"Build me a Bench Boost squad for GW29 (assuming I use Free Hit)"
"Optimize my squad for Bench Boost in next double gameweek"
```

---

### 7. **Price Change Predictor** 💰
**Priority:** LOW

**Current State:**
- No price change prediction
- Transfers don't account for price volatility

**Planned Improvements:**
- Predict which players will rise/fall tonight
- Use FPL API data:
  - `transfers_in_event`
  - `transfers_out_event`
  - `transfers_in_delta`
- Suggest "beat the price rise" transfers

**Implementation:**
```python
def predict_price_changes():
    # Use transfer deltas to predict rises/falls
    # Threshold: ~100k net transfers for rise
    # Return: {player_id: 'RISE'/'FALL'/'STABLE'}
```

---

### 8. **Live Gameweek Tracker** ⚡
**Priority:** LOW

**Current State:**
- No live gameweek data

**Planned Improvements:**
- Live points tracker during gameweek
- Shows current score vs overall average
- Captain pick performance
- Bench points (ouch factor)

**Example Usage:**
```
"How is my team doing this gameweek?"
"Show my live score and rank change"
```

---

## 🔧 Technical Improvements

### 1. **Caching & Performance**
- Cache FPL API responses (5-minute TTL)
- Reduce optimization time from 2-3s to <1s
- Pre-compute fixture difficulty matrix

### 2. **Error Handling**
- More descriptive error messages
- Graceful fallbacks when API is slow
- Retry logic for failed requests

### 3. **Testing Suite**
- Unit tests for each tool
- Integration tests for full workflows
- Mock FPL API for testing

### 4. **Logging**
- Structured logging (JSON format)
- Debug mode for troubleshooting
- Performance metrics

---

## 📊 Success Metrics

After Phase 3 implementation:

- **Prediction Accuracy:** <2 points MAE (currently ~2.5)
- **Optimization Speed:** <1 second (currently 2-3s)
- **Tool Coverage:** 18+ tools (currently 12)
- **User Satisfaction:** Handles 95% of FPL queries

---

## 🎯 Priority Order

1. **HIGH:** Enhanced Transfer Analysis (multi-GW)
2. **MEDIUM:** Fixture-Aware ML Model
3. **MEDIUM:** Rotation Risk Analysis
4. **MEDIUM:** Wildcard Squad Builder
5. **LOW:** Differential Finder
6. **LOW:** Bench Boost Optimizer
7. **LOW:** Price Change Predictor
8. **LOW:** Live Gameweek Tracker

---

## 🚧 Known Limitations (To Address)

1. **No cup/league analysis** - Only focuses on overall rank
2. **No player injury status** - Relies on FPL API availability
3. **No historical "what-if" analysis** - Can't simulate past decisions
4. **No team performance trends** - Doesn't track team form separately
5. **No set piece takers tracking** - Doesn't identify penalty/free kick takers

---

## 💡 Future Ideas (Beyond Phase 3)

- **Mini-leagues analyzer:** Compare your squad vs league rivals
- **Historical performance:** Track your decisions over season
- **Voice interface:** "Alexa, who should I captain?"
- **Discord/Slack bot:** Get recommendations in chat
- **Web dashboard:** Visual interface for all tools
- **Email alerts:** "Price rise alert! Salah rising tonight!"

---

## 🎮 Next Steps

To start Phase 3:

1. ✅ Finish Phase 2b documentation (DONE)
2. ⏭️ Implement enhanced transfer analysis
3. ⏭️ Retrain ML model with fixture features
4. ⏭️ Add rotation risk scoring
5. ⏭️ Create comprehensive test suite
6. ⏭️ Performance optimization (caching)

---

## 📅 Estimated Timeline

- **Phase 3 Core (items 1-3):** 2-3 weeks development
- **Phase 3 Complete (items 1-8):** 4-6 weeks development
- **Testing & Polish:** 1-2 weeks
- **Total:** 6-8 weeks for full Phase 3

---

## 🎯 End Goal

By end of Phase 3, the FPL Optimizer should be:

- **Comprehensive:** Covers 95% of FPL decision-making
- **Accurate:** ML predictions within 2 points MAE
- **Fast:** All queries answered in <2 seconds
- **Reliable:** Graceful error handling, 99.9% uptime
- **User-friendly:** Natural language → optimal decisions

**Vision:** The ultimate AI assistant for FPL managers, handling everything from squad building to live gameweek tracking, with expert-level strategic advice.
