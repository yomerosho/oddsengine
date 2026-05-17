"""Expected value computation.

Ported from build_dashboard() in main.py:~700-950. The original was tightly
coupled to FastAPI + SQLite cursors; here it's a pure function over pandas
DataFrames so it's testable and easy to call from Streamlit.

The math (unchanged from the original):
  1. Group cached sportsbook odds by (event, market, player, line).
  2. For each book that posts both an Over and an Under at that (line),
     compute no-vig fair probabilities: io / (io + iu) for Over, etc.
  3. Average those no-vig probabilities across all books with a both-sides
     pair → consensus fair probability.
  4. Find the BEST decimal price for Over and Under across all books.
  5. EV at best price = consensus_p * (best_decimal - 1) - (1 - consensus_p).
  6. Flag value bets at EV >= 4% (matches USER.md per-leg edge rule).

DFS anchors:
  For every PrizePicks/Underdog line in dfs_lines, find the closest sportsbook
  line (player + market match) and attach its consensus probability so the LLM
  can recommend Over/Under on the DFS platform.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

VALUE_BET_EDGE_PCT = 4.0  # USER.md per-leg edge floor


def build_dashboard(
    matches: pd.DataFrame,
    odds: pd.DataFrame,
    pp_lines: pd.DataFrame,
    ud_lines: pd.DataFrame,
    meta: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return the same dict shape the FastAPI /api/dashboard returned.

    Output:
      {
        "meta": {...},
        "props": [...],         # all (player, line) props with EV
        "pp_anchors": [...],    # PrizePicks lines joined to sportsbook consensus
        "ud_anchors": [...],    # Underdog lines joined to sportsbook consensus
      }
    """
    meta = meta or {}
    if odds.empty or matches.empty:
        return {
            "meta": _empty_meta(matches, meta),
            "props": [],
            "pp_anchors": [],
            "ud_anchors": [],
        }

    # Coerce types we'll rely on.
    odds = odds.copy()
    odds["line"] = odds["line"].astype(float)
    odds["price_decimal"] = odds["price_decimal"].astype(float)

    # Index matches by id for cheap lookup.
    matches_by_id = matches.set_index("id").to_dict("index")

    props: list[dict] = []

    # Group by (event, market, player, line) — each group is one prop.
    grouping = odds.groupby(["event_id", "market", "player", "line"], sort=False)
    for (event_id, market, player, line), grp in grouping:
        match = matches_by_id.get(event_id)
        if match is None:
            continue

        # Build book → {over, under} dict.
        book_pairs: dict[str, dict[str, dict]] = {}
        for _, row in grp.iterrows():
            book = row["book"]
            side = row["side"]
            if side not in ("Over", "Under"):
                continue
            book_pairs.setdefault(book, {})[side.lower()] = {
                "decimal": float(row["price_decimal"]),
                "american": int(row["price_american"]),
            }

        # No-vig per book → consensus across books.
        no_vig_overs: list[float] = []
        no_vig_unders: list[float] = []
        for book, pair in book_pairs.items():
            if "over" not in pair or "under" not in pair:
                continue
            io = 1 / pair["over"]["decimal"]
            iu = 1 / pair["under"]["decimal"]
            tot = io + iu
            no_vig_overs.append(io / tot)
            no_vig_unders.append(iu / tot)

        if not no_vig_overs:
            continue

        consensus_p_over = sum(no_vig_overs) / len(no_vig_overs)
        consensus_p_under = 1 - consensus_p_over

        all_overs = [
            {"book": b, **p["over"]} for b, p in book_pairs.items() if "over" in p
        ]
        all_unders = [
            {"book": b, **p["under"]} for b, p in book_pairs.items() if "under" in p
        ]
        best_over = max(all_overs, key=lambda x: x["decimal"])
        best_under = max(all_unders, key=lambda x: x["decimal"])

        ev_over = consensus_p_over * (best_over["decimal"] - 1) - (1 - consensus_p_over)
        ev_under = consensus_p_under * (best_under["decimal"] - 1) - (1 - consensus_p_under)

        props.append(
            {
                "sport": match["sport"],
                "event_id": event_id,
                "game": f"{match['away_team']} @ {match['home_team']}",
                "home_team": match["home_team"],
                "away_team": match["away_team"],
                "commence_time": str(match["commence_time"]),
                "player": player,
                "market": market,
                "line": float(line),
                "best_over": {
                    "american": best_over["american"],
                    "decimal": round(best_over["decimal"], 3),
                    "book": best_over["book"],
                },
                "best_under": {
                    "american": best_under["american"],
                    "decimal": round(best_under["decimal"], 3),
                    "book": best_under["book"],
                },
                "consensus_p_over": round(consensus_p_over, 4),
                "consensus_p_under": round(consensus_p_under, 4),
                "ev_over_pct": round(ev_over * 100, 2),
                "ev_under_pct": round(ev_under * 100, 2),
                "books_count": len(book_pairs),
            }
        )

    props.sort(key=lambda p: -max(p["ev_over_pct"], p["ev_under_pct"]))

    # DFS anchors: join PP/UD lines to the sportsbook prop with the closest line.
    props_by_pm: dict[tuple[str, str], list[dict]] = {}
    for p in props:
        props_by_pm.setdefault((p["player"].lower(), p["market"]), []).append(p)

    pp_anchors = _build_dfs_anchors(pp_lines, props_by_pm, "prizepicks")
    ud_anchors = _build_dfs_anchors(ud_lines, props_by_pm, "underdog")

    by_sport: dict[str, int] = {}
    for m in matches_by_id.values():
        by_sport[m["sport"]] = by_sport.get(m["sport"], 0) + 1

    value_bets = sum(
        1
        for p in props
        if p["ev_over_pct"] >= VALUE_BET_EDGE_PCT
        or p["ev_under_pct"] >= VALUE_BET_EDGE_PCT
    )

    return {
        "meta": {
            "quota_remaining": meta.get("quota_remaining"),
            "total_games": len(matches_by_id),
            "by_sport": by_sport,
            "total_props": len(props),
            "value_bets": value_bets,
            "last_pp_refresh": meta.get("last_pp_refresh"),
            "total_pp_lines": int(len(pp_lines)),
            "total_pp_anchors": len(pp_anchors),
            "last_ud_refresh": meta.get("last_ud_refresh"),
            "total_ud_lines": int(len(ud_lines)),
            "total_ud_anchors": len(ud_anchors),
        },
        "props": props,
        "pp_anchors": pp_anchors,
        "ud_anchors": ud_anchors,
    }


