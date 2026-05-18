"""LLM analyst — the 'Yomero' layer.

Takes the dashboard data (props, PP anchors, UD anchors) and asks an LLM,
primed with SOUL.md + USER.md + AGENTS.md + the relevant sport skill, to
recommend the best PrizePicks / Underdog plays for the day.

Supports two providers — pick whichever you have keys for:
  - Anthropic (Claude)  — preferred per your OpenClaw config
  - Google (Gemini)     — fallback / cost option

Set LLM_PROVIDER in secrets to 'anthropic' or 'google' to choose.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

try:
    import streamlit as st
    _SECRETS = st.secrets if hasattr(st, "secrets") else {}
except Exception:
    _SECRETS = {}

from . import db, skill_loader


def _cfg(name: str, default: str | None = None) -> str | None:
    return _SECRETS.get(name) or os.environ.get(name) or default


# ----------------------------------------------------------------------------
# Prompt construction
# ----------------------------------------------------------------------------

def build_user_message(
    sport: str,
    dashboard: dict,
    bankroll: float,
    platform_focus: str = "both",
) -> str:
    """The user-facing prompt the LLM sees alongside the system prompt.

    `sport`           — sport label or "ALL" for cross-sport mode.
    `platform_focus`  ∈ {'prizepicks', 'underdog', 'both'}.
    """
    is_cross_sport = sport.upper() == "ALL"

    pp_anchors = dashboard.get("pp_anchors", [])
    ud_anchors = dashboard.get("ud_anchors", [])
    props = dashboard.get("props", [])

    # Trim to a manageable context size — top props by absolute EV.
    # On cross-sport nights we cap higher since there's more legitimate ground
    # to cover, but still bounded to keep prompt cost predictable.
    cap = 120 if is_cross_sport else 60
    top_props = [
        {
            "sport": p.get("sport"),
            "player": p["player"],
            "market": p["market"],
            "line": p["line"],
            "game": p["game"],
            "consensus_p_over": p["consensus_p_over"],
            "consensus_p_under": p["consensus_p_under"],
            "ev_over_pct": p["ev_over_pct"],
            "ev_under_pct": p["ev_under_pct"],
            "best_over": p["best_over"],
            "best_under": p["best_under"],
            "books_count": p["books_count"],
        }
        for p in props[:cap]
    ]

    pp_block = pp_anchors if platform_focus in ("prizepicks", "both") else []
    ud_block = ud_anchors if platform_focus in ("underdog", "both") else []

    # Compute which sports actually have edges in this payload (for headline).
    sports_in_payload = sorted({p.get("sport") for p in top_props if p.get("sport")})

    payload = {
        "today": datetime.now(timezone.utc).date().isoformat(),
        "sport": sport,
        "sports_in_payload": sports_in_payload,
        "bankroll_usd": bankroll,
        "platform_focus": platform_focus,
        "sportsbook_consensus_props": top_props,
        "prizepicks_lines_with_consensus": pp_block,
        "underdog_lines_with_consensus": ud_block,
    }

    if is_cross_sport:
        headline = (
            f"You are analyzing today's CROSS-SPORT slate. The data spans "
            f"{', '.join(sports_in_payload) if sports_in_payload else 'no sports yet'}. "
            f"Find the highest-edge slip mix across sports — uncorrelated legs "
            f"from different sports are preferred when edges are comparable."
        )
        rules_extra = (
            "- Cross-sport cap: max 4 legs from any single sport on this slip\n"
            "- Same-game cap still applies WITHIN each sport (max 3, max 2 on 4+ leg slips)\n"
            "- Each leg in your output must state the SPORT explicitly\n"
        )
    else:
        headline = f"You are analyzing today's {sport} slate for the user."
        rules_extra = (
            "- Avoid more than 3 legs from the same game (correlation cap)\n"
            "- Apply the sport-specific risks from the loaded sport skill\n"
        )

    instruction = f"""\
{headline}

The data below contains:
1. **sportsbook_consensus_props** — sportsbook player props, with no-vig consensus
   probabilities computed across all available books. Treat consensus_p as the
   true fair probability. Each prop is tagged with its `sport`.
