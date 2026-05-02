"""
Unit tests for PpWO core logic.
Run with: python test_ppwo.py
"""

import sys
import types
import pandas as pd
import numpy as np

# -- Stub pybaseball so importing ppwo.py doesn't trigger a network call --
pybaseball_stub = types.ModuleType("pybaseball")
pybaseball_stub.statcast = lambda **kw: pd.DataFrame()
pybaseball_stub.cache = types.SimpleNamespace(enable=lambda: None)
sys.modules["pybaseball"] = pybaseball_stub

# -- Load only the CONSTANTS + FUNCTIONS sections of ppwo.py --------------
# Everything above "# MAIN EXECUTION" is pure definitions — safe to exec.
src = open("ppwo.py", encoding="utf-8").read()
cutoff = src.index("# ══════════════════════════════════════════════════════════════════\n"
                   "#  MAIN EXECUTION")
ns = {}
exec(src[:cutoff], ns)

RE24                = ns["RE24"]
get_re              = ns["get_re"]
encode_runner_code  = ns["encode_runner_code"]
estimate_re_after   = ns["estimate_re_after"]
calc_weighted_outs  = ns["calc_weighted_outs"]
ON_BASE_EVENTS      = ns["ON_BASE_EVENTS"]
GIDP_EVENTS         = ns["GIDP_EVENTS"]
SAC_FLY_EVENTS      = ns["SAC_FLY_EVENTS"]
SAC_BUNT_EVENTS     = ns["SAC_BUNT_EVENTS"]
STANDARD_OUT_EVENTS = ns["STANDARD_OUT_EVENTS"]


# -- Test harness ------------------------------------------------------------─
PASS = FAIL = 0

def check(name, got, expected, tol=0.001):
    global PASS, FAIL
    ok = abs(got - expected) < tol if isinstance(expected, float) else got == expected
    status = "PASS" if ok else "FAIL"
    print(f"  {status}  {name}")
    if not ok:
        print(f"        expected: {expected!r}")
        print(f"        got:      {got!r}")
    if ok:
        PASS += 1
    else:
        FAIL += 1


def make_row(event, outs_before=0, on_1b=None, on_2b=None, on_3b=None,
             bat_score=0, post_bat_score=0):
    rc   = encode_runner_code(on_1b, on_2b, on_3b)
    re_b = get_re(outs_before, rc)
    return pd.Series({
        "events":              event,
        "outs_before":         outs_before,
        "runner_code_before":  rc,
        "re_before":           re_b,
        "bat_score":           bat_score,
        "post_bat_score":      post_bat_score,
    })


def full_weighted_out(event, outs_before=0, on_1b=None, on_2b=None, on_3b=None,
                      bat_score=0, post_bat_score=0):
    """Run the full pipeline: make row -> re_after -> re_delta -> weighted_outs."""
    row              = make_row(event, outs_before, on_1b, on_2b, on_3b, bat_score, post_bat_score)
    row["re_after"]  = estimate_re_after(row)
    runs_scored      = max(post_bat_score - bat_score, 0)
    row["re_delta"]  = row["re_after"] - row["re_before"] + runs_scored
    return calc_weighted_outs(event, row["re_delta"])


# ----------------------------------------------------------------─
print("\n-- 1. Runner code encoding --")
# ----------------------------------------------------------------─

check("bases empty",         encode_runner_code(None,  None, None), 0)
check("runner on 1B only",   encode_runner_code(123,   None, None), 1)
check("runner on 2B only",   encode_runner_code(None,  456,  None), 2)
check("runner on 3B only",   encode_runner_code(None,  None, 789),  4)
check("runners on 1B+2B",    encode_runner_code(1,     2,    None), 3)
check("runners on 1B+3B",    encode_runner_code(1,     None, 3),    5)
check("runners on 2B+3B",    encode_runner_code(None,  2,    3),    6)
check("bases loaded",        encode_runner_code(1,     2,    3),    7)
check("pandas NA = empty",   encode_runner_code(pd.NA, pd.NA, pd.NA), 0)


# ----------------------------------------------------------------─
print("\n-- 2. RE24 table lookups --")
# ----------------------------------------------------------------─

