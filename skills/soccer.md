# Soccer Betting Skill (Reference)

## DFS Pick'em Context

PrizePicks and Underdog Fantasy do not segregate soccer leagues — all soccer
projections come through under a single "SOCCER" bucket on the DFS side
(`league_id=82` in PrizePicks). The OddsEngine config mirrors this: one
SOCCER sport entry that pulls events from multiple sportsbook league keys
(EPL, La Liga, Bundesliga). Per-league character below is preserved for the
analytical layer — when you're judging an edge, the league context still
matters even if the data plumbing treats them as one.

## Common across all leagues

### Core advanced metrics
- **xG / xGA**: Expected goals for/against
- **xPTS**: Expected points based on xG
- **Big chances created/conceded**
- **PPDA**: Passes per defensive action (pressing intensity)
- **Shot quality (xG per shot)**

### Why soccer is structurally different from American sports
- **Draws are real outcomes** (3-way market for moneylines)
- **Asian Handicap** removes the draw — cleaner edge identification
- **Both Teams to Score (BTTS)** is a common standalone market
- **Corners and cards** have liquid prop markets in many books
- **Promotion/relegation** creates motivation spots

### Common DFS / prop markets
- Player shots / shots on target / assists / goals
- Match goals (over/under 2.5 most common)
- BTTS YES/NO
- Player to score anytime
- Corners (team or match total)
- Cards (team or match total)
- Asian Handicap (best market for sharp bettors)

### Universal prop drivers
1. Squad rotation (UCL/Europa conflicts)
2. Home/away splits (HFA varies massively by club & league)
3. Manager tactical setup (high press vs. low block)
4. Set piece quality (10–15% of EPL goals come from set pieces)
5. Pace of play (impacts shots, corners, cards)

### Information sources (any league)
- **FBref.com** — Opta-powered advanced stats, free
- **Understat** — xG model, free
- **The Athletic** — tactical analysis (subscription)
- **Wyscout / Opta** — paid, deep professional data

---

## EPL (English Premier League)

### Style profile
- Faster tempo than other top-5 leagues
- Higher possession turnover, more transitions
- ~2.8 goals/match historically
- Big-6 + frequent shake-up below

### League-specific situational factors
- **Fixture congestion**: Teams in UCL + FA Cup rotate heavily
- **December/January (festive period)**: Squad fatigue
- **International breaks**: Returning players may rest
- **Manager change bounce**: Short-term overperformance
- **Newly promoted sides**: Often overrated early, then fade

### Edge spots
- Asian Handicap on home favorites pricing draw risk too high
- BTTS on attacking sides facing high defensive lines
- Corners overs in matches with two attacking, possession-based sides
- Player shot props on penalty takers / set piece specialists

### Sources
- **EPL Twitter**: @JamesBenge, @swissramble (financial side)
- **Twitter tactics**: @lastwordontm, @tacticalpad

### Calendar
- August–May regular season (38 matches)
- Multiple cup competitions overlap (FA Cup, EFL Cup, UCL)
- Boxing Day (Dec 26) congested fixture period — fatigue spots

---

## La Liga (Spain)

