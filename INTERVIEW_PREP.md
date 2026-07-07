# Football-MCP — Interview Prep Doc

> Personal reference for the NeuralFort AI Developer Co-op screening call.
> Goal: be able to talk about this project confidently end-to-end — what it does, how it works, and the AI/security concepts behind it.

---

## 1. The 30-second pitch

**Football-MCP is a full-stack AI system for Fantasy Premier League (FPL) decision-making.** It exposes football intelligence as **MCP (Model Context Protocol) tools** that an LLM (Claude Sonnet 4) can call to answer questions like *"who should I captain this week?"* or *"suggest a transfer given my £1.5m bank and 1 free transfer."*

Three things make it more than a toy:

1. **A real ML pipeline** — a Random Forest trained on **58 engineered features** merged from three data sources (the official FPL API, Understat for expected goals/assists, and FBRef for defensive/progressive stats).
2. **Agentic LLM orchestration** — Claude is given ~12 tools and decides which to call (often in parallel) to answer a user's question. Topic restriction + a strict system prompt keep it on-task.
3. **A real product surface** — a FastAPI backend + React 19 frontend, JWT-gated chat, and a deployable web app. Not just a script.

---

## 2. What the project actually does

There are **two MCP servers** in the repo:

| Server | Purpose | Tools |
|---|---|---|
| [`fpl-optimizer/Server.py`](fpl-optimizer/Server.py) | FPL team optimization, transfer/captain advice, ML-based point prediction | ~12 tools |
| [`soccer-stats/Server.py`](soccer-stats/Server.py) | Live match results, standings, fixtures, ML-based match outcome prediction | ~5 tools |

The **fpl-optimizer** server is the one to talk about — it's where most of the engineering depth lives. It's wired up to:

- A **FastAPI REST backend** ([`api_server.py`](fpl-optimizer/api_server.py)) that mirrors the MCP tools as HTTP endpoints so the website can use them.
- A **React 19 frontend** ([`fpl-website/`](fpl-website/)) with a chat UI, team viewer, formation display, transfer suggestions, and an autonomous "bot team" that runs itself each gameweek using [`bot_decision_maker.py`](fpl-optimizer/bot_decision_maker.py).

So the same logic powers two surfaces: an LLM client like Claude Desktop (via MCP) **and** a normal web app (via REST).

---

## 3. Tech stack

### Backend (Python 3.11+)
- **`mcp>=1.0.0`** — Model Context Protocol SDK
- **`fastapi` + `uvicorn`** — REST API for the React frontend
- **`anthropic`** — Claude API client (Sonnet 4, tool calling)
- **`scikit-learn`** — Random Forest predictor
- **`pandas` / `numpy`** — feature engineering
- **`PuLP`** — Linear Programming for squad optimization
- **`understatapi`** — xG / xA / npxG scraping
- **`soccerdata`** — FBRef defensive & progressive stats
- **`thefuzz` + `python-Levenshtein`** — fuzzy player name matching across data sources
- **`PyJWT`** — JWT auth on the chat endpoint
- **`httpx` / `aiohttp`** — async HTTP
- **`requests-cache`** + custom [`data_cache.py`](fpl-optimizer/data_sources/__pycache__/data_cache.cpython-312.pyc) — TTL caching (6h) for external data

### Frontend ([`fpl-website/`](fpl-website/))
- **React 19** + **Vite 7**
- **React Router 7**
- **Tailwind CSS 4**
- No state library — `useState` + `localStorage`
- No UI kit — custom components

### ML / data
- **Model**: scikit-learn `RandomForestRegressor` ([`predict_points.py`](fpl-optimizer/predict_points.py))
- **Features**: 58 (17 FPL + ~20 Understat + ~21 FBRef)
- **Training data**: ~1,960 samples, persisted as CSV
- **Artifacts**: [`models/points_model.pkl`](models/points_model.pkl), [`models/scaler.pkl`](models/scaler.pkl)

### Deployment
- `start_website.sh` runs FastAPI + Vite locally
- `render.yaml` for Render deploy

---

## 4. APIs the project consumes

