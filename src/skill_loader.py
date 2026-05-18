"""Markdown skill loader for the LLM analyst layer.

Reads the same .md files OpenClaw used (SOUL.md, USER.md, AGENTS.md, and the
sport knowledge files like nba.md). The Streamlit app passes the concatenated
text as the LLM's system prompt.

This is the bridge between your hand-tuned analytical persona and the data
pipeline — the LLM sees:
  [SOUL.md + USER.md + AGENTS.md + {selected_sport}.md] as system instructions
  [JSON dashboard data]                                  as user message
and is asked to recommend PrizePicks / Underdog plays.
"""
from __future__ import annotations

from pathlib import Path

SKILLS_DIR = Path(__file__).parent.parent / "skills"


def load(name: str) -> str:
    """Load a single skill file. Returns empty string if missing."""
    path = SKILLS_DIR / name
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def load_sport_skill(sport: str) -> str:
    """Map a sport label (NBA/MLB/NHL/SOCCER) to its skill file."""
    mapping = {
        "NBA": "nba.md",
        "NFL": "nfl.md",
        "MLB": "mlb.md",
        "NHL": "nhl.md",
        "SOCCER": "soccer.md",
        "NCAAF": "ncaaf.md",
        "NCAAB": "ncaab.md",
        "MMA": "mma.md",
        "TENNIS": "tennis.md",
        "GOLF": "golf.md",
        "NASCAR": "nascar.md",
    }
    fname = mapping.get(sport.upper())
    return load(fname) if fname else ""


def build_system_prompt(sport: str | list[str]) -> str:
    """Concatenate SOUL + USER + AGENTS + sport skill(s) into one system prompt.

    Accepts either:
      - a single sport string (e.g. "NBA") → loads one sport skill
      - a list of sport strings (e.g. ["NBA", "MLB"]) → loads each in order
    For cross-sport mode, pass only the sports that actually have edges so
    Yomero isn't filling its context with NHL knowledge during an NBA+MLB night.
    """
    if isinstance(sport, str):
        sports = [sport]
    else:
        sports = list(sport)

    sections = [
        ("# CORE IDENTITY (SOUL.md)", load("SOUL.md")),
        ("# USER PROFILE (USER.md)", load("USER.md")),
        ("# OPERATING RULES (AGENTS.md)", load("AGENTS.md")),
    ]
    for s in sports:
        body = load_sport_skill(s)
        if body.strip():
            sections.append((f"# SPORT KNOWLEDGE ({s.upper()})", body))

    if len(sports) > 1:
        sections.append((
            "# CROSS-SPORT MODE",
            "You are analyzing player props ACROSS MULTIPLE SPORTS tonight. The "
            "data payload includes edges from each sport above. Slate-night "
            "correlation across sports is naturally low — an NBA game's result "
            "does not drive an MLB result. Per USER.md, the cross-sport cap is "
            "max 4 legs from any single sport on a multi-sport slip.\n\n"
            "When building slips:\n"
            "- Look for the highest-edge legs regardless of sport\n"
            "- Prefer cross-sport mixing when edges are comparable, since "
            "uncorrelated legs improve risk-adjusted return\n"
            "- Still respect the same-game cap within each sport\n"
            "- Be explicit about which sport each leg comes from in the output"
        ))

    return "\n\n".join(f"{header}\n\n{body}" for header, body in sections if body.strip())


def list_available() -> list[str]:
    """List all markdown skills present (for sidebar display / debugging)."""
    if not SKILLS_DIR.exists():
        return []
    return sorted(p.name for p in SKILLS_DIR.glob("*.md"))
