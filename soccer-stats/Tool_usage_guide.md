# Soccer Stats MCP Server - Tool Usage Guide

## 🎯 Quick Reference: Which Tool to Use?

### User asks about **TODAY**
- ✅ Use: `get_live_matches`
- Examples: "What games are on today?", "Live scores", "Any matches now?"

### User asks about **FUTURE** (tomorrow onwards)
- ✅ Use: `get_fixtures`
- Examples: "Upcoming matches", "Next week's fixtures", "Schedule"

### User asks about **LEAGUE TABLE**
- ✅ Use: `get_standings`
- Examples: "Premier League table", "Who's top?", "Where is Arsenal?"

### User asks about **ONE TEAM**
- ✅ Use: `get_team_matches`
- Examples: "Arsenal's recent matches", "Liverpool fixtures", "How's City doing?"

### User asks about **TOP SCORERS**
- ✅ Use: `get_top_scorers`
- Examples: "Golden boot", "Most goals", "Best strikers"

### User asks about **PREDICTIONS**
- ✅ Use: `predict_match`
- Examples: "Who will win Arsenal vs City?", "Predict Liverpool vs Chelsea"

---

## 📖 Detailed Tool Descriptions

### 1. `get_live_matches`
**When to use:**
- User mentions: today, now, live, current
- Time context: Present day only

**Good queries:**
- ✅ "What Premier League games are on today?"
- ✅ "Any matches happening right now?"
- ✅ "Show me today's fixtures"

**Bad queries (use different tools):**
- ❌ "Next week's matches" → Use `get_fixtures`
- ❌ "Arsenal's recent results" → Use `get_team_matches`

**Parameters:**
- `competition`: "premier_league", "champions_league", or "both"

---

### 2. `get_fixtures`
**When to use:**
- User mentions: upcoming, next, schedule, future, this weekend, next week
- Time context: 1-10 days ahead

**Good queries:**
- ✅ "What are the upcoming Premier League fixtures?"
- ✅ "Show me matches this weekend"
- ✅ "Next week's schedule"

**Bad queries:**
- ❌ "Today's matches" → Use `get_live_matches`
- ❌ "Arsenal's next match" → Use `get_team_matches`

**Parameters:**
- `competition`: Which league
- `days_ahead`: How many days to look ahead (default: 7)

**Pro tip:** For "this weekend", use `days_ahead: 3-4`

---

### 3. `get_standings`
**When to use:**
- User mentions: table, standings, position, ranking, league table, top of the league
- Context: Current league positions

**Good queries:**
- ✅ "Show me the Premier League table"
- ✅ "Who's top of the league?"
- ✅ "Where is Manchester United in the standings?"

**Bad queries:**
- ❌ "Who's the top scorer?" → Use `get_top_scorers`

**No parameters needed!**

**Response includes:**
- Position (1-20)
- Team name
- Points
- Games played
- Goal difference

---

### 4. `get_team_matches`
**When to use:**
- User mentions a SPECIFIC team name
- User wants to see multiple matches for that team
- Context: Recent past AND near future

**Good queries:**
- ✅ "Show me Arsenal's recent matches"
- ✅ "How has Liverpool been performing?"
- ✅ "When is Chelsea's next match?"
- ✅ "Give me Man City's last 10 games"

**Bad queries:**
- ❌ "Today's matches" → Use `get_live_matches`
- ❌ "Predict Arsenal vs City" → Use `predict_match`

**Parameters:**
- `team_name`: Team to look up (e.g., "Arsenal", "Liverpool")
- `num_matches`: How many to show (default: 5)

**Pro tip:** Partial names work! "City" finds "Manchester City"

---

### 5. `get_top_scorers`
**When to use:**
- User mentions: goals, scorers, golden boot, top strikers, most goals
- Context: Individual player statistics

**Good queries:**
- ✅ "Who are the top scorers in the Premier League?"
- ✅ "Show me the golden boot race"
- ✅ "Who has the most goals this season?"

**Bad queries:**
- ❌ "Which team scores the most?" → Use `get_standings` (shows GD)

**Parameters:**
- `limit`: How many scorers to show (default: 10)

**Response includes:**
- Player name
- Team
- Total goals