| API | Auth | Used for |
|---|---|---|
| **Fantasy Premier League official API** (`https://fantasy.premierleague.com/api/`) | None | All player data, prices, ownership, fixtures, user team lookup |
| **Understat** (via `understatapi`) | None | xG, xA, npxG, xGChain, xGBuildup, shots, key passes |
| **FBRef** (via `soccerdata`) | None | Tackles, interceptions, blocks, clearances, progressive passes/carries, SCA, GCA |
| **Football-Data.org** (soccer-stats server only) | API key in `.env` | Live scores, standings, match data |
| **Anthropic Claude API** | API key in `.env` | LLM chat + tool orchestration (`claude-sonnet-4-20250514`) |

**Why three football data sources?** The FPL API alone doesn't give you advanced stats. Understat gives you the attacking quality signals (xG/xA — how many goals a player *should have* scored based on shot quality), and FBRef gives the defensive workload that the new FPL defensive-contribution scoring rewards. Merging them is non-trivial because player names don't match cleanly across sources — that's why the project has [`player_mapping/name_matcher.py`](fpl-optimizer/player_mapping/__pycache__/name_matcher.cpython-312.pyc) with fuzzy matching at an 85% similarity threshold and a manual override file with 166+ hand-mapped edge cases.

---

## 5. APIs the project exposes (FastAPI)

REST endpoints in [`api_server.py`](fpl-optimizer/api_server.py), consumed by the React app via [`fpl-website/src/api/fplApi.js`](fpl-website/src/api/fplApi.js):

- `GET /api/players` — filter/sort all 600+ Premier League players
- `GET /api/players/{id}` — single player detail
- `GET /api/team/{teamId}` — load a user's FPL squad
- `GET /api/bot/team` — view the autonomous bot's current team
- `GET /api/optimal/wildcard` — generate an optimal wildcard squad
- `GET /api/optimal/freehit` — generate an optimal free-hit squad
- `POST /api/chat` — **JWT-protected** Claude chat with tool orchestration
- `GET /health` — health check
- `GET /docs` — Swagger UI (auto-generated by FastAPI)

CORS is configured for `localhost:3000` by default, overridable via the `ALLOWED_ORIGINS` env var.

---

## 6. What is MCP? (Model Context Protocol)

> **You will absolutely get asked this. NeuralFort's job description explicitly mentions MCP.**

### The general concept

**MCP is an open protocol — created by Anthropic in late 2024 — that standardizes how LLMs connect to external tools, data sources, and systems.** Think of it as "USB-C for AI integrations": instead of every LLM app inventing its own way to talk to GitHub, a database, or a set of internal APIs, MCP defines one common interface.

It's a **client-server protocol**, usually spoken over **JSON-RPC** on either:
- **stdio** (stdin/stdout) — the server is a subprocess of the LLM client. This is what Claude Desktop uses.
- **HTTP / Server-Sent Events** — the server runs as a network service.

There are three main capability types an MCP server can expose:

1. **Tools** — functions the LLM can *call* (e.g. `get_player_details`). This is the most common one.
2. **Resources** — data the LLM can *read* (e.g. files, query results).
3. **Prompts** — reusable prompt templates the user can pick from.

### Why it matters

Before MCP, if you wanted Claude to be able to query Postgres, search Slack, and read your Notion docs, you had to build three custom integrations into your app. MCP lets the **server author** ship one MCP server and any MCP-compatible client (Claude Desktop, Cursor, Zed, custom agents, etc.) can use it. The integration surface stops being **N clients × M tools** and becomes **N + M**.

For a startup like NeuralFort building agentic systems for enterprise clients, MCP is the natural way to expose internal systems (CRMs, ticketing, security telemetry) to an agent without rebuilding the connector for every framework.

### MCP tools — what they are *in this project*

In Football-MCP, the MCP server is a Python process that, when started, advertises a list of tools to whatever LLM client launches it. Each tool has:
- a **name** (e.g. `suggest_transfers`)
- a **description** (the LLM reads this to decide when to call it)
- a **JSON schema** for its arguments (so the LLM knows how to format the call)

The 12 tools the FPL server exposes:

| Tool | What it does |
|---|---|
| `get_all_players` | Filter/sort 600+ PL players by position, team, price, form, etc. |
| `get_player_details` | Deep-dive on one player (form, fixtures, xG, defensive contribution probability) |
| `get_fixtures` | Upcoming matches with FDR (Fixture Difficulty Rating) |
| `get_my_team` | Load a user's 15-player squad, bank, and chip status |
| `get_top_performers` | Ranked lists by metric (form, xG/90, value, ownership delta, etc.) |
| `evaluate_transfer` | Compare two players, return point diff and hit cost |
| `optimize_squad_lp` | Build the optimal 15-player squad under budget using Linear Programming |
| `analyze_fixtures` | Multi-gameweek FDR analysis — find good runs, blanks, doubles |
| `optimize_lineup` | Pick the best starting XI from a given 15 |
| `suggest_captain` | Top-3 captain picks with predicted points |
| `suggest_chips_strategy` | When to play Wildcard / Free Hit / Bench Boost / Triple Captain |
| `suggest_transfers` | Recommend transfers given free-transfer count and chips available |

When the user asks the chatbot *"who should I captain?"*, the flow is:
1. React sends `POST /api/chat` with the message + the user's team context.
2. The FastAPI handler calls Claude via the Anthropic SDK, passing all 12 tools.
3. Claude decides — in this case it'll typically call `suggest_captain` and `get_fixtures` **in parallel** (the system prompt explicitly encourages parallel tool use).
4. Tools execute server-side, return JSON.
5. Claude synthesizes a natural-language answer using the results.
6. Response streams back to the user.

### MCP transport in this codebase

The FPL server runs over **stdio** ([`Server.py`](fpl-optimizer/Server.py) end of file):
```python
async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
    await server.run(read_stream, write_stream, ...)
```
That's why there's aggressive logging suppression at the top of the file — anything written to stdout that isn't valid JSON-RPC will break the protocol. All logs are redirected to stderr.

---

## 7. The LLM integration ([`anthropic_chat.py`](fpl-optimizer/anthropic_chat.py))

This is where the "agentic" part lives. Worth understanding cold.

### Model
`claude-sonnet-4-20250514` via the official `anthropic` Python SDK.

### Tool orchestration loop
1. Build the message: user input **+ injected team context** (team ID, free transfers, chips, full squad with prices and form, bank balance).
2. Send to Claude with the tool definitions and `tool_choice="auto"`.
3. If the response contains `tool_use` blocks, execute those tools (in parallel where possible) and feed results back as `tool_result` messages.
4. Loop until Claude returns a pure text response or hits the iteration cap. Max tokens scales up if responses get truncated.

### System prompt (engineering choices worth calling out)
- **Topic restriction** — explicit allow/deny lists for football vs. off-topic queries. Off-topic queries get a canned redirect rather than an LLM-generated refusal (cheaper and harder to jailbreak).
- **`<use_parallel_tool_calls>`** directive telling Claude to fan out tool calls instead of going sequential.
- **"Never mention tool names"** — keeps the UX conversational instead of "I will now use the `evaluate_transfer` tool…".
- **Context-aware** — every message includes the user's current team, so Claude never asks "what's your team ID?" (a major UX failure mode in early versions).

### Why this is real "agentic" work
Claude is making decisions about *which* tools to call, *what arguments* to pass, and *how to combine* their outputs — not following a hardcoded chain. That's the difference between an "AI feature" and an agentic workflow, and it's exactly what NeuralFort's JD describes (LangChain/LangGraph/CrewAI all do roughly the same thing as this hand-rolled loop).

---

## 8. The ML pipeline

### The merge ([`enhanced_features.py`](fpl-optimizer/enhanced_features.py))
Three sources, joined on player name with fuzzy matching:

```
FPL API (600+ players, base stats)
        ↓
   join Understat (xG, xA, xGChain) → ~58% match rate
        ↓
   join FBRef (defensive + progressive stats) → ~55% match rate
        ↓
Position-based fallback values for unmatched players
```

The fallback strategy matters: rather than dropping a player with no Understat match, the pipeline backfills with position-typical values (forwards get higher npxG defaults than defenders). This keeps every player scoreable.

### The model ([`predict_points.py`](fpl-optimizer/predict_points.py))
- `RandomForestRegressor` predicting expected FPL points
- Trained on ~1,960 augmented samples
- **Most important feature: `form` (~78% importance)**, followed by `xG_per_90`, `npxG_per_90`, `xGChain_per_90`, `def_contributions_per_90`
- The defensive-contribution feature was added in Phase 4 to capture the new 2025/26 FPL defensive scoring rule — a good story for "I read the spec, found the gap in my model, and added a feature for it."

