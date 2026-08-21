#!/usr/bin/env python3
"""
Authenticated FPL writes — transfers, captain, lineup.

## Why this exists (and why it isn't email/password)

`bot_manager.py` authenticates by POSTing email+password to
`users.premierleague.com`. **That host no longer resolves** — FPL migrated to
PingFederate/PingOne SSO on `account.premierleague.com`. Verified against the
live OIDC discovery document (`/as/.well-known/openid-configuration`):

    grant_types_supported: authorization_code, implicit, client_credentials,
                           refresh_token, device_code, ciba, token-exchange

There is **no `password` grant**, so credentials can never be exchanged for a
token directly. No amount of repairing the old `login()` recovers this.

`refresh_token` *is* supported, which is the path used here: you extract a
refresh token from a browser you've already logged into (once), and this module
exchanges it for short-lived access tokens. You never store your password, and
this project never sees it — strictly safer than the old approach.

## Getting a refresh token

Log in at fantasy.premierleague.com, then in the browser console:

    JSON.parse(localStorage.getItem(
      Object.keys(localStorage).find(k => k.startsWith('oidc.user:'))
    )).refresh_token

Put it in `.env` as `FPL_REFRESH_TOKEN`. Note that FPL **rotates** the token on
first use, which retires the browser's copy — this module persists each new one
so the chain continues, but if it breaks you re-copy from the browser.

## Safety

Writes are gated by `FPL_BOT_MODE` and default to the safest setting:

    notify  (default) — never writes; returns the intended change for a human
    dry_run           — validates against FPL (transfers use confirmed=false)
                        but never commits
    auto              — actually writes

Nothing here submits an initial 15-player squad: FPL publishes no documented
endpoint for that, and inventing one risks corrupting a real team. Transfers
and lineup/captain endpoints *are* documented and are what this supports.
"""
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

import httpx

TOKEN_URL = "https://account.premierleague.com/as/token"
FPL_API = "https://fantasy.premierleague.com/api"

# Undocumented but stable public client id for FPL's web app. Not a secret —
# it's visible in the site's own OAuth requests. If FPL rotates it, token
# exchange starts failing with invalid_client and this needs updating.
CLIENT_ID = os.getenv("FPL_CLIENT_ID", "bfcbaf69-aade-4c1b-8f00-c1cb8a193030")

# Where a rotated refresh token is persisted. Kept out of .env so a rotation
# doesn't require rewriting a file the user hand-maintains.
TOKEN_CACHE = Path(__file__).parent / "cache" / "fpl_token.json"

VALID_MODES = ("notify", "dry_run", "auto")


class FPLAuthError(RuntimeError):
    """Raised when authentication is impossible or the token is unusable."""


def bot_mode() -> str:
    """Current write mode. Anything unrecognised falls back to the safe default."""
    mode = os.getenv("FPL_BOT_MODE", "notify").strip().lower()
    return mode if mode in VALID_MODES else "notify"


def _load_refresh_token() -> Optional[str]:
    """Prefer a rotated token from cache; fall back to the one in the env."""
    if TOKEN_CACHE.exists():
        try:
            cached = json.loads(TOKEN_CACHE.read_text())
            if cached.get("refresh_token"):
                return cached["refresh_token"]
        except Exception:
            pass  # corrupt cache shouldn't block the env fallback
    return os.getenv("FPL_REFRESH_TOKEN") or None


def _store_refresh_token(refresh_token: str, access_token: str, expires_in: int):
    """
    Persist the rotated refresh token.

    FPL rotates on every exchange — losing the new token means the chain is
    broken and the user has to re-copy from the browser, so this write is
    load-bearing, not an optimisation.
    """
    try:
        TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_CACHE.write_text(json.dumps({
            "refresh_token": refresh_token,
            "access_token": access_token,
            "access_expires_at": time.time() + max(0, expires_in - 60),  # refresh early
        }))
    except Exception as e:
        print(f"⚠️  Could not persist rotated FPL refresh token: {e}")


