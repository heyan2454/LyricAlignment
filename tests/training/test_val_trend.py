"""CPU tests for the block-bootstrap validation-trend test."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("analyze_val_trend", ROOT / "scripts" / "training" / "analyze_val_trend.py")
assert SPEC and SPEC.loader
TREND = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TREND)


def test_ols_slope_is_percentage_points_per_thousand_steps():
    line = [(step, 0.5 + 0.001 * step / 1000.0) for step in range(0, 2000, 50)]
    assert TREND.ols_slope(line) == pytest.approx(0.1, abs=1e-9)
    assert TREND.ols_slope([(0, 0.3)]) == 0.0


def test_window_difference_reports_percentage_points_and_its_interval_contains_it():
    points = [(step, 0.5) for step in range(0, 500, 50)] + [(step, 0.6) for step in range(500, 1000, 50)]
    assert TREND.window_difference(points, window=5) == pytest.approx(10.0, abs=1e-9)
    out = TREND.analyse(points, block=2, resamples=300, window=5)
    interval = out["window_difference_pp"]
    assert interval["low"] == pytest.approx(interval["estimate"], abs=1e-9)
    assert interval["high"] == pytest.approx(interval["estimate"], abs=1e-9)
    assert out["verdict"] == "rising"


def test_block_bootstrap_of_a_constant_series_has_a_zero_width_interval():
    points = [(step, 0.7) for step in range(0, 1000, 50)]
    out = TREND.block_bootstrap(points, TREND.ols_slope, block=5, resamples=200)
    assert out["estimate"] == pytest.approx(0.0, abs=1e-12)
    assert out["low"] == pytest.approx(0.0, abs=1e-12) and out["high"] == pytest.approx(0.0, abs=1e-12)


def test_analyse_flags_a_noisy_line_with_no_slope_as_flat():
    import random
    rng = random.Random(7)
    points = [(step, 0.9 + rng.gauss(0, 0.01)) for step in range(0, 2000, 50)]
    out = TREND.analyse(points, block=5, resamples=500)
    assert out["verdict"] == "flat_within_noise"
    assert out["points"] == 40 and out["span_steps"] == 1950


def test_read_points_uses_the_latest_record_per_step_and_skips_garbage(tmp_path: Path):
    import json
    path = tmp_path / "funnel_evals.jsonl"
    path.write_text("\n".join([
        json.dumps({"funnel_eval": {"evaluated_step": 50, "level": "l1", "se": 0.1,
                                    "variants": {"fixed": {"macro_within_primary": 0.5}}}}),
        json.dumps({"funnel_eval": {"evaluated_step": 50, "level": "l1", "se": 0.1,
                                    "variants": {"fixed": {"macro_within_primary": 0.6}}}}),
        json.dumps({"funnel_eval": {"evaluated_step": 50, "level": "l2",
                                    "variants": {"fixed": {"macro_within_primary": 0.9}}}}),
        "{oops"]), encoding="utf-8")
    assert TREND.read_points(path, "fixed") == [(50, 0.6)]
