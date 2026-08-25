#!/usr/bin/env python3
"""
Deadline detection and run scheduling for the autonomous bot.

## What this schedules

Per gameweek, two runs with different jobs:

- **early** — shortly after the previous GW's matches, before that night's price
  changes. Only acts on a transfer whose *timing* is price-sensitive. Sets no
  captain and plays no chip: more team news arrives before the deadline, and
  deciding early throws that information away.
- **final** — `FINAL_RUN_HOURS_BEFORE` (default 2h) before the deadline, once
  press conferences have happened. Transfers, captain, vice, bench order, chip.

Deadlines come from FPL's own `bootstrap-static` events, so there is no hardcoded
calendar to rot. The next deadline is recomputed after every run.

## Render free tier: read this before trusting the schedule

An in-process scheduler **cannot** be made reliable on Render's free tier. The
service is spun down after ~15 minutes idle, and a spun-down process is not
running, so APScheduler is not merely late — it does not exist to fire. A
self-pinger does not fix this: it burns the same free instance hours it is trying
to protect, and Render still reserves the right to spin down.

So this module supports both, and is explicit about which is trustworthy:

  SCHEDULER (in-process)      — fine on a paid/always-on host or a local run.
  EXTERNAL TRIGGER (default)  — `POST /api/bot/run` hit by an outside cron
                                (GitHub Actions, cron-job.org). Survives dozing,
                                because the request itself wakes the service.

`BOT_SCHEDULER_ENABLED` defaults to **false** precisely so that deploying this
does not create the illusion of a bot that is watching the deadline when the
host is asleep. The external trigger is the supported production path; see
`.github/workflows/fpl-bot.yml`.

## Safety

Nothing here writes to FPL by itself. It calls the agent, then hands the result
to `fpl_auth`, which is gated by `FPL_BOT_MODE` (default `notify` = no writes).
Any agent failure downgrades to notify and records the reason — a failed run must
never look like "no changes needed".
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx

logger = logging.getLogger("bot_scheduler")

FPL_BOOTSTRAP = "https://fantasy.premierleague.com/api/bootstrap-static/"

# How long before the deadline the final (real) decision runs.
FINAL_RUN_HOURS_BEFORE = float(os.getenv("FINAL_RUN_HOURS_BEFORE", "2"))
# How long after the previous GW's deadline the early (price-timing) run goes.
# Default 48h ≈ after that GW's matches, before the following night's price moves.
EARLY_RUN_HOURS_AFTER = float(os.getenv("EARLY_RUN_HOURS_AFTER", "48"))

SCHEDULER_ENABLED = os.getenv("BOT_SCHEDULER_ENABLED", "false").strip().lower() in ("1", "true", "yes")

# Run history, so a restart can tell whether this GW was already handled. FPL is
# the source of truth for team state; this only guards against double-running.
STATE_PATH = Path(__file__).parent / "cache" / "bot_runs.json"

# One decision at a time. Two concurrent agent runs could submit conflicting
# lineups, and the second would silently win.
_run_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Deadlines
# ---------------------------------------------------------------------------

async def get_gameweek_schedule() -> Dict[str, Any]:
    """
    Next gameweek id + deadline (UTC), read from FPL's own event list.

    Returns `next_gameweek: None` at season end, when no event has `is_next`.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(FPL_BOOTSTRAP)
        resp.raise_for_status()
        events = resp.json().get("events", [])

    def parse(ts: Optional[str]) -> Optional[datetime]:
        if not ts:
            return None
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))

    current = next((e for e in events if e.get("is_current")), None)
    nxt = next((e for e in events if e.get("is_next")), None)

    # Pre-season: nothing is current and GW1 is next. Fall back to the first
    # unfinished event so the scheduler still works before a season starts.
    if nxt is None:
        nxt = next((e for e in events if not e.get("finished")), None)

    return {
        "current_gameweek": current.get("id") if current else None,
        "next_gameweek": nxt.get("id") if nxt else None,
        "deadline": parse(nxt.get("deadline_time")) if nxt else None,
        "previous_deadline": parse(current.get("deadline_time")) if current else None,
    }


