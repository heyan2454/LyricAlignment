# -*- coding: utf-8 -*-
"""round02：MIR 跨域 eval CLI（--domain mir1k）单测 —— 纯内存 fixture，无模型/真实数据。

fixture 仿 test_research_v7_gt_eval.py：1 条合成 timeline（song=s1, 20 canonical units,
每单位 1s）+ baseline/missing 配对。
- 评价逻辑与 T1 完全同一套（复用 evaluate_evidence/evaluate 纯函数），配对规则不变：
  missing 无 baseline 配对时计入 skipped、不得把 recall 真空膨成 1.0。
- mir1k 域输出：schema=research_v7_mir1k_cross_domain_eval_v1、domain="mir1k"、
  gt_axis_note=weak_labeled_qwen_fa_timestamps…、默认输出 MIR_CROSS_DOMAIN_EVAL.json、
  m4_reference 在 --m4-gt-eval 存在时并列（只读三键）、缺省 None。
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

MIR1K_SCHEMA = "research_v7_mir1k_cross_domain_eval_v1"
MIR1K_GT_AXIS_NOTE = "weak_labeled_qwen_fa_timestamps (validation_basis=null, not human GT)"


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
    """构造 run 目录：MIR timeline manifest + baseline evidence + missing evidence。"""
    run = tmp_path / "run"; run.mkdir()
    ev_dir = run / "evidence"; ev_dir.mkdir()
    (run / "formal").mkdir()
    (tmp_path / "formal_manifest").mkdir()
    _write(tmp_path / "formal_manifest" / "MIR_TIMELINE_MANIFEST.jsonl", TIMELINE)

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


def _run_cli(run_root, out, extra=None) -> dict:
    cmd = [sys.executable, str(ROOT / "scripts/research_v7/evaluate_long_slot_gt.py"),
           "--run-root", str(run_root), "--timeline-manifest",
           str(run_root.parent / "formal_manifest" / "MIR_TIMELINE_MANIFEST.jsonl"),
           "--domain", "mir1k", "--out", str(out)]
    if extra:
        cmd.extend(extra)
    r = subprocess.run(cmd, capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    return json.loads(out.read_text())


def test_mir1k_domain_schema_fields_and_metrics(tmp_path):
    """--domain mir1k：schema/domain/gt_axis_note 正确；metrics 与 T1 同口径非空。"""
    run = _make_run(tmp_path, missing_n_rows=18)
    out = tmp_path / "eval_out" / "MIR_CROSS_DOMAIN_EVAL.json"
    g = _run_cli(run, out)

    assert g["schema"] == MIR1K_SCHEMA
    assert g["domain"] == "mir1k"
    assert g["gt_axis_note"] == MIR1K_GT_AXIS_NOTE
    assert g["m4_reference"] is None  # 未提供 --m4-gt-eval
    m = g["metrics"]
    # 与 T1 相同的配对/分子语义（合成 fixture 数值与 test_research_v7_gt_eval 一致）
    assert m["n_units_evaluated"] == 20 + 14
    assert m["n_decoder_rows"] == 20 + 18
    assert m["n_baseline"] == 1 and m["n_missing"] == 1
    assert m["n_truly_unsafe_gt_units"] == 6
    assert m["n_unsafe_pred_units"] == 4
    assert m["n_hit"] == 4 and m["n_fn"] == 2
    assert abs(m["unit_recall"] - round(4 / 6, 4)) < 1e-9
    assert m["correct_unit_fpr"] == 0.0
    assert m["n_gt_gaps"] == 1 and m["n_gap_hits"] == 1
    assert m["gap_recall"] == 1.0 and m["gap_weighted_recall"] == 1.0
    assert all(v is not None for v in (m["unit_recall"], m["correct_unit_fpr"],
                                       m["gap_recall"], m["gap_weighted_recall"]))
    json.dumps(g, ensure_ascii=False)  # round-trip 可序列化

    by_rid = {r["request_id"]: r for r in g["per_request"]}
    assert by_rid["s1:w0:full"]["unit"]["unit_recall"] == 1.0
    miss = by_rid["s1:w0:full:missing"]
    assert miss["unit"]["truly_unsafe_canonical_ids"] == list(range(14, 20))
    assert miss["unit"]["unsafe_pred_canonical_ids"] == [14, 15, 16, 17]
    assert miss["gap"]["gap_size_sec"] == pytest.approx(2.0)
    assert miss["gap"]["omitted_canonical_ids"] == list(range(14, 20))


def test_mir1k_metrics_identical_to_m4_domain(tmp_path):
    """同一 evidence 下 mir1k 与 m4 域 metrics 完全一致（仅 GT 轴来源/标注不同）。"""
    run = _make_run(tmp_path, missing_n_rows=18)
    out_m4 = tmp_path / "eval_out_m4" / "GT_EVAL.json"
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/research_v7/evaluate_long_slot_gt.py"),
         "--run-root", str(run), "--timeline-manifest",
         str(run.parent / "formal_manifest" / "MIR_TIMELINE_MANIFEST.jsonl"),
         "--domain", "m4", "--out", str(out_m4)],
        capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    m4 = json.loads(out_m4.read_text())
    out_mir = tmp_path / "eval_out_mir" / "MIR_CROSS_DOMAIN_EVAL.json"
    mir = _run_cli(run, out_mir)
    assert m4["schema"] == "research_v7_gt_eval_v1"
    assert "domain" not in m4 and "m4_reference" not in m4  # m4 域保持 T1 现有行为
    assert m4["metrics"] == mir["metrics"]
    assert m4["per_request"] == mir["per_request"]


def test_mir1k_default_out_path(tmp_path):
    """不传 --out 时：mir1k 写 <run-root>/MIR_CROSS_DOMAIN_EVAL.json；m4 写 GT_EVAL.json。"""
    run = _make_run(tmp_path, missing_n_rows=14)
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/research_v7/evaluate_long_slot_gt.py"),
         "--run-root", str(run), "--timeline-manifest",
         str(run.parent / "formal_manifest" / "MIR_TIMELINE_MANIFEST.jsonl"),
         "--domain", "mir1k"],
        capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    assert (run / "MIR_CROSS_DOMAIN_EVAL.json").is_file()
    assert not (run / "GT_EVAL.json").exists()
    r2 = subprocess.run(
        [sys.executable, str(ROOT / "scripts/research_v7/evaluate_long_slot_gt.py"),
         "--run-root", str(run), "--timeline-manifest",
         str(run.parent / "formal_manifest" / "MIR_TIMELINE_MANIFEST.jsonl"),
         "--domain", "m4"],
        capture_output=True, text=True, env=ENV)
    assert r2.returncode == 0, r2.stderr
    assert (run / "GT_EVAL.json").is_file()


def test_mir1k_m4_reference_present_when_provided(tmp_path):
    """--m4-gt-eval 指向真实 M4 GT_EVAL.json 时，m4_reference 只读三键并列展示。"""
    run = _make_run(tmp_path, missing_n_rows=18)
    m4_eval = tmp_path / "m4_gt" / "GT_EVAL.json"
    _write(m4_eval, {
        "schema": "research_v7_gt_eval_v1",
        "metrics": {"unit_recall": 0.75, "gap_recall": 0.9,
                    "n_units_evaluated": 340, "n_decoder_rows": 999},
        "per_request": [], "rows": [],
    })
    out = tmp_path / "eval_out2" / "MIR_CROSS_DOMAIN_EVAL.json"
    g = _run_cli(run, out, extra=["--m4-gt-eval", str(m4_eval)])
    ref = g["m4_reference"]
    assert ref == {"unit_recall": 0.75, "gap_recall": 0.9, "n_units_evaluated": 340}
    # 并列展示不影响本域 metrics（不合并分母）
    assert g["metrics"]["n_units_evaluated"] == 34
    # 只取三个并列键，不透传其他字段
    assert "n_decoder_rows" not in ref


def test_mir1k_m4_reference_none_when_missing_file(tmp_path):
    """--m4-gt-eval 指向不存在的文件（或未提供）→ m4_reference 缺省 None。"""
    run = _make_run(tmp_path, missing_n_rows=18)
    out = tmp_path / "eval_out3" / "MIR_CROSS_DOMAIN_EVAL.json"
    g = _run_cli(run, out, extra=["--m4-gt-eval", str(tmp_path / "nope" / "GT_EVAL.json")])
    assert g["m4_reference"] is None
    assert g["metrics"]["unit_recall"] is not None


def test_m4_domain_m4_gt_eval_warns_stderr(tmp_path):
    """T1：domain=m4 时传 --m4-gt-eval → stderr 有 warn，行为（忽略）不变。"""
    run = _make_run(tmp_path, missing_n_rows=18)
    m4_eval = tmp_path / "m4_gt" / "GT_EVAL.json"
    _write(m4_eval, {
        "schema": "research_v7_gt_eval_v1",
        "metrics": {"unit_recall": 0.75, "gap_recall": 0.9, "n_units_evaluated": 340},
    })
    out = tmp_path / "eval_out_m4w" / "GT_EVAL.json"
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/research_v7/evaluate_long_slot_gt.py"),
         "--run-root", str(run), "--timeline-manifest",
         str(run.parent / "formal_manifest" / "MIR_TIMELINE_MANIFEST.jsonl"),
         "--domain", "m4", "--m4-gt-eval", str(m4_eval), "--out", str(out)],
        capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    assert "warning" in r.stderr and "--m4-gt-eval ignored" in r.stderr
    g = json.loads(out.read_text())
    assert "m4_reference" not in g  # m4 域输出不携带 m4_reference（行为不变）


def test_m4_reference_malformed_json_returns_none(tmp_path):
    """T1：--m4-gt-eval 文件 malformed JSON → 不崩、m4_reference=None、stderr 有原因。"""
    run = _make_run(tmp_path, missing_n_rows=18)
    bad = tmp_path / "m4_gt" / "GT_EVAL.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{not valid json!!")
    out = tmp_path / "eval_out_bad" / "MIR_CROSS_DOMAIN_EVAL.json"
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/research_v7/evaluate_long_slot_gt.py"),
         "--run-root", str(run), "--timeline-manifest",
         str(run.parent / "formal_manifest" / "MIR_TIMELINE_MANIFEST.jsonl"),
         "--domain", "mir1k", "--m4-gt-eval", str(bad), "--out", str(out)],
        capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    assert "warning" in r.stderr and "m4-gt-eval unreadable" in r.stderr
    g = json.loads(out.read_text())
    assert g["m4_reference"] is None
    assert g["metrics"]["unit_recall"] is not None


def test_mir1k_missing_without_baseline_skipped_not_inflated(tmp_path):
    """配对规则与 T1 一致：missing 无配对 baseline evidence → 计入 skipped，
    unit_recall 不得被真空膨成 1.0。"""
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
    res = m.evaluate(run_root=run, timeline_manifest=tl, domain="mir1k")
    assert res["schema"] == MIR1K_SCHEMA
    assert res["domain"] == "mir1k"
    assert res["m4_reference"] is None
    assert res["metrics"]["n_evidence_skipped"] == 1, res
    assert res["metrics"]["n_missing"] == 0
    assert res["metrics"]["n_units_evaluated"] == 0
    assert res["metrics"]["unit_recall"] is None or res["metrics"]["unit_recall"] != 1.0


def test_evaluate_api_domain_validation_and_defaults(tmp_path):
    """evaluate() API：m4 为默认域；非法 domain 抛 ValueError。"""
    sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    import evaluate_long_slot_gt as m
    run = _make_run(tmp_path, missing_n_rows=18)
    tl = run.parent / "formal_manifest" / "MIR_TIMELINE_MANIFEST.jsonl"
    res = m.evaluate(run, tl)  # 默认 domain=m4，保持 T1 兼容
    assert res["schema"] == "research_v7_gt_eval_v1"
    assert "domain" not in res
    with pytest.raises(ValueError):
        m.evaluate(run, tl, domain="demo")
    res = m.evaluate(run, tl, domain="mir1k", m4_gt_eval=None)
    assert res["schema"] == MIR1K_SCHEMA
    assert res["metrics"]["unit_recall"] == round(4 / 6, 4)