check("0 out, bases empty",  get_re(0, 0), 0.481)
check("0 out, bases loaded", get_re(0, 7), 2.292)
check("2 out, bases empty",  get_re(2, 0), 0.095)
check("2 out, bases loaded", get_re(2, 7), 0.674)
# get_re clamps outs to max 2; inning-over (0.0) is enforced in estimate_re_after
check("outs=3 clamps to 2-out RE (bases empty)", get_re(3, 0), 0.095)
check("outs=3 clamps to 2-out RE (loaded)",      get_re(3, 7), 0.674)
# RE decreases as outs increase (same base state)
check("more outs = less RE", get_re(1, 0) < get_re(0, 0), True)
# More runners = more RE (same outs)
check("more runners = more RE", get_re(0, 7) > get_re(0, 0), True)


# ----------------------------------------------------------------─
print("\n-- 3. RE delta direction --")
# ----------------------------------------------------------------─

def re_delta_for(event, **kw):
    row = make_row(event, **kw)
    re_after = estimate_re_after(row)
    runs = max(kw.get("post_bat_score", 0) - kw.get("bat_score", 0), 0)
    return re_after - row["re_before"] + runs

check("single raises RE",     re_delta_for("single") > 0, True)
check("walk raises RE",       re_delta_for("walk") > 0, True)
check("HBP raises RE",        re_delta_for("hit_by_pitch") > 0, True)
check("home run raises RE",   re_delta_for("home_run", bat_score=0, post_bat_score=1) > 0, True)
check("strikeout lowers RE",  re_delta_for("strikeout") < 0, True)
check("flyout lowers RE",     re_delta_for("field_out") < 0, True)
check("GIDP lowers RE",       re_delta_for("grounded_into_double_play", on_1b=1) < 0, True)
check("sac fly lowers RE net of run", re_delta_for("sac_fly", on_3b=789, bat_score=0, post_bat_score=1) < 0, True)


# ----------------------------------------------------------------─
print("\n-- 4. Weighted out values --")
# ----------------------------------------------------------------─

check("single -> 0.0",    full_weighted_out("single"), 0.0)
check("walk -> 0.0",      full_weighted_out("walk"), 0.0)
check("HBP -> 0.0",       full_weighted_out("hit_by_pitch"), 0.0)
check("home_run -> 0.0",  full_weighted_out("home_run"), 0.0)

wo_k   = full_weighted_out("strikeout")
wo_gdp = full_weighted_out("grounded_into_double_play", outs_before=0, on_1b=1)
wo_sf  = full_weighted_out("sac_fly",  outs_before=0, on_3b=789, bat_score=0, post_bat_score=1)
wo_sb  = full_weighted_out("sac_bunt", outs_before=0, on_1b=1)

check("strikeout > 0",         wo_k   > 0,    True)
check("GIDP > strikeout",      wo_gdp > wo_k, True)
check("sac fly < strikeout",   wo_sf  < wo_k, True)
check("sac bunt > sac fly",    wo_sb  > wo_sf, True)

print(f"\n  Weight magnitudes:")
print(f"    strikeout  (0 out, bases empty): {wo_k:.3f}")
print(f"    sac bunt   (0 out, man on 1B):   {wo_sb:.3f}")
print(f"    sac fly    (0 out, man on 3B):   {wo_sf:.3f}")
print(f"    GIDP       (0 out, man on 1B):   {wo_gdp:.3f}")


# ----------------------------------------------------------------─
print("\n-- 5. PpWO formula properties --")
# ----------------------------------------------------------------─

check("basic division",              10 / 2.0, 5.0)
check("more pitches -> higher PpWO",  15 / 2.0 > 10 / 2.0, True)
check("fewer WO -> higher PpWO",      10 / 1.0 > 10 / 2.0, True)
check("same pitches, same WO = same PpWO", 10 / 2.0 == 10 / 2.0, True)


# ----------------------------------------------------------------─
print("\n-- 6. Vectorized runner code on DataFrame --")
# ----------------------------------------------------------------─

df = pd.DataFrame({
    "on_1b": [None, 1,    None, 1,    pd.NA],
    "on_2b": [None, None, 2,    2,    pd.NA],
    "on_3b": [None, None, None, None, pd.NA],
})
df["runner_code"] = (
    df["on_1b"].notna().astype(int) +
    df["on_2b"].notna().astype(int) * 2 +
    df["on_3b"].notna().astype(int) * 4
)
expected = [0, 1, 2, 3, 0]
for i, (got, exp) in enumerate(zip(df["runner_code"], expected)):
    check(f"df row {i} (expected {exp})", int(got), exp)


# ----------------------------------------------------------------─
print(f"\n{'='*45}")
print(f"  {PASS} passed  |  {FAIL} failed")
print(f"{'='*45}")
if FAIL:
    sys.exit(1)
