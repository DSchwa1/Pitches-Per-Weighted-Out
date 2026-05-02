# Notes

## Commands

```bash
# Run the full metric calculation (pulls Statcast data, outputs CSVs)
python ppwo.py

# Run the test suite (42 tests, no network required)
python test_ppwo.py

# Install dependencies
pip install pybaseball pandas numpy
```

## Key parameters (top of ppwo.py)

```python
MIN_PA       = 50             # PA threshold to qualify for leaderboard
SEASON_START = "2026-03-27"  # update each season
SEASON_END   = "2026-05-01"  # update to today or desired cutoff
```

## Architecture

The script is structured in two halves separated by a `# MAIN EXECUTION` sentinel comment:

- **Top half (constants + functions):** RE24 table, event bucket sets, and pure functions. The test suite loads only this half via `exec(src[:cutoff], ns)` -- keeping it free of side effects is required for tests to work.
- **Bottom half (execution):** Linear 11-step pipeline that runs when the script is invoked directly.

### Pipeline flow

```
statcast() raw pitch rows
  -> filter to events-notna (PA-ending pitches only)
  -> attach pitch counts per PA via (game_pk, at_bat_number)
  -> encode pre-play base state as 3-bit runner_code int
  -> estimate RE before/after each PA
  -> calc re_delta = re_after - re_before + runs_scored
  -> weighted_outs = max(-re_delta, 0)  [0 for on-base events]
  -> groupby batter_id -> aggregate
  -> playerid_reverse_lookup for batter names
  -> filter MIN_PA, sort, rank
  -> print leaderboards + write CSVs
```

### Critical Statcast schema notes

- `player_name` is the **pitcher's** name, not the batter's. Batter names come from `playerid_reverse_lookup(ids, key_type="mlbam")`.
- `on_1b` / `on_2b` / `on_3b` hold the **player ID** of the runner (or pandas `NA` if empty) -- not booleans. Use `.notna()` to test occupancy, never `bool()`.
- `batting_team` does not exist in current Statcast exports. `resolve_team_col()` derives team from `home_team` / `away_team` + `inning_topbot`.
- Pitch count per PA is reconstructed by grouping all pitches on `(game_pk, at_bat_number)` and taking `max(pitch_number)`.

### RE24 weighting design

`estimate_re_after()` approximates post-play base state from outcome type (Statcast does not provide post-play baserunner positions per pitch row). This is a known simplification. The 24-state RE table is hardcoded from 2022-2024 MLB consensus averages; `get_re()` clamps outs to 0-2 -- it does NOT return 0.0 for inning-over states. That 0.0 is returned explicitly inside `estimate_re_after()` when `new_outs >= 3`.

### Output files (gitignored)

- `ppwo_leaderboard_mlb.csv` - full league, sorted by PpWO descending
- `ppwo_leaderboard_mets.csv` - NYM only

### Test isolation

`test_ppwo.py` stubs out `pybaseball` in `sys.modules` before exec-ing `ppwo.py`, then slices the source at the `# MAIN EXECUTION` sentinel. If you rename or move that comment, tests will break.

---

## 2026 Season Output Summary (through 2026-05-01)

**Data pulled:** 136,374 raw Statcast pitch rows, 34,794 PA-ending events
**Qualified batters:** 315 (>= 50 PA)
**Date range:** 2026-03-27 to 2026-05-01

### MLB leaderboard top 10

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

### Mets leaderboard

| Rank | Player | PpWO | P/PA | GIDPs |
|---|---|---|---|---|
| 1 | Juan Soto | 25.54 | 4.02 | 0 |
| 2 | Francisco Lindor | 25.09 | 4.34 | 2 |
| 3 | Francisco Alvarez | 21.13 | 4.01 | 6 |
| 4 | Carson Benge | 20.74 | 4.02 | 1 |
| 5 | Luis Robert | 20.02 | 3.80 | 2 |
| 6 | Bo Bichette | 20.50 | 3.60 | 6 |
| 7 | Marcus Semien | 19.77 | 3.72 | 3 |
| 8 | Brett Baty | 20.25 | 4.03 | 3 |
| 9 | Mark Vientos | 19.04 | 3.92 | 3 |
| 10 | Jorge Polanco | 19.05 | 3.68 | 1 |
| 11 | Tyrone Taylor | 19.59 | 3.75 | 1 |

### PpWO vs P/PA divergence findings

PpWO and P/PA are correlated at the extremes (patient hitters top both lists) but diverge meaningfully through the middle of the leaderboard via two effects:

**Biggest rank drops (GIDP penalty):**

| Player | P/PA rank (approx) | PpWO rank | Drop | GIDPs |
|---|---|---|---|---|
| Nolan Schanuel | ~160 | 298 | -138 | 9 |
| Kyle Manzardo | ~80 | 255 | -175 | 5 |
| Francisco Alvarez | ~130 | 184 | -54 | 6 |

**Biggest rank rises (OBP rewarded):**

| Player | P/PA rank (approx) | PpWO rank | Rise |
|---|---|---|---|
| Vladimir Guerrero | ~265 | 45 | +220 |
| Dalton Rushing | ~305 | 93 | +212 |
| Ozzie Albies | ~295 | 112 | +183 |
| Chandler Simpson | ~313 | 177 | +136 |

The metric rewards batters who get on base frequently (reducing weighted outs per PA) and penalizes batters whose outs do maximum inning damage (GIDPs, outs with runners on). The GIDP effect is the strongest single differentiator.