### Style profile
- Tactical & technical — possession-heavy, lower tempo than EPL
- Defensive structure generally tighter than EPL
- Lower goals per game historically (~2.5 vs. EPL's ~2.8)
- Big 3 (Real Madrid, Barcelona, Atlético) dominate top positions
- Mid-table parity — lots of close matches

### League-specific situational factors
- **El Clásico (Real vs. Barca)**: Throw analytics out — variance is massive
- **Madrid Derby (Real vs. Atleti)**: Tactical, low-scoring often
- **Newly promoted sides**: Usually fold defensively
- **Late-season survival fights**: Motivation spots
- HFA generally smaller than EPL or Bundesliga
- Referees stricter on physicality (more cards)

### Common markets (regional flavor)
- Asian Handicap (best for sharp pricing)
- Cards markets (La Liga averages high cards/match)
- Corners less reliable here than EPL — fewer crosses
- Totals often skew unders due to defensive style

### Edge spots
- Total unders in mid-table tactical battles
- Cards markets — La Liga refs whistle more
- Asian Handicap on Atlético when priced too short
  (defensive but rarely thrash)

### Sources
- **MARCA, AS** (Spanish coverage)
- **Tactical Twitter**: @euansport, @grace_robertson_

---

## Bundesliga (Germany)

### Style profile
- Most attacking league in Europe — highest goals/game in top 5
- Pressing-heavy (gegenpressing legacy)
- Open, transition-based games
- Bayern Munich dominance — but parity grew in recent years
- Average ~3.0 goals/game historically

### League-specific situational factors
- **Der Klassiker (Bayern vs. Dortmund)**: National TV, high variance
- **Winter break return**: Some teams come back rusty
- **Relegation playoff**: 16th-place team plays 2.Bundesliga 3rd
- **Newly promoted clubs**: Often punch up in Bundesliga (open style helps)
- Fewer matches (18 teams, 34 games — vs. 38 elsewhere)
- Winter break (December–January)

### Edge spots
- Total overs in attacking matchups (top-half teams head-to-head)
- BTTS YES in pressing-vs-pressing matchups
- Bayern overs early in season (often blitz weaker sides)
- Asian Handicap on Dortmund when priced as heavy favorites
  (they've been inconsistent)

### Sources
- **kicker.de** (German sports media)
- **Bundesliga Twitter**: @Bundesliga_EN, @ConstantinE9 (transfer/lineup news)

---

## Serie A (Italy)

### Style profile
- Most tactical league in Europe — chess match feel
- Defensive culture (catenaccio legacy) — lower goals/game
- Set piece efficiency critical
- Counter-attacking play common
- Goal totals lower than EPL/Bundesliga historically

### League-specific situational factors
- **Derbies (Milan, Rome, Turin)**: Variance spikes
- **Mid-week European nights → weekend rotation**
- **Late-season Champions League race tight**: Top 4 always contested
- **Relegation 6-pointers**: Often defensive, low-scoring
- More draws than other top-5 leagues
- Tactical fouls common — high yellow card counts
- VAR usage is more decisive (more goals chalked off)

### Edge spots
- Total unders in tactical mid-table matchups
- BTTS NO in matchups featuring Inter, Juve, or Napoli defensively
- Atalanta totals overs — outlier scoring profile (high-press, high-tempo)
- Cards overs in derby matches

### Sources
- **Italian football Twitter**: @TancrediPalmeri, @SerieA_EN (official)
- **Calcio media**: Gazzetta dello Sport

---

## MLS (USA / Canada)

### Format notes
- Eastern & Western Conferences with intra-conference bias
- Regular season (Feb–Oct) + MLS Cup Playoffs
- Designated Player rule creates star asymmetries
- Apple TV+ broadcasting deal — full match data publicly available
- Salary cap league — no super-clubs like Europe

### League-specific situational factors
- **Travel matters more than any European league** — cross-country flights weekly
- **HFA stronger** — averages 0.5+ goals advantage
- **Weather extremes**: Vancouver cold to Miami heat
- **Roster turnover** is high mid-season (transfer windows + summer trades)
- **Squad depth varies** — DPs can be unavailable on international duty
- **MLS All-Star Break** mid-season disrupts rhythm
- **CONCACAF Champions Cup**: Mid-week conflicts
- **US Open Cup**: Squad rotation distorts league form
- **Leagues Cup (vs. Liga MX)**: Mid-summer disruption
- **Decision Day**: Playoff seeding chaos

### Edge spots
- Heavy home favorites with rested squads
- Travel-fatigued road teams in early kickoff slots
- Total overs in late-season "everyone scores" weekends
- Inter Miami matches with Messi confirmed (line lags)

### Caveats
- Lower limits on most books — sharp action moves lines fast
- Weekly schedule can be irregular; check fixture list
- Salary cap means no team is dramatically better than another (small ATS edges)

### Sources
- **American Soccer Analysis (americansocceranalysis.com)** — best public xG model for MLS
- **MLS Twitter**: @TomBogert, @PaulTenorio
- **The Athletic MLS coverage**

---

## UEFA Champions League

### Format notes (2024+)
- New Swiss model: 36 teams, 8 league-phase matches each
- Top 8 advance directly to Round of 16
- Teams 9–24 go to playoff round
- Teams 25–36 eliminated
- Knockout stages from R16 → Final

### Key differences from domestic leagues
- Squad strength varies — domestic vs. UCL XIs differ
- Tactical respect is higher — fewer wide-open games
- Away goal rule abolished (since 2021/22)
- Travel impact — long trips (especially from English clubs to Eastern Europe)

### League-specific prop drivers
1. Squad rotation between domestic & European matches
2. Manager tactical setup vs. specific opponent style
3. Home/away leg dynamics (knockouts)
4. Aggregate scoring leverage (when one team needs to chase)
5. European pedigree of manager (some consistently over/underperform in UCL)

### Situational factors
- **League phase**: Teams already qualified may rest stars
- **Knockout 1st leg vs. 2nd leg**: Different game scripts
- **English clubs** historically struggle vs. tactical Italian & Spanish sides
- **Final**: Defensive, often unders trigger

### Edge spots
- Big domestic sides resting before key league fixtures (squad rotation = upset risk)
- Underdog +Asian Handicap when favorite is in midweek scheduling crisis
- Unders in knockout 1st legs (cagey, defensive games the norm)

### Personal caution (Yomi)
> Yomi watches UCL live and has flagged emotional bias risk. Only recommend
> bets here if edge > 6% and confirmed via sharp market comparison. Default
> to "no bet" unless edge is unambiguous.

### Sources
- **UEFA.com** (official stats)
- **The Athletic UCL coverage**
- **European football Twitter**: @MichaelCox_zonal, @SwissRamble
