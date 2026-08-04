# -*- coding: utf-8 -*-
"""round04 T4：跨域 assessor 评价 CLI 单测 —— 纯内存 fixture（合成 assessor + MIR collection），
不依赖真实模型/真实数据。

- 合成 m4_assessor：小 beta/mean/std + feature_keys 与 unit_features 输出键匹配；
- 合成 mir1k collection：2 evidence、official rows 带 raw_*/official_fixed_global_* 字段、
  gt_eval 含 unsafe_unit_indices（弱标签）；
- 断言：输出 schema/两域字段、打分不崩、unsafe_rate 数值合理、缺 model 字段的旧 assessor
  → 非零退出且报错、feature 键对齐缺失填 0。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENV = dict(os.environ, PYTHONPATH=str(ROOT / "src"))

SCHEMA = "research_v7_assessor_cross_domain_eval_v1"
GT_AXIS_NOTE = "weak_labeled_qwen_fa_timestamps (not human GT)"
FEATURE_KEYS = ["official_duration_sec", "raw_duration_sec", "raw_zero"]


def _rows(n: int, dur: float) -> list[dict]:
    return [{
        "global_character_index": i,
        "character": chr(97 + i),
        "raw_start_sec": i * dur, "raw_end_sec": (i + 1) * dur,
        "raw_global_start_sec": i * dur, "raw_global_end_sec": (i + 1) * dur,
        "official_fixed_global_start_sec": i * dur,
        "official_fixed_global_end_sec": (i + 1) * dur,
    } for i in range(n)]


_UNSET = object()


def _make_assessor(tmp_path, *, weights=None, mean=0.5, std=1.0, feature_keys=None,
                   operating_points=_UNSET, with_model=True, name="ASSESSOR.json") -> Path:
    fkeys = feature_keys if feature_keys is not None else FEATURE_KEYS
    if weights is None:
        weights = {k: (0.5 if k == "raw_duration_sec" else 0.0) for k in fkeys}
    model = {
        "beta": [0.0] + [weights.get(k, 0.0) for k in fkeys],
        "mean": [mean] * len(fkeys),
        "std": [std] * len(fkeys),
        "feature_keys": fkeys,
    }
    data = {"operating_points": {"high_recall_95": 0.52, "high_recall_99": 0.6}}
    if operating_points is not _UNSET:
        data["operating_points"] = operating_points  # None → 省略键（触发 model 默认）
    if with_model:
        data["model"] = model
    p = tmp_path / name
    p.write_text(json.dumps(data))
    return p


def _make_collection(tmp_path, *, specs=((1.0, (0, 1)), (0.2, (2,))),
                     name="mir1k_collection.json") -> Path:
    """合成 MIR collection：specs = [(row_duration, gt_unsafe_indices), ...] 每项一份 evidence。"""
    ev_dir = tmp_path / "mir1k_ev"
    ev_dir.mkdir(exist_ok=True)
    entries = []
    for k, (dur, gt) in enumerate(specs):
        rid = f"s1:w0:full:{k}"
        ev = {
            "content_identity": f"sha256:e{k}",
            "attempt": {
                "status": "ok",
                "request": {
                    "request_id": rid, "item_id": f"s1:{k}",
                    "mutation_type": "baseline",
                    "text_units": [chr(97 + i) for i in range(4)],
                    "canonical_ids": list(range(4)),
                    "canonical_to_local": {str(i): i for i in range(4)},
                    "source_window_sec": [0.0, 4.0],
                    "canonical_timeline_file_sha": "tlf",
                    "canonical_timeline_row_sha": "tlr",
                },
                "decoder_outputs": {"official": {"rows": _rows(4, dur)}},
                "gt_eval": {"unsafe_unit_indices": list(gt)},
            },
        }
        p = ev_dir / f"{rid}.json"
        p.write_text(json.dumps(ev))
        entries.append({
            "request_identity": rid,
            "path": str(p),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "canonical_ids": list(range(4)),
            "canonical_timeline_file_sha": "tlf",
            "canonical_timeline_row_sha": "tlr",
            "source_window_sec": [0.0, 4.0],
        })
    collection = {
        "schema": "research_v7_trainable_evidence_collection_v1",
        "run_id": "mir1k-synth",
        "guard": {"present": True, "trainable_count": len(entries), "rejected_count": 0},
        "trainable_evidence": entries,
    }
    data = json.dumps(collection, ensure_ascii=False, sort_keys=True).encode("utf-8")
    collection["collection_sha256"] = hashlib.sha256(data).hexdigest()
    cp = tmp_path / name
    cp.write_text(json.dumps(collection))
    return cp


def _run_cli(assessor: Path, collection: Path, out: Path):
    cmd = [sys.executable, str(ROOT / "scripts/research_v7/evaluate_cross_domain_assessor.py"),
           "--m4-assessor", str(assessor),
           "--mir1k-collection", str(collection),
           "--out", str(out)]
    return subprocess.run(cmd, capture_output=True, text=True, env=ENV)


def _load_out(out: Path) -> dict:
    return json.loads((out / "ASSESSOR_CROSS_DOMAIN_EVAL.json").read_text(encoding="utf-8"))


def test_cross_domain_schema_and_two_domain_fields(tmp_path):
    """输出 schema/两域字段：m4_assessor 冻结信息 + mir1k 打分指标，GT 轴弱标签注明。"""
    ap = _make_assessor(tmp_path)
    cp = _make_collection(tmp_path)
    out = tmp_path / "out"
    r = _run_cli(ap, cp, out)
    assert r.returncode == 0, r.stderr
    g = _load_out(out)

    assert g["schema"] == SCHEMA
    assert g["gt_axis_note"] == GT_AXIS_NOTE
    assert "never merged" in g["note"]

    m4 = g["m4_assessor"]
    assert m4["operating_points"] == {"high_recall_95": 0.52, "high_recall_99": 0.6}
    assert m4["operating_points_source"] == "assessor"
    assert m4["model_feature_keys"] == FEATURE_KEYS
    assert m4["n_features"] == len(FEATURE_KEYS)

    m = g["mir1k"]
    for k in ("n_units", "n_unsafe_pred_95", "n_unsafe_pred_99", "unsafe_rate_95",
              "unsafe_rate_99", "unit_recall_95", "unit_recall_99",
              "correct_unit_fpr_95", "correct_unit_fpr_99",
              "n_evidence", "n_rows"):
        assert k in m, k
    assert set(m["score_distribution"]) == {"min", "p50", "p90", "max"}


def test_cross_domain_metrics_values(tmp_path):
    """打分数值：dur=1.0（proba≈0.562）在 0.52 阈值下全判 unsafe、0.6 下不判；
    dur=0.2（proba≈0.463）两阈值均不判。弱标签 recall/FPR 分母正确。"""
    ap = _make_assessor(tmp_path)
    cp = _make_collection(tmp_path)
    out = tmp_path / "out2"
    r = _run_cli(ap, cp, out)
    assert r.returncode == 0, r.stderr
    m = _load_out(out)["mir1k"]

    assert m["n_evidence"] == 2
    assert m["n_rows"] == 8 and m["n_units"] == 8
    assert m["n_units_labeled"] == 8 and m["n_label_errors"] == 0
    assert m["n_gt_unsafe_units"] == 3
    # dur=1.0 行（4 个）proba≈0.562：>0.52 且 <0.6
    assert m["n_unsafe_pred_95"] == 4 and m["n_unsafe_pred_99"] == 0
    assert m["unsafe_rate_95"] == 0.5 and m["unsafe_rate_99"] == 0.0
    # 弱标签：gt unsafe 3 个（ev1 的 0,1 + ev2 的 2）；hit95=2（ev1 的 0,1）
    assert m["unit_recall_95"] == round(2 / 3, 4)
    assert m["unit_recall_99"] == 0.0
    # FPR 分母 = 正确保留 unit = 8 - 3 = 5；fp95=2（ev1 的 2,3）
    assert m["correct_unit_fpr_95"] == 0.4
    assert m["correct_unit_fpr_99"] == 0.0
    # 分数分布：4×0.463、4×0.562
    d = m["score_distribution"]
    assert 0.46 < d["min"] < 0.47
    assert 0.51 < d["p50"] < 0.52
    assert 0.56 < d["p90"] <= d["max"] < 0.57
    # leak 审计：unit_features 不泄漏 GT/mutation 字段
    assert m["leak_check"]["ok"] is True and m["leak_check"]["leak_keys"] == []


def test_old_assessor_without_model_fails_nonzero(tmp_path):
    """旧格式 ASSESSOR.json（只有 operating_points、无 model）→ 非零退出 + 明确报错。"""
    ap = _make_assessor(tmp_path, with_model=False)
    cp = _make_collection(tmp_path)
    r = _run_cli(ap, cp, tmp_path / "out3")
    assert r.returncode != 0
    assert "lacks persisted model weights" in r.stderr
    assert "op persistence" in r.stderr
    assert not (tmp_path / "out3" / "ASSESSOR_CROSS_DOMAIN_EVAL.json").exists()


def test_assessor_missing_weight_key_raises(tmp_path):
    """model 缺 feature_keys 等权重键 → load_m4_assessor 抛 ValueError。"""
    sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    import evaluate_cross_domain_assessor as m
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"model": {"beta": [0.0], "mean": [0.0]}}))
    with pytest.raises(ValueError) as ei:
        m.load_m4_assessor(bad)
    assert "missing weights keys" in str(ei.value)


def test_feature_alignment_fills_missing_with_zero(tmp_path):
    """model feature_keys 含 MIR 行不产的键（hidden_*、phantom）：缺失填 0 不打崩。
    ghost_feature 权重 5.0、mean=10：若真按 0 对齐 → z=-50 → proba≈0。"""
    fkeys = FEATURE_KEYS + ["hidden_start_norm", "ghost_feature"]
    ap = _make_assessor(tmp_path, weights={"ghost_feature": 5.0},
                        mean=10.0, std=1.0, feature_keys=fkeys, name="ASSESSOR2.json")
    cp = _make_collection(tmp_path)
    out = tmp_path / "out4"
    r = _run_cli(ap, cp, out)
    assert r.returncode == 0, r.stderr
    g = _load_out(out)
    assert g["m4_assessor"]["n_features"] == 5
    m = g["mir1k"]
    assert m["n_units"] == 8
    assert m["score_distribution"]["max"] < 0.01  # 缺失键按 0 处理（NaN 会污染分布）
    assert m["unsafe_rate_95"] == 0.0 and m["unsafe_rate_99"] == 0.0
    assert m["unit_recall_95"] == 0.0


def test_operating_points_model_default_when_missing(tmp_path):
    """ASSESSOR.json 无 operating_points → 用 model 默认 0.5（两阈值同判）。"""
    ap = _make_assessor(tmp_path, operating_points=None, name="ASSESSOR3.json")
    cp = _make_collection(tmp_path)
    out = tmp_path / "out5"
    r = _run_cli(ap, cp, out)
    assert r.returncode == 0, r.stderr
    g = _load_out(out)
    m4 = g["m4_assessor"]
    assert m4["operating_points"] == {"high_recall_95": 0.5, "high_recall_99": 0.5}
    assert m4["operating_points_source"] == "model_default"
    m = g["mir1k"]
    # dur=1.0 行 proba≈0.562 > 0.5：两阈值同判 unsafe
    assert m["n_unsafe_pred_95"] == 4 and m["n_unsafe_pred_99"] == 4


def test_empty_collection_reports_null_metrics(tmp_path):
    """空 collection：n_units=0 时 recall 为 None、分布四键全 None，不虚构 1.0。"""
    ap = _make_assessor(tmp_path)
    collection = {
        "schema": "research_v7_trainable_evidence_collection_v1",
        "run_id": "mir1k-empty",
        "guard": {"present": True, "trainable_count": 0, "rejected_count": 0},
        "trainable_evidence": [],
    }
    data = json.dumps(collection, ensure_ascii=False, sort_keys=True).encode("utf-8")
    collection["collection_sha256"] = hashlib.sha256(data).hexdigest()
    cp = tmp_path / "empty_collection.json"
    cp.write_text(json.dumps(collection))
    out = tmp_path / "out6"
    r = _run_cli(ap, cp, out)
    assert r.returncode == 0, r.stderr
    m = _load_out(out)["mir1k"]
    assert m["n_evidence"] == 0 and m["n_units"] == 0
    assert m["unit_recall_95"] is None and m["unit_recall_99"] is None
    assert m["score_distribution"] == {"min": None, "p50": None, "p90": None, "max": None}
