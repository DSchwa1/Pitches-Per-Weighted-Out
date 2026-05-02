# Pitches Per Weighted Out (PpWO)

A new baseball metric that measures how hard a batter makes a pitcher work per out surrendered, weighted by the run expectancy damage of each out.

## Formula

```
PpWO = Total Pitches Seen / Total Weighted Outs
```

A higher PpWO means a batter is forcing pitchers to throw more pitches for every unit of damage they do to their own team's inning.

## Why PpWO

Two existing metrics capture pieces of this concept but neither captures the whole picture:

- **P/PA (Fangraphs)** counts pitches per plate appearance but treats all outs equally. A strikeout on a full count with bases empty gets the same treatment as a bases-loaded GIDP.
- **RE24** measures run expectancy damage but ignores pitch count entirely.

PpWO combines both dimensions. It rewards batters for working deep into counts AND penalizes them appropriately when their outs do maximum damage to an inning.

## Out Weighting

Outs are weighted by their RE24 run expectancy delta: the difference in expected runs from the start of the plate appearance to the end. A larger negative swing means a heavier penalty.

| Outcome | Weight logic |
|---|---|
| Hit, walk, HBP | 0 weighted outs (contribute pitches to numerator only) |
| Strikeout, flyout, groundout | RE delta for that base/out state (roughly 0.2-0.4) |
| Sac fly | Lighter penalty because a run scored (roughly 0.1-0.2) |
| Sac bunt | Slightly heavier than sac fly (roughly 0.2) |
| GIDP | Heaviest penalty because two outs recorded (roughly 0.7-2.0+) |

Weights are derived from a hardcoded RE24 table using 2022-2024 MLB consensus averages (source: Tom Tango / Baseball Prospectus). The post-play base state is approximated from outcome type because Statcast does not provide per-pitch post-play baserunner positions directly.

## Key Properties

- Hits, walks, and HBPs improve your PpWO naturally without breaking the math. They add pitches to the numerator but zero to the denominator.
- GIDP is properly penalized as an inning killer, not just a single out.
- A patient hitter who also avoids GIDPs will score higher than a patient hitter who kills rallies.
- The metric is context-sensitive: the same out type is penalized more heavily with runners on base than with the bases empty.

## Stack

- Python 3
- pybaseball (Statcast pitch-by-pitch data)
- pandas, numpy

## Usage

```bash
pip install pybaseball pandas numpy
python ppwo.py
```

Configurable variables at the top of `ppwo.py`:

| Variable | Default | Description |
|---|---|---|
| `MIN_PA` | 50 | Minimum plate appearances to qualify |
| `SEASON_START` | 2026-03-27 | First date to pull data from |
| `SEASON_END` | 2026-05-01 | Last date to pull data through |

## Output

Two CSV files are written to the working directory:

- `ppwo_leaderboard_mlb.csv` - full league leaderboard sorted by PpWO descending
- `ppwo_leaderboard_mets.csv` - New York Mets players only

Columns: Rank, Player, Team, PpWO, P/PA, Total Pitches, Weighted Outs, PA, GIDP, Avg Pitches/PA, Is Met

## Tests

```bash
python test_ppwo.py
```

Covers runner code encoding, RE24 table lookups, RE delta direction, weighted out ordering, PpWO formula properties, and vectorized DataFrame operations (42 tests).

## Limitations

- Post-play base state is approximated from outcome type rather than tracked directly. This is a principled approximation that preserves the correct ordering of all out types.
- RE24 weights are static averages, not park- or season-adjusted.
- Minimum PA threshold excludes part-time players and those with injuries.
