"""
Pitches Per Weighted Out (PpWO) - 2026 MLB Season
==================================================
PpWO = Total Pitches Seen / Total Weighted Outs

Weighted outs use RE24 run expectancy deltas so that high-damage outs
(GIDP, outs with runners in scoring position) count heavier than cheap outs.
Hits, walks, and HBPs contribute pitches to the numerator but zero to the
denominator — they improve your score without breaking the math.
"""

import pandas as pd
import numpy as np
import pybaseball
from pybaseball import statcast, playerid_reverse_lookup
import warnings

warnings.filterwarnings("ignore")

# ══════════════════════════════════════════════════════════════════
#  CONFIGURABLE PARAMETERS
# ══════════════════════════════════════════════════════════════════

MIN_PA       = 50             # minimum plate appearances to qualify
SEASON_START = "2026-03-27"  # Opening Day 2026
SEASON_END   = "2026-05-01"  # update to today or desired cutoff

# ══════════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════

METS_TEAM_CODES = {"NYM"}

# RE24 run expectancy table (2022–2024 MLB consensus averages)
# Key: (outs, runner_code) where runner_code is a 3-bit int:
#   bit 0 (value 1) = runner on 1B
#   bit 1 (value 2) = runner on 2B
#   bit 2 (value 4) = runner on 3B
# Value: expected runs to end of inning from this state
RE24 = {
    (0, 0b000): 0.481,
    (0, 0b001): 0.859,
    (0, 0b010): 1.100,
    (0, 0b100): 1.351,
    (0, 0b011): 1.437,
    (0, 0b101): 1.784,
    (0, 0b110): 1.964,
    (0, 0b111): 2.292,
    (1, 0b000): 0.254,
    (1, 0b001): 0.509,
    (1, 0b010): 0.664,
    (1, 0b100): 0.865,
    (1, 0b011): 0.884,
    (1, 0b101): 1.068,
    (1, 0b110): 1.194,
    (1, 0b111): 1.399,
    (2, 0b000): 0.095,
    (2, 0b001): 0.224,
    (2, 0b010): 0.319,
    (2, 0b100): 0.353,
    (2, 0b011): 0.429,
    (2, 0b101): 0.457,
    (2, 0b110): 0.563,
    (2, 0b111): 0.674,
}

# PA outcome buckets — maps Statcast `events` values to weighting logic
ON_BASE_EVENTS = {
    "single", "double", "triple", "home_run",
    "walk", "hit_by_pitch", "intent_walk", "catcher_interf",
}
SAC_FLY_EVENTS  = {"sac_fly", "sac_fly_double_play"}
SAC_BUNT_EVENTS = {"sac_bunt", "sac_bunt_double_play"}
GIDP_EVENTS     = {
    "grounded_into_double_play", "double_play",
    "triple_play", "strikeout_double_play",
}
STANDARD_OUT_EVENTS = {
    "strikeout", "field_out", "force_out", "grounded_out",
    "flyout", "lineout", "pop_out", "fielders_choice",
    "fielders_choice_out", "other_out",
}
ALL_KNOWN_EVENTS = (
    ON_BASE_EVENTS | SAC_FLY_EVENTS | SAC_BUNT_EVENTS |
    GIDP_EVENTS    | STANDARD_OUT_EVENTS
)

# ══════════════════════════════════════════════════════════════════
#  FUNCTIONS
# ══════════════════════════════════════════════════════════════════

def get_re(outs, runner_code):
    """Look up run expectancy, clamping outs to 0-2. Inning-over (outs>=3) returns 0.0
    in estimate_re_after, not here."""
    return RE24.get((min(int(outs), 2), int(runner_code)), 0.0)


def encode_runner_code(on_1b, on_2b, on_3b):
    """
    Encode base occupancy as a 3-bit int from scalar values.
    Statcast on_1b/2b/3b hold the runner's player ID (or NA if empty).
    Use pd.notna() rather than bool() to avoid NA ambiguity.
    """
    return (int(pd.notna(on_1b)) +
            int(pd.notna(on_2b)) * 2 +
            int(pd.notna(on_3b)) * 4)


