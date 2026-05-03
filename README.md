# Pitches Per Weighted Out (PpWO)

A pitcher-attrition metric that measures how hard a batter makes a pitcher work per unit of run-expectancy damage. Built on 2026 Statcast data.

---

## Overview

P/PA (pitches per plate appearance) is the standard proxy for how much a batter tires a pitcher. It has a problem: it treats all outs equally. A 6-pitch GIDP with runners on second and third counts the same as a 6-pitch strikeout with nobody on.

PpWO (Pitches Per Weighted Out) fixes this by weighting each out by its RE24 run expectancy delta — the actual damage that out did to the inning. The result is a metric that captures both how deep a batter works the count *and* how much their outs hurt their team when they do make one.

---

## Research Question

**Do high-P/PA hitters actually wear down pitchers as effectively as their reputation suggests?**

For some, yes. But a non-trivial group of hitters score well on P/PA while repeatedly killing rallies with GIDPs — providing the pitch count without the attrition value. PpWO surfaces that gap: it rewards batters who work counts and reach base, and penalizes batters whose outs do maximum damage to the inning.

---

## Why It Matters

For a front office evaluating lineup construction:

- A GIDP-prone hitter in the 3rd or 5th slot does double damage: it ends the inning early *and* negates the pitch-count attrition that would otherwise expose a starter.
- A hitter with modest P/PA but elite OBP and zero GIDPs may extract more total pitcher stress than the raw pitch-count number implies.
- At the team level, aggregate PpWO is a proxy for how quickly a lineup forces starter removal — a variable with real downstream effects on bullpen leverage and workload.

---

## Data Sources

- **Statcast** pitch-by-pitch data via [`pybaseball`](https://github.com/jldbc/pybaseball) — 2026 season through May 1: 136,374 pitches, 34,794 PA-ending events, 315 qualified batters (≥50 PA)
- **RE24 table** — 24-state run expectancy averages from 2022–2024 MLB consensus (Tom Tango / Baseball Prospectus), used as a hardcoded lookup

---

## Methodology

```
PpWO = Total Pitches Seen / Total Weighted Outs
```

Each out is weighted by its RE24 delta — the change in expected run value from the start to the end of the plate appearance. A larger negative swing means a heavier denominator contribution.

| Outcome | Weight |
|---|---|
| Hit, walk, HBP | 0 — adds to numerator only; improves PpWO |
| Strikeout, flyout, groundout | RE delta for that base/out state (~0.2–0.4) |
| Sac fly | Lighter penalty — a run scored (~0.1–0.2) |
| GIDP | Heaviest penalty — two outs, inning-killer context (~0.7–2.0+) |

The same GIDP in different base/out states carries a different weight. A bases-loaded, one-out GIDP is penalized more heavily than a first-and-second, two-out GIDP. The metric is context-sensitive at the individual PA level.

**Implementation note:** Statcast doesn't provide post-play baserunner state at the pitch level. Post-play state is approximated from outcome type (strikeout = same runners, one more out; GIDP = runners cleared, two more outs; etc.). This approximation preserves the correct ordering across all outcome types and is the standard approach when working from pitch-row data.

---

## Key Findings (2026 season, through May 1)

### MLB Top 10 (≥50 PA)

| Rank | Player | Team | PpWO | P/PA |
|---|---|---|---|---|
| 1 | Nick Kurtz | ATH | 34.84 | 4.68 |
| 2 | Taylor Ward | BAL | 34.83 | 4.39 |
| 3 | Austin Martin | MIN | 33.03 | 4.52 |
| 4 | Ryan Jeffers | MIN | 32.74 | 4.41 |
| 5 | Ben Rice | NYY | 32.73 | 4.20 |
| 6 | Kevin McGonigle | DET | 30.98 | 4.22 |
| 7 | Christian Yelich | MIL | 30.87 | 4.59 |
| 8 | Corbin Carroll | AZ | 30.44 | 4.18 |
| 9 | Aaron Judge | NYY | 30.39 | 4.48 |
| 10 | Garrett Mitchell | MIL | 30.25 | 4.42 |

*Run `python ppwo.py` to generate the full 315-player leaderboard.*

### PpWO vs P/PA Divergence

The main finding: PpWO and P/PA correlate at the extremes but diverge significantly in the middle of the distribution. Two effects drive the separation.

**Biggest rank drops — GIDP penalty:**

| Player | P/PA rank | PpWO rank | Swing | GIDPs |
|---|---|---|---|---|
| Kyle Manzardo | ~80 | 255 | −175 | 5 |
| Nolan Schanuel | ~160 | 298 | −138 | 9 |
| Francisco Álvarez | ~130 | 184 | −54 | 6 |

**Biggest rank rises — OBP rewarded:**

| Player | P/PA rank | PpWO rank | Swing |
|---|---|---|---|
| Vladimir Guerrero Jr. | ~265 | 45 | +220 |
| Dalton Rushing | ~305 | 93 | +212 |
| Ozzie Albies | ~295 | 112 | +183 |
| Chandler Simpson | ~313 | 177 | +136 |

GIDP frequency is the dominant differentiator between the two rankings. Nine GIDPs in ~140 PA is enough to drop a player nearly 140 spots, because each double play simultaneously removes two outs from the inning, clears baserunners, and produces the maximum negative RE delta. The implication: GIDP avoidance — particularly with runners on — contributes more to pitcher-attrition strategy than raw pitch count per plate appearance.

### Team-Level Filtering

The script produces a per-team view alongside the league leaderboard. The NYM output illustrates the metric at a roster level: Juan Soto leads (PpWO 25.54, zero GIDPs in 63 PA) while Francisco Álvarez ranks third despite matching Soto's P/PA — his 6 GIDPs account for the gap.

---

## Limitations

1. **Post-play base state approximation** — estimated from outcome type rather than read from Statcast's game event feed; correct in expectation but introduces noise for non-standard plays
2. **Static RE24 weights** — 2022–2024 averages; not adjusted by park, season, or run environment
3. **PA minimum threshold** — MIN_PA = 50 excludes platoon players and recently activated starters
4. **No cross-season normalization** — absolute PpWO values are not directly comparable across seasons with different run environments

---

## How to Run

```bash
pip install pybaseball pandas numpy
python ppwo.py
```

Configure at the top of `ppwo.py`:

| Variable | Default | Description |
|---|---|---|
| `MIN_PA` | `50` | Minimum PA to appear on leaderboard |
| `SEASON_START` | `"2026-03-27"` | First date to pull |
| `SEASON_END` | `"2026-05-01"` | Update to current date or desired cutoff |

Two CSVs are written to the working directory: `ppwo_leaderboard_mlb.csv` (full league) and `ppwo_leaderboard_mets.csv` (NYM only).

**Test suite** (42 tests, no network calls):

```bash
python test_ppwo.py
```

Covers runner code encoding, RE24 table lookups, RE delta sign correctness, weighted out ordering, formula properties, and vectorized DataFrame operations.

---

## Future Improvements

- **Season-over-season tracking** — identify batters whose PpWO rank diverges from their P/PA rank across years as they age or change roles
- **Team-level aggregate PpWO** — test whether collective PpWO correlates with starter durability metrics (innings per start, early removal rate) across the full MLB
- **Live RE24 calibration** — replace the static table with current-season park-adjusted run expectancy values
- **Full post-play state tracking** — Statcast's game event feed provides actual post-play baserunner state; using it would eliminate the base-state approximation
- **Downstream outcome correlation** — does high team PpWO correlate with more inherited-runner situations or increased leverage in opponents' bullpens?