---

### 6. `predict_match`
**When to use:**
- User mentions: predict, who will win, chances, probability, forecast
- Context: Future match between TWO SPECIFIC teams

**Good queries:**
- ✅ "Predict Arsenal vs Manchester City"
- ✅ "Who will win Liverpool vs Chelsea?"
- ✅ "What are the chances of Man United beating Tottenham?"
- ✅ "Expected score for Arsenal vs City"

**Bad queries:**
- ❌ "Show me Arsenal's fixtures" → Use `get_team_matches`
- ❌ "Who will win the league?" → Too broad, not supported

**Parameters:**
- `home_team`: Team playing at home
- `away_team`: Team playing away

**IMPORTANT:** Home/away matters! Predictions factor in home advantage.

**Response includes:**
- Predicted result (HOME_WIN/DRAW/AWAY_WIN)
- Win probabilities (%)
- Expected goals for each team
- Recent form analysis (last 5 matches)
- Confidence level (High/Moderate/Low)

---

## 🔗 Tool Combinations

### Complex queries may need multiple tools:

**"How's Arsenal doing and who will they beat next?"**
1. `get_team_matches` (team_name: "Arsenal") → See recent form
2. Identify next opponent from results
3. `predict_match` (home_team: "Arsenal", away_team: "opponent") → Predict

**"Show me the top of the table and their next matches"**
1. `get_standings` → Get top teams
2. `get_fixtures` → Show upcoming matches

**"Will the top scorer's team win their next match?"**
1. `get_top_scorers` (limit: 1) → Find top scorer's team
2. `get_team_matches` (team_name: "that team") → Find next match
3. `predict_match` → Predict outcome

---

## 💡 Tips for Better Results

### 1. **Be specific about time context**
- ❌ "matches" → Unclear
- ✅ "today's matches" → Clear (use `get_live_matches`)
- ✅ "upcoming matches" → Clear (use `get_fixtures`)

### 2. **One team vs two teams**
- One team: Use `get_team_matches`
- Two teams (prediction): Use `predict_match`

### 3. **Individual stats vs team stats**
- Individual: Use `get_top_scorers`
- Team: Use `get_team_matches` or `get_standings`

### 4. **Current vs future**
- Current/past: Use `get_live_matches`, `get_standings`, `get_team_matches`
- Future: Use `get_fixtures`, `predict_match`

---

## ⚠️ Current Limitations

1. **Only Premier League & Champions League** supported
2. **No player injury/suspension data** in predictions
3. **Head-to-head stats** are simplified (not real H2H data yet)
4. **Predictions** based on last 5 matches only
5. **No live streaming** or video highlights
6. **No betting odds** or gambling information

---

## 🎯 Example Conversations

### Example 1: Simple Query
**User:** "What games are on today?"
**Tool:** `get_live_matches(competition: "both")`

### Example 2: Team-Specific
**User:** "Show me Arsenal's recent form"
**Tool:** `get_team_matches(team_name: "Arsenal", num_matches: 5)`

### Example 3: Prediction
**User:** "Who will win the match between Liverpool and Manchester City?"
**Tool:** `predict_match(home_team: "Liverpool", away_team: "Manchester City")`

### Example 4: Multi-Step
**User:** "Show me the league table and predict if the top team will win their next match"
**Tools:**
1. `get_standings()` → Get table
2. Extract top team from results
3. `get_team_matches(team_name: "top_team")` → Find next match
4. `predict_match(...)` → Predict outcome

---

## 🚀 Quick Decision Tree

```
User Query
    ├─ Mentions "today/now/live"?
    │   └─ YES → get_live_matches
    │
    ├─ Mentions "upcoming/next/schedule"?
    │   └─ YES → get_fixtures
    │
    ├─ Mentions "table/standings/position"?
    │   └─ YES → get_standings
    │
    ├─ Mentions ONE team name?
    │   └─ YES → get_team_matches
    │
    ├─ Mentions "goals/scorers/golden boot"?
    │   └─ YES → get_top_scorers
    │
    └─ Mentions "predict/who will win" + TWO teams?
        └─ YES → predict_match
```

---

This guide helps LLMs choose the right tool for each user query!