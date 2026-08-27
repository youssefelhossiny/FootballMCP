#!/bin/bash
# Scheduled FPL bot run — headless Claude Code driving the local MCP server.
#
# ## Why this shape
#
# launchd fires this HOURLY, but a decision is only made when one is actually
# due. `bot_scheduler.due_runs()` owns that judgement (it reads FPL's own
# deadlines), so the expensive part — invoking Claude — happens roughly twice a
# gameweek rather than 168 times a week. The hourly tick is just a cheap Python
# call that usually prints nothing and exits.
#
# ## Why Claude Code and not the API
#
# Verified on this machine: `claude --print` with `--mcp-config` loads the local
# MCP server and can call all 17 tools, and it worked while the project's
# ANTHROPIC_API_KEY had **zero credit** — i.e. it authenticated through the
# Claude Code subscription session, not the API key. That is the entire cost
# argument for this approach. (Caveat worth re-checking: there are reports that
# headless runs may bill at API rates. Watch the usage dashboard after the first
# few real runs rather than assuming either way.)
#
# ## Safety
#
# Nothing here writes to FPL. The agent is given READ-ONLY tools via an explicit
# --allowedTools allowlist, so even a badly-worded prompt cannot submit a
# transfer. Writes stay behind fpl_auth's FPL_BOT_MODE gate, which defaults to
# `notify`. Making this write is a deliberate, separate change.
set -uo pipefail

PROJECT="/Users/youssefelhossiny/Documents/GitHub/Football-MCP/fpl-optimizer"
VENV_PY="$PROJECT/.venv/bin/python"
CLAUDE_BIN="${CLAUDE_BIN:-/Users/youssefelhossiny/.nvm/versions/node/v22.14.0/bin/claude}"
# Logs live OUTSIDE ~/Documents: macOS TCC blocks launchd-spawned processes from
# touching Documents at all ("Operation not permitted" even on an executable
# file), so both this script and its logs sit in ~/.clankerfc. The Python and
# MCP server stay in the repo — the venv reads those as YOUR user, not launchd's
# sandboxed context, which is allowed.
LOG_DIR="${BOT_LOG_DIR:-$HOME/.clankerfc/logs}"
LOG="$LOG_DIR/bot_runs.log"
MCP_CONFIG="${BOT_MCP_CONFIG:-$HOME/.clankerfc/mcp_bot.json}"

mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S%z')] $*" >> "$LOG"; }

# --force runs regardless of whether the scheduler says one is due, for testing.
FORCE_TYPE=""
if [[ "${1:-}" == "--force" ]]; then
  FORCE_TYPE="${2:-final}"
fi

if [[ -n "$FORCE_TYPE" ]]; then
  RUN_TYPE="$FORCE_TYPE"
  log "FORCED $RUN_TYPE run"
else
  # Ask the scheduler what (if anything) is due. Prints one of: "", "early",
  # "final". Anything else is treated as an error and logged.
  DUE=$("$VENV_PY" - <<'PY' 2>>"$LOG"
import asyncio, sys
sys.path.insert(0, "/Users/youssefelhossiny/Documents/GitHub/Football-MCP/fpl-optimizer")
try:
    import bot_scheduler
    due = asyncio.run(bot_scheduler.due_runs())
    # "final" must never be skipped in favour of "early" if both somehow apply.
    print("final" if "final" in due else (due[0] if due else ""))
except Exception as e:
    print(f"ERROR:{e}", file=sys.stderr)
    print("")
PY
)
  DUE="$(echo "$DUE" | tr -d '[:space:]')"

  if [[ -z "$DUE" ]]; then
    # Quiet by default: an hourly "nothing due" line would bury the real runs.
    # Set BOT_LOG_QUIET_TICKS=0 to see every tick while debugging the schedule.
    if [[ "${BOT_LOG_QUIET_TICKS:-1}" != "1" ]]; then
      log "tick — nothing due"
    fi
    exit 0
  fi
  RUN_TYPE="$DUE"
  log "$RUN_TYPE run is DUE"
fi

if [[ ! -x "$CLAUDE_BIN" ]]; then
  log "ERROR: claude binary not found at $CLAUDE_BIN — set CLAUDE_BIN"
  exit 1
fi

# Read-only tool allowlist. Deliberately excludes anything that could mutate a
# real FPL team; the MCP server exposes no write tools today, and this allowlist
# means adding one later cannot silently become reachable from a cron job.
ALLOWED="mcp__fpl-optimizer__get_squad_strategy,\
mcp__fpl-optimizer__get_ml_prediction,\
mcp__fpl-optimizer__get_team_news,\
mcp__fpl-optimizer__get_injury_report,\
mcp__fpl-optimizer__search_player_news,\
mcp__fpl-optimizer__get_fixtures,\
mcp__fpl-optimizer__analyze_fixtures,\
mcp__fpl-optimizer__get_my_team,\
mcp__fpl-optimizer__suggest_captain,\
mcp__fpl-optimizer__suggest_transfers,\
mcp__fpl-optimizer__evaluate_transfer,\
mcp__fpl-optimizer__optimize_lineup,\
mcp__fpl-optimizer__optimize_squad_lp,\
mcp__fpl-optimizer__suggest_chips_strategy,\
mcp__fpl-optimizer__get_player_details,\
mcp__fpl-optimizer__get_all_players,\
mcp__fpl-optimizer__get_top_performers"

