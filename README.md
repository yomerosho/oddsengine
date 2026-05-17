# OddsEngine — Cloud Edition

Hosted Streamlit port of the original OpenClaw OddsEngine. Same EV math, same
data pipeline, same skill-driven analyst voice ("Yomero") — but with zero
local install, zero CLI, and zero compute costs beyond what your data
providers charge.

```
                ┌─────────────────────────────────────────────────────────┐
                │            Streamlit Cloud  (free tier)                 │
                │                                                         │
                │   streamlit_app.py  ── tabs: EV / PP / UD / Analyst    │
                │              │                                          │
                │   ┌──────────┴──────────────┐                          │
                │   ▼                         ▼                          │
                │  src/ev.py            src/analyst.py                    │
                │  (math)               (Claude / Gemini)                 │
                │   │                         │                          │
                │   ▼                         ▼                          │
                │  src/db.py ───► Supabase Postgres (free tier)          │
                │   ▲                                                    │
                │   │                                                    │
                │  src/odds_api.py    src/apify_ingest.py                │
                │   │                         │                          │
                │   ▼                         ▼                          │
                │  the-odds-api.com    Apify (PP + UD actors)           │
                └─────────────────────────────────────────────────────────┘
```

## Features

- **Sportsbook EV** — no-vig consensus probability across all US books, EV at
  best available price, sorted by edge.
- **PrizePicks lines** — every PP line joined to its closest sportsbook line
  so you can see the gap.
- **Underdog lines** — same, for Underdog Fantasy.
- **🧠 Yomero analyst** — primed with `SOUL.md` + `USER.md` + `AGENTS.md` +
  the relevant sport skill (`nba.md`, etc.), then handed the slate and asked
  for the best plays. Output follows the SOUL.md format.
- **Slip ledger** — log slips, settle them, audit ROI/CLV over time.

## What's where

| Path | Purpose |
| --- | --- |
| `streamlit_app.py` | Single-page Streamlit UI. |
| `src/db.py` | Supabase Postgres client. |
| `src/odds_api.py` | The Odds API fetcher (`/events`, `/odds`). |
| `src/apify_ingest.py` | PrizePicks + Underdog ingest via Apify actors. |
| `src/ev.py` | Vig removal, consensus probability, EV at best price, slip EV. |
| `src/skill_loader.py` | Reads markdown skills for LLM prompts. |
| `src/analyst.py` | LLM analyst — Claude or Gemini, primed with skills. |
| `skills/*.md` | SOUL, USER, AGENTS, sport knowledge files. |
| `supabase/schema.sql` | Postgres tables. Run once at setup. |
| `.streamlit/secrets.toml.example` | Template. Copy to `secrets.toml` locally; never commit. |
| `.github/workflows/refresh.yml` | Optional scheduled refresher. |

## Deploy from scratch (45 min, end to end)

### 1. Set up Supabase (5 min)

1. Sign up at https://supabase.com (free tier is plenty).
2. Create a new project. Pick a region close to Streamlit Cloud's US-east.
3. Once provisioned, go to **SQL Editor** → paste the contents of
   `supabase/schema.sql` → **Run**. You should see "Success. No rows returned."
4. Settings → **API** → copy the **Project URL** and the **service_role**
   secret. Keep these handy.

### 2. Get API keys (10 min)

| Service | Where | Cost |
| --- | --- | --- |
| The Odds API | https://the-odds-api.com | 500 credits/mo free |
| Apify | https://console.apify.com | Pay per actor run |
| Anthropic | https://console.anthropic.com | Pay per token (cheap on Sonnet) |
| Google AI Studio (alt) | https://aistudio.google.com/app/apikey | Free tier generous |

### 3. Push to GitHub (5 min)

```bash
git init
git add .
git commit -m "Initial OddsEngine cloud port"
git remote add origin https://github.com/<you>/oddsengine.git
git push -u origin main
```

Make the repo **private** unless you want others using your quotas.

### 4. Deploy on Streamlit Cloud (5 min)

1. Sign in at https://share.streamlit.io with GitHub.
2. **New app** → pick your repo, branch `main`, main file `streamlit_app.py`.
3. Click **Advanced settings** → **Secrets** → paste the contents of
   `.streamlit/secrets.toml.example` with your real values filled in.
4. **Deploy.** First boot takes ~3 minutes.

### 5. Password-protect (2 min)

The app will burn your API quotas if it's public. In the Streamlit Cloud
dashboard → app settings → **Sharing** → set to "Only specific people" or
add Google SSO restriction to your email.

### 6. First-use checklist (15 min)

1. Open the app. Confirm the sidebar loads.
2. Set your bankroll in the sidebar → 💾 Save.
3. Click **📊 Odds API (NBA)**. Wait ~30s. Should see "X games, Y prop rows".
4. Click **🎲 PrizePicks**. Wait ~60s for the Apify actor.
5. Switch to the **🧠 Analyst (Yomero)** tab → **Get today's best plays**.
6. Review output, log any slips you take in the **📒 Slip log** tab.

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Fill in real keys in .streamlit/secrets.toml
streamlit run streamlit_app.py
```

App opens at http://localhost:8501.

## Cost model

- **Streamlit Community Cloud:** $0 (free tier).
- **Supabase:** $0 (free tier — 500MB DB, plenty for years of slip history).
- **The Odds API:** $0 (500 credits/mo free). One NBA refresh = ~24 credits.
  Budget ≈ 20 NBA refreshes/month on the free tier. Upgrade if needed.
- **Apify:** Pay per actor run — typically $0.05-$0.20 per refresh. Button-
  triggered only; never on page render.
- **Anthropic API:** ~$0.01-$0.05 per analysis on Claude Sonnet. Cheaper on
  Haiku. Pricier on Opus.
- **Google AI:** Free tier handles personal use; effectively $0.

Realistic monthly cost for personal use: **$5-$15** in API calls,
**$0** in hosting.

## Modifying the analyst

The LLM gets four markdown files as system context, in order:

1. `skills/SOUL.md` — the analytical persona, output format, hard stops.
2. `skills/USER.md` — your bankroll, slip-sizing rules, books you use.
3. `skills/AGENTS.md` — session protocol, escalation triggers.
4. `skills/{sport}.md` — sport-specific knowledge for the active sport.

**Edit any of these files in the repo, push, and the next analysis uses the
new content.** No restart, no CLI, no `openclaw doctor`. This is the win.

## Migrating your slip history

If you have entries in `memory/bets/2026-05.md`, copy each row into the
**Slip log** tab manually, or write a one-time SQL insert into the `slips`
table in Supabase. The schema's there for it.

## Known limitations

- Streamlit Cloud apps sleep after 7 days with no traffic. First open after a
  sleep takes ~30s to warm up. The GitHub Actions cron keeps it alive if you
  enable it.
- The `v_latest_odds` view scans all odds rows on each query. Fine up to
  ~100K rows; if you ingest aggressively, add a TTL job in Supabase to delete
  rows older than 7 days.
- No NBA back-to-back detection yet — port from `main.py:detect_b2b_for_event`
  into `src/ev.py` when ready. It's a 2-hour task.
