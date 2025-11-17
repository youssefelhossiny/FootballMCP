# Football-MCP

Soccer Stats MCP Server
Version: 1.0.0
Data Source: Football-Data.org API
Coverage: Premier League, UEFA Champions League
Current Season: 2024/2025

🎯 Server Capabilities
This MCP server provides 6 tools for soccer/football data and predictions:

Real-time Match Data - Live scores and today's matches
Future Fixtures - Upcoming matches (1-10 days ahead)
League Standings - Current Premier League table
Team Analysis - Individual team match history and schedule
Player Statistics - Top goal scorers
ML Predictions - Machine learning match outcome predictions


📊 Data Coverage
Competitions

✅ Premier League (English top division)
✅ UEFA Champions League (European competition)

Time Periods

Historical: Matches from 2021/2022 season onwards
Current: Live season 2024/2025
Future: Scheduled matches up to 10 days ahead

Update Frequency

Live scores: Real-time during matches
Standings: Updated after each matchday
Fixtures: Updated as matches are scheduled
ML models: Trained on historical data (retrain monthly recommended)


🛠️ Tool Capabilities & Limitations
✅ What This Server CAN Do

Get Today's Matches

Live scores with current minute
Finished matches with final scores
Upcoming kickoffs for today


Get Upcoming Fixtures

Scheduled matches for next 1-10 days
Match dates and times
Home/away teams


Get League Table

All 20 Premier League teams
Position, points, games played
Goal difference


Analyze Specific Teams

Recent match results (with scores)
Upcoming fixtures
Recent form (W/D/L record)


Get Top Scorers

Player names and teams
Total goals scored
Current season only


Predict Match Outcomes

Win/draw/loss probabilities
Expected goals for each team
Team form analysis
Confidence ratings



❌ What This Server CANNOT Do

Player Details

❌ Injuries or suspensions
❌ Player transfers
❌ Individual player stats (except goals)
❌ Lineups or formations


Advanced Statistics

❌ Possession percentages
❌ Pass completion rates
❌ xG (expected goals) from matches
❌ Shot statistics


Other Leagues

❌ La Liga, Serie A, Bundesliga
❌ Lower divisions
❌ International tournaments (except Champions League)


Historical Deep Dives

❌ Matches before 2021
❌ All-time records
❌ Historical head-to-head (simplified only)


Real-Time Everything

❌ Live commentary
❌ Video highlights
❌ Live player positions/events


Betting Information

❌ Odds or betting lines
❌ Gambling recommendations




🎯 Best Use Cases
✅ Great For:

"What matches are on today?"
"Show me the Premier League table"
"How has Arsenal been performing?"
"Predict Liverpool vs Manchester City"
"Who are the top scorers?"
"What's Chelsea's next match?"

⚠️ Not Ideal For:

"Show me La Liga table" (not supported)
"Is Salah injured?" (no injury data)
"What are the betting odds?" (no betting info)
"Show me the 1998 Arsenal squad" (too historical)


🔄 Data Freshness

Live Match Scores: Updated in real-time during matches
Fixtures: Updated as officially scheduled
Standings: Updated after each matchday completes
Top Scorers: Updated after each matchday
Team Stats: Based on last 5 completed matches
ML Predictions: Based on training data (retrain for best accuracy)


🚀 Performance Notes
Response Times

Fast (<1s): Standings, top scorers
Medium (1-2s): Live matches, fixtures, team matches
Slower (2-5s): ML predictions (requires team stat calculation)

Rate Limits

Free Tier: 10 requests per minute
Daily Limit: None (only per-minute limit)

Tip: Batch requests when possible (e.g., use get_fixtures for all matches instead of checking teams individually)

💡 Usage Tips for LLMs
1. Choose the Right Tool

Single team query → get_team_matches
Two teams + prediction → predict_match
Time-based → get_live_matches (today) or get_fixtures (future)

2. Handle Ambiguity

"matches" → Ask: "Today's matches or upcoming?"
Team names → Use partial matching ("City" works for "Manchester City")
Predictions → Always specify home/away team clearly

3. Combine Tools When Needed

Complex queries may need 2-3 tool calls
Example: "Predict next week's top matches" = get_fixtures + predict_match

4. Interpret Results

Predictions are probabilities, not certainties
Form analysis shows trends, not guarantees
Consider confidence levels in predictions

5. Graceful Degradation

If predictions unavailable → Offer form analysis instead
If no matches found → Suggest checking different date range
If team not found → Suggest similar team names


🎓 Understanding ML Predictions
Model Details

Algorithm: Random Forest (Classifier + Regressors)
Training Data: Last 3 seasons of Premier League matches
Features: Recent form, goals scored/conceded, wins/draws/losses
Accuracy: ~52% for match results (better than random 33%)
Goals RMSE: ~1.1 goals (predictions within ±1 goal typically)

Interpreting Predictions
Win Probabilities:

>60% - Strong favorite (high confidence)
45-55% - Even match (low confidence)
<40% - Underdog (moderate confidence)

Expected Goals:

>2.5 - High-scoring team/match
1.5-2.5 - Average
<1.5 - Defensive/low-scoring

Confidence Levels:

High - One outcome >60% likely
Moderate - One outcome 45-60% likely
Low - All outcomes close (<45% each)

What Predictions Consider
✅ Recent form (last 5 matches)
✅ Goals scored/conceded averages
✅ Home advantage
✅ Win/draw/loss records
✅ Historical patterns
What Predictions DON'T Consider
❌ Injuries/suspensions
❌ Specific player matchups
❌ Weather conditions
❌ Managerial changes
❌ Motivation factors
Note: Predictions are statistical estimates, not guarantees. Soccer is inherently unpredictable!

📞 Error Handling
The server provides helpful error messages that guide users to alternative approaches:

Team not found → Suggests correct team names
No matches → Suggests different date ranges
ML unavailable → Offers alternative analysis methods
Rate limit → Explains wait time and batching options


🔧 Maintenance
Recommended Actions

Weekly: Check for API updates
Monthly: Retrain ML models with new data
Seasonally: Update competition IDs if needed

Known Issues

Champions League availability may vary (depends on match schedule)
International breaks = no Premier League matches
Off-season = limited data available
