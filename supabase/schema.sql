-- OddsEngine — Supabase Postgres schema
-- Ported from the SQLite schema in app/main.py (lines 112-162 of the export).
-- Run this once in Supabase SQL editor before first app launch.

-- ============================================================================
-- Tables
-- ============================================================================

create table if not exists matches (
    id            text primary key,
    sport         text not null,
    sport_key     text not null,
    home_team     text not null,
    away_team     text not null,
    commence_time timestamptz not null,
    fetched_at    timestamptz not null default now()
);

create table if not exists odds (
    id             bigserial primary key,
    event_id       text not null references matches(id) on delete cascade,
    market         text not null,
    player         text not null,
    line           numeric not null,
    side           text not null check (side in ('Over','Under')),
    book           text not null,
    price_american integer not null,
    price_decimal  numeric not null,
    fetched_at     timestamptz not null default now()
);
create index if not exists idx_odds_event  on odds(event_id);
create index if not exists idx_odds_player on odds(player, line, side);
create index if not exists idx_odds_market on odds(market, fetched_at desc);

create table if not exists dfs_lines (
    id              bigserial primary key,
    platform        text not null check (platform in ('prizepicks','underdog')),
    sport           text not null,
    player          text not null,
    market          text not null,
    line            numeric not null,
    odds_tier       text,
    projection_id   text,
    start_time      timestamptz,
    home_team       text,
    away_team       text,
    fetched_at      timestamptz not null default now(),
    unique (platform, sport, player, market, line, odds_tier)
);
create index if not exists idx_dfs_lines_lookup on dfs_lines(platform, player, market);

create table if not exists meta (
    key   text primary key,
    value text not null,
    updated_at timestamptz not null default now()
);

-- Slip ledger — replaces memory/bets/YYYY-MM.md markdown tables.
create table if not exists slips (
    id            bigserial primary key,
    placed_at     timestamptz not null default now(),
    platform      text not null,
    leg_count     integer not null,
    stake         numeric not null,
    payout_mult   numeric,           -- e.g. 5.0 for 3-leg PP power play
    result        text check (result in ('win','loss','push','void','pending')) default 'pending',
    net           numeric,
    legs_json     jsonb not null,    -- [{player, market, line, side, sharp_consensus_p, edge_pct, thesis}]
    notes         text,
    settled_at    timestamptz
);
create index if not exists idx_slips_placed_at on slips(placed_at desc);
create index if not exists idx_slips_result    on slips(result);

-- LLM analysis history — so you can review what Yomero said and when.
create table if not exists analyses (
    id            bigserial primary key,
    created_at    timestamptz not null default now(),
    sport         text not null,
    model         text not null,         -- 'claude-opus-4-7', 'gemini-2.5-pro', etc.
    user_prompt   text,
    system_prompt text,                  -- skills concatenated; large
    response      text,
    dashboard_snapshot jsonb              -- the data the LLM was given
);
create index if not exists idx_analyses_created on analyses(created_at desc);

-- ============================================================================
-- Convenience views
-- ============================================================================

-- Latest odds per (event, market, player, line, side, book) — collapses
-- multi-refresh history so the dashboard query stays simple.
create or replace view v_latest_odds as
select distinct on (event_id, market, player, line, side, book)
    event_id, market, player, line, side, book,
    price_american, price_decimal, fetched_at
from odds
order by event_id, market, player, line, side, book, fetched_at desc;
