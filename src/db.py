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


def delete_stale_matches(sport: str, cutoff_iso: str) -> int:
    """Delete matches whose commence_time is older than cutoff.

    Returns count of deleted rows. The `odds` table has ON DELETE CASCADE
    on its FK to matches.id, so removing a match also removes its odds.
    Called at the start of refresh_sport() so finished games don't linger
    in the dashboard.
    """
    res = (
        db()
        .table("matches")
        .delete()
        .eq("sport", sport)
        .lt("commence_time", cutoff_iso)
        .execute()
    )
    return len(res.data) if res.data else 0


def delete_stale_dfs_lines(sport: str, cutoff_iso: str) -> int:
    """Delete PP/UD lines whose start_time is older than cutoff.

    DFS line tables (`dfs_lines`) don't cascade off matches because PP/UD
    have their own game records — same player×market on the same night,
    but a separate row keyed by `appearanceId` or `projection_id`. Stale
    PP/UD lines accumulate if the user hasn't clicked PrizePicks/Underdog
    in a while, so we sweep them whenever they refresh sportsbook odds.

    NOTE: this filters by sport, so it only cleans the sport currently
    being refreshed. Other sports stay untouched.
    """
    res = (
        db()
        .table("dfs_lines")
        .delete()
        .eq("sport", sport)
        .lt("start_time", cutoff_iso)
        .execute()
    )
    return len(res.data) if res.data else 0


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
    """Pull latest odds per (event, market, player, line, side, book).

    Originally used the `v_latest_odds` PostgreSQL view, but PostgREST has a
    `db-max-rows` cap (1000 by default on Supabase free tier) that applies to
    VIEWS even with `.range()` pagination — so the view could only ever return
    1000 rows total. Symptoms: dashboard shows 0 props cached even though the
    underlying tables have thousands of rows.

    Fix: query the raw `odds` table (regular table, not a view, so pagination
    works correctly), then dedupe in pandas. Same end result, no quirks.
    """
    odds_df = pd.DataFrame(_fetch_all("odds"))
    if odds_df.empty:
        return odds_df

    # Replicate v_latest_odds: keep latest fetched_at per (event, market, player, line, side, book)
    odds_df = (
        odds_df
        .sort_values("fetched_at")
        .drop_duplicates(
            subset=["event_id", "market", "player", "line", "side", "book"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    if sport:
        matches_df = load_matches(sport=sport)
        if matches_df.empty:
            return odds_df.iloc[0:0]
        odds_df = odds_df[odds_df["event_id"].isin(matches_df["id"])]

    return odds_df


def _fetch_all(table: str, eq_filters: dict | None = None, page_size: int = 1000) -> list[dict]:
    """Paginate through a Supabase table to bypass the default 1000-row limit.

    The supabase-py client returns at most 1000 rows per request. For tables
    with thousands of rows (dfs_lines can hit 5000+ with both PP and UD loaded),
    a single .select() silently truncates. This loops with range() until
    fewer rows come back than the page size.
    """
    out: list[dict] = []
    offset = 0
    while True:
        q = db().table(table).select("*")
        for k, v in (eq_filters or {}).items():
            q = q.eq(k, v)
        # Supabase range is inclusive on both ends.
        q = q.range(offset, offset + page_size - 1)
        chunk = q.execute().data or []
        out.extend(chunk)
        if len(chunk) < page_size:
            break
        offset += page_size
        # Safety: cap at 50K rows. Anything more means something's wrong.
        if offset > 50_000:
            break
    return out


def load_dfs_lines(platform: str | None = None, sport: str | None = None) -> pd.DataFrame:
    filters = {}
    if platform:
        filters["platform"] = platform
    if sport:
        filters["sport"] = sport
    return pd.DataFrame(_fetch_all("dfs_lines", filters))


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
