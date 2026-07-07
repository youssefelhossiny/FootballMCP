# Football-MCP — Football Intelligence Suite

> AI-powered soccer analytics and Fantasy Premier League optimization,
> available as **MCP servers** *and* a **full-stack web app**.

## 🎯 What This Project Does

**Football-MCP** provides football intelligence through two specialized MCP
servers, plus a React web app that surfaces the FPL tools over a REST API:

1. **⚽ Soccer Stats Server** - Match predictions, live scores, league standings
2. **🏆 FPL Optimizer Server** - Fantasy Premier League team optimization and analysis
3. **🌐 FPL Website** - React 19 frontend + FastAPI backend (chat, team viewer,
   transfer suggestions, autonomous "bot team")

The MCP servers work with any MCP-compatible LLM client (Claude Desktop, etc.).
The FPL optimizer's ML pipeline now runs on **58 engineered features** merged
from the FPL API, Understat (xG/xA), and FBRef (defensive/progressive stats).

> 📄 For the current architecture, ML pipeline details, and roadmap, see
> **[PROJECT_STATUS.md](PROJECT_STATUS.md)**.

---

## 📊 Server 1: Soccer Stats MCP

**Location:** `soccer-stats/`

### What It Does
- Live match scores and schedules
- League standings (Premier League & Champions League)
- Team performance analysis
- Machine learning match predictions
- Head-to-head comparisons

### Key Tools
- `get_live_matches` - Today's matches with live scores
- `get_standings` - Current league table
- `predict_match` - ML-powered match predictions
- `get_team_matches` - Team-specific fixtures
- `get_top_scorers` - Leading goal scorers

### Data Source
- **Football-Data.org API** (requires free API key)
- Coverage: Premier League, Champions League
- 10 requests per minute limit

[📖 Full Soccer Stats Documentation →](soccer-stats/README.md)

---

## 🏆 Server 2: FPL Optimizer MCP

**Location:** `fpl-optimizer/`

### What It Does
- Player analysis for all 600+ Premier League players
- Fixture difficulty ratings
- Team value optimization
- Transfer recommendations
- Captain selection advice

### Tools (~12, all live)
- `get_all_players` - Filter & sort all PL players
- `get_player_details` - Deep player statistics (incl. xG/xA + defensive stats)
- `get_top_performers` - Top players by any metric
- `optimize_squad_lp` - Build optimal 15-player team (Linear Programming)
- `evaluate_transfer` / `suggest_transfers` - Transfer analysis & suggestions
- `suggest_captain` - Data-driven captain picks
- `suggest_chips_strategy` - Chip timing advice
- ML-powered points prediction (Random Forest, 58 features)

### Data Source
- **Official FPL API** (no API key needed!)
- Real-time data, unlimited requests
- Updated instantly during matches

[📖 Full FPL Optimizer Documentation →](fpl-optimizer/README.md)

---

## 🚀 Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/yourusername/FootballMCP.git
cd FootballMCP

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r soccer-stats/requirements.txt
pip install -r fpl-optimizer/requirements.txt
```

### 2. Configure API Keys

Create `.env` file in project root:

```bash
# Soccer Stats API (get free key from football-data.org)
FOOTBALL_DATA_API_KEY=your_key_here
```

**Note:** FPL Optimizer doesn't need an API key!

### 3. Test Both Servers

```bash
# Test Soccer Stats
cd soccer-stats
python test_api.py