def get_access_token(force: bool = False) -> str:
    """
    Exchange the refresh token for an access token, reusing a cached one while valid.

    Raises FPLAuthError with an actionable message rather than a bare HTTP error,
    since every failure mode here needs a specific human action.
    """
    if not force and TOKEN_CACHE.exists():
        try:
            cached = json.loads(TOKEN_CACHE.read_text())
            if cached.get("access_token") and cached.get("access_expires_at", 0) > time.time():
                return cached["access_token"]
        except Exception:
            pass

    refresh_token = _load_refresh_token()
    if not refresh_token:
        raise FPLAuthError(
            "No FPL refresh token. FPL no longer supports password login (the old "
            "users.premierleague.com host is gone and the OAuth server exposes no "
            "password grant), so a browser-extracted refresh token is required.\n\n"
            "Log in at fantasy.premierleague.com, then run in the browser console:\n"
            "  JSON.parse(localStorage.getItem(Object.keys(localStorage)"
            ".find(k => k.startsWith('oidc.user:')))).refresh_token\n\n"
            "Set the result as FPL_REFRESH_TOKEN in .env"
        )

    resp = httpx.post(
        TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": refresh_token,
              "client_id": CLIENT_ID},
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": "Mozilla/5.0"},
        timeout=20,
    )

    if resp.status_code != 200:
        detail = resp.text[:200]
        if "invalid_grant" in detail:
            raise FPLAuthError(
                "FPL rejected the refresh token (invalid_grant). Refresh tokens rotate "
                "on use and can be revoked, so this usually means it's stale or was "
                "already spent. Re-copy it from the browser (see fpl_auth docstring)."
            )
        raise FPLAuthError(f"Token exchange failed ({resp.status_code}): {detail}")

    payload = resp.json()
    access_token = payload.get("access_token")
    if not access_token:
        raise FPLAuthError(f"Token response contained no access_token: {payload}")

    _store_refresh_token(
        payload.get("refresh_token", refresh_token),  # keep old if not rotated
        access_token,
        int(payload.get("expires_in", 3600)),
    )
    return access_token


def _auth_headers(access_token: str, referer: str) -> Dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-API-Authorization": f"Bearer {access_token}",
        "Referer": f"https://fantasy.premierleague.com{referer}",
        "User-Agent": "Mozilla/5.0",
    }


def verify_session() -> Dict:
    """
    Confirm the token actually authenticates, via /api/me/.

    Unauthenticated, /api/me/ returns 200 with {"player": null} — so a 200 alone
    proves nothing. The `player` field is the real signal.
    """
    token = get_access_token()
    resp = httpx.get(f"{FPL_API}/me/", headers=_auth_headers(token, "/"), timeout=20)
    if resp.status_code != 200:
        return {"authenticated": False, "status": resp.status_code, "detail": resp.text[:200]}
    data = resp.json()
    player = data.get("player")
    if not player:
        return {"authenticated": False,
                "detail": "Token accepted but no player attached — treat as unauthenticated."}
    return {
        "authenticated": True,
        "entry": player.get("entry"),
        "name": f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
        "email": player.get("email"),
    }