def compute_run_times(deadline: datetime, previous_deadline: Optional[datetime]) -> Dict[str, datetime]:
    """
    When the early and final runs should happen for a deadline.

    The early run is anchored to the PREVIOUS deadline (that is when the last
    GW's matches happen, which is what makes prices move). Without one, it falls
    back to a fixed offset before the next deadline.
    """
    final_at = deadline - timedelta(hours=FINAL_RUN_HOURS_BEFORE)
    if previous_deadline:
        early_at = previous_deadline + timedelta(hours=EARLY_RUN_HOURS_AFTER)
    else:
        early_at = deadline - timedelta(hours=24)

    # Never let the early run land after the final run — on a short turnaround
    # (midweek GWs) the 48h offset can overshoot.
    if early_at >= final_at:
        early_at = final_at - timedelta(hours=1)

    return {"early": early_at, "final": final_at}


# ---------------------------------------------------------------------------
# Run state
# ---------------------------------------------------------------------------

def _load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {"runs": []}
    try:
        return json.loads(STATE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        # Corrupt state must not block a deadline-critical run.
        logger.warning("bot_runs.json unreadable; treating as empty.")
        return {"runs": []}


def _record_run(entry: Dict[str, Any]) -> None:
    state = _load_state()
    state["runs"].append(entry)
    state["runs"] = state["runs"][-60:]  # ~a season of two-run gameweeks
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, default=str))


def already_ran(gameweek: int, run_type: str) -> bool:
    """Whether this (gameweek, run_type) already completed successfully."""
    return any(
        r.get("gameweek") == gameweek
        and r.get("run_type") == run_type
        and r.get("ok")
        for r in _load_state().get("runs", [])
    )


def run_history(limit: int = 20) -> List[Dict[str, Any]]:
    return _load_state().get("runs", [])[-limit:][::-1]


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

async def execute_run(
    run_type: str,
    decide: Callable[..., Any],
    force: bool = False,
    submit: bool = True,
) -> Dict[str, Any]:
    """
    Run one decision for the upcoming gameweek.

    `decide(run_type, submit)` is injected rather than imported so this module
    stays testable without FastAPI or the Anthropic API — and so the caller owns
    which tool set the agent gets.

    Returns a result dict either way; never raises for an agent failure, because
    a scheduled job that raises just vanishes into a log. Failures are recorded
    with `ok: False` and a reason.
    """
    schedule = await get_gameweek_schedule()
    gw = schedule.get("next_gameweek")

    if gw is None:
        return {"ok": False, "skipped": "No next gameweek — season over or FPL data unavailable."}

    if not force and already_ran(gw, run_type):
        return {"ok": True, "skipped": f"GW{gw} {run_type} run already completed.", "gameweek": gw}

    if _run_lock.locked():
        return {"ok": False, "skipped": "Another decision run is in progress."}

    async with _run_lock:
        started = datetime.now(timezone.utc)
        try:
            result = await decide(run_type=run_type, submit=submit)
            ok = True
            error = None
        except Exception as e:
            # Includes BotAgentError. Downgrade to notify: record it loudly and
            # let a human see it, rather than proceeding on a broken decision.
            logger.error("GW%s %s run failed: %s", gw, run_type, e)
            result = None
            ok = False
            error = str(e)

        entry = {
            "gameweek": gw,
            "run_type": run_type,
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "ok": ok,
            "error": error,
            "deadline": schedule["deadline"].isoformat() if schedule.get("deadline") else None,
        }
        if ok and isinstance(result, dict):
            decision = result.get("decision", {})
            entry["confidence"] = decision.get("confidence")
            entry["captain"] = decision.get("captain_name")
            entry["transfers"] = len(decision.get("transfers") or [])
            entry["submitted"] = result.get("submitted", False)
        _record_run(entry)

        return {"ok": ok, "gameweek": gw, "run_type": run_type,
                "error": error, "result": result, "summary": entry}


# ---------------------------------------------------------------------------
# In-process scheduler (paid/always-on hosts only — see module docstring)
# ---------------------------------------------------------------------------

