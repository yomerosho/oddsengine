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


def build_system_prompt(sport: str) -> str:
    """Concatenate SOUL + USER + AGENTS + sport skill into one system prompt."""
    sections = [
        ("# CORE IDENTITY (SOUL.md)", load("SOUL.md")),
        ("# USER PROFILE (USER.md)", load("USER.md")),
        ("# OPERATING RULES (AGENTS.md)", load("AGENTS.md")),
        (f"# SPORT KNOWLEDGE ({sport.upper()})", load_sport_skill(sport)),
    ]
    return "\n\n".join(f"{header}\n\n{body}" for header, body in sections if body.strip())


def list_available() -> list[str]:
    """List all markdown skills present (for sidebar display / debugging)."""
    if not SKILLS_DIR.exists():
        return []
    return sorted(p.name for p in SKILLS_DIR.glob("*.md"))
