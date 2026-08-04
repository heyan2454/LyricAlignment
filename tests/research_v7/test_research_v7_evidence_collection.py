# -*- coding: utf-8 -*-
"""review9-6：evidence collection CLI（唯一 train/eval 入口）单测。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV = dict(os.environ, PYTHONPATH=str(ROOT / "src"))


def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False))


def _make_run(tmp_path, with_guard=True):
    run = tmp_path / "run"; run.mkdir()
    ev_dir = run / "evidence"; ev_dir.mkdir()
    # 两个 evidence：一个 trainable(lyrics_aligned)、一个 probe(被拒)
    train_idn = "sha256:trainable_idn"
    _write(ev_dir / f"{train_idn}.json", {
        "content_identity": train_idn,
        "attempt": {"status": "ok", "request": {
            "item_id": "song1", "canonical_timeline_file_sha": "tlf1",
            "canonical_timeline_row_sha": "tl1", "canonical_ids": [0, 1],
            "source_window_sec": [40.0, 42.0], "canonical_to_local": {"0": 0, "1": 1}}},
    })
    guard = {
        "trainable_identity_count": 1,
        "trainable": [{"request_identity": train_idn, "item_id": "song1", "request_id": "r1"}],
        "rejected": [{"item_id": "pr", "reason": "role_not_lyrics_aligned"}],
        "rejected_count": 1,
        "denominator": {"all": 2, "trainable": 1, "rejected": 1},
    }
    _write(run / "RUN_MANIFEST.json", {
        "schema": "v1", "run_id": "rl-test",
        "code_identity": {"imports_inventory": []},
        "train_filter": guard if with_guard else {"error": "none"},
        "row_audit": [], "cache_keys": [], "evidence_inventory": [], "failures": [],
        "requests_identity": [{"evaluation_role": "lyrics_aligned", "text_window_aligned": True}],
    })
    return run, train_idn


def test_collect_returns_only_trainable_evidence(tmp_path):
    run, train_idn = _make_run(tmp_path)
    out = tmp_path / "collection.json"
    r = subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/collect_trainable_evidence.py"),
                        "--run-manifest", str(run / "RUN_MANIFEST.json"), "--out", str(out)],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    c = json.loads(out.read_text())
    assert len(c["trainable_evidence"]) == 1
    assert c["trainable_evidence"][0]["request_identity"] == train_idn
    assert c["guard"]["rejected_count"] == 1
    # canonical lineage 从 evidence.request 带入 collection
    assert c["trainable_evidence"][0]["canonical_timeline_row_sha"] == "tl1"
    assert c["trainable_evidence"][0]["canonical_timeline_file_sha"] == "tlf1"
    assert c["trainable_evidence"][0]["canonical_ids"] == [0, 1]
    assert c["trainable_evidence"][0]["source_window_sec"] == [40.0, 42.0]


def test_collect_refuses_un_guarded_manifest(tmp_path):
    run, _ = _make_run(tmp_path, with_guard=False)
    out = tmp_path / "collection.json"
    r = subprocess.run([sys.executable, str(ROOT / "scripts/research_v7/collect_trainable_evidence.py"),
                        "--run-manifest", str(run / "RUN_MANIFEST.json"), "--out", str(out)],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 1
    assert "not guarded" in r.stderr
    assert not out.exists()


def test_lineage_transfer_conflict_helper():
    # review17-minor：collection 转存字段与 evidence.request 的 canonical lineage 一致性。
    # 仅“两侧都存在但冲突”失败；缺失字段（旧 evidence）容错，向后兼容。
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    from collect_trainable_evidence import _lineage_transfer_conflict
    # 一致 → 无冲突
    req = {"canonical_timeline_file_sha": "tlf1", "canonical_timeline_row_sha": "tl1",
           "source_window_sec": [40.0, 42.0]}
    assert _lineage_transfer_conflict(req, dict(req)) is None
    # 三个字段任一冲突 → 报错
    assert _lineage_transfer_conflict(req, {**req, "canonical_timeline_row_sha": "tl2"}) is not None
    assert _lineage_transfer_conflict(req, {**req, "canonical_timeline_file_sha": "x"}) is not None
    assert _lineage_transfer_conflict(req, {**req, "source_window_sec": [1.0, 2.0]}) is not None
    # 缺失字段（一侧或两侧）→ 不硬失败
    assert _lineage_transfer_conflict({}, req) is None
    assert _lineage_transfer_conflict(req, {}) is None
    assert _lineage_transfer_conflict({}, {}) is None


def test_collect_rejects_lineage_transfer_conflict(tmp_path):
    # review17-minor：collect 时若 collection 转存字段与 evidence.request 冲突必须拒绝
    # （模拟“收集时串台”：转存值来自别的 evidence）。
    import sys as _sys
    import pytest as _pt
    _sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    from collect_trainable_evidence import _verify_lineage_transfer
    run, train_idn = _make_run(tmp_path)
    ev_path = run / "evidence" / f"{train_idn}.json"
    # 转存字段被人为写成与 evidence.request 冲突的值（串台信号）
    bad_entry = {"request_identity": train_idn, "path": str(ev_path),
                 "canonical_timeline_file_sha": "tlf1",
                 "canonical_timeline_row_sha": "WRONG-ROW",
                 "source_window_sec": [40.0, 42.0]}
    with _pt.raises(ValueError) as ei:
        _verify_lineage_transfer([bad_entry])
    assert "cross-talk" in str(ei.value)
    # 字段一致 → 通过
    good_entry = {**bad_entry, "canonical_timeline_row_sha": "tl1"}
    _verify_lineage_transfer([good_entry])


def test_collect_importable():
    sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    import importlib
    m = importlib.import_module("collect_trainable_evidence")
    assert callable(m.collect)


def test_collection_has_sha_and_verified_load(tmp_path):
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    from collect_trainable_evidence import collect, finalize_collection, load_verified
    run, train_idn = _make_run(tmp_path)
    c = collect(run / "RUN_MANIFEST.json", tmp_path / "c.json")
    c = finalize_collection(c, tmp_path / "c.json")
    # 带 collection_sha256
    assert c["collection_sha256"]
    # 消费者唯一入口：校验 guard + evidence 存在
    loaded, sha = load_verified(tmp_path / "c.json")
    assert sha == c["collection_sha256"]
    assert loaded["trainable_evidence"][0]["request_identity"] == train_idn


def test_verified_load_rejects_un_guarded_collection(tmp_path):
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    from collect_trainable_evidence import load_verified
    # 手工构造缺 guard 的 collection
    run, _ = _make_run(tmp_path, with_guard=False)
    c = {"collection_sha256": "x", "trainable_evidence": [], "guard": {}}
    (tmp_path / "bad.json").write_text(json.dumps(c)) if isinstance(tmp_path, object) else None
    # guard present is False → 拒绝
    import pytest as _pt
    with _pt.raises(ValueError):
        load_verified(tmp_path / "bad.json")


def _make_evidence_with_rows(tmp_path, run, train_idn, n_units=4, gt_unsafe=(0,)):
    """给 evidence 补 decoder official rows + gt_eval（consumer 消费所需），返回 run。"""
    ev_path = run / "evidence" / f"{train_idn}.json"
    ev = json.loads(ev_path.read_text())
    rows = [{"raw_start_sec": i * 0.5, "raw_end_sec": i * 0.5 + 0.4,
             "raw_global_start_sec": i * 0.5, "raw_global_end_sec": i * 0.5 + 0.4,
             "fixed_global_start_sec": i * 0.5, "fixed_global_end_sec": i * 0.5 + 0.4}
            for i in range(n_units)]
    ev["attempt"]["decoder_outputs"] = {"official": {"rows": rows}}
    ev["attempt"]["gt_eval"] = {"unsafe_unit_indices": list(gt_unsafe)}
    ev_path.write_text(json.dumps(ev))
    return run


def test_assessor_consumer_records_collection_sha_and_denominator(tmp_path):
    """review11-4：真实 consumer 只消费 guarded collection，run manifest 记录
    collection SHA、实际 train/eval 分母与输出路径。"""
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    from collect_trainable_evidence import collect, finalize_collection
    run, train_idn = _make_run(tmp_path)
    _make_evidence_with_rows(tmp_path, run, train_idn, n_units=4, gt_unsafe=(0, 1))
    c = finalize_collection(collect(run / "RUN_MANIFEST.json", tmp_path / "c.json"),
                            tmp_path / "c.json")
    from assessor_train_eval import consume
    out = tmp_path / "asr"
    m = consume(tmp_path / "c.json", out)
    assert m["collection_sha256"] == c["collection_sha256"]
    assert m["denominator"]["trainable_evidence"] == 1
    assert m["denominator"]["units"] == 4
    assert m["denominator"]["items"] == 1
    assert m["labels"]["available"] is True
    # operating points 来自 val 冻结
    assert isinstance(m["assessor"]["operating_points"], dict)
    assert "high_recall_95" in m["assessor"]["operating_points"]
    # 输出路径全部写出
    for fp in m["outputs"].values():
        assert Path(fp).is_file()
    # features 每行带 identity + features
    rows = [json.loads(l) for l in (out / "UNIT_FEATURES.jsonl").read_text().splitlines()]
    assert len(rows) == 4
    assert all(r["request_identity"] == train_idn for r in rows)


def test_assessor_consumer_refuses_no_labels(tmp_path):
    """review11-4：无 gt_eval 标签的 evidence → labels_available=false，拒绝产 operating points。
    review12 C3：CLI 对无标签返回非零退出码（防止 formal 管线误当训练成功）。"""
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    from collect_trainable_evidence import collect, finalize_collection
    from assessor_train_eval import consume
    run, train_idn = _make_run(tmp_path)
    _make_evidence_with_rows(tmp_path, run, train_idn, n_units=2, gt_unsafe=())
    ev = json.loads((run / "evidence" / f"{train_idn}.json").read_text())
    del ev["attempt"]["gt_eval"]  # 无标签
    (run / "evidence" / f"{train_idn}.json").write_text(json.dumps(ev))
    c = finalize_collection(collect(run / "RUN_MANIFEST.json", tmp_path / "c2.json"),
                            tmp_path / "c2.json")
    m = consume(tmp_path / "c2.json", tmp_path / "asr2")
    assert m["labels"]["available"] is False
    assert m["assessor"]["operating_points"] is None
    assert m["assessor"]["model"] is None  # round04/op-persist：无标签不伪造权重
    assert "no gt_eval" in (m["assessor"]["reason"] or "")
    assert m["denominator"]["units"] == 2  # 特征仍被提取审计
    # CLI 对无标签返回非零退出码（formal 检测用）
    import subprocess as _sp
    r = _sp.run([sys.executable, str(ROOT / "scripts/research_v7/assessor_train_eval.py"),
                 "--collection", str(tmp_path / "c2.json"), "--out", str(tmp_path / "asr2cli")],
                capture_output=True, text=True, env=ENV)
    assert r.returncode == 2, r.stderr


def test_assessor_consumer_rejects_un_guarded_collection(tmp_path):
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    from assessor_train_eval import consume
    bad = {"schema": "research_v7_trainable_evidence_collection_v1",
           "collection_sha256": "x", "trainable_evidence": [], "guard": {}}
    (tmp_path / "badc.json").write_text(json.dumps(bad))
    import pytest as _pt
    with _pt.raises(ValueError):
        consume(tmp_path / "badc.json", tmp_path / "asr3")


def test_assessor_consumer_aligns_feature_columns_across_rows(tmp_path):
    """review11：不同 evidence 行特征键集合不一致（如缺 official geometry）时，
    consumer 按统一 feature_keys 对齐（缺失填 0.0），不得因列形状不一致崩溃。"""
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    from collect_trainable_evidence import collect, finalize_collection
    from assessor_train_eval import consume
    run, train_idn = _make_run(tmp_path)
    _make_evidence_with_rows(tmp_path, run, train_idn, n_units=2, gt_unsafe=(0,))
    # 行0 有 official geometry；行1 缺 official 键（模拟不同 decoder 输出）→ 键集不同
    ev_path = run / "evidence" / f"{train_idn}.json"
    ev = json.loads(ev_path.read_text())
    rows = ev["attempt"]["decoder_outputs"]["official"]["rows"]
    del rows[1]["fixed_global_start_sec"]
    del rows[1]["fixed_global_end_sec"]
    ev_path.write_text(json.dumps(ev))
    c = finalize_collection(collect(run / "RUN_MANIFEST.json", tmp_path / "c3.json"),
                            tmp_path / "c3.json")
    m = consume(tmp_path / "c3.json", tmp_path / "asr4")
    assert m["labels"]["available"] is True
    assert isinstance(m["assessor"]["operating_points"], dict)  # 列对齐成功，可训练
    # feature_keys 是跨行并集且每行都按同一键序
    assert "official_duration_sec" in m["feature_keys"]
    rows_out = [json.loads(l) for l in (Path(m["outputs"]["features"]).read_text().splitlines())]
    assert len(rows_out) == 2
    # 行1 缺 official 几何 → 其 official_duration_sec 为 None（键仍存在但值 None）
    # 该键不进 feature_keys（统一列只含数值键）；特征矩阵仍可训练
    assert any(fr["features"].get("official_duration_sec") is None for fr in rows_out)


def test_assessor_consumer_persists_model_weights(tmp_path):
    """round04/op-persist：consume 持久化冻结权重（beta/mean/std + feature_keys），
    供 T4 对 MIR 打分；manifest schema 升 v2 并记录 v1 兼容说明。"""
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    from collect_trainable_evidence import collect, finalize_collection
    from assessor_train_eval import consume, ASSESSOR_MANIFEST_SCHEMA
    run, train_idn = _make_run(tmp_path)
    _make_evidence_with_rows(tmp_path, run, train_idn, n_units=4, gt_unsafe=(0, 1))
    c = finalize_collection(collect(run / "RUN_MANIFEST.json", tmp_path / "c4.json"),
                            tmp_path / "c4.json")
    m = consume(tmp_path / "c4.json", tmp_path / "asr5")
    # schema v2 + v1 兼容说明
    assert m["schema"] == ASSESSOR_MANIFEST_SCHEMA == "research_v7_assessor_consumer_run_v2"
    assert "v1" in (m.get("schema_note") or "")
    model = m["assessor"]["model"]
    assert isinstance(model, dict)
    for k in ("beta", "mean", "std"):
        assert isinstance(model[k], list) and len(model[k]) > 0
        assert all(isinstance(v, float) for v in model[k])  # numpy → float list
    # feature_keys 与模型列一一对应（beta 含截距 = d+1；mean/std = d）
    assert model["feature_keys"] == m["feature_keys"]
    d = len(m["feature_keys"])
    assert len(model["beta"]) == d + 1
    assert len(model["mean"]) == d == len(model["std"])
    # ASSESSOR.json 落盘内容与 manifest 一致（加载方直接读文件）
    on_disk = json.loads((tmp_path / "asr5" / "ASSESSOR.json").read_text())
    assert on_disk["model"] == model
    assert on_disk["model"]["feature_keys"] == m["feature_keys"]


def test_load_assessor_legacy_without_model_returns_none(tmp_path):
    """round04/op-persist：_load_assessor() 对无 model 字段的旧 v1 文件/缺失文件
    返回 (None, reason)，对 v2 文件返回 (assessor, None)——加载方兼容性保证。"""
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    from assessor_train_eval import _load_assessor
    # 旧 v1：无 model 字段
    legacy = tmp_path / "legacy_ASSESSOR.json"
    _write(legacy, {"labels_available": True,
                    "operating_points": {"high_recall_95": 0.9}})
    a, reason = _load_assessor(legacy)
    assert a is None and reason and "model" in reason
    # 文件不存在
    a, reason = _load_assessor(tmp_path / "nope.json")
    assert a is None and reason
    # 损坏 JSON
    bad = tmp_path / "bad_ASSESSOR.json"
    bad.write_text("{not json")
    a, reason = _load_assessor(bad)
    assert a is None and reason and "unreadable" in reason
    # 不完整 model（缺 std）
    partial = tmp_path / "partial_ASSESSOR.json"
    _write(partial, {"model": {"beta": [0.1], "mean": [0.2]}})
    a, reason = _load_assessor(partial)
    assert a is None and reason and "std" in reason
    # 合法 v2：返回 assessor + None
    ok = tmp_path / "ok_ASSESSOR.json"
    _write(ok, {"labels_available": True,
                "model": {"beta": [0.1], "mean": [0.2], "std": [0.3], "feature_keys": ["f1"]}})
    a, reason = _load_assessor(ok)
    assert a is not None and reason is None
    assert a["model"]["feature_keys"] == ["f1"]