# Test FPL Optimizer
cd ../fpl-optimizer
python test_fpl_api.py
python test_tools.py
```

### 4. Configure Your MCP Client

Add to your MCP client config (e.g., Claude Desktop):

```json
{
  "mcpServers": {
    "soccer-stats": {
      "command": "python",
      "args": ["/absolute/path/to/FootballMCP/soccer-stats/Server.py"],
      "env": {
        "FOOTBALL_DATA_API_KEY": "your_key_here"
      }
    },
    "fpl-optimizer": {
      "command": "python",
      "args": ["/absolute/path/to/FootballMCP/fpl-optimizer/Server.py"]
    }
  }
}
```

**Restart your MCP client after configuration!**

---

## 💡 Example Queries

### Soccer Stats Queries

```
"What Premier League matches are on today?"
"Show me the current Premier League standings"
"Predict the outcome of Liverpool vs Manchester City"
"How has Arsenal been performing recently?"
"Who are the top scorers in the Premier League?"
```

### FPL Optimizer Queries

```
"Show me all midfielders under £8m sorted by form"
"Tell me about Mohamed Salah's stats and upcoming fixtures"
"Which teams have the easiest fixtures in the next 5 gameweeks?"
"Who are the top 10 scorers this season?"
"Show me the best value defenders"
```

### Combined Queries (Using Both Servers!)

```
"Compare Haaland's FPL stats with City's upcoming fixtures and predict their next match"
"Show me Arsenal's fixture difficulty and their top FPL assets"
"Who are the in-form players from teams with easy fixtures?"
```

---

## 📁 Project Structure

```
Football-MCP/
├── README.md                    # This file
├── PROJECT_STATUS.md            # Current architecture, ML pipeline, roadmap
├── start_website.sh             # Launch backend (:8000) + frontend (:3000)
├── .env                         # API keys (create this — not tracked)
├── models/                      # Trained ML models (.pkl) + feature lists
│
├── soccer-stats/                # Soccer Stats MCP server
│   ├── Server.py                # Main MCP server
│   ├── collect_training_data.py # ML data collection
│   ├── train_model.py           # Train ML models
│   ├── README.md / Tool_usage_guide.md
│
├── fpl-optimizer/               # FPL MCP server + FastAPI backend
│   ├── Server.py                # MCP server (~12 tools)
│   ├── api_server.py            # FastAPI REST API for the website
│   ├── enhanced_features.py     # FPL + Understat + FBRef → 58 features
│   ├── predict_points.py        # Random Forest predictor
│   ├── data_sources/            # scrapers + cache
│   ├── player_mapping/          # fuzzy name matching
│   ├── README.md / SETUP.md
│
└── fpl-website/                 # React 19 + Vite 7 + Tailwind 4 frontend
```

---

## 🔧 Development Status

The FPL optimizer is production-ready: squad optimization (Linear Programming),
transfer/captain/chip advice, and ML points prediction on 58 features are all
live, powering both the MCP server and the web app.

See **[PROJECT_STATUS.md](PROJECT_STATUS.md)** for the current ML pipeline,
feature breakdown, and roadmap.

---

## 🎓 Technical Details

### Soccer Stats Server

**Technologies:**
- MCP Protocol
- Football-Data.org API
- scikit-learn (Random Forest ML)
- pandas, numpy

**ML Model:**
- Random Forest Classifier (match results)
- Random Forest Regressor (goal predictions)
- Features: Recent form, goals, wins/draws/losses
- Training data: Last 3 seasons

### FPL Optimizer Server

**Technologies:**
- MCP Protocol
- Official FPL API (free!)
- pandas, numpy
- PuLP (for Phase 2 optimization)

**Phase 2 Planned:**
- Linear Programming for squad optimization
- ML for points prediction
- Expected points calculations

---

## 🐛 Troubleshooting

### Soccer Stats Issues

**"API Key Invalid" Error:**
1. Check your API key at football-data.org
2. Verify `.env` file format
3. Make sure key is active (free tier)

**"Rate Limit" Error:**
- Free tier: 10 requests per minute
- Wait 60 seconds between batches
- Consider upgrading to paid tier

### FPL Optimizer Issues

**"Could not find team" Error:**
- Verify your FPL team ID
- URL: `fantasy.premierleague.com/entry/YOUR_ID/`
- Team must be active for current season

**"Player not found" Error:**
- Use shorter names (e.g., "Salah" not "Mohamed Salah")
- Names use partial matching
- Check spelling

### General Issues

**MCP Server Not Connecting:**
1. Test servers individually: `python Server.py`
2. Check Python version (3.8+)
3. Verify absolute paths in MCP config
4. Restart your MCP client after config changes

**Import Errors:**
```bash
pip install -r soccer-stats/requirements.txt
pip install -r fpl-optimizer/requirements.txt
```

---

## 📊 Data Sources

### Soccer Stats
- **Football-Data.org API**
  - Free tier: 10 req/min
  - Coverage: 10+ leagues
  - Historical data: 2021+
  - [Get API Key →](https://www.football-data.org/client/register)

### FPL Optimizer
- **Official FPL API**
  - No API key needed
  - No rate limits
  - Real-time data
  - [API Docs (Unofficial) →](https://fantasy.premierleague.com/api/bootstrap-static/)

---

## 🤝 Contributing

Contributions welcome! Areas of interest:

1. **Soccer Stats Improvements:**
   - Better ML models
   - More data sources
   - Additional leagues

2. **FPL Optimizer Phase 2:**
   - Optimization algorithms
   - ML predictions
   - Advanced analytics

3. **General:**
   - Documentation
   - Testing
   - Bug fixes

---

## 📝 License

MIT License - See LICENSE file for details

---

## 🙏 Acknowledgments

- [Football-Data.org](https://www.football-data.org/) for soccer data
- [Fantasy Premier League](https://fantasy.premierleague.com/) for FPL API
- [Model Context Protocol](https://modelcontextprotocol.io/) by Anthropic

---

## 📞 Support

- Issues: [GitHub Issues](https://github.com/yourusername/FootballMCP/issues)
- Discussions: [GitHub Discussions](https://github.com/yourusername/FootballMCP/discussions)

---