def set_lineup(team_id: int, picks: List[Dict], chip: Optional[str] = None) -> Dict:
    """
    Set lineup order, captain and vice-captain.

    Args:
        team_id: FPL entry id.
        picks: 15 dicts of {element, position (1-15), is_captain, is_vice_captain}.
            Positions 1-11 start, 12-15 are the bench in order.
        chip: optional chip name to play with this lineup.

    Honours FPL's own constraints so a malformed request fails here rather than
    being rejected (or worse, partially applied) upstream.
    """
    if len(picks) != 15:
        return {"ok": False, "error": f"Expected 15 picks, got {len(picks)}"}
    if sum(1 for p in picks if p.get("is_captain")) != 1:
        return {"ok": False, "error": "Exactly one pick must be captain"}
    if sum(1 for p in picks if p.get("is_vice_captain")) != 1:
        return {"ok": False, "error": "Exactly one pick must be vice-captain"}

    mode = bot_mode()
    body = {"chip": chip, "picks": picks}

    if mode == "notify":
        return {"ok": True, "written": False, "mode": mode,
                "message": "notify mode — nothing submitted. Set FPL_BOT_MODE=auto to write.",
                "intended": body}

    token = get_access_token()
    if mode == "dry_run":
        # The lineup endpoint has no validate-only flag, so dry_run verifies
        # auth and payload shape without POSTing. Claiming otherwise would be
        # a lie about what was checked.
        session = verify_session()
        return {"ok": session.get("authenticated", False), "written": False, "mode": mode,
                "message": "dry_run — authenticated and payload validated locally; not submitted.",
                "session": session, "intended": body}

    resp = httpx.post(
        f"{FPL_API}/my-team/{team_id}/",
        headers=_auth_headers(token, "/a/team/my"),
        json=body, timeout=30,
    )
    ok = resp.status_code in (200, 204)
    return {"ok": ok, "written": ok, "mode": mode, "status": resp.status_code,
            "detail": None if ok else resp.text[:300], "intended": body}


def make_transfers(team_id: int, gameweek: int, transfers: List[Dict],
                   wildcard: bool = False, freehit: bool = False) -> Dict:
    """
    Execute transfers.

    Args:
        transfers: dicts of {element_in, element_out, purchase_price, selling_price}.

    FPL wants this posted twice — once with confirmed=false to validate, then
    with confirmed=true to commit — so a rejected transfer never half-applies.
    """
    if not transfers:
        return {"ok": False, "error": "No transfers supplied"}

    mode = bot_mode()
    base = {"entry": team_id, "event": gameweek, "transfers": transfers,
            "wildcard": wildcard, "freehit": freehit}

    if mode == "notify":
        return {"ok": True, "written": False, "mode": mode,
                "message": "notify mode — nothing submitted. Set FPL_BOT_MODE=auto to write.",
                "intended": {**base, "confirmed": True}}

    token = get_access_token()
    headers = _auth_headers(token, "/a/squad/transfers")

    validate = httpx.post(f"{FPL_API}/transfers/", headers=headers,
                          json={**base, "confirmed": False}, timeout=30)
    if validate.status_code not in (200, 204):
        return {"ok": False, "written": False, "mode": mode, "stage": "validate",
                "status": validate.status_code, "detail": validate.text[:300]}

    if mode == "dry_run":
        return {"ok": True, "written": False, "mode": mode,
                "message": "dry_run — FPL accepted the transfer as valid; not committed.",
                "intended": {**base, "confirmed": True}}

    commit = httpx.post(f"{FPL_API}/transfers/", headers=headers,
                        json={**base, "confirmed": True}, timeout=30)
    ok = commit.status_code in (200, 204)
    return {"ok": ok, "written": ok, "mode": mode, "stage": "commit",
            "status": commit.status_code,
            "detail": None if ok else commit.text[:300]}


def auth_status() -> Dict:
    """Non-throwing summary for /api/health and the bot endpoints."""
    mode = bot_mode()
    has_token = bool(_load_refresh_token())
    status = {
        "mode": mode,
        "writes_enabled": mode == "auto",
        "refresh_token_present": has_token,
        "initial_squad_submission": "unsupported — FPL has no documented endpoint",
    }
    if not has_token:
        status["authenticated"] = False
        status["hint"] = "Set FPL_REFRESH_TOKEN in .env (see fpl_auth docstring)"
        return status
    try:
        status.update(verify_session())
    except FPLAuthError as e:
        status["authenticated"] = False
        status["error"] = str(e).split("\n")[0]
    return status
