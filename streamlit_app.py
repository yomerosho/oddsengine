"""OddsEngine — Streamlit Cloud edition.

Trader-terminal aesthetic: dark theme, monospace numerics, plotly charts,
sparse use of color (emerald for +EV, rose for -EV, amber for risk flags).

Pages (radio in sidebar):
  • Slate           — overview KPIs + EV heatmap, the landing screen
  • Sportsbook EV   — filtered prop table with plotly bar of top edges
  • DFS line-shop   — PrizePicks ↔ Underdog ↔ sharp consensus side-by-side
  • Yomero analyst  — LLM that reads SOUL/USER/AGENTS + sport skill
  • Slip builder    — pick legs from the dashboard, compute slip EV live
  • Slip ledger     — placed slips, ROI, calibration
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src import analyst, apify_ingest, db, ev, odds_api, skill_loader

# ============================================================================
# Page config + design tokens
# ============================================================================

st.set_page_config(
    page_title="OddsEngine",
    page_icon="◎",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"Get help": None, "Report a bug": None, "About": "OddsEngine — Yomi's edge layer"},
)

PALETTE = {
    "pos":      "#10b981",   # emerald — +EV, win
    "neg":      "#ef4444",   # rose    — -EV, loss
    "warn":     "#f59e0b",   # amber   — risk flags, marginal edges
    "neutral":  "#64748b",   # slate
    "ink":      "#e6e6e6",
    "panel":    "#11161d",
    "bg":       "#0a0e14",
    "accent":   "#06b6d4",   # cyan    — secondary actions
}

EDGE_THRESHOLD = 4.0  # USER.md per-leg floor

st.markdown(
    f"""
    <style>
    [data-testid="stMetricValue"], [data-testid="stMetricDelta"],
    .stDataFrame, .stTable {{ font-variant-numeric: tabular-nums; }}

    [data-testid="stMetricLabel"] {{
        font-size: 0.72rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: {PALETTE['neutral']};
    }}

    .block-container {{ padding-top: 2rem; padding-bottom: 3rem; }}

    hr.rule {{
        border: none;
        height: 1px;
        background: linear-gradient(90deg, transparent, {PALETTE['neutral']}55, transparent);
        margin: 1.2rem 0;
    }}

    [data-testid="stSidebar"] {{ border-right: 1px solid #1f2937; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================================
# Cached accessors
# ============================================================================

@st.cache_data(ttl=120, show_spinner=False)
def cached_matches(sport: str | None) -> pd.DataFrame:
    return db.load_matches(sport=sport)


@st.cache_data(ttl=120, show_spinner=False)
def cached_odds(sport: str | None) -> pd.DataFrame:
    return db.load_latest_odds(sport=sport)


@st.cache_data(ttl=120, show_spinner=False)
def cached_dfs(platform: str | None, sport: str | None) -> pd.DataFrame:
    return db.load_dfs_lines(platform=platform, sport=sport)


def clear_data_caches() -> None:
    cached_matches.clear()
    cached_odds.clear()
    cached_dfs.clear()


def meta_bundle() -> dict[str, str]:
    keys = [
        "quota_remaining", "bankroll",
        "last_pp_refresh", "last_ud_refresh",
        "last_refresh_NBA", "last_refresh_MLB", "last_refresh_NHL", "last_refresh_SOCCER",
    ]
    return {k: db.get_meta(k) or "" for k in keys}


# ============================================================================
# Sidebar — navigation, filters, refresh
# ============================================================================

with st.sidebar:
    st.markdown("# ◎ OddsEngine")
    st.caption("Yomero · edge layer")

    page = st.radio(
        "Navigate",
        ["Slate", "Sportsbook EV", "DFS line-shop", "Yomero analyst", "Slip builder", "Slip ledger"],
        label_visibility="collapsed",
    )

    st.markdown('<hr class="rule">', unsafe_allow_html=True)

    st.markdown("##### Filters")
    sport = st.selectbox("Sport", ["NBA", "MLB", "NHL", "SOCCER"], index=0)

    sport_markets = odds_api.SPORTS[sport]["prop_markets"]
    market_filter = st.multiselect(
        "Markets",
        options=sport_markets,
        default=sport_markets,
        format_func=lambda m: m.replace("player_", "").replace("_", " ").title(),
    )

    min_edge = st.slider(
        "Min edge %",
        min_value=0.0, max_value=15.0, value=4.0, step=0.5,
        help="USER.md: every leg must clear 4% vs. sharp consensus.",
    )

    min_books = st.slider(
        "Min books per consensus",
        min_value=1, max_value=10, value=3,
        help="More books = more reliable consensus. 3 is a sane floor.",
    )

    platform_filter = st.multiselect(
        "DFS platforms",
        options=["prizepicks", "underdog"],
        default=["prizepicks", "underdog"],
    )

    st.markdown('<hr class="rule">', unsafe_allow_html=True)

    st.markdown("##### Bankroll")
    meta = meta_bundle()
    bankroll = st.number_input(
        "$ in play",
        min_value=1.0,
        value=float(meta.get("bankroll") or 100.0),
        step=1.0, format="%.2f",
        label_visibility="collapsed",
    )
    if st.button("Save bankroll", use_container_width=True):
        db.set_meta("bankroll", str(bankroll))
        st.success(f"Bankroll set to ${bankroll:,.2f}")

    st.markdown('<hr class="rule">', unsafe_allow_html=True)

    st.markdown("##### Refresh data")
    if st.button(f"Pull {sport} odds", use_container_width=True,
                 help="1 credit per (event × market) — default cap 3 events."):
        with st.spinner(f"Pulling {sport} via The Odds API..."):
            try:
                r = odds_api.refresh_sport(sport, max_events=3)
                clear_data_caches()
                st.success(f"{r['games']} games · {r['props_added']} rows · quota {r['quota_remaining']}")
                if r["errors"]:
                    st.warning("\n".join(r["errors"]))
            except Exception as e:
                st.error(str(e))

    c1, c2 = st.columns(2)
    if c1.button("PrizePicks", use_container_width=True, help="Apify actor, 30-90s."):
        with st.spinner("PP actor running..."):
            try:
                r = apify_ingest.refresh_prizepicks()
                clear_data_caches()
                st.success(f"+{r['lines_added']} PP lines")
            except Exception as e:
                st.error(str(e))
    if c2.button("Underdog", use_container_width=True, help="Apify actor, 30-90s."):
        with st.spinner("UD actor running..."):
            try:
                r = apify_ingest.refresh_underdog()
                clear_data_caches()
                st.success(f"+{r['lines_added']} UD lines")
            except Exception as e:
                st.error(str(e))

    st.markdown('<hr class="rule">', unsafe_allow_html=True)
    meta = meta_bundle()
    quota = meta.get("quota_remaining") or "?"
    st.markdown(f"**Quota** `{quota}`")
    if meta.get(f"last_refresh_{sport}"):
        st.caption(f"{sport} odds · {meta[f'last_refresh_{sport}'][:16].replace('T',' ')} UTC")
    if meta.get("last_pp_refresh"):
        st.caption(f"PP · {meta['last_pp_refresh'][:16].replace('T',' ')} UTC")
    if meta.get("last_ud_refresh"):
        st.caption(f"UD · {meta['last_ud_refresh'][:16].replace('T',' ')} UTC")


# ============================================================================
# Build dashboard once per render — passed to each page
# ============================================================================

matches_df = cached_matches(sport)
odds_df = cached_odds(sport)
pp_df = cached_dfs("prizepicks", sport) if "prizepicks" in platform_filter else pd.DataFrame()
ud_df = cached_dfs("underdog", sport) if "underdog" in platform_filter else pd.DataFrame()

dashboard = ev.build_dashboard(
    matches=matches_df, odds=odds_df,
    pp_lines=pp_df, ud_lines=ud_df,
    meta=meta_bundle(),
)


def apply_filters(props: list[dict]) -> list[dict]:
    out = []
    for p in props:
        if market_filter and p["market"] not in market_filter:
            continue
        if p["books_count"] < min_books:
            continue
        if max(p["ev_over_pct"], p["ev_under_pct"]) < min_edge:
            continue
        out.append(p)
    return out


filtered_props = apply_filters(dashboard["props"])


# ============================================================================
# Reusable bits
# ============================================================================

def _ev_color(pct: float) -> str:
    if pct >= EDGE_THRESHOLD:
        return PALETTE["pos"]
    if pct <= -EDGE_THRESHOLD:
        return PALETTE["neg"]
    return PALETTE["neutral"]


def style_props_df(df: pd.DataFrame):
    def _color(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return ""
        if v >= EDGE_THRESHOLD:
            return f"color: {PALETTE['pos']}; font-weight: 600"
        if v <= -EDGE_THRESHOLD:
            return f"color: {PALETTE['neg']}"
        return f"color: {PALETTE['neutral']}"
    styler = df.style
    for col in df.columns:
        if "ev" in col.lower() or "edge" in col.lower():
            styler = styler.map(_color, subset=[col])
    return styler


def plotly_defaults(fig: go.Figure, height: int = 360) -> go.Figure:
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=PALETTE["bg"],
        plot_bgcolor=PALETTE["bg"],
        font=dict(family="monospace", color=PALETTE["ink"], size=12),
        margin=dict(l=10, r=10, t=40, b=10),
        height=height,
        showlegend=False,
    )
    fig.update_xaxes(gridcolor="#1f2937", zerolinecolor="#1f2937")
    fig.update_yaxes(gridcolor="#1f2937", zerolinecolor="#1f2937")
    return fig


def pretty_market(m: str) -> str:
    return m.replace("player_", "").replace("_", " ").title()


# ============================================================================
# PAGE: Slate (landing)
# ============================================================================

if page == "Slate":
    st.markdown(f"### {sport} slate · {datetime.now(timezone.utc).date().isoformat()}")
    st.caption("Filters apply across all pages. Set them once in the sidebar.")

    m = dashboard["meta"]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Games", m["total_games"])
    c2.metric("Props cached", m["total_props"])
    c3.metric(f"Value bets ≥ {min_edge:g}%", sum(
        1 for p in filtered_props
        if max(p["ev_over_pct"], p["ev_under_pct"]) >= min_edge
    ))
    c4.metric("PP lines", m["total_pp_lines"], delta=f"{m['total_pp_anchors']} anchored")
    c5.metric("UD lines", m["total_ud_lines"], delta=f"{m['total_ud_anchors']} anchored")

    st.markdown('<hr class="rule">', unsafe_allow_html=True)

    if not filtered_props:
        st.info("No props match the current filters. Refresh data or relax filters in the sidebar.")
    else:
        # --- Top edges chart ---
        st.markdown("#### Top edges, this slate")
        chart_rows = []
        for p in filtered_props:
            if p["ev_over_pct"] >= p["ev_under_pct"]:
                chart_rows.append({
                    "label": f"{p['player']} {pretty_market(p['market'])} O{p['line']}",
                    "ev": p["ev_over_pct"],
                    "books": p["books_count"],
                })
            else:
                chart_rows.append({
                    "label": f"{p['player']} {pretty_market(p['market'])} U{p['line']}",
                    "ev": p["ev_under_pct"],
                    "books": p["books_count"],
                })
        top = sorted(chart_rows, key=lambda r: -r["ev"])[:15]
        if top:
            tdf = pd.DataFrame(top)
            colors = [_ev_color(v) for v in tdf["ev"]]
            fig = go.Figure(go.Bar(
                x=tdf["ev"], y=tdf["label"],
                orientation="h",
                marker=dict(color=colors),
                text=[f"{v:+.1f}%" for v in tdf["ev"]],
                textposition="outside",
                hovertemplate="<b>%{y}</b><br>EV: %{x:.2f}%<br>Books: %{customdata}<extra></extra>",
                customdata=tdf["books"],
            ))
            fig.update_layout(
                title=dict(text=f"Top 15 by EV · {sport}", x=0.0, font=dict(size=14)),
                xaxis_title="EV %",
                yaxis=dict(autorange="reversed"),
            )
            fig = plotly_defaults(fig, height=480)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        # --- EV distribution histogram ---
        st.markdown("#### EV distribution")
        all_ev = []
        for p in filtered_props:
            all_ev.append(p["ev_over_pct"])
            all_ev.append(p["ev_under_pct"])
        if all_ev:
            fig = px.histogram(x=all_ev, nbins=40, color_discrete_sequence=[PALETTE["accent"]])
            fig.add_vline(x=min_edge, line_dash="dash", line_color=PALETTE["pos"],
                          annotation_text=f"threshold {min_edge:g}%", annotation_position="top right")
            fig.add_vline(x=0, line_dash="dot", line_color=PALETTE["neutral"])
            fig.update_layout(
                title=dict(text="EV % across all filtered (player, line, side) combos", x=0.0, font=dict(size=14)),
                xaxis_title="EV %", yaxis_title="count",
            )
            fig = plotly_defaults(fig, height=320)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ============================================================================
# PAGE: Sportsbook EV
# ============================================================================

elif page == "Sportsbook EV":
    st.markdown(f"### {sport} · sportsbook EV table")
    st.caption(f"Showing props where the best side EV ≥ {min_edge:g}% and books ≥ {min_books}.")

    if not filtered_props:
        st.info("Nothing meets the filters. Relax min edge, or refresh data.")
    else:
        df = pd.DataFrame(filtered_props)
        df["Best Over"]  = df["best_over"].apply(lambda x: f"{x['american']:+d} {x['book']}")
        df["Best Under"] = df["best_under"].apply(lambda x: f"{x['american']:+d} {x['book']}")
        df["Market"] = df["market"].apply(pretty_market)
        display = df[[
            "player", "Market", "line", "game",
            "ev_over_pct", "ev_under_pct",
            "consensus_p_over", "consensus_p_under",
            "Best Over", "Best Under", "books_count",
        ]].rename(columns={
            "player": "Player",
            "line": "Line",
            "game": "Game",
            "ev_over_pct": "EV Over %",
            "ev_under_pct": "EV Under %",
            "consensus_p_over": "P(Over)",
            "consensus_p_under": "P(Under)",
            "books_count": "Books",
        })
        st.dataframe(style_props_df(display), use_container_width=True, hide_index=True,
                     height=min(640, 60 + 35 * len(display)))

        # Per-game grouped view
        st.markdown('<hr class="rule">', unsafe_allow_html=True)
        st.markdown("#### Edges grouped by game")
        for game, group in df.groupby("game"):
            with st.expander(f"{game}  ·  {len(group)} props"):
                gdf = group[[
                    "player", "Market", "line",
                    "ev_over_pct", "ev_under_pct",
                    "Best Over", "Best Under", "books_count",
                ]].rename(columns={
                    "player": "Player", "line": "Line",
                    "ev_over_pct": "EV Over %", "ev_under_pct": "EV Under %",
                    "books_count": "Books",
                })
                st.dataframe(style_props_df(gdf), use_container_width=True, hide_index=True)


# ============================================================================
# PAGE: DFS line-shop
# ============================================================================

elif page == "DFS line-shop":
    st.markdown(f"### {sport} · DFS line-shop")
    st.caption("Each row = a player×market where PP and/or UD has a line. Pick the platform with the better implied edge.")

    pp = [a for a in dashboard["pp_anchors"]
          if a["sport"] == sport and (not market_filter or a["market"] in market_filter)]
    ud = [a for a in dashboard["ud_anchors"]
          if a["sport"] == sport and (not market_filter or a["market"] in market_filter)]

    if not pp and not ud:
        st.info("No DFS lines anchored. Refresh PrizePicks or Underdog from the sidebar.")
    else:
        pp_map = {(a["player"], a["market"]): a for a in pp}
        ud_map = {(a["player"], a["market"]): a for a in ud}
        keys = sorted(set(pp_map.keys()) | set(ud_map.keys()))

        rows = []
        for k in keys:
            p = pp_map.get(k)
            u = ud_map.get(k)
            ref = p or u
            pp_edge_o = ((p["consensus_p_over"]  * 3 - 1) * 100) if p else None
            pp_edge_u = ((p["consensus_p_under"] * 3 - 1) * 100) if p else None
            ud_edge_o = ((u["consensus_p_over"]  * 3 - 1) * 100) if u else None
            ud_edge_u = ((u["consensus_p_under"] * 3 - 1) * 100) if u else None
            rows.append({
                "Player":   ref["player"],
                "Market":   pretty_market(ref["market"]),
                "Game":     ref["game"],
                "PP line":  p["dfs_line"] if p else None,
                "UD line":  u["dfs_line"] if u else None,
                "Sharp":    ref["cached_line"],
                "P(Over)":  round(ref["consensus_p_over"],  4),
                "P(Under)": round(ref["consensus_p_under"], 4),
                "Edge Over PP %":  round(pp_edge_o, 2) if pp_edge_o is not None else None,
                "Edge Under PP %": round(pp_edge_u, 2) if pp_edge_u is not None else None,
                "Edge Over UD %":  round(ud_edge_o, 2) if ud_edge_o is not None else None,
                "Edge Under UD %": round(ud_edge_u, 2) if ud_edge_u is not None else None,
            })
        sdf = pd.DataFrame(rows)
        edge_cols = ["Edge Over PP %", "Edge Under PP %", "Edge Over UD %", "Edge Under UD %"]
        mask = sdf[edge_cols].max(axis=1).fillna(-99) >= min_edge
        sdf = sdf[mask].sort_values(by=edge_cols, ascending=False, na_position="last")

        st.caption(f"{len(sdf)} player×market combos cleared {min_edge:g}% on at least one platform×side.")
        st.dataframe(style_props_df(sdf), use_container_width=True, hide_index=True,
                     height=min(640, 60 + 35 * len(sdf)))


# ============================================================================
# PAGE: Yomero analyst (LLM)
# ============================================================================

elif page == "Yomero analyst":
    st.markdown("### 🧠 Yomero")
    st.caption(
        f"Primed with SOUL.md + USER.md + AGENTS.md + skills/{sport.lower()}.md. "
        "Data passed: filtered props above + PP/UD anchors."
    )

    c1, c2 = st.columns([1, 3])
    with c1:
        platform_focus = st.radio("Platform focus", ["both", "prizepicks", "underdog"], index=0)
        st.markdown(f"**Bankroll:** ${bankroll:,.2f}")
        st.markdown(f"**Edge floor:** {min_edge:g}%")
        st.markdown(f"**Markets:** {len(market_filter)} of {len(sport_markets)}")
        analyze_btn = st.button(
            "Get today's best plays",
            type="primary",
            use_container_width=True,
            disabled=(len(filtered_props) == 0),
        )
        if len(filtered_props) == 0:
            st.warning("No props pass the filters yet. Refresh data or relax filters.")

    with c2:
        if analyze_btn:
            trimmed = {
                **dashboard,
                "props": filtered_props,
                "pp_anchors": [a for a in dashboard["pp_anchors"]
                               if a["sport"] == sport and a["market"] in market_filter],
                "ud_anchors": [a for a in dashboard["ud_anchors"]
                               if a["sport"] == sport and a["market"] in market_filter],
            }
            with st.spinner("Yomero is reading the slate..."):
                try:
                    result = analyst.analyze(
                        sport=sport,
                        dashboard=trimmed,
                        bankroll=bankroll,
                        platform_focus=platform_focus,
                    )
                    st.markdown(f"**Model:** `{result['model']}` · log id `{result['analysis_id']}`")
                    st.markdown('<hr class="rule">', unsafe_allow_html=True)
                    st.markdown(result["response"])
                except Exception as e:
                    st.error(f"Analyst failed: {e}")
                    with st.expander("Debug"):
                        st.exception(e)

    st.markdown('<hr class="rule">', unsafe_allow_html=True)
    st.markdown("#### Recent analyses")
    recent = db.load_recent_analyses(limit=10)
    if recent.empty:
        st.caption("No analyses logged yet.")
    else:
        for _, row in recent.iterrows():
            with st.expander(f"{row['created_at'][:19].replace('T',' ')}  ·  {row['sport']}  ·  {row['model']}"):
                st.markdown(row["response"])


# ============================================================================
# PAGE: Slip builder (interactive)
# ============================================================================

elif page == "Slip builder":
    st.markdown("### Slip builder")
    st.caption("Pick legs from the filtered slate. EV, hit probability, and slip cap update live.")

    if not filtered_props:
        st.info("No legs pass the filters. Relax min edge or refresh data.")
    else:
        # Build candidate list (one entry per (prop, side) clearing the edge floor).
        candidates: list[dict] = []
        for p in filtered_props:
            if p["ev_over_pct"] >= min_edge:
                candidates.append({
                    "key":      f"{p['event_id']}|{p['market']}|{p['player']}|{p['line']}|Over",
                    "label":    f"{p['player']} · {pretty_market(p['market'])} O{p['line']} "
                                f"({p['game']})  ·  P={p['consensus_p_over']:.3f}  EV={p['ev_over_pct']:+.2f}%",
                    "event_id": p["event_id"], "game": p["game"],
                    "player":   p["player"],  "market": p["market"], "line": p["line"], "side": "Over",
                    "p":        p["consensus_p_over"],
                    "edge_pct": p["ev_over_pct"],
                })
            if p["ev_under_pct"] >= min_edge:
                candidates.append({
                    "key":      f"{p['event_id']}|{p['market']}|{p['player']}|{p['line']}|Under",
                    "label":    f"{p['player']} · {pretty_market(p['market'])} U{p['line']} "
                                f"({p['game']})  ·  P={p['consensus_p_under']:.3f}  EV={p['ev_under_pct']:+.2f}%",
                    "event_id": p["event_id"], "game": p["game"],
                    "player":   p["player"],  "market": p["market"], "line": p["line"], "side": "Under",
                    "p":        p["consensus_p_under"],
                    "edge_pct": p["ev_under_pct"],
                })

        if not candidates:
            st.warning(f"No legs clear {min_edge:g}% edge. Relax min edge or refresh data.")
            st.stop()

        cand_by_key = {c["key"]: c for c in candidates}

        c1, c2 = st.columns([2, 1])
        with c1:
            chosen_keys = st.multiselect(
                "Legs",
                options=[c["key"] for c in candidates],
                format_func=lambda k: cand_by_key[k]["label"],
                help="Pick 2-6 legs. USER.md cap: ≤ 2 legs per game.",
            )
        with c2:
            platform = st.selectbox("Platform", ["prizepicks", "underdog"], index=0)
            stake_input = st.number_input("Stake ($)", min_value=0.0, value=1.0, step=0.25, format="%.2f")

        if chosen_keys:
            legs = [cand_by_key[k] for k in chosen_keys]
            leg_count = len(legs)

            # USER.md violations
            game_counts: dict[str, int] = {}
            player_counts: dict[str, int] = {}
            for l in legs:
                game_counts[l["game"]] = game_counts.get(l["game"], 0) + 1
                player_counts[l["player"]] = player_counts.get(l["player"], 0) + 1
            same_game_violation = any(v > 2 for v in game_counts.values())
            duplicate_player    = any(v > 1 for v in player_counts.values())

            cap  = ev.max_slip_stake(bankroll, leg_count) if 2 <= leg_count <= 6 else 0.0
            mult = ev.DFS_MULTIPLIERS.get(platform, {}).get(leg_count, 0.0)
            slip = ev.slip_ev(platform, leg_count, [l["p"] for l in legs])

            st.markdown('<hr class="rule">', unsafe_allow_html=True)

            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Legs", leg_count)
            k2.metric("Payout mult", f"{mult:g}x" if mult else "—")
            k3.metric("Hit P", f"{slip['hit_p']*100:.2f}%")
            k4.metric("Slip EV %", f"{slip['ev_pct']:+.2f}%",
                      delta="+EV" if slip["ev_pct"] > 0 else "-EV")
            k5.metric("Stake cap (USER.md)", f"${cap:.2f}")

            if leg_count < 2 or leg_count > 6:
                st.error(f"DFS slips must be 2–6 legs (you have {leg_count}).")
            if same_game_violation:
                st.error("USER.md: max 2 legs from the same game. Remove same-game extras.")
            if duplicate_player:
                st.error("USER.md: max 1 leg per player. Remove duplicate player legs.")
            if stake_input > cap and cap > 0:
                st.warning(f"Stake ${stake_input:.2f} exceeds USER.md cap of ${cap:.2f} for {leg_count}-leg slip.")
            if slip["ev_pct"] < 0:
                st.warning(f"Slip has negative EV ({slip['ev_pct']:+.2f}%). Reconsider before placing.")

            # Per-leg breakdown
            st.markdown("#### Leg breakdown")
            leg_df = pd.DataFrame([{
                "Player": l["player"],
                "Market": pretty_market(l["market"]),
                "Line":   l["line"],
                "Side":   l["side"],
                "Game":   l["game"],
                "P":      round(l["p"], 4),
                "Edge %": round(l["edge_pct"], 2),
            } for l in legs])
            st.dataframe(style_props_df(leg_df), use_container_width=True, hide_index=True)

            # Per-leg probability dot plot
            fig = go.Figure(go.Scatter(
                x=leg_df["P"],
                y=leg_df["Player"] + " " + leg_df["Side"],
                mode="markers+text",
                marker=dict(size=14, color=[_ev_color(v) for v in leg_df["Edge %"]]),
                text=[f"{v:.3f}" for v in leg_df["P"]],
                textposition="middle right",
                hovertemplate="<b>%{y}</b><br>P=%{x:.4f}<extra></extra>",
            ))
            fig.add_vline(x=0.5, line_dash="dot", line_color=PALETTE["neutral"])
            fig.update_layout(
                title=dict(text="Per-leg consensus probability (0.5 = coin flip)", x=0, font=dict(size=14)),
                xaxis=dict(range=[0, 1], title="Consensus P"),
                yaxis=dict(autorange="reversed"),
            )
            fig = plotly_defaults(fig, height=max(220, 40 * leg_count + 80))
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            # Place button
            st.markdown('<hr class="rule">', unsafe_allow_html=True)
            disabled = (
                leg_count < 2 or leg_count > 6
                or same_game_violation or duplicate_player
                or stake_input > cap
            )
            colA, colB = st.columns([3, 1])
            thesis = colA.text_area("Thesis (USER.md beginner rule: 1 line per leg)", height=80,
                                    placeholder="One sentence per leg explaining why this is +EV. Blocks placement if empty.")
            if colB.button("LOG SLIP", type="primary",
                           disabled=disabled or not thesis.strip(),
                           use_container_width=True):
                slip_id = db.insert_slip({
                    "platform":    platform,
                    "leg_count":   leg_count,
                    "stake":       float(stake_input),
                    "payout_mult": float(mult),
                    "legs_json":   [{
                        "player": l["player"], "market": l["market"], "line": l["line"],
                        "side":   l["side"],   "p": l["p"],           "edge_pct": l["edge_pct"],
                        "game":   l["game"],   "event_id": l["event_id"],
                    } for l in legs],
                    "notes":       thesis,
                })
                st.success(f"Slip #{slip_id} logged. Hit P {slip['hit_p']*100:.2f}%, EV {slip['ev_pct']:+.2f}%.")


# ============================================================================
# PAGE: Slip ledger
# ============================================================================

elif page == "Slip ledger":
    st.markdown("### Slip ledger")
    slips = db.load_slips()
    pending = slips[slips["result"] == "pending"] if not slips.empty else slips
    settled = slips[slips["result"] != "pending"] if not slips.empty else slips

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total slips", len(slips))
    c2.metric("Pending", len(pending))
    c3.metric("Settled", len(settled))
    if not settled.empty and "net" in settled.columns:
        net = settled["net"].fillna(0).astype(float).sum()
        stake_sum = settled["stake"].astype(float).sum()
        roi = (net / stake_sum * 100) if stake_sum else 0.0
        c4.metric("ROI %", f"{roi:+.2f}%", delta=f"${net:+,.2f}")
    else:
        c4.metric("ROI %", "—")

    st.markdown('<hr class="rule">', unsafe_allow_html=True)

    # Cumulative net chart
    if not settled.empty:
        sdf = settled.sort_values("placed_at").copy()
        sdf["net"] = sdf["net"].fillna(0).astype(float)
        sdf["cum_net"] = sdf["net"].cumsum()
        fig = go.Figure(go.Scatter(
            x=sdf["placed_at"], y=sdf["cum_net"],
            mode="lines+markers",
            line=dict(color=PALETTE["accent"], width=2),
            marker=dict(size=8, color=[PALETTE["pos"] if n >= 0 else PALETTE["neg"] for n in sdf["net"]]),
            hovertemplate="placed %{x}<br>cum net: $%{y:,.2f}<extra></extra>",
        ))
        fig.add_hline(y=0, line_dash="dot", line_color=PALETTE["neutral"])
        fig.update_layout(
            title=dict(text="Cumulative net ($) over time", x=0, font=dict(size=14)),
            xaxis_title="placed_at", yaxis_title="cum_net ($)",
        )
        fig = plotly_defaults(fig, height=320)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    if not pending.empty:
        st.markdown("#### Pending")
        st.dataframe(pending[["id", "placed_at", "platform", "leg_count", "stake", "payout_mult"]],
                     use_container_width=True, hide_index=True)

        st.markdown("##### Settle a slip")
        with st.form("settle", clear_on_submit=True):
            sid = st.selectbox("Slip ID", options=pending["id"].tolist())
            colA, colB = st.columns(2)
            result = colA.selectbox("Result", ["win", "loss", "push", "void"])
            net = colB.number_input("Net ($)", value=0.0, step=0.5, format="%.2f",
                                    help="Win = (stake × payout_mult) − stake. Loss = −stake. Push/void = 0.")
            if st.form_submit_button("Settle"):
                db.update_slip_result(int(sid), result, float(net))
                st.success(f"Slip {sid} settled: {result} (net ${net:+,.2f})")
                st.rerun()

    if not settled.empty:
        st.markdown("#### Settled")
        view = settled[["id", "placed_at", "platform", "leg_count", "stake", "payout_mult", "result", "net"]].copy()
        view["placed_at"] = view["placed_at"].astype(str).str[:19].str.replace("T", " ")

        def _row_color(r):
            if r == "win":  return f"color: {PALETTE['pos']}"
            if r == "loss": return f"color: {PALETTE['neg']}"
            return f"color: {PALETTE['neutral']}"
        styled = view.style.map(_row_color, subset=["result"])
        st.dataframe(styled, use_container_width=True, hide_index=True)