# Team id: env var first (launchd supplies it via the plist), then a config
# file. The file matters because a MANUAL run from a normal shell has no
# BOT_TEAM_ID exported — the first real-squad test silently produced generic
# advice for exactly that reason, and the failure is invisible in the output
# unless you read the wording carefully.
TEAM_ID="${BOT_TEAM_ID:-}"
if [[ -z "$TEAM_ID" && -f "$HOME/.clankerfc/team_id" ]]; then
  TEAM_ID="$(tr -d '[:space:]' < "$HOME/.clankerfc/team_id")"
fi
TEAM_LINE="No BOT_TEAM_ID is configured, so analyse generally rather than for a specific squad."
if [[ -z "$TEAM_ID" ]]; then
  log "WARNING: no team id (env or ~/.clankerfc/team_id) — output will be GENERIC, not squad-specific"
fi
if [[ -n "$TEAM_ID" ]]; then
  TEAM_LINE="The team id is $TEAM_ID — use get_my_team to load the current squad."
fi

if [[ "$RUN_TYPE" == "early" ]]; then
  TIMING="This is the EARLY run, ~48h before the deadline. Its ONLY job is to flag a transfer whose
TIMING is price-sensitive — someone you would buy anyway who is about to rise, or someone you would
sell who is about to fall. Do NOT pick a captain or a chip now; more team news arrives before the
deadline. If nothing is both merited AND urgent, say so plainly. That is the expected answer most weeks."
else
  TIMING="This is the FINAL run, ~2h before the deadline. Press conferences have happened, so team
news is at its most reliable. Decide transfers, captain, vice-captain and bench order."
fi

PROMPT="You are the manager of an FPL team, running unattended before a deadline.
$TEAM_LINE

$TIMING

Work like an FPL expert, not a stats reader:
- Call get_squad_strategy FIRST for the structural picture: clean-sheet teams, budget rotation pairs
  with complementary fixtures, value picks, xG bargains and regression risks.
- Check availability with get_team_news and get_injury_report. Where FPL's chance-of-playing
  disagrees with the press, or a partial doubt (25/50/75%) appears, use search_player_news and
  TRUST THE LIVE NEWS over FPL's flag.
- Remember FPL auto-substitutes: starting a doubtful player you already own is free upside, so never
  bench someone to 'protect' against a blank. Bench order is best-player-first.
- Judge transfers over the next 3-5 gameweeks, not just this one. Captaincy is this gameweek only.
- Overperforming xG is a WARNING (price inflated by finishing luck), not a buy signal.

Finish with a short, decisive report: what you would do, and WHY, citing the evidence. State clearly
if you would make no change — rolling a transfer is often correct. You cannot submit anything; this
is advice for a human to action."

log "invoking claude (run_type=$RUN_TYPE)"
START=$(date +%s)

OUT_FILE="$LOG_DIR/decision_$(date '+%Y%m%d_%H%M%S')_${RUN_TYPE}.md"

if echo "$PROMPT" | "$CLAUDE_BIN" --print \
    --mcp-config "$MCP_CONFIG" \
    --allowedTools "$ALLOWED" \
    > "$OUT_FILE" 2>>"$LOG"; then
  ELAPSED=$(( $(date +%s) - START ))
  log "SUCCESS in ${ELAPSED}s -> $(basename "$OUT_FILE") ($(wc -c <"$OUT_FILE" | tr -d ' ') bytes)"
  # Record the run so the scheduler will not repeat it this gameweek.
  "$VENV_PY" - "$RUN_TYPE" "$OUT_FILE" <<'PY' 2>>"$LOG"
import asyncio, sys
sys.path.insert(0, "/Users/youssefelhossiny/Documents/GitHub/Football-MCP/fpl-optimizer")
import bot_scheduler

async def noop(run_type, submit):
    # The decision was already produced by the Claude Code run; this only
    # records it so due_runs() stops offering the same run again.
    return {"decision": {"confidence": "n/a", "captain_name": "(see report)",
                         "transfers": []}, "submitted": False,
            "report": sys.argv[2]}

print(asyncio.run(bot_scheduler.execute_run(sys.argv[1], noop, submit=False)).get("ok"))
PY
  # macOS notification so a real decision is not silently buried in a log.
  if [[ -n "${BOT_NOTIFY:-1}" ]]; then
    osascript -e "display notification \"FPL $RUN_TYPE run complete — see $(basename "$OUT_FILE")\" with title \"Clanker FC\"" 2>/dev/null || true
  fi
else
  log "FAILED (claude exited non-zero) — see log above; run NOT recorded so it will retry"
  exit 1
fi
