"""Apify ingest for PrizePicks and Underdog Fantasy lines.

Two actors:
- zen-studio/prizepicks-player-props
    Input  : {"leagues": ["NBA", "MLB", "NHL", "Soccer"]}
    Output : items keyed by `stat`, `player_name`, `line`, `league`
- brilliant_gum/sports-props-aggregator
    Input  : {"platforms": ["underdog"], "sports": [...], "onlyLiveGames": false,
              "includeInjuredPlayers": false}
    Output : items keyed by `propType`, `playerName`, `line`, `sport`

Apify charges per actor run. NEVER call these on app load — button-triggered
only, with a per-platform "last refreshed" timestamp visible to the user.
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

# ============================================================================
# Actor IDs and input shapes
# ============================================================================

PP_ACTOR = "zen-studio/prizepicks-player-props"
PP_APIFY_LEAGUES = ["NBA", "MLB", "NHL", "Soccer"]

UD_ACTOR = "brilliant_gum/sports-props-aggregator"
UD_APIFY_SPORTS = ["NBA", "MLB", "SOCCER"]

# ============================================================================
# PrizePicks mappings (actor returns `stat` strings)
# ============================================================================

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

# ============================================================================
# Underdog mappings — handles BOTH propType formats this actor emits.
# Same actor returns "player_points" on some rows and "points" on others;
# normalize both to our internal market keys before storage.
# Markets without a sportsbook-prop equivalent (e.g. fantasy_points, 1q_*,
# first_fg_attempt) are mapped to None and skipped — no consensus to compare.
# ============================================================================

UD_PROPTYPE_TO_MARKET: dict[str, str | None] = {
    # ----- already in our format -----
    "player_points":     "player_points",
    "player_rebounds":   "player_rebounds",
    "player_assists":    "player_assists",
    "player_threes":     "player_threes",
    "player_blocks":     "player_blocks",
    "player_steals":     "player_steals",
    "player_turnovers":  "player_turnovers",

    # ----- short-form NBA variants the actor also emits -----
    "points":            "player_points",
    "rebounds":          "player_rebounds",
    "assists":           "player_assists",
    "threes_made":       "player_threes",
    "pts_rebs_asts":     "player_points_rebounds_assists",

    # ----- variants WITHOUT a sportsbook prop equivalent (skip) -----
    "points_rebounds":   None,
    "points_assists":    None,
    "rebounds_assists":  None,
    "fg_attempted":      None,
    "3s_attempted":      None,
    "ft_made":           None,
    "fantasy_points":    None,
    "first_fg_attempt":  None,
    "1q_points":         None,
    "1q_3pointers_made": None,
    "double_double":     None,
    "triple_double":     None,

    # ----- MLB short-form -----
    "strikeouts":        "pitcher_strikeouts",
    "hits":              "batter_hits",
    "total_bases":       "batter_total_bases",
    "home_runs":         "batter_home_runs",
    "rbis":              "batter_rbis",
    # ----- NHL short-form -----
    "goals":             "player_goals",
    "shots_on_goal":     "player_shots_on_goal",
    # ----- Soccer short-form -----
    "shots":             "player_shots",
    "shots_on_target":   "player_shots_on_target",
}

UD_SPORT_MAP = {"NBA": "NBA", "MLB": "MLB", "NHL": "NHL", "SOCCER": "SOCCER", "FIFA": "SOCCER"}


# ============================================================================
# Apify client helpers
# ============================================================================

def _token() -> str:
    tok = _SECRETS.get("APIFY_API_TOKEN") or os.environ.get("APIFY_API_TOKEN")
    if not tok:
        raise RuntimeError("APIFY_API_TOKEN not configured")
    return tok


def _run_actor(actor: str, run_input: dict) -> list[dict]:
    """Trigger an Apify actor with a custom input dict, return dataset items."""
    from apify_client import ApifyClient

    client = ApifyClient(token=_token())
    run = client.actor(actor).call(run_input=run_input)
    if not run or run.get("status") != "SUCCEEDED":
        status = run.get("status") if run else "unknown"
        raise RuntimeError(f"Apify actor finished with status={status}")
    dataset_id = run.get("defaultDatasetId")
    if not dataset_id:
        raise RuntimeError("Apify run missing defaultDatasetId")
    return list(client.dataset(dataset_id).iterate_items())


# ============================================================================
# PrizePicks parser (unchanged from original)
# ============================================================================

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

        rows.append({
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
        })
        counters["lines_added"] += 1

    # Defensive dedupe on the DB unique key. Last occurrence wins.
    seen: dict[tuple, dict] = {}
    for r in rows:
        key = (r["platform"], r["sport"], r["player"], r["market"], r["line"], r["odds_tier"])
        seen[key] = r
    deduped = list(seen.values())
    counters["deduplicated"] = len(rows) - len(deduped)
    counters["lines_added"] = len(deduped)

    return deduped, counters


# ============================================================================
# Underdog parser — new actor's schema (brilliant_gum/sports-props-aggregator)
# ============================================================================

def _parse_ud_items(items: list[dict]) -> tuple[list[dict], dict]:
    counters = {
        "total_items": len(items),
        "lines_added": 0,
        "skipped_live": 0,
        "skipped_no_sportsbook_equivalent": 0,  # propType has no sharp consensus to compare
        "skipped_unknown_proptype": 0,
        "skipped_unknown_sport": 0,
    }
    now_iso = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []

    for it in items:
        if it.get("isLive"):
            counters["skipped_live"] += 1
            continue

        sport_raw = (it.get("sport") or "").strip().upper()
        sport = UD_SPORT_MAP.get(sport_raw)
        if not sport:
            counters["skipped_unknown_sport"] += 1
            continue

        prop_type = (it.get("propType") or "").strip()
        if prop_type not in UD_PROPTYPE_TO_MARKET:
            counters["skipped_unknown_proptype"] += 1
            continue
        market = UD_PROPTYPE_TO_MARKET[prop_type]
        if market is None:
            counters["skipped_no_sportsbook_equivalent"] += 1
            continue

        player = (it.get("playerName") or "").strip()
        line = it.get("line")
        if not player or line is None:
            continue

        # Resolve home/away from `team` + `gameVenue` ("home" or "away" relative
        # to the player's own team).
        team = (it.get("team") or "").strip()
        opp = (it.get("opponent") or "").strip()
        venue = (it.get("gameVenue") or "").strip().lower()
        if venue == "home":
            home_team, away_team = team, opp
        else:  # "away" or unknown — default to player team being away
            home_team, away_team = opp, team

        rows.append({
            "platform": "underdog",
            "sport": sport,
            "player": player,
            "market": market,
            "line": float(line),
            "odds_tier": "standard",   # this actor doesn't tier; treat all as standard
            "projection_id": str(it.get("appearanceId") or ""),
            "start_time": it.get("gameTime"),
            "home_team": home_team,
            "away_team": away_team,
            "fetched_at": now_iso,
        })
        counters["lines_added"] += 1

    # Deduplicate by the same key the DB has a unique constraint on:
    # (platform, sport, player, market, line, odds_tier).
    # This actor emits the same prop more than once (over-row + under-row);
    # we keep the LAST occurrence so the most recent scrape wins.
    seen: dict[tuple, dict] = {}
    for r in rows:
        key = (r["platform"], r["sport"], r["player"], r["market"], r["line"], r["odds_tier"])
        seen[key] = r
    deduped = list(seen.values())
    counters["deduplicated"] = len(rows) - len(deduped)
    counters["lines_added"] = len(deduped)

    return deduped, counters


# ============================================================================
# Public refresh entrypoints — called by Streamlit buttons
# ============================================================================

def refresh_prizepicks() -> dict:
    items = _run_actor(PP_ACTOR, {"leagues": PP_APIFY_LEAGUES})
    rows, counters = _parse_pp_items(items)
    db.replace_platform_dfs_lines("prizepicks", rows)
    db.set_meta("last_pp_refresh", datetime.now(timezone.utc).isoformat())
    return counters


def refresh_underdog() -> dict:
    items = _run_actor(UD_ACTOR, {
        "platforms": ["underdog"],
        "sports": UD_APIFY_SPORTS,
        "onlyLiveGames": False,
        "includeInjuredPlayers": False,
    })
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
    db.set_meta(
        f"last_{'pp' if platform == 'prizepicks' else 'ud'}_refresh",
        datetime.now(timezone.utc).isoformat(),
    )
    return counters