### Optimization ([`enhanced_optimization.py`](fpl-optimizer/enhanced_optimization.py))
**Linear Programming** with PuLP for squad selection. Constraints:
- 15 players, £100m budget
- 2 GK / 5 DEF / 5 MID / 3 FWD
- Max 3 from any one club
- Objective: maximize expected points (from the ML predictor) over an N-gameweek window

This is genuinely classical OR work bolted onto the ML predictions — a nice distinction to draw if asked "is this just ML?" No: it's ML predictions feeding an LP solver feeding an LLM-facing tool.

---

## 9. Security

### JWT authentication ([`auth.py`](fpl-optimizer/auth.py))

**What JWT is in general:**
A **JSON Web Token** is a signed, base64-encoded token with three parts separated by dots: `header.payload.signature`.
- **Header**: algorithm (e.g. `HS256`) and token type
- **Payload**: claims — arbitrary JSON, typically including `iat` (issued-at), `exp` (expiry), and a user identifier
- **Signature**: HMAC of `header.payload` using a secret key (HS256) or an RSA/ECDSA private key (RS256/ES256)

The server can verify the signature with the same secret/public key without storing session state — this is what makes JWT *stateless*. If the signature checks out and `exp` hasn't passed, the token is valid.

**Tradeoffs to know:**
- Pros: stateless, scales horizontally, no session DB lookup per request.
- Cons: revocation is hard (you can't invalidate a JWT before its `exp` without a deny-list), so keep expiries short. Don't put secrets in the payload — it's signed, not encrypted.

**How it's used here ([`auth.py`](fpl-optimizer/auth.py)):**
1. The user enters an access code in the React modal (`AccessCodeModal.jsx`).
2. The backend SHA-256 hashes the code and compares to `ACCESS_CODE_HASH` (env var). The plaintext code is never stored.
3. On match, `create_access_token` issues an HS256-signed JWT with `verified: true` and a 24-hour expiry.
4. The frontend stores the token and sends it as `Authorization: Bearer <token>` on subsequent requests.
5. `verify_token` is a FastAPI dependency that decodes and validates on protected endpoints (the chat endpoint specifically).
6. Expired or malformed tokens → 401.

This is a deliberately minimal design — it's a *portfolio access gate*, not a multi-user auth system. There are no user accounts; it's a single shared code that gates access to the (paid) Anthropic API.

### Other security-relevant choices
- **Secrets in env vars** via `python-dotenv` — `JWT_SECRET_KEY`, `ACCESS_CODE_HASH`, `ANTHROPIC_API_KEY`, `FOOTBALL_DATA_API_KEY`. None of these live in code.
- **CORS middleware** locks the API to specific origins (`localhost:3000` by default, `ALLOWED_ORIGINS` env var in production).
- **Pydantic models** validate every request body — basic input sanitization at the framework layer.
- **LLM topic restriction** in [`anthropic_chat.py`](fpl-optimizer/anthropic_chat.py) — both an allow-list and an off-topic phrase deny-list, plus a strict system prompt. This is a lightweight form of prompt-injection defense: an attacker trying to make the bot answer non-FPL questions hits the topic filter before Claude is even called.
- **No tool returns raw user input to the LLM unsanitized** — all tool inputs go through Pydantic schemas defined in the MCP tool definitions.

### What I'd improve if asked
- Secrets are currently in `.env` files committed to the repo — a real deployment would use a secrets manager (AWS Secrets Manager, Doppler, etc.) and the files would be `.gitignore`d.
- No rate limiting on the chat endpoint — trivial to add with `slowapi`, and important because each call costs Anthropic credits.
- No persistent token deny-list — for a real product you'd want a Redis-backed revocation list.
- HTTPS termination is assumed at the reverse proxy / hosting layer.

---

## 10. Connecting it back to the NeuralFort JD

This project hits almost every line of the requirements:

| JD requirement | Where it shows up here |
|---|---|
| LLM integration (Claude / GPT-4) | Anthropic Claude Sonnet 4 in [`anthropic_chat.py`](fpl-optimizer/anthropic_chat.py) |
| Agentic workflows | Tool-calling loop with parallel execution; autonomous bot in [`bot_decision_maker.py`](fpl-optimizer/bot_decision_maker.py) |
| LLM frameworks (LangChain/LangGraph/CrewAI) | Hand-rolled equivalent — I can speak to *why* (lower abstraction, fewer dependencies) and would happily use the frameworks at NeuralFort |
| REST API integration | FPL API, Understat, FBRef, Football-Data.org all consumed; FastAPI exposes our own |
| Python proficiency | Whole backend |
| TypeScript/JavaScript | React 19 frontend in JSX |
| ML / NLP | Random Forest with 58 features, LLM orchestration |
| Prompt engineering | System prompt design with topic restriction + parallel-tool directive |
| MCP | The literal protocol the project is built on |
| Vector DBs / RAG | Not in this project — be honest, but I understand the concept (embed docs → store in pgvector/Pinecone/Chroma → retrieve top-k by similarity → inject into prompt). Happy to learn on the job. |
| AI governance / prompt injection | Topic restriction + system-prompt hardening + Pydantic validation |
| Cybersecurity x AI | JWT auth on the LLM endpoint specifically (so attackers can't burn API credits or exfiltrate via prompt injection without authenticating first) |
| Cloud (AWS/Azure/GCP) | Deployed via Render — not the same, but the deployment workflow translates |
| Git / collaborative dev | Whole project history |

---

## 11. Things to be ready to discuss

**Strengths to lead with:**
- "I built and shipped a full agentic system end-to-end — ML pipeline, LLM orchestration, REST API, and frontend. I understand each layer, not just one."
- "MCP is the integration substrate I chose for this — I can explain the protocol, the tradeoffs vs. plain function-calling, and why it matters for an agent platform serving multiple clients."
- "The ML and the LLM are doing different jobs here: the Random Forest is the predictor, Claude is the orchestrator. Knowing when to use a model vs. when to use an agent is the lesson."

**Honest gaps:**
- No production RAG / vector DB experience yet — but I understand the architecture and the failure modes (chunking strategy, embedding model choice, retrieval quality eval).
- No formal LangChain/LangGraph in-project — I built the equivalent by hand, which means I know what those frameworks abstract away.
- Security here is portfolio-grade, not enterprise-grade — I can articulate exactly what would need to harden for prod (secrets manager, rate limiting, token revocation, audit logging).

**Story arc for "why AI engineering / why NeuralFort":**
The interesting problems in software right now sit at the boundary between deterministic systems and probabilistic ones — the LLM decides, the tools execute, and the engineering challenge is making that loop reliable, observable, and safe. NeuralFort is doing exactly that for enterprise clients, with cybersecurity as the quality bar. That's the work I want to be doing.

---

## 12. Quick file map (for showing in the call if asked)

| File | What to point at |
|---|---|
| [`fpl-optimizer/Server.py`](fpl-optimizer/Server.py) | MCP server, tool definitions, stdio transport setup |
| [`fpl-optimizer/anthropic_chat.py`](fpl-optimizer/anthropic_chat.py) | Claude integration, system prompt, tool orchestration loop |
| [`fpl-optimizer/auth.py`](fpl-optimizer/auth.py) | JWT issuance + verification, SHA-256 access code |
| [`fpl-optimizer/api_server.py`](fpl-optimizer/api_server.py) | FastAPI REST layer, CORS, endpoint definitions |
| [`fpl-optimizer/enhanced_features.py`](fpl-optimizer/enhanced_features.py) | Three-source data merge with fallbacks |
| [`fpl-optimizer/predict_points.py`](fpl-optimizer/predict_points.py) | Random Forest predictor, 58 features |
| [`fpl-optimizer/enhanced_optimization.py`](fpl-optimizer/enhanced_optimization.py) | Linear Programming squad builder |
| [`fpl-optimizer/bot_decision_maker.py`](fpl-optimizer/bot_decision_maker.py) | Autonomous bot team logic |
| [`fpl-website/src/pages/UserTeamPage.jsx`](fpl-website/src/pages/UserTeamPage.jsx) | Main React page — team viewer + chat integration |
