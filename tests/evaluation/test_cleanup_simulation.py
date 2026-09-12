"""Fast tests for the GT-free cleanup-rule simulation (synthetic raw/selected geometry)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lyricalign.analysis import cleanup_simulation as C

VIEW = "b4_60s_windowed"


def _frame() -> pd.DataFrame:
    """One song with a gross negative interval, an overlap, a regression and a clean unit."""
    raw_s = [0.0, 1.0, 3.0, 2.0, 5.0]
    raw_e = [0.8, 0.5, 4.5, 2.6, 5.4]          # unit 1 negative, unit 2 overlaps unit 3 order
    sel_s = [0.0, 1.0, 3.0, 3.0, 5.0]
    sel_e = [0.8, 1.0, 3.0, 2.6, 5.4]          # shipped collapses unit 2 and 3
    rows = []
    for i in range(len(raw_s)):
        rows.append({"song": "s1", "language": "Chinese", "unit_index": i, "unit_type": "cjk_character",
                     f"{VIEW}__rs": raw_s[i], f"{VIEW}__re": raw_e[i],
                     f"{VIEW}__s": sel_s[i], f"{VIEW}__e": sel_e[i],
                     f"{VIEW}__ent_s": 0.2 + 0.3 * i, f"{VIEW}__ent_e": 0.9 - 0.1 * i,
                     f"{VIEW}__mar_min": np.nan})
    return pd.DataFrame(rows)


def test_structure_flags_raw_defects_and_caps_mass():
    out = C.simulate(_frame(), view=VIEW)
    assert out["units"] == 5
    raw = out["raw_structure"]
    assert raw["negative_share"] == pytest.approx(1 / 5)
    assert raw["degenerate_share"] == pytest.approx(1 / 5)
    assert raw["overshoot_units_share"] == 0.0
    # plausible mass caps instead of summing the absurd
    assert raw["plausible_mass_sec"] == pytest.approx(
        min(0.8, 3.0) + 0.0 + min(1.5, 3.0) + min(0.6, 3.0) + min(0.4, 3.0), abs=1e-6)


def test_rules_never_manufacture_degenerate_units_except_shipped():
    out = C.simulate(_frame(), view=VIEW)
    r = out["rules"]
    assert r["R1_shipped"]["degenerate_share"] > r["R0_none"]["degenerate_share"]
    for name in ("R3_end_trim_min0.05s", "R6_clip_then_trim", "R7_clip_only"):
        assert r[name]["negative_share"] == 0.0
        assert r[name]["degenerate_share"] == 0.0
    assert "R6_clip_then_trim" in out["ranking_by_degenerate_share"]


def test_clip_only_preserves_more_mass_than_shipped():
    out = C.simulate(_frame(), view=VIEW)
    r = out["rules"]
    assert r["R7_clip_only"]["plausible_mass_lost_share"] <= r["R1_shipped"]["plausible_mass_lost_share"]
    assert r["R6_clip_then_trim"]["plausible_mass_lost_share"] < r["R1_shipped"]["plausible_mass_lost_share"]


def test_naive_monotone_repair_moves_almost_everything():
    """Documented negative control: force-ordering starts ratchets after a single gross raw
    interval, so it moves nearly every unit (on the production panel: 97.9% moved, overlap 97.9%)."""
    out = C.simulate(_frame(), view=VIEW)
    r = out["rules"]
    assert r["R2_monotone_clamp"]["share_units_moved"] >= r["R6_clip_then_trim"]["share_units_moved"]
    assert r["R2_monotone_clamp"]["start_regression_share"] == 0.0
    assert r["R6_clip_then_trim"]["overlap_share"] <= r["R2_monotone_clamp"]["overlap_share"]


def test_missing_view_columns_are_handled():
    df = _frame().drop(columns=[f"{VIEW}__ent_s"])
    out = C.simulate(df, view=VIEW)
    assert out["available"] is False
    assert out["missing"] == [f"{VIEW}__ent_s"]
