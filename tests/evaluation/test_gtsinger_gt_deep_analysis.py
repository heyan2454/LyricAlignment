"""Fast (L1) tests for the GTSinger ground-truth deep-analysis modules.

Synthetic fixtures only: no dependency on the external data directory, so these
run in well under a second and can be executed by every implementation agent.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from lyricalign.analysis import gtsinger_gt_deep as deep
from lyricalign.analysis import gtsinger_gt_evidence as gge


def _gt_row(word: str, start: float, end: float, *, ph=("k", "ai"), notes=(55,)) -> dict:
    return {
        "word": word, "start_time": start, "end_time": end,
        "ph": list(ph), "ph_start": [start] * len(ph), "ph_end": [end] * len(ph),
        "note": list(notes), "note_dur": [end - start] * len(notes),
        "note_start": [start] * len(notes), "note_end": [end] * len(notes),
        "mix": ["0"] * len(ph), "falsetto": ["0"] * len(ph), "breathy": ["0"] * len(ph),
        "pharyngeal": ["0"] * len(ph), "glissando": ["0"] * len(ph), "vibrato": ["0"] * len(ph),
        "tech": "0", "singing_method": "pop", "pace": "fast", "range": "medium",
        "emotion": "sad",
    }


def _alignment(units, *, audio_sha: str, model: str, mode: str, audio_name: str,
               pin_start_to_prev_end: bool = False) -> dict:
    chars = []
    prev_end = None
    for i, (start, end) in enumerate(units):
        raw_start, raw_end = start, end
        sel_start, sel_end = start, end
        if pin_start_to_prev_end and prev_end is not None and prev_end > raw_start:
            sel_start = prev_end  # mimic the official overlap-resolution rule
        chars.append({
            "global_character_index": i, "character": f"c{i}", "unit_type": "cjk_character",
            "decoder_kind": "official",
            "raw_global_start_sec": raw_start, "raw_global_end_sec": raw_end,
            "fixed_global_start_sec": sel_start, "fixed_global_end_sec": sel_end,
            "selected_start_sec": sel_start, "selected_end_sec": sel_end,
            "raw_start_top1_probability": 0.9 - 0.1 * i, "raw_end_top1_probability": 0.8,
            "raw_start_margin": 0.7, "raw_end_margin": 0.6,
            "raw_start_entropy": 0.3, "raw_end_entropy": 0.4,
            "raw_boundary_margin_mean": 0.65, "candidate_count": 1,
            "inference_source": mode, "cross_window_repaired": False,
        })
        prev_end = sel_end
    trace = [{"window_index": 0, "core_start_sec": 0.0, "core_end_sec": 20.0,
              "committed_character_start": 0, "committed_character_end": len(units),
              "left_context_character_count": 0,
              "serial_policy": "silence_aware_global_core_plan_v7"}] if mode == "windowed" else []
    return {
        "schema_version": "test", "identity": {
            "model_name": model, "revision": "rev1", "audio_name": audio_name,
            "audio": {"path": f"/data/{audio_name}.wav", "sha256": audio_sha},
            "mode": mode, "window": ({"core_sec": 20.0, "left_context_sec": 0.0,
                                      "policy": "silence_aware_global_core_plan_v7"}
                                     if mode == "windowed" else None),
            "decoder": {"kind": "official"}, "checkpoint": {"checkpoint_kind": "lora",
                                                            "checkpoint_path": "/ckpt"},
            "request_hash": f"rh-{model}-{audio_name}-{mode}",
        },
        "summary": {"audio_duration_sec": 20.0, "language": "Chinese",
                    "alignment_unit_mode": "cjk_character_or_latin_word",
                    "character_count": len(units)},
        "characters": chars,
        "window_trace": trace, "lines": [],
    }


@pytest.fixture()
def fake_run(tmp_path: Path) -> Path:
    """One segment, 3 units, the 12 labelled configs, mix and vocal share one wav."""
    run_root = tmp_path / "runs" / "20260816_evaluation_v1_gtsinger_diag_all"
    run_root.mkdir(parents=True, exist_ok=True)
    gt = [_gt_row("应", 0.0, 0.4), _gt_row("该", 0.4, 0.8), _gt_row("开", 0.8, 1.2),
          _gt_row("<AP>", 1.2, 1.3), _gt_row("心", 1.3, 1.6)]
    gt_json = run_root / "0000.json"
    gt_json.write_text(json.dumps(gt), encoding="utf-8")
    item = run_root / "gtsinger_ZH-Tenor-1__Glissando__x__Control_Group__0000"
    units_pred = [(0.0, 0.4), (0.5, 0.8), (0.8, 1.2), (1.3, 1.6)]
    for model in ("r0", "r1", "r2"):
        for audio in ("mix", "vocal"):
            for mode in ("full", "windowed"):
                path = item / "alignments" / model / audio / mode
                path.mkdir(parents=True, exist_ok=True)
                doc = _alignment(units_pred, audio_sha="SAME-SHA", model=model, mode=mode,
                                 audio_name=audio, pin_start_to_prev_end=(model == "r2"))
                (path / "alignment.json").write_text(json.dumps(doc), encoding="utf-8")
    (run_root / "gt_map.jsonl").write_text(
        json.dumps({"gt_json": str(gt_json), "out_dir": item.name}) + "\n", encoding="utf-8")
    return run_root


def test_ap_filtering_and_join():
    rows = gge.clean_gt_rows([{"word": "<AP>", "start_time": 0, "end_time": 1},
                              {"word": "<AP/>", "start_time": 1, "end_time": 2},
                              {"word": "应", "start_time": 2, "end_time": 3}])
    assert [r["word"] for r in rows] == ["应"]


def test_extract_item_rows_and_provenance(fake_run: Path):
    stats = gge.ExtractionStats()
    rows = list(gge.extract_item(
        fake_run / "gtsinger_ZH-Tenor-1__Glissando__x__Control_Group__0000",
        fake_run / "0000.json", gge.RunSpec.infer(fake_run), stats))
    # 4 GT units after <AP> filtering x 12 labelled configs
    assert len(rows) == 48
    assert stats.configs_ok == 12 and stats.configs_skipped == 0
    win = [r for r in rows if r["model"] == "r2" and r["mode"] == "windowed"]
    assert len(win) == 8                                    # 2 audio labels x 4 units
    r2 = win[1]                                             # unit index 1, overlap-resolved
    assert r2["pred_start_sec"] == 0.5 and r2["raw_start_sec"] == 0.5
    assert r2["start_err_signed_sec"] == pytest.approx(0.1)
    assert r2["audio_sha256"] == "SAME-SHA" and r2["request_hash"].startswith("rh-")
    assert r2["window_index"] == 0 and r2["units_from_window_start"] == 1
    full = [r for r in rows if r["model"] == "r0" and r["mode"] == "full"]
    assert "window_index" not in full[0]                    # full has no window provenance
    first = full[0]
    assert first["gt_start_sec"] == 0.0 and first["gt_ph_count"] == 2
    assert first["gt_is_melisma"] == 0 and first["gt_is_multi_phoneme"] == 1


def test_extract_skips_count_mismatch(fake_run: Path):
    bad = fake_run / "gtsinger_ZH-Tenor-1__Glissando__x__Control_Group__0000"
    p = bad / "alignments" / "r1" / "mix" / "full" / "alignment.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["characters"] = doc["characters"][:2]
    p.write_text(json.dumps(doc), encoding="utf-8")
    stats = gge.ExtractionStats()
    rows = list(gge.extract_item(bad, fake_run / "0000.json", gge.RunSpec.infer(fake_run), stats))
    assert len(rows) == 44
    assert stats.configs_skipped == 1
    assert any("count_mismatch:r1/mix/full" in s["reason"] for s in stats.items_skipped)


def test_auc_orientation_and_run_lengths():
    y = np.array([0, 0, 1, 1, 0, 1], dtype=float)
    s_good = np.array([0.9, 0.8, 0.1, 0.2, 0.7, 0.05])
    assert deep._auc(y, s_good) == pytest.approx(0.0)      # perfect inverse ranking
    assert deep._auc(y, -s_good) == pytest.approx(1.0)
    counts = deep._run_length_counts([np.array([1, 1, 0, 1, 0, 1, 1, 1])])
    assert counts == {2: 1.0, 1: 1.0, 3: 1.0}


def test_confidence_frame_disagreement_and_labels():
    rows = []
    for model, shift in (("r0", 0.0), ("r1", 0.2), ("r2", 0.4)):
        for mode in ("full", "windowed"):
            for i, (gs, ge) in enumerate(((0.0, 0.4), (0.4, 0.8))):
                rows.append({
                    "run": "R", "pipeline": "official", "item": "it", "unit_index": i,
                    "model": model, "audio_input": "vocal", "mode": mode,
                    "singer": "s", "group": "g", "technique": "t", "song": "x",
                    "segment": str(i), "gt_start_sec": gs, "gt_end_sec": ge,
                    "gt_dur_sec": ge - gs, "gt_is_melisma": 0, "gt_is_multi_phoneme": 1,
                    "gt_note_count": 1, "gt_ph_count": 1, "gt_ph_dur_max_sec": 0.4,
                    "unit_pos_frac": i, "units_from_window_start": i,
                    "units_from_window_end": 1 - i, "pace": "fast", "range": "m",
                    "emotion": "e", "raw_margin_start": 0.5, "raw_margin_end": 0.5,
                    "raw_top1_start": 0.7, "raw_top1_end": 0.7, "raw_entropy_start": 0.2,
                    "raw_entropy_end": 0.2, "raw_boundary_margin_mean": 0.5,
                    "pred_start_sec": gs + shift, "pred_end_sec": ge + shift,
                    "raw_start_sec": gs + shift, "raw_end_sec": ge + shift,
                    "start_err_signed_sec": shift, "end_err_signed_sec": shift,
                    "start_abs_err_sec": abs(shift), "end_abs_err_sec": abs(shift),
                    "both_abs_err_sec": abs(shift), "iou": 0.5, "dur_err_sec": 0.0,
                    "center_offset_sec": shift, "seg_key": "R|it",
                    "unit_key": f"R|it|{model}|vocal|{mode}",
                })
    frame = deep.build_confidence_frame(pd.DataFrame(rows))
    r1 = frame[(frame["model"] == "r1") & (frame["mode"] == "windowed")]
    # other models are r0 (0.0) and r2 (0.4) -> LOO mean 0.2 -> |0.2-0.2| = 0
    assert np.allclose(r1["sig_model_loo_start"].to_numpy(dtype=float), 0.0)
    r0 = frame[(frame["model"] == "r0") & (frame["mode"] == "windowed")]
    assert np.allclose(r0["sig_model_loo_start"].to_numpy(dtype=float), 0.3)  # mean(0.2, 0.4)
    # full-cell LOO is diluted by duplicated cells (same value appears twice)
    # duplicated cells pull the LOO mean toward the row's own value (0.24 < 0.3)
    assert float(r0["sig_disagree_loo_start"].max()) == pytest.approx(0.24)
    assert set(frame["bad100"].unique()) <= {0.0, 1.0}
    assert "oracle_dur_ratio_err" in frame.columns


def test_matrix_audit_flags_identical_audio_inputs():
    rows = []
    for m_idx, model in enumerate(("r0", "r1")):
        for audio in ("mix", "vocal"):
            for mode in ("full", "windowed"):
                for i in range(2):
                    rows.append({"run": "R", "pipeline": "official", "item": "it",
                                 "model": model, "audio_input": audio, "mode": mode,
                                 "unit_index": i, "audio_sha256": "SAME",
                                 "pred_start_sec": float(i) + 0.1 * m_idx,
                                 "pred_end_sec": float(i) + 0.4 + 0.1 * m_idx})
    out = deep.compute_matrix(pd.DataFrame(rows))
    per = out["per_run"]["R"]
    assert per["items"] == 1
    assert per["audio_sha_distinct_per_item_min"] == 1
    assert per["share_items_mix_equals_vocal_audio"] == 1.0
    assert per["distinct_prediction_vectors_per_item_mean"] == 2.0
    assert per["redundancy_factor"] == pytest.approx(4.0)  # 8 labelled cells / 2 vectors


def test_postprocess_mechanism_detects_pinned_start():
    # unit 1's raw start is correct but overlaps unit 0's late raw tail, so the
    # overlap-resolution rule pins it to the previous end and thereby damages it.
    rows = [
        {"run": "R", "pipeline": "official", "item": "it", "model": "r2",
         "audio_input": "vocal", "mode": "windowed", "unit_index": 0,
         "gt_start_sec": 0.0, "gt_end_sec": 0.6,
         "raw_start_sec": 0.0, "raw_end_sec": 0.8,
         "pred_start_sec": 0.0, "pred_end_sec": 0.8,
         "start_abs_err_sec": 0.0, "end_abs_err_sec": 0.2, "both_abs_err_sec": 0.2,
         "start_err_signed_sec": 0.0, "end_err_signed_sec": 0.2,
         "raw_margin_start": 0.5, "raw_margin_end": 0.5, "raw_top1_start": 0.5,
         "raw_top1_end": 0.5, "raw_entropy_start": 0.5, "raw_entropy_end": 0.5},
        {"run": "R", "pipeline": "official", "item": "it", "model": "r2",
         "audio_input": "vocal", "mode": "windowed", "unit_index": 1,
         "gt_start_sec": 0.7, "gt_end_sec": 1.2,
         "raw_start_sec": 0.7, "raw_end_sec": 1.2,
         "pred_start_sec": 0.8, "pred_end_sec": 1.2,
         "start_abs_err_sec": 0.1, "end_abs_err_sec": 0.0, "both_abs_err_sec": 0.1,
         "start_err_signed_sec": 0.1, "end_err_signed_sec": 0.0,
         "raw_margin_start": 0.5, "raw_margin_end": 0.5, "raw_top1_start": 0.5,
         "raw_top1_end": 0.5, "raw_entropy_start": 0.5, "raw_entropy_end": 0.5},
    ]
    out = deep.compute_postprocess(pd.DataFrame(rows))
    block = out["r2_vocal_windowed"]
    mech = block["mechanism"]
    assert mech["n_start_moved"] == 1
    assert mech["start_moved"]["share_pinned_to_prev_end"] == pytest.approx(1.0)
    assert mech["start_moved"]["direction_later"] == 1
    assert mech["final_zero_duration_share"] < mech["raw_zero_duration_share"] + 1e-9
    assert block["touched"]["damage_rate_both"] == pytest.approx(1.0)
    assert block["touched"]["flips_out_of_tol"] == 1