2. **prizepicks_lines_with_consensus** / **underdog_lines_with_consensus** —
   DFS pick'em lines from each platform, joined to the closest sportsbook line.
   `exact_line_match: false` means the sportsbook line differs from the DFS
   line — apply judgment, don't blindly use the consensus.

Your task:
- Identify the best Over/Under picks on {platform_focus} for today.
- Apply the user's slip-sizing rules from USER.md (stake caps by leg count).
- Each leg must have edge ≥ 4% vs. consensus (USER.md hard rule).
{rules_extra}- If no leg clears the edge threshold, explicitly say "pass" — don't force action.

Output format (per SOUL.md):
For each recommended leg, give:
  • The bet (sport, player, market, line, side, platform)
  • Implied probability vs. assessed probability
  • Edge %
  • Confidence (Low/Medium/High) + reasoning
  • Key drivers (2-4 bullets)
  • Risk factors
Then propose 1-2 slip constructions with: leg count, total stake (in $),
expected hit probability, slip EV %. Bold the recommended slip. For
cross-sport slips, show the sport mix (e.g. "2 NBA + 2 MLB").

Data:
```json
{json.dumps(payload, indent=2, default=str)}
```
"""
    return instruction


# ----------------------------------------------------------------------------
# Provider adapters
# ----------------------------------------------------------------------------

def _call_anthropic(system: str, user: str, model: str | None = None) -> str:
    from anthropic import Anthropic

    client = Anthropic(api_key=_cfg("ANTHROPIC_API_KEY"))
    model = model or _cfg("ANTHROPIC_MODEL", "claude-opus-4-5")
    resp = client.messages.create(
        model=model,
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def _call_gemini(system: str, user: str, model: str | None = None) -> str:
    import google.generativeai as genai

    genai.configure(api_key=_cfg("GOOGLE_API_KEY"))
    model = model or _cfg("GEMINI_MODEL", "gemini-2.5-pro")
    gm = genai.GenerativeModel(model, system_instruction=system)
    resp = gm.generate_content(user)
    return resp.text


# ----------------------------------------------------------------------------
# Public entrypoint — what the Streamlit "Analyze" button calls
# ----------------------------------------------------------------------------

def analyze(
    sport: str,
    dashboard: dict,
    bankroll: float,
    platform_focus: str = "both",
    log: bool = True,
) -> dict:
    """Run the LLM analyst end-to-end and (optionally) log the result.

    Returns: {model, response, system_prompt, user_prompt, analysis_id}.
    """
    # Determine which sport skills to load. In ALL mode, load only the ones
    # that actually have edges in the payload — saves tokens, keeps Yomero
    # focused on actionable knowledge.
    if sport.upper() == "ALL":
        sports_with_data = sorted({
            p.get("sport") for p in dashboard.get("props", [])
            if p.get("sport")
        })
        skill_sports = sports_with_data if sports_with_data else ["NBA"]
    else:
        skill_sports = [sport]

    system = skill_loader.build_system_prompt(skill_sports)
    user = build_user_message(sport, dashboard, bankroll, platform_focus)

    provider = (_cfg("LLM_PROVIDER", "anthropic") or "anthropic").lower()
    if provider == "anthropic":
        model = _cfg("ANTHROPIC_MODEL", "claude-opus-4-5")
        response = _call_anthropic(system, user, model)
    elif provider == "google":
        model = _cfg("GEMINI_MODEL", "gemini-2.5-pro")
        response = _call_gemini(system, user, model)
    else:
        raise RuntimeError(f"Unknown LLM_PROVIDER: {provider!r}")

    analysis_id = None
    if log:
        try:
            analysis_id = db.log_analysis(
                {
                    "sport": sport,
                    "model": model,
                    "user_prompt": user,
                    "system_prompt": system,
                    "response": response,
                    "dashboard_snapshot": dashboard,
                }
            )
        except Exception as e:
            # Don't fail the analysis if logging fails.
            print(f"[warn] analysis log failed: {e}")

    return {
        "model": model,
        "response": response,
        "system_prompt": system,
        "user_prompt": user,
        "analysis_id": analysis_id,
    }
