"""Supabase Postgres client wrapper.

Replaces the local SQLite (`odds_engine.db`) used in the original OpenClaw
FastAPI app. The math layer (`src/ev.py`) consumes pandas DataFrames, so this
module's job is just to read/write rows.

All credentials come from Streamlit secrets (or env vars locally).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from supabase import Client, create_client

try:
    import streamlit as st  # only available in app context
    _SECRETS = st.secrets if hasattr(st, "secrets") else {}
except Exception:
    _SECRETS = {}


def _cfg(name: str) -> str:
    """Read a secret from Streamlit secrets first, then env, then raise."""
    val = _SECRETS.get(name) or os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Missing config: {name}. Set it in .streamlit/secrets.toml or as an env var."
        )
    return val


_client: Client | None = None


def db() -> Client:
    """Singleton Supabase client. Service-role key is required for writes."""
    global _client
    if _client is None:
        _client = create_client(
            _cfg("SUPABASE_URL"),
            _cfg("SUPABASE_SERVICE_KEY"),
        )
    return _client


# ----------------------------------------------------------------------------
# Match / odds writers
# ----------------------------------------------------------------------------

def upsert_match(match: dict) -> None:
    db().table("matches").upsert(match, on_conflict="id").execute()


def replace_event_odds(event_id: str, markets: list[str], rows: list[dict]) -> None:
    """Wipe stale odds for these markets, then insert the fresh ones.

    Mirrors the original `DELETE ... WHERE event_id=? AND market IN (...)`
    followed by `INSERT` loop in main.py:362-398.
    """
    if not markets:
        return
    db().table("odds").delete().eq("event_id", event_id).in_("market", markets).execute()
    if rows:
        db().table("odds").insert(rows).execute()


def replace_platform_dfs_lines(platform: str, rows: list[dict]) -> None:
    """Wipe all PP/UD rows then re-insert. Matches main.py:510."""
    db().table("dfs_lines").delete().eq("platform", platform).execute()
    if rows:
        # Supabase has a payload limit; chunk if large.
        chunk = 500
        for i in range(0, len(rows), chunk):
            db().table("dfs_lines").insert(rows[i : i + chunk]).execute()


def set_meta(key: str, value: str) -> None:
    db().table("meta").upsert(
        {"key": key, "value": value, "updated_at": datetime.now(timezone.utc).isoformat()},
        on_conflict="key",
    ).execute()


def get_meta(key: str) -> str | None:
    res = db().table("meta").select("value").eq("key", key).execute()
    return res.data[0]["value"] if res.data else None


# ----------------------------------------------------------------------------
# Readers — return DataFrames so EV layer can stay vectorized
# ----------------------------------------------------------------------------

def load_matches(sport: str | None = None) -> pd.DataFrame:
    q = db().table("matches").select("*")
    if sport:
        q = q.eq("sport", sport)
    return pd.DataFrame(q.execute().data)


def load_latest_odds(sport: str | None = None) -> pd.DataFrame:
    """Pull from v_latest_odds view, optionally filtered by sport (via matches join)."""
    # supabase-py doesn't support joins; do it client-side.
    odds_df = pd.DataFrame(db().table("v_latest_odds").select("*").execute().data)
    if sport and not odds_df.empty:
        matches_df = load_matches(sport=sport)
        if matches_df.empty:
            return odds_df.iloc[0:0]  # empty with right columns
        odds_df = odds_df[odds_df["event_id"].isin(matches_df["id"])]
    return odds_df


def load_dfs_lines(platform: str | None = None, sport: str | None = None) -> pd.DataFrame:
    q = db().table("dfs_lines").select("*")
    if platform:
        q = q.eq("platform", platform)
    if sport:
        q = q.eq("sport", sport)
    return pd.DataFrame(q.execute().data)


# ----------------------------------------------------------------------------
# Slip ledger + LLM analysis history
# ----------------------------------------------------------------------------

def insert_slip(slip: dict) -> int:
    """Insert a placed slip; returns the new row's id."""
    res = db().table("slips").insert(slip).execute()
    return res.data[0]["id"]


def update_slip_result(slip_id: int, result: str, net: float) -> None:
    db().table("slips").update(
        {
            "result": result,
            "net": net,
            "settled_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", slip_id).execute()


def load_slips(status: str | None = None) -> pd.DataFrame:
    q = db().table("slips").select("*").order("placed_at", desc=True)
    if status:
        q = q.eq("result", status)
    return pd.DataFrame(q.execute().data)


def log_analysis(payload: dict) -> int:
    res = db().table("analyses").insert(payload).execute()
    return res.data[0]["id"]


def load_recent_analyses(limit: int = 25) -> pd.DataFrame:
    res = (
        db()
        .table("analyses")
        .select("id, created_at, sport, model, response")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return pd.DataFrame(res.data)
