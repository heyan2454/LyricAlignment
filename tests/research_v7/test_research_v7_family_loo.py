# -*- coding: utf-8 -*-
"""round18：family 分层 + per-song LOO（13 §10.3/§10.2）单测。

覆盖：collection 的 mutation_type 转存、--split-by song 歌隔离（同歌 request 不跨折）、
--family 过滤（family 只用于分层不进特征）、family-LOO 输出结构。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
ENV = dict(os.environ, PYTHONPATH=str(ROOT / "src"))


def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False))


def _make_rows(n_units: int, offset: float = 0.0) -> list[dict]:
    """合成 decoder official rows：raw margin 随索引单调，供判别器可分离。"""
    rows = []
    for i in range(n_units):
        rows.append({
            "raw_start_sec": offset + i * 0.5,
            "raw_end_sec": offset + i * 0.5 + 0.4,
            "raw_global_start_sec": offset + i * 0.5,
            "raw_global_end_sec": offset + i * 0.5 + 0.4,
            "fixed_global_start_sec": offset + i * 0.5,
            "fixed_global_end_sec": offset + i * 0.5 + 0.4,
            "raw_start_margin": 0.2 + 0.1 * i,
            "raw_end_margin": 0.2 + 0.1 * i,
        })
    return rows


def _make_run(tmp_path, songs=("songA", "songB"), families=("baseline", "missing"),
              items_per_song=2, n_units=6):
    """合成 guarded run：songs × families × items_per_song 份 evidence。"""
    run = tmp_path / "run"
    ev_dir = run / "evidence"
    trainable = []
    for song in songs:
        for fam in families:
            for it in range(items_per_song):
                idn = f"sha256:{song}:{fam}:{it}"
                _write(ev_dir / f"{idn}.json", {
                    "content_identity": idn,
                    "attempt": {
                        "status": "ok",
                        "request": {
                            "item_id": f"{song}:w0:slot{it}:{fam}",
                            "mutation_type": fam,
                            "canonical_timeline_file_sha": "tlf1",
                            "canonical_timeline_row_sha": "tl1",
                            "canonical_ids": list(range(n_units)),
                            "source_window_sec": [0.0, 6.0],
                            "canonical_to_local": {str(i): i for i in range(n_units)},
                        },
                        "decoder_outputs": {"official": {"rows": _make_rows(n_units, offset=it * 6)}},
                        "gt_eval": {"unsafe_unit_indices": [0, 1] if it % 2 == 0 else [3]},
                    },
                })
                trainable.append({"request_identity": idn, "item_id": f"{song}:w0:slot{it}:{fam}",
                                  "request_id": idn})
    _write(run / "RUN_MANIFEST.json", {
        "schema": "v1", "run_id": "fl-test", "code_identity": {"imports_inventory": []},
        "train_filter": {"trainable_identity_count": len(trainable), "trainable": trainable,
                         "rejected": [], "rejected_count": 0,
                         "denominator": {"all": len(trainable), "trainable": len(trainable),
                                         "rejected": 0}},
        "row_audit": [], "cache_keys": [], "evidence_inventory": [], "failures": [],
        "requests_identity": [{"evaluation_role": "lyrics_aligned", "text_window_aligned": True}],
    })
    return run


def _make_collection(tmp_path):
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    from collect_trainable_evidence import collect, finalize_collection
    run = _make_run(tmp_path)
    c = finalize_collection(collect(run / "RUN_MANIFEST.json", tmp_path / "c.json"),
                            tmp_path / "c.json")
    return run, c, tmp_path / "c.json"


def test_collect_carries_mutation_type(tmp_path):
    """collection 每条 trainable 转存 mutation_type（evidence request 来源，schema v1 兼容）。"""
    run, c, _ = _make_collection(tmp_path)
    entries = c["trainable_evidence"]
    assert len(entries) == 8
    by_id = {t["request_identity"]: t for t in entries}
    assert all("mutation_type" in t for t in entries)
    assert by_id["sha256:songA:baseline:0"]["mutation_type"] == "baseline"
    assert by_id["sha256:songB:missing:1"]["mutation_type"] == "missing"
    # 旧 evidence 无 mutation_type（request 也无）→ None 容错
    run2 = _make_run(tmp_path / "run_old")
    ev_path = run2 / "evidence" / "sha256:songA:baseline:0.json"
    ev = json.loads(ev_path.read_text())
    del ev["attempt"]["request"]["mutation_type"]
    ev_path.write_text(json.dumps(ev))
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    from collect_trainable_evidence import collect, finalize_collection
    c2 = finalize_collection(collect(run2 / "RUN_MANIFEST.json", tmp_path / "c_old.json"),
                             tmp_path / "c_old.json")
    old = {t["request_identity"]: t for t in c2["trainable_evidence"]}
    assert old["sha256:songA:baseline:0"]["mutation_type"] is None


def test_consume_split_by_song_isolates_songs(tmp_path):
    """--split-by song：同歌 request 不跨折（train/val 的歌集合不相交）。"""
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    from assessor_train_eval import consume
    _, c, cpath = _make_collection(tmp_path)
    m = consume(cpath, tmp_path / "asr", split_by="song")
    assert m["split_by"] == "song"
    assert m["assessor"]["split_mode"] == "by_song"
    split = m["split"]
    assert split["mode"] == "by_song"
    train_songs = {k.split(":")[0] for k in split["train_keys"]}
    val_songs = {k.split(":")[0] for k in split["val_keys"]}
    assert train_songs and val_songs
    assert train_songs.isdisjoint(val_songs), "同歌 request 跨折（歌隔离破坏）"
    assert train_songs | val_songs == {"songA", "songB"}
    # 默认 split_by=item：item 不跨折但歌可跨折
    m2 = consume(cpath, tmp_path / "asr_item", split_by="item")
    assert m2["assessor"]["split_mode"] == "by_item"
    it_train = set(m2["split"]["train_keys"])
    it_val = set(m2["split"]["val_keys"])
    assert it_train.isdisjoint(it_val)
    assert "songA" in {k.split(":")[0] for k in it_train}


def test_consume_family_filter(tmp_path):
    """--family：只训练/评价指定 family；family 不进特征键。"""
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    from assessor_train_eval import consume
    _, c, cpath = _make_collection(tmp_path)
    m = consume(cpath, tmp_path / "asr_f", families=["baseline"])
    assert m["families"] == ["baseline"]
    assert m["denominator"]["trainable_evidence"] == 4  # 2 songs × 2 items
    assert m["denominator"]["items"] == 4
    assert m["family_counts"] == {"baseline": 24}  # unit 行计数（4 evidence × 6 units）
    rows = [json.loads(l) for l in
            Path(m["outputs"]["features"]).read_text().splitlines()]
    assert all(r["family"] == "baseline" for r in rows)
    # family/mutation_type 不得进特征键（13 §10.1）
    assert not any(k in {"family", "mutation_type", "mutation_family"} for k in m["feature_keys"])
    assert m["labels"]["available"] is True
    assert m["assessor"]["val_metrics"]["unit_recall_95"] is not None


def test_family_loo_structure(tmp_path):
    """family-LOO：每 family 留出重训 + 对留出 family 打分，输出结构完整。"""
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    from assessor_train_eval import family_loo
    _, c, cpath = _make_collection(tmp_path)
    s = family_loo(cpath, tmp_path / "fl")
    assert s["schema"] == "research_v7_assessor_family_loo_v1"
    assert s["labels_available"] is True
    assert s["families"] == ["baseline", "missing"]
    assert len(s["loo"]) == 2
    by_fam = {r["family"]: r for r in s["loo"]}
    for fam in ("baseline", "missing"):
        r = by_fam[fam]
        assert r["operating_points"] is not None
        assert "high_recall_95" in r["operating_points"]
        assert r["test"] is not None
        assert r["test"]["n_units"] == 24  # 留出 family 全部 unit（2 songs × 2 items × 6）
        assert r["test"]["unit_recall_95"] is not None
        assert r["test"]["correct_unit_fpr_95"] is not None
        assert r["fit_units"] > 0 and r["val_units"] > 0
    # pooled 跨 family 汇总
    assert s["pooled_test"]["n_units"] == 48
    assert s["pooled_test"]["unit_recall_95"] is not None
    assert Path(tmp_path / "fl" / "FAMILY_LOO.json").is_file()


def test_family_loo_heldout_not_in_fit(tmp_path):
    """family-LOO：留出 family 的 evidence 完全不参与拟合（fit 折只含其他 family）。"""
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    from assessor_train_eval import _extract_rows, _feature_keys, _fit_freeze_eval, _row_y
    _, c, _ = _make_collection(tmp_path)
    ex = _extract_rows(c)
    rows = ex["feature_rows"]
    labels = ex["labels"]
    keys = _feature_keys(rows)
    fit_rows = [fr for fr in rows if fr["family"] != "baseline"]
    test_rows = [fr for fr in rows if fr["family"] == "baseline"]
    assert all(fr["family"] == "missing" for fr in fit_rows)
    res = _fit_freeze_eval(fit_rows, test_rows, labels, keys, 0.7, "item")
    assert res["operating_points"] is not None
    assert res["test"]["n_units"] == 24
    assert np.asarray([_row_y(fr, labels) for fr in test_rows]).sum() > 0


def test_cli_family_loo_and_split_flags(tmp_path):
    """CLI：--split-by song / --family / --family-loo 接线正确、退出码语义保留。"""
    _, c, cpath = _make_collection(tmp_path)
    r = subprocess.run([sys.executable,
                        str(ROOT / "scripts/research_v7/assessor_train_eval.py"),
                        "--collection", str(cpath), "--out", str(tmp_path / "cli_loo"),
                        "--split-by", "song", "--family-loo"],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    out = json.loads((tmp_path / "cli_loo" / "FAMILY_LOO.json").read_text())
    assert out["split_by"] == "song"
    assert len(out["loo"]) == 2
    r2 = subprocess.run([sys.executable,
                         str(ROOT / "scripts/research_v7/assessor_train_eval.py"),
                         "--collection", str(cpath), "--out", str(tmp_path / "cli_fam"),
                         "--family", "missing"],
                        capture_output=True, text=True, env=ENV)
    assert r2.returncode == 0, r2.stderr
    man = json.loads((tmp_path / "cli_fam" / "ASSESSOR_RUN_MANIFEST.json").read_text())
    assert man["families"] == ["missing"]
    assert man["denominator"]["trainable_evidence"] == 4
    assert man["split_by"] == "item"
    # 非法 split-by 确定性失败
    r3 = subprocess.run([sys.executable,
                         str(ROOT / "scripts/research_v7/assessor_train_eval.py"),
                         "--collection", str(cpath), "--out", str(tmp_path / "cli_bad"),
                         "--split-by", "album"],
                        capture_output=True, text=True, env=ENV)
    assert r3.returncode == 2  # argparse choices 拒绝


def test_split_keys_helper_song_groups(tmp_path):
    """_split_keys(split_by='song')：key 按歌分组切分（组内不分裂）。"""
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))
    from assessor_train_eval import _split_keys
    keys = ["songA:w0:i0", "songA:w1:i1", "songB:w0:i0", "songB:w1:i1"]
    tr, va, mode = _split_keys(keys, "song", 0.5)
    assert mode == "by_song"
    assert {k.split(":")[0] for k in tr}.isdisjoint({k.split(":")[0] for k in va})
    assert len(tr) == 2 and len(va) == 2  # 同歌 request 一起进同一折
