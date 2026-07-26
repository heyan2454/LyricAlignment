from __future__ import annotations

import importlib.util
from pathlib import Path


def load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "demo" / "run_mir1k_demo_diagnostics.py"
    spec = importlib.util.spec_from_file_location("run_mir1k_demo_diagnostics_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_candidate_bounds_separates_matched_and_omitted_left_text() -> None:
    module = load_module()
    gt = [
        {"character_index": i, "start_sec": float(i), "end_sec": float(i) + 0.8}
        for i in range(12)
    ]
    matched = module.candidate_bounds(
        gt,
        input_start_sec=2.0,
        input_end_sec=7.0,
        core_start_sec=4.0,
        core_end_sec=6.0,
        future_text_sec=2.0,
        left_text_policy="matched",
    )
    omitted = module.candidate_bounds(
        gt,
        input_start_sec=2.0,
        input_end_sec=7.0,
        core_start_sec=4.0,
        core_end_sec=6.0,
        future_text_sec=2.0,
        left_text_policy="omit",
    )
    assert matched[0] < omitted[0]
    assert matched[1] == omitted[1]
    assert matched[2] == [4, 5]


def test_metric_summary_keeps_onset_and_offset_separate() -> None:
    module = load_module()
    rows = [
        {"onset_abs_error_sec": 0.1, "offset_abs_error_sec": 0.2,
         "onset_signed_error_sec": 0.1, "offset_signed_error_sec": -0.2},
        {"onset_abs_error_sec": 0.3, "offset_abs_error_sec": 0.4,
         "onset_signed_error_sec": -0.3, "offset_signed_error_sec": 0.4},
    ]
    summary = module.metric_summary(rows)
    assert summary["onset_mae_sec"] == 0.2
    assert summary["offset_mae_sec"] == 0.30000000000000004
    assert summary["onset_within_0p16_rate"] == 0.5
    assert summary["joint_onset_offset_within_0p24_rate"] == 0.5


def test_oracle_trial_uses_gt_only_for_coverage_and_evaluation(monkeypatch) -> None:
    from types import SimpleNamespace
    import numpy as np

    module = load_module()
    document = module.parse_lyrics_text("甲乙丙丁戊己庚辛壬癸\n", language="Chinese")
    gt = [
        {
            "character_index": index,
            "normalized_character": meta.text,
            "start_sec": index * 6.0 + 1.0,
            "end_sec": index * 6.0 + 2.0,
        }
        for index, meta in enumerate(document.characters)
    ]

    def fake_infer_slice(*, document, character_start, character_end, **kwargs):
        rows = []
        for index in range(character_start, character_end):
            row = gt[index]
            rows.append({
                "global_character_index": index,
                "raw_global_start_sec": row["start_sec"],
                "raw_global_end_sec": row["end_sec"],
                "fixed_global_start_sec": row["start_sec"],
                "fixed_global_end_sec": row["end_sec"],
                "raw_start_top1_probability": 0.9,
                "raw_end_top1_probability": 0.9,
                "raw_start_margin": 0.5,
                "raw_end_margin": 0.5,
                "raw_start_entropy": 0.2,
                "raw_end_entropy": 0.2,
            })
        return rows, {"candidate_count": character_end - character_start}

    monkeypatch.setattr(module.SERIAL, "infer_slice", fake_infer_slice)
    args = SimpleNamespace(
        oracle_core_sec=30.0,
        left_context_sec=10.0,
        right_context_sec=10.0,
    )
    result = module.oracle_trial(
        processor=object(),
        model=object(),
        audio=np.zeros(65 * 16000, dtype=np.float32),
        document=document,
        gt=gt,
        args=args,
        future_text_sec=5.0,
        left_text_policy="matched",
    )
    assert result["metrics"]["processor_decoded"]["missing_unit_count"] == 0
    assert result["metrics"]["processor_decoded"]["onset_mae_sec"] == 0.0
    assert len(result["windows"]) == 2
