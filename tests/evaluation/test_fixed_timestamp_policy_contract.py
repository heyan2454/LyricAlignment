"""Contract tests for the fixed-timestamp policy switch (round 48).

The switch exists so the mainline can adopt the measured repair without changing today's behaviour.
These tests protect the two properties that make that safe: the writer's default must remain
``upstream_repaired``, and the row-level application must be a no-op at that default.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

WRITER = Path(__file__).resolve().parents[2] / "scripts" / "demo" / "align_qwen_fa_serial_demo.py"


def _policy_argument() -> ast.Call:
    tree = ast.parse(WRITER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_argument":
            if node.args and isinstance(node.args[0], ast.Constant) \
                    and node.args[0].value == "--fixed-timestamp-policy":
                return node
    raise AssertionError("--fixed-timestamp-policy not found in the writer")


def test_writer_default_is_the_current_behaviour():
    call = _policy_argument()
    kwargs = {k.arg: k.value for k in call.keywords}
    assert isinstance(kwargs["default"], ast.Constant)
    assert kwargs["default"].value == "upstream_repaired", \
        "the default must stay identical to today's product behaviour"
    choices = kwargs["choices"]
    assert isinstance(choices, ast.Tuple)
    names = [c.value for c in choices.elts]
    assert names[0] == "upstream_repaired" and "raw_with_targeted_repair" in names


def test_writer_applies_the_policy_before_any_research_decoder_hook():
    """The rewrite must happen right after the row loop, upstream of other decoders."""
    src = WRITER.read_text(encoding="utf-8")
    policy_at = src.index("fixed_policy = str(getattr(args,")
    # the *call*, not the import line, is the ordering constraint
    decoder_at = src.index("rows = apply_research_timestamp_decoder(")
    assert policy_at < decoder_at


def test_default_policy_returns_the_official_values_untouched():
    import numpy as np
    from lyricalign.analysis.monotone_repair import apply_fixed_timestamp_policy

    raw_s, raw_e = np.array([0.0, 1.0]), np.array([0.9, 1.9])
    off_s, off_e = np.array([4.0, 4.0]), np.array([4.0, 4.0])
    res = apply_fixed_timestamp_policy(raw_s, raw_e, off_s, off_e)
    assert np.array_equal(res["starts"], off_s) and np.array_equal(res["ends"], off_e)