def estimate_re_after(row):
    """
    Estimate the run expectancy of the base/out state AFTER a PA ends.
    Uses a principled approximation from outcome type since Statcast doesn't
    provide post-play baserunner state directly per pitch row.
    """
    event  = row["events"]
    outs_b = row["outs_before"]
    rc_b   = row["runner_code_before"]

    if event in ON_BASE_EVENTS:
        # No out — batter reaches 1B, runners advance one base (approximate)
        new_outs = outs_b
        new_rc   = min((rc_b << 1) | 0b001, 0b111)
        return get_re(new_outs, new_rc)

    elif event in SAC_FLY_EVENTS:
        # 1 out, runner from 3B scores
        new_outs = outs_b + 1
        new_rc   = rc_b & ~0b100   # clear 3B bit
        return 0.0 if new_outs >= 3 else get_re(new_outs, new_rc)

    elif event in SAC_BUNT_EVENTS:
        # 1 out, runners advance one base
        new_outs = outs_b + 1
        new_rc   = min(rc_b << 1, 0b111)
        return 0.0 if new_outs >= 3 else get_re(new_outs, new_rc)

    elif event in GIDP_EVENTS:
        # 2 outs; lead runner and batter both out
        new_outs = outs_b + 2
        new_rc   = rc_b >> 1   # remaining runners advance
        return 0.0 if new_outs >= 3 else get_re(new_outs, new_rc)

    elif event in STANDARD_OUT_EVENTS:
        # 1 out; runners hold
        new_outs = outs_b + 1
        return 0.0 if new_outs >= 3 else get_re(new_outs, rc_b)

    else:
        return row["re_before"]   # unknown event: no delta


def calc_weighted_outs(event, re_delta):
    """
    Convert an RE delta into a weighted-out value.
    On-base events → 0.0 (no penalty; they help PpWO naturally).
    All outs → magnitude of run expectancy drop, floored at 0.
    """
    if event in ON_BASE_EVENTS:
        return 0.0
    return max(-re_delta, 0.0)


def resolve_team_col(df):
    """
    Return the batting-team column name, deriving it from home/away + inning
    if the direct column isn't present.
    """
    for col in ("batting_team", "bat_team", "batter_team"):
        if col in df.columns:
            print(f"Note: using '{col}' as batting team column.")
            return col, df

    if "home_team" in df.columns and "inning_topbot" in df.columns:
        df = df.copy()
        df["_team"] = df.apply(
            lambda r: r["away_team"] if r["inning_topbot"] == "Top" else r["home_team"],
            axis=1,
        )
        print("Note: batting_team not found — derived from home/away + inning_topbot.")
        return "_team", df

    df = df.copy()
    df["_team"] = "UNK"
    print("WARNING: Could not determine batting team. Team set to 'UNK'.")
    return "_team", df


def print_leaderboard(df, title, display_cols):
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")
    out = df[display_cols].copy()
    out["ppwo"]             = out["ppwo"].round(3)
    out["p_per_pa"]         = out["p_per_pa"].round(3)
    out["total_wo"]         = out["total_wo"].round(2)
    out["avg_pitches_per_pa"] = out["avg_pitches_per_pa"].round(2)
    out.columns = ["Rk", "Player", "Team", "PpWO", "P/PA",
                   "Pitches", "WtdOuts", "PA", "GIDP", "Avg P/PA"]
    print(out.to_string(index=False))


# ══════════════════════════════════════════════════════════════════
#  MAIN EXECUTION
# ══════════════════════════════════════════════════════════════════

# ── Step 1: Pull Statcast data ───────────────────────────────────
print("=" * 60)
print("Pulling 2026 Statcast data...")
print(f"  Date range: {SEASON_START} → {SEASON_END}")
print("=" * 60)

pybaseball.cache.enable()
raw = statcast(start_dt=SEASON_START, end_dt=SEASON_END)

print(f"\nRaw rows pulled: {len(raw):,}")
print(f"\nColumn names ({len(raw.columns)}):")
print(list(raw.columns))
print("\nSample rows (5):")
print(raw.head())

# ── Step 2: Filter to PA-ending pitches ─────────────────────────
pa_df = raw[raw["events"].notna()].copy()
print(f"\nPA-ending pitches (events not null): {len(pa_df):,}")

team_col, pa_df = resolve_team_col(pa_df)

# Note: Statcast `player_name` is the PITCHER's name, not the batter's.
# Batter names are looked up separately in Step 8 via playerid_reverse_lookup.
pa_df = pa_df.rename(columns={
    "batter":       "batter_id",
    team_col:       "team",
    "pitch_number": "pitch_num_in_pa",
})

# ── Step 3: Pitch counts per PA ─────────────────────────────────
pitch_counts = (
    raw.groupby(["game_pk", "at_bat_number"])["pitch_number"]
    .max()
    .reset_index()
    .rename(columns={"pitch_number": "pitches_in_pa"})
)
pa_df = pa_df.merge(pitch_counts, on=["game_pk", "at_bat_number"], how="left")
pa_df["pitches_in_pa"] = pa_df["pitches_in_pa"].fillna(1).astype(int)

# ── Step 4: Encode pre-play base/out state ───────────────────────
pa_df["outs_before"] = pa_df["outs_when_up"].fillna(0).astype(int)

# Vectorized runner encoding — notna() because on_Xb holds player IDs, not booleans
pa_df["runner_code_before"] = (
    pa_df["on_1b"].notna().astype(int) +
    pa_df["on_2b"].notna().astype(int) * 2 +
    pa_df["on_3b"].notna().astype(int) * 4
)

pa_df["re_before"] = [
    get_re(o, rc)
    for o, rc in zip(pa_df["outs_before"], pa_df["runner_code_before"])
]

