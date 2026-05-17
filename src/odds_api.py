"""The Odds API fetcher. Port of main.py:169-417.

Cost model (CRITICAL): 1 credit per (event × market) pair on /odds calls.
500 credits/month on free tier. Never call from a page-render path; always
button-triggered with a clear "last refreshed" indicator visible to the user.

Sports and prop markets are kept identical to the original OpenClaw config
(main.py:47-92) so PrizePicks / Underdog ingest pipelines stay aligned.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

try:
    import streamlit as st
    _SECRETS = st.secrets if hasattr(st, "secrets") else {}
except Exception:
    _SECRETS = {}

from . import db

ODDS_API_BASE = "https://api.the-odds-api.com/v4"

SPORTS: dict[str, dict] = {
    "NBA": {
        "keys": ["basketball_nba"],
        "prop_markets": [
            "player_points",
            "player_rebounds",
            "player_assists",
            "player_threes",
            "player_points_rebounds_assists",
            "player_blocks",
            "player_steals",
            "player_turnovers",
        ],
    },
    "MLB": {
        "keys": ["baseball_mlb"],
        "prop_markets": [
            "pitcher_strikeouts",
            "batter_hits",
            "batter_total_bases",
            "batter_home_runs",
            "batter_rbis",
        ],
    },
    "NHL": {
        "keys": ["icehockey_nhl"],
        "prop_markets": [
            "player_points",
            "player_goals",
            "player_assists",
            "player_shots_on_goal",
        ],
    },
    "SOCCER": {
        "keys": [
            "soccer_epl",
            "soccer_spain_la_liga",
            "soccer_germany_bundesliga",
        ],
        "prop_markets": [
            "player_shots_on_target",
            "player_shots",
            "player_assists",
        ],
    },
}


def _api_key() -> str:
    key = _SECRETS.get("THE_ODDS_API_KEY") or os.environ.get("THE_ODDS_API_KEY")
    if not key:
        raise RuntimeError("THE_ODDS_API_KEY not configured")
    return key


def fetch_events(sport_key: str) -> tuple[list[dict], str | None]:
    r = requests.get(
        f"{ODDS_API_BASE}/sports/{sport_key}/events",
        params={"apiKey": _api_key()},
        timeout=30,
    )
    r.raise_for_status()
    return r.json(), r.headers.get("x-requests-remaining")


def fetch_event_odds(
    sport_key: str, event_id: str, markets_csv: str
) -> tuple[dict, str | None]:
    r = requests.get(
        f"{ODDS_API_BASE}/sports/{sport_key}/events/{event_id}/odds",
        params={
            "apiKey": _api_key(),
            "regions": "us",
            "markets": markets_csv,
            "oddsFormat": "american",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json(), r.headers.get("x-requests-remaining")


def american_to_decimal(odds: int) -> float:
    return 1 + (odds / 100 if odds > 0 else 100 / (-odds))


def refresh_sport(sport_label: str, max_events: int = 3) -> dict:
    """Refresh events + per-event prop odds for one sport.

    Default max_events=3 mirrors the original cost guardrail. Each event × market
    pair costs 1 credit, so NBA with 8 prop markets × 3 events = 24 credits per
    refresh. With 500 credits/month, that's ~20 NBA refreshes/month — budget
    accordingly.
    """
    cfg = SPORTS[sport_label]
    keys = cfg["keys"]
    markets = cfg["prop_markets"]
    markets_csv = ",".join(markets)
    markets_set = set(markets)
    now_iso = datetime.now(timezone.utc).isoformat()
    cutoff = datetime.now(timezone.utc) + timedelta(hours=48)

    games_added, props_added, errors = 0, 0, []
    quota: str | None = None

    for sport_key in keys:
        try:
            events, quota = fetch_events(sport_key)
        except requests.HTTPError as e:
            errors.append(f"{sport_key} events: HTTP {e.response.status_code}")
            continue

        chosen = [
            e
            for e in events
            if datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")) <= cutoff
        ][:max_events]

        for ev in chosen:
            db.upsert_match(
                {
                    "id": ev["id"],
                    "sport": sport_label,
                    "sport_key": sport_key,
                    "home_team": ev["home_team"],
                    "away_team": ev["away_team"],
                    "commence_time": ev["commence_time"],
                    "fetched_at": now_iso,
                }
            )
            games_added += 1

            try:
                odds_data, quota = fetch_event_odds(sport_key, ev["id"], markets_csv)
            except requests.HTTPError as e:
                errors.append(f"{ev['id']}: {e}")
                continue

            new_rows: list[dict] = []
            for bm in odds_data.get("bookmakers", []):
                book = bm["title"]
                for mkt in bm.get("markets", []):
                    if mkt["key"] not in markets_set:
                        continue
                    for o in mkt.get("outcomes", []):
                        player = o.get("description") or o.get("participant") or "unknown"
                        line = o.get("point")
                        side = o.get("name")
                        price = o.get("price")
                        if line is None or price is None or side is None:
                            continue
                        price_int = int(price)
                        new_rows.append(
                            {
                                "event_id": ev["id"],
                                "market": mkt["key"],
                                "player": player,
                                "line": float(line),
                                "side": side,
                                "book": book,
                                "price_american": price_int,
                                "price_decimal": american_to_decimal(price_int),
                                "fetched_at": now_iso,
                            }
                        )
                        props_added += 1

            db.replace_event_odds(ev["id"], list(markets_set), new_rows)

    db.set_meta(f"last_refresh_{sport_label}", now_iso)
    if quota is not None:
        db.set_meta("quota_remaining", str(quota))

    return {
        "sport": sport_label,
        "leagues_fetched": keys,
        "games": games_added,
        "props_added": props_added,
        "quota_remaining": quota,
        "errors": errors,
    }
