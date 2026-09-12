"""Document the upstream timestamps-repair defect that collapses whole spans (round 45).

This test pins *upstream* behaviour on purpose: `_fix_timestamps` fills an outlier block with a
single constant whenever the block touches either end of the sequence.  If a future transformers
release fixes that, this test fails — which is the signal we want, because it means the shipped
`fixed_*` values change and every downstream conclusion about zero-length damage must be re-measured.
"""

from __future__ import annotations

import pytest

pytest.importorskip("transformers")
import numpy as np  # noqa: E402
from transformers.models.qwen3_asr.processing_qwen3_asr import _fix_timestamps  # noqa: E402


def _fix(values):
    """The upstream helper calls ``raw.tolist()``, so it requires an ndarray, not a list."""
    return _fix_timestamps(np.asarray(values, dtype=float))


def test_decreasing_tail_block_is_replaced_by_a_single_constant():
    raw = [0.0, 50.0, 40.0, 30.0, 20.0, 10.0, 0.0]
    out = _fix(raw)
    assert out[0] == 0 and out[1] == 50
    # the entire trailing block becomes the same value -> zero-length characters downstream
    assert out[2:] == [50] * 5
    assert len(set(out)) == 2


def test_bounded_outlier_block_keeps_distinct_values():
    """With distinct good values on *both* sides the repair interpolates instead of collapsing."""
    raw = [0.0, 80.0, 160.0, 240.0] + [240.0 - 10.0 * i for i in range(1, 21)] + [400.0, 480.0]
    out = _fix(raw)
    assert len(set(out)) >= len(set(raw)) - 2      # no collapse
    assert out[0] < out[-1]


def test_short_outlier_blocks_snap_to_a_neighbour_and_can_duplicate():
    raw = [0.0, 80.0, 75.0, 160.0, 240.0]
    out = _fix(raw)
    assert out == sorted(out)                      # monotone, as documented
    assert len(set(out)) <= len(set(raw))          # snapping may duplicate values
