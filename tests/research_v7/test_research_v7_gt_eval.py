# -*- coding: utf-8 -*-
"""round01：GT 逐字符评价（formal 指标分子计算）单测 —— 纯内存 fixture，无模型/真实数据。

fixture：1 条合成 timeline（song=s1, 20 canonical units, 每单位 1s）+ baseline/missing 配对。
- baseline 全对：unit_recall=1.0（空集约定：无真 unsafe 且未误报），fpr=0。
- missing 删尾部（canonical [0..13]，被删=[14..19]）：解码输出越界行（gci 14..17，
  对齐偏移落进被删区）→ unsafe_pred={14..17}，unit_recall=4/6 非零分子；
  pred gap=窗尾-末行尾 → gap_event_recall=1.0、omitted 加权=1.0。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENV = dict(os.environ, PYTHONPATH=str(ROOT / "src"))

TIMELINE = {
    "song_id": "s1",
    "canonical_units": [
        {"canonical_unit_id": i, "text": chr(ord("a") + i), "start_sec": float(i),
         "end_sec": float(i + 1)}
        for i in range(20)
    ],
}


def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False))


def _rows(n: int, chars: list[str], offset: int = 0) -> list[dict]:
    """gci i -> 时间 [i, i+1)（相对窗起点 offset）。"""
    return [{
        "global_character_index": i,
        "character": chars[i],
        "raw_start_sec": float(i), "raw_end_sec": float(i + 1),
        "raw_global_start_sec": float(offset + i), "raw_global_end_sec": float(offset + i + 1),
        "official_fixed_global_start_sec": float(offset + i),
        "official_fixed_global_end_sec": float(offset + i + 1),
        "fixed_global_start_sec": float(offset + i), "fixed_global_end_sec": float(offset + i + 1),
    } for i in range(n)]


def _make_run(tmp_path, missing_n_rows=18) -> Path:
    """构造 run 目录：timeline + baseline evidence + missing evidence。"""
    run = tmp_path / "run"; run.mkdir()
    ev_dir = run / "evidence"; ev_dir.mkdir()
    (run / "formal").mkdir()
    (tmp_path / "formal_manifest").mkdir()
    _write(tmp_path / "formal_manifest" / "LONG_TIMELINE_MANIFEST.jsonl", TIMELINE)

    text = [chr(ord("a") + i) for i in range(20)]
    _write(ev_dir / "sha256:baseline.json", {
        "content_identity": "sha256:baseline",
        "attempt": {
            "status": "ok",
            "request": {
                "request_id": "s1:w0:full", "item_id": "s1:w0:full",
                "mutation_type": "baseline",
                "canonical_text_start": 0, "canonical_text_end": 20,
                "canonical_ids": list(range(20)),
                "canonical_to_local": {str(i): i for i in range(20)},
                "text_units": text, "source_window_sec": [0.0, 20.0],
            },
            "decoder_outputs": {"official": {"rows": _rows(20, text)}},
        },
    })
    missing_text = text[:14]
    rows = _rows(missing_n_rows, text[:missing_n_rows])
    _write(ev_dir / "sha256:missing.json", {
        "content_identity": "sha256:missing",
        "attempt": {
            "status": "ok",
            "request": {
                "request_id": "s1:w0:full:missing", "item_id": "s1:w0:full:missing",
                "mutation_type": "missing",
                "canonical_text_start": 0, "canonical_text_end": 14,
                "canonical_ids": list(range(14)),
                "canonical_to_local": {str(i): i for i in range(14)},
                "text_units": missing_text, "source_window_sec": [0.0, 20.0],
            },
            "decoder_outputs": {"official": {"rows": rows}},
        },
    })
    return run


def _run_cli(run_root, out) -> dict:
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/research_v7/evaluate_long_slot_gt.py"),
         "--run-root", str(run_root), "--timeline-manifest",
         str(run_root.parent / "formal_manifest" / "LONG_TIMELINE_MANIFEST.jsonl"),
         "--out", str(out)],
        capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    return json.loads(out.read_text())


def test_gt_eval_missing_tail_deletion_nonzero_numerator(tmp_path):
    """missing 删尾部（含对齐偏移越界行）→ unit_recall 非零分子；gap recall=1。"""
    run = _make_run(tmp_path, missing_n_rows=18)  # gci 14..17 越界落入被删区
    out = tmp_path / "gt_eval_out" / "GT_EVAL.json"
    g = _run_cli(run, out)

    assert g["schema"] == "research_v7_gt_eval_v1"
    assert g["gt_axis_note"] == "synthetic_uniform_timeline_axis (not human GT)"
    m = g["metrics"]
    # 共同评分子集：text 覆盖 canonical ids = baseline 20 + missing 14（与 RUN_MANIFEST
    # metrics.n_units 同口径）；n_decoder_rows 为实际解码行数（可少于子集）
    assert m["n_units_evaluated"] == 20 + 14
    assert m["n_decoder_rows"] == 20 + 18
    assert m["n_baseline"] == 1 and m["n_missing"] == 1
    # 被删尾部 = baseline.canonical_ids[14:] = [14..19]
    assert m["n_truly_unsafe_gt_units"] == 6
    assert m["n_unsafe_pred_units"] == 4
    assert m["n_hit"] == 4 and m["n_fn"] == 2
    assert abs(m["unit_recall"] - round(4 / 6, 4)) < 1e-9  # 非零分子
    assert m["correct_unit_fpr"] == 0.0
    assert m["n_gt_gaps"] == 1 and m["n_gap_hits"] == 1
    assert m["gap_recall"] == 1.0 and m["gap_weighted_recall"] == 1.0
    # 输出可序列化且无 null 指标
    assert all(v is not None for v in (m["unit_recall"], m["correct_unit_fpr"],
                                       m["gap_recall"], m["gap_weighted_recall"]))
    json.dumps(g, ensure_ascii=False)  # round-trip 可序列化

    by_rid = {r["request_id"]: r for r in g["per_request"]}
    b = by_rid["s1:w0:full"]
    assert b["unit"]["unit_recall"] == 1.0  # baseline 全对（空集约定）
    assert b["unit"]["correct_unit_fpr"] == 0.0
    miss = by_rid["s1:w0:full:missing"]
    assert miss["unit"]["truly_unsafe_canonical_ids"] == list(range(14, 20))
    assert miss["unit"]["unsafe_pred_canonical_ids"] == [14, 15, 16, 17]
    assert abs(miss["unit"]["unit_recall"] - round(4 / 6, 4)) < 1e-9
    assert miss["gap"]["gap_event_recall"] == 1.0
    assert miss["gap"]["gap_size_sec"] == pytest.approx(2.0)
    assert miss["gap"]["omitted_canonical_ids"] == list(range(14, 20))


def test_gt_eval_missing_real_shape_no_offset_rows(tmp_path):
    """真实形状（rows 全在请求文本内，无越界行）→ unsafe_pred 空、unit_recall=0、
    fn 覆盖全部被删单位；gap 仍检出。"""
    run = _make_run(tmp_path, missing_n_rows=14)
    out = tmp_path / "gt_eval_out2" / "GT_EVAL.json"
    g = _run_cli(run, out)
    m = g["metrics"]
    assert m["n_units_evaluated"] == 20 + 14
    assert m["n_decoder_rows"] == 20 + 14
    assert m["n_truly_unsafe_gt_units"] == 6
    assert m["n_hit"] == 0 and m["n_fn"] == 6
    assert m["unit_recall"] == 0.0
    assert m["gap_recall"] == 1.0 and m["gap_weighted_recall"] == 1.0
    by_rid = {r["request_id"]: r for r in g["per_request"]}
    miss = by_rid["s1:w0:full:missing"]
    assert miss["unit"]["n_hit"] == 0 and miss["unit"]["n_fn"] == 6
    assert miss["gap"]["gap_size_sec"] == pytest.approx(6.0)


def test_gt_eval_baseline_only_vacuous_perfect(tmp_path):
    """只有 baseline（无 missing 配对）→ 空集约定 pooled unit_recall=1.0。"""
    run = _make_run(tmp_path, missing_n_rows=14)
    (run / "evidence" / "sha256:missing.json").unlink()
    out = tmp_path / "gt_eval_out3" / "GT_EVAL.json"
    g = _run_cli(run, out)
    m = g["metrics"]
    assert m["n_baseline"] == 1 and m["n_missing"] == 0
    assert m["unit_recall"] == 1.0
    assert m["correct_unit_fpr"] == 0.0
    assert m["n_units_evaluated"] == 20

def test_gt_eval_rows_join_timeline(tmp_path):
    """row -> canonical id join 到 timeline：GT start/end 落在 timeline 单位区间。"""
    run = _make_run(tmp_path, missing_n_rows=18)
    out = tmp_path / "gt_eval_out4" / "GT_EVAL.json"
    g = _run_cli(run, out)
    rows = g["rows"]
    assert len(rows) == 38
    for row in rows:
        cid = row["canonical_unit_id"]
        assert row["gt_start_sec"] == float(cid)
        assert row["gt_end_sec"] == float(cid + 1)
        assert row["pred_start_sec"] == row["gt_start_sec"]
    missing_rows = [r for r in rows if r["mutation_type"] == "missing"]
    oob = [r for r in missing_rows if r["canonical_unit_id"] >= 14]
    assert [r["canonical_unit_id"] for r in oob] == [14, 15, 16, 17]


def test_evaluate_importable_and_api(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    import importlib
    m = importlib.import_module("evaluate_long_slot_gt")
    assert callable(m.evaluate)
    run = _make_run(tmp_path, missing_n_rows=18)
    res = m.evaluate(run, run.parent / "formal_manifest" / "LONG_TIMELINE_MANIFEST.jsonl")
    assert res["schema"] == "research_v7_gt_eval_v1"
    assert res["metrics"]["n_units_evaluated"] == 34
    assert res["metrics"]["n_decoder_rows"] == 38
    assert res["metrics"]["unit_recall"] == round(4 / 6, 4)


def test_gt_eval_missing_without_baseline_skipped_not_inflated(tmp_path):
    """round1 review MAJOR：missing 请求无配对 baseline evidence 时不得按
    '无真 unsafe' 评价（那会把 recall 真空膨成 1.0）；应计入 skipped。"""
    sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    import evaluate_long_slot_gt as m
    run = tmp_path / "run"; ev_dir = run / "evidence"; ev_dir.mkdir(parents=True)
    req = {
        "request_id": "s1:w0:full:missing", "item_id": "s1:w0:full:missing",
        "mutation_type": "missing", "song_id": "s1", "text_units": [chr(97 + i) for i in range(14)],
        "text_start_index": 0, "text_end_index": 14,
        "canonical_ids": list(range(14)), "canonical_to_local": {"0": 0, "1": 1},
        "source_window_sec": [0.0, 20.0],
    }
    rows = _rows(14, [chr(97 + i) for i in range(14)], offset=0)
    ev = {"content_identity": "x", "attempt": {"status": "ok", "request": req,
          "decoder_outputs": {"official": {"rows": rows}}}}
    (ev_dir / "e1.json").write_text(json.dumps(ev))
    tl = tmp_path / "timeline.jsonl"
    tl.write_text(json.dumps(TIMELINE) + "\n")
    # 无任何 baseline evidence（只有一条 missing）
    res = m.evaluate(run_root=run, timeline_manifest=tl)
    assert res["metrics"]["n_evidence_skipped"] == 1, res
    assert res["metrics"]["n_missing"] == 0, res   # missing 未评价（无 baseline 配对）
    assert res["metrics"]["n_units_evaluated"] == 0
    assert res["metrics"]["unit_recall"] is None or res["metrics"]["unit_recall"] != 1.0
