"""Apify ingest for PrizePicks and Underdog Fantasy lines.

Ported from main.py:469-700 of the OpenClaw export. Two actors:
- zen-studio/prizepicks-player-props  (leagues: NBA, MLB, NHL, Soccer)
- zen-studio/underdog-player-props    (leagues: NBA, MLB, NHL, FIFA)

Apify charges per actor run (compute units). NEVER call these on app load.
Always button-triggered, with a per-platform "last refreshed" timestamp.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

try:
    import streamlit as st
    _SECRETS = st.secrets if hasattr(st, "secrets") else {}
except Exception:
    _SECRETS = {}

from . import db

PP_ACTOR = "zen-studio/prizepicks-player-props"
UD_ACTOR = "zen-studio/underdog-player-props"

PP_APIFY_LEAGUES = ["NBA", "MLB", "NHL", "Soccer"]
UD_APIFY_LEAGUES = ["NBA", "MLB", "NHL", "FIFA"]

# PrizePicks `stat` strings → our internal market keys (mirrors main.py:429-451).
PP_STAT_TO_MARKET = {
    "Points": "player_points",
    "Rebounds": "player_rebounds",
    "Assists": "player_assists",
    "3-PT Made": "player_threes",
    "Pts+Rebs+Asts": "player_points_rebounds_assists",
    "Blocked Shots": "player_blocks",
    "Steals": "player_steals",
    "Turnovers": "player_turnovers",
    "Pitcher Strikeouts": "pitcher_strikeouts",
    "Hits": "batter_hits",
    "Total Bases": "batter_total_bases",
    "Home Runs": "batter_home_runs",
    "RBIs": "batter_rbis",
    "Goals": "player_goals",
    "Shots On Goal": "player_shots_on_goal",
    "Shots": "player_shots",
    "Shots On Target": "player_shots_on_target",
}

PP_LEAGUE_TO_SPORT = {"NBA": "NBA", "MLB": "MLB", "NHL": "NHL", "SOCCER": "SOCCER"}

# Underdog uses a slightly different schema. Same target market keys.
UD_STAT_TO_MARKET = dict(PP_STAT_TO_MARKET)  # Apify normalizes most labels; extend here if needed
UD_LEAGUE_TO_SPORT = {"NBA": "NBA", "MLB": "MLB", "NHL": "NHL", "FIFA": "SOCCER"}


def _token() -> str:
    tok = _SECRETS.get("APIFY_API_TOKEN") or os.environ.get("APIFY_API_TOKEN")
    if not tok:
        raise RuntimeError("APIFY_API_TOKEN not configured")
    return tok


def _run_actor(actor: str, leagues: list[str]) -> list[dict]:
    """Trigger an Apify actor, block until done, return dataset items."""
    from apify_client import ApifyClient

    client = ApifyClient(token=_token())
    run = client.actor(actor).call(run_input={"leagues": leagues})
    if not run or run.get("status") != "SUCCEEDED":
        status = run.get("status") if run else "unknown"
        raise RuntimeError(f"Apify actor finished with status={status}")
    dataset_id = run.get("defaultDatasetId")
    if not dataset_id:
        raise RuntimeError("Apify run missing defaultDatasetId")
    return list(client.dataset(dataset_id).iterate_items())


# ----------------------------------------------------------------------------
# Parsers — translate Apify items → dfs_lines rows
# ----------------------------------------------------------------------------

def _parse_pp_items(items: list[dict]) -> tuple[list[dict], dict]:
    counters = {
        "total_items": len(items),
        "lines_added": 0,
        "skipped_live": 0,
        "skipped_promo": 0,
        "skipped_combo": 0,
        "skipped_non_single_stat": 0,
        "skipped_unknown_stat": 0,
        "skipped_unknown_league": 0,
    }
    now_iso = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []

    for it in items:
        if it.get("is_live") or it.get("game_is_live"):
            counters["skipped_live"] += 1
            continue
        if it.get("is_promo"):
            counters["skipped_promo"] += 1
            continue
        if it.get("player_combo"):
            counters["skipped_combo"] += 1
            continue
        if it.get("projection_type") != "Single Stat":
            counters["skipped_non_single_stat"] += 1
            continue

        league = (it.get("league") or "").strip().upper()
        sport = PP_LEAGUE_TO_SPORT.get(league)
        if not sport:
            counters["skipped_unknown_league"] += 1
            continue

        stat = (it.get("stat") or it.get("stat_short") or "").strip()
        market = PP_STAT_TO_MARKET.get(stat)
        if not market:
            counters["skipped_unknown_stat"] += 1
            continue

        player = (it.get("player_name") or "").strip()
        line = it.get("line")
        if not player or line is None:
            continue

        rows.append(
            {
                "platform": "prizepicks",
                "sport": sport,
                "player": player,
                "market": market,
                "line": float(line),
                "odds_tier": (it.get("odds_type") or "standard").lower(),
                "projection_id": str(it.get("projection_id") or it.get("id") or ""),
                "start_time": it.get("start_time"),
                "home_team": it.get("home_team"),
                "away_team": it.get("away_team"),
                "fetched_at": now_iso,
            }
        )
        counters["lines_added"] += 1

    return rows, counters


def _parse_ud_items(items: list[dict]) -> tuple[list[dict], dict]:
    counters = {
        "total_items": len(items),
        "lines_added": 0,
        "skipped_live": 0,
        "skipped_unknown_stat": 0,
        "skipped_unknown_league": 0,
    }
    now_iso = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []

    for it in items:
        if it.get("is_live"):
            counters["skipped_live"] += 1
            continue

        league = (it.get("league") or "").strip().upper()
        sport = UD_LEAGUE_TO_SPORT.get(league)
        if not sport:
            counters["skipped_unknown_league"] += 1
            continue

        stat = (it.get("stat") or "").strip()
        market = UD_STAT_TO_MARKET.get(stat)
        if not market:
            counters["skipped_unknown_stat"] += 1
            continue

        player = (it.get("player_name") or "").strip()
        line = it.get("line")
        if not player or line is None:
            continue

        rows.append(
            {
                "platform": "underdog",
                "sport": sport,
                "player": player,
                "market": market,
                "line": float(line),
                "odds_tier": (it.get("odds_type") or "standard").lower(),
                "projection_id": str(it.get("projection_id") or it.get("id") or ""),
                "start_time": it.get("start_time"),
                "home_team": it.get("home_team"),
                "away_team": it.get("away_team"),
                "fetched_at": now_iso,
            }
        )
        counters["lines_added"] += 1

    return rows, counters


# ----------------------------------------------------------------------------
# Public refresh entrypoints — called by Streamlit buttons
# ----------------------------------------------------------------------------

def refresh_prizepicks() -> dict:
    items = _run_actor(PP_ACTOR, PP_APIFY_LEAGUES)
    rows, counters = _parse_pp_items(items)
    db.replace_platform_dfs_lines("prizepicks", rows)
    db.set_meta("last_pp_refresh", datetime.now(timezone.utc).isoformat())
    return counters


def refresh_underdog() -> dict:
    items = _run_actor(UD_ACTOR, UD_APIFY_LEAGUES)
    rows, counters = _parse_ud_items(items)
    db.replace_platform_dfs_lines("underdog", rows)
    db.set_meta("last_ud_refresh", datetime.now(timezone.utc).isoformat())
    return counters


def ingest_dump(platform: str, items: list[dict]) -> dict:
    """For when you have a JSON dump and want to skip Apify cost.

    Mirrors /api/ingest_pp_dump and /api/ingest_ud_dump from the original app.
    """
    if platform == "prizepicks":
        rows, counters = _parse_pp_items(items)
    elif platform == "underdog":
        rows, counters = _parse_ud_items(items)
    else:
        raise ValueError(f"Unknown platform: {platform}")
    db.replace_platform_dfs_lines(platform, rows)
    db.set_meta(f"last_{'pp' if platform == 'prizepicks' else 'ud'}_refresh",
                datetime.now(timezone.utc).isoformat())
    return counters