class BotScheduler:
    """
    APScheduler wrapper that reschedules itself each gameweek.

    Rather than registering 38 gameweeks up front (which rots the moment FPL
    moves a fixture), it holds one job per run type for the *next* deadline and
    recomputes after each run.
    """

    def __init__(self, decide: Callable[..., Any]):
        self._decide = decide
        self._scheduler = None

    async def start(self) -> Dict[str, Any]:
        if not SCHEDULER_ENABLED:
            return {"started": False,
                    "reason": "BOT_SCHEDULER_ENABLED is false. Use the external "
                              "trigger (POST /api/bot/run) — see bot_scheduler docstring."}
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
        except ImportError:
            return {"started": False, "reason": "apscheduler not installed."}

        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._scheduler.start()
        planned = await self.reschedule()
        return {"started": True, **planned}

    async def reschedule(self) -> Dict[str, Any]:
        """Point the jobs at the next deadline. Safe to call repeatedly."""
        if self._scheduler is None:
            return {"scheduled": False, "reason": "Scheduler not started."}

        schedule = await get_gameweek_schedule()
        deadline, gw = schedule.get("deadline"), schedule.get("next_gameweek")
        if not deadline or gw is None:
            return {"scheduled": False, "reason": "No upcoming deadline found."}

        times = compute_run_times(deadline, schedule.get("previous_deadline"))
        now = datetime.now(timezone.utc)
        scheduled = {}

        for run_type, when in times.items():
            job_id = f"bot_{run_type}"
            if self._scheduler.get_job(job_id):
                self._scheduler.remove_job(job_id)
            if when <= now:
                # Already past — don't fire a stale run on startup. The final run
                # is the one worth flagging, since missing it means missing the GW.
                scheduled[run_type] = f"skipped (was due {when.isoformat()})"
                continue
            self._scheduler.add_job(
                self._run_and_reschedule, "date", run_date=when,
                args=[run_type], id=job_id, replace_existing=True,
            )
            scheduled[run_type] = when.isoformat()

        logger.info("GW%s runs scheduled: %s", gw, scheduled)
        return {"scheduled": True, "gameweek": gw,
                "deadline": deadline.isoformat(), "runs": scheduled}

    async def _run_and_reschedule(self, run_type: str) -> None:
        await execute_run(run_type, self._decide)
        if run_type == "final":
            # The final run closes this gameweek out; point at the next one.
            # FPL flips is_next only after the deadline, so wait it out.
            await asyncio.sleep(int(os.getenv("RESCHEDULE_DELAY_SECONDS", "3600")))
            await self.reschedule()

    def shutdown(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

    def status(self) -> Dict[str, Any]:
        if self._scheduler is None:
            return {"running": False, "enabled": SCHEDULER_ENABLED}
        return {
            "running": True,
            "enabled": SCHEDULER_ENABLED,
            "jobs": [
                {"id": j.id, "next_run": j.next_run_time.isoformat() if j.next_run_time else None}
                for j in self._scheduler.get_jobs()
            ],
        }


async def due_runs(grace_minutes: int = 90) -> List[str]:
    """
    Which run types are due right now — for an EXTERNAL cron that wakes the
    service periodically and asks "is there anything to do?".

    `grace_minutes` is the window after a scheduled time in which a run still
    counts as due, so a cron that fires every 30-60 minutes cannot step over a
    deadline. The final run additionally stays due right up to the deadline
    itself: late is better than never.
    """
    schedule = await get_gameweek_schedule()
    deadline, gw = schedule.get("deadline"), schedule.get("next_gameweek")
    if not deadline or gw is None:
        return []

    now = datetime.now(timezone.utc)
    if now >= deadline:
        return []

    times = compute_run_times(deadline, schedule.get("previous_deadline"))
    due: List[str] = []
    for run_type, when in times.items():
        if already_ran(gw, run_type):
            continue
        if run_type == "final":
            if when <= now < deadline:
                due.append(run_type)
        elif when <= now <= when + timedelta(minutes=grace_minutes):
            due.append(run_type)
    return due


if __name__ == "__main__":
    async def main():
        schedule = await get_gameweek_schedule()
        print("FPL schedule:")
        for k, v in schedule.items():
            print(f"  {k}: {v}")
        if schedule.get("deadline"):
            times = compute_run_times(schedule["deadline"], schedule.get("previous_deadline"))
            now = datetime.now(timezone.utc)
            print("\nPlanned runs:")
            for rt, when in times.items():
                delta = (when - now).total_seconds() / 3600
                print(f"  {rt:6s} {when.isoformat()}  ({delta:+.1f}h from now)")
            print(f"\nDue now: {await due_runs() or 'nothing'}")
        print(f"\nIn-process scheduler enabled: {SCHEDULER_ENABLED}")

    asyncio.run(main())