# ── Step 5: Calculate RE after, then RE delta ────────────────────
pa_df["re_after"] = pa_df.apply(estimate_re_after, axis=1)

pa_df["runs_scored"] = (
    pa_df["post_bat_score"].fillna(0) - pa_df["bat_score"].fillna(0)
).clip(lower=0)

# RE delta: positive = offense gained, negative = offense lost
# Runs scored are credited back because they left the RE pool when they scored
pa_df["re_delta"] = pa_df["re_after"] - pa_df["re_before"] + pa_df["runs_scored"]

# ── Step 6: Weighted outs ────────────────────────────────────────
pa_df["weighted_outs"] = [
    calc_weighted_outs(ev, rd)
    for ev, rd in zip(pa_df["events"], pa_df["re_delta"])
]

pa_df["is_gidp"] = pa_df["events"].isin(GIDP_EVENTS).astype(int)

# ── Step 7: Data quality check ───────────────────────────────────
unknown = pa_df.loc[~pa_df["events"].isin(ALL_KNOWN_EVENTS), "events"].value_counts()
if len(unknown) > 0:
    print("\n  DATA QUALITY — Unknown event types (no RE delta applied):")
    print(unknown.to_string())
else:
    print("\n  Data quality check passed — all event types mapped.")

# ── Step 8: Aggregate by batter ──────────────────────────────────
# Group by batter_id only — player_name in Statcast is the pitcher, not the batter.
agg = pa_df.groupby("batter_id").agg(
    total_pitches = ("pitches_in_pa", "sum"),
    total_wo      = ("weighted_outs", "sum"),
    total_pa      = ("game_pk",       "count"),
    total_gidp    = ("is_gidp",       "sum"),
).reset_index()

# Look up batter names from MLBAM IDs
print("Looking up batter names...")
try:
    name_lookup = playerid_reverse_lookup(agg["batter_id"].tolist(), key_type="mlbam")
    name_lookup["batter_name"] = (
        name_lookup["name_first"].str.capitalize() + " " +
        name_lookup["name_last"].str.capitalize()
    )
    name_lookup = name_lookup[["key_mlbam", "batter_name"]].rename(
        columns={"key_mlbam": "batter_id"}
    )
    agg = agg.merge(name_lookup, on="batter_id", how="left")
except Exception as e:
    print(f"Name lookup failed ({e}) — using batter IDs as names.")
    agg["batter_name"] = agg["batter_id"].astype(str)

agg["batter_name"] = agg["batter_name"].fillna(agg["batter_id"].astype(str))

# Attach most-recent team via map (avoids merge column conflicts)
team_map = (
    pa_df.sort_values("game_date")
    .drop_duplicates("batter_id", keep="last")
    .set_index("batter_id")["team"]
)
agg["team"] = agg["batter_id"].map(team_map).fillna("UNK")

print(f"  {len(agg)} batters aggregated, {(agg['total_pa'] >= MIN_PA).sum()} qualify (>={MIN_PA} PA)")
agg["p_per_pa"]         = agg["total_pitches"] / agg["total_pa"]
agg["avg_pitches_per_pa"] = agg["total_pitches"] / agg["total_pa"]
agg["ppwo"] = np.where(
    agg["total_wo"] > 0,
    agg["total_pitches"] / agg["total_wo"],
    np.inf,
)

# ── Step 9: Filter, sort, rank ───────────────────────────────────
qualified = agg[agg["total_pa"] >= MIN_PA].copy()
qualified = qualified.sort_values("ppwo", ascending=False).reset_index(drop=True)
qualified["rank"]   = qualified.index + 1
qualified["is_met"] = qualified["team"].isin(METS_TEAM_CODES)

display_cols = ["rank", "batter_name", "team", "ppwo", "p_per_pa",
                "total_pitches", "total_wo", "total_pa",
                "total_gidp", "avg_pitches_per_pa"]

# ── Step 10: Print leaderboards ──────────────────────────────────
print_leaderboard(qualified, f"PpWO MLB Leaderboard — Min {MIN_PA} PA (2026)", display_cols)

mets = qualified[qualified["is_met"]].reset_index(drop=True)
mets["rank"] = mets.index + 1
print_leaderboard(mets, "PpWO Mets Leaderboard — 2026", display_cols)

# ── Step 11: Export CSVs ─────────────────────────────────────────
qualified[display_cols + ["is_met"]].to_csv("ppwo_leaderboard_mlb.csv",  index=False)
mets[display_cols + ["is_met"]].to_csv("ppwo_leaderboard_mets.csv", index=False)

print("\n  Saved: ppwo_leaderboard_mlb.csv")
print("  Saved: ppwo_leaderboard_mets.csv")
print(f"\nQualified batters (>={MIN_PA} PA): {len(qualified)}")
print(f"Mets qualifiers:                    {len(mets)}")