def _build_dfs_anchors(
    dfs_df: pd.DataFrame,
    props_by_pm: dict[tuple[str, str], list[dict]],
    platform_label: str,
) -> list[dict]:
    """For each PP/UD line, attach the closest sportsbook consensus."""
    if dfs_df.empty:
        return []

    out: list[dict] = []
    for _, r in dfs_df.iterrows():
        key = (str(r["player"]).lower(), r["market"])
        candidates = props_by_pm.get(key)
        if not candidates:
            continue
        dfs_line = float(r["line"])
        exact = next(
            (c for c in candidates if abs(c["line"] - dfs_line) < 0.01), None
        )
        chosen = exact or min(candidates, key=lambda c: abs(c["line"] - dfs_line))

        # EV vs the DFS line: payout multipliers vary by leg count, so we report
        # the raw consensus_p and let the slip-sizing layer compute slip EV.
        out.append(
            {
                "platform": platform_label,
                "sport": chosen["sport"],
                "player": chosen["player"],
                "market": chosen["market"],
                "game": chosen["game"],
                "event_id": chosen["event_id"],
                "commence_time": chosen["commence_time"],
                "dfs_line": dfs_line,
                "odds_tier": r.get("odds_tier", "standard"),
                "projection_id": r.get("projection_id"),
                "cached_line": chosen["line"],
                "exact_line_match": exact is not None,
                "consensus_p_over": chosen["consensus_p_over"],
                "consensus_p_under": chosen["consensus_p_under"],
                "books_count": chosen["books_count"],
            }
        )
    return out


def _empty_meta(matches: pd.DataFrame, meta: dict) -> dict:
    return {
        "quota_remaining": meta.get("quota_remaining"),
        "total_games": int(len(matches)),
        "by_sport": {},
        "total_props": 0,
        "value_bets": 0,
        "last_pp_refresh": meta.get("last_pp_refresh"),
        "total_pp_lines": 0,
        "total_pp_anchors": 0,
        "last_ud_refresh": meta.get("last_ud_refresh"),
        "total_ud_lines": 0,
        "total_ud_anchors": 0,
    }


# ----------------------------------------------------------------------------
# DFS slip sizing (USER.md rules)
# ----------------------------------------------------------------------------

DFS_STAKE_CAPS_PCT = {2: 2.0, 3: 1.5, 4: 1.0, 5: 0.5, 6: 0.25}
DFS_MULTIPLIERS = {
    "prizepicks": {2: 3.0, 3: 5.0, 4: 10.0, 5: 20.0, 6: 37.5},
    "underdog":   {2: 3.0, 3: 6.0, 4: 10.0, 5: 20.0, 6: 35.0},
}


def max_slip_stake(bankroll: float, leg_count: int) -> float:
    """Return the max stake in dollars per USER.md rule."""
    pct = DFS_STAKE_CAPS_PCT.get(leg_count, 0.0)
    return round(bankroll * pct / 100, 2)


def slip_ev(
    platform: str, leg_count: int, leg_probs: list[float]
) -> dict[str, float]:
    """Compute slip EV given consensus probabilities for each leg.

    Assumes independence (DFS pick'em payouts assume legs are independent;
    user is responsible for correlation discipline per USER.md).
    """
    if not leg_probs or len(leg_probs) != leg_count:
        return {"hit_p": 0.0, "ev_pct": 0.0}
    mult = DFS_MULTIPLIERS.get(platform, {}).get(leg_count, 0.0)
    hit_p = 1.0
    for p in leg_probs:
        hit_p *= p
    # EV per $1 staked: hit_p * (mult - 1) - (1 - hit_p)
    ev_per_dollar = hit_p * (mult - 1) - (1 - hit_p)
    return {"hit_p": round(hit_p, 4), "ev_pct": round(ev_per_dollar * 100, 2)}
