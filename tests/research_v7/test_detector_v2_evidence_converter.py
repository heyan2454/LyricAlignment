# -*- coding: utf-8 -*-
"""Detector V2 evidence converter tests（Dev-F）：真实 runner evidence → EvidenceRow v2。

纯内存合成 fake runner 输出（official/raw rows + _posterior entropy/margin/topk +
_repair_trace boundary_moves），验证 canonical 映射、raw/official 取值、repair shift 匹配、
hidden blocked、leak 拒绝、缺失 canonical_to_local raise；CLI 端到端一条。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV = dict(__import__("os").environ, PYTHONPATH=str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src"))

import pytest

from lyricalign.research_v7.detector_v2_evidence import assert_no_label_leak
from lyricalign.research_v7.detector_v2_evidence_converter import convert_evidence


def _request_row(*, n=4, view="full", hidden_schema=None, extra=None, rid="song:0:legal:full"):
    cids = [10 + i for i in range(n)]
    row = {
        "request_id": rid,
        "canonical_to_local": {str(c): i for i, c in enumerate(cids)},
        "canonical_ids": cids,
        "view_id": view,
        "hidden_schema": hidden_schema,
        "family": "baseline_legal",
        "mutation_type": "baseline",
    }
    if extra:
        row.update(extra)
    return row


def _official_row(i):
    return {
        "global_character_index": i,
        "character": f"字{i}",
        "raw_global_start_sec": i * 1.0,
        "raw_global_end_sec": i * 1.0 + 0.8,
        "official_fixed_global_start_sec": i * 1.0 + 0.05,
        "official_fixed_global_end_sec": i * 1.0 + 0.82,
        "fixed_global_start_sec": i * 1.0 + 0.05,
        "fixed_global_end_sec": i * 1.0 + 0.82,
    }


def _posterior_row(i):
    return {
        "global_character_index": i,
        "start_entropy": 0.1 + i,
        "end_entropy": 0.2 + i,
        "start_margin": 0.3 + i,
        "end_margin": 0.4 + i,
        "start_topk_classes": [i, i + 1],
        "start_topk_probabilities": [0.6, 0.3],
        "end_topk_classes": [i + 2, i + 3],
        "end_topk_probabilities": [0.5, 0.4],
    }


def _evidence(rows, *, posterior=True, repair=True, raw_geometry=True, content_identity="sha256:abc"):
    decoder = {"official": {"rows": rows}}
    if raw_geometry:
        raw_rows = []
        for i in range(len(rows)):
            rr = dict(_official_row(i))
            rr["fixed_global_start_sec"] = rr["raw_global_start_sec"]
            rr["fixed_global_end_sec"] = rr["raw_global_end_sec"]
            raw_rows.append(rr)
        decoder["raw"] = {"rows": raw_rows,
                          "availability": "derived_from_official_decoder_raw_geometry"}
    if posterior:
        decoder["_posterior"] = {"top_k": 16, "rows": [_posterior_row(i) for i in range(len(rows))]}
    if repair:
        decoder["_repair_trace"] = {"decoder": "official", "changed_boundary_count": 1,
                                    "boundary_moves": [
                                        {"global_character_index": 0,
                                         "start_shift_sec": 0.05, "end_shift_sec": 0.02}]}
    return {"content_identity": content_identity,
            "attempt": {"request": {"request_id": "song:0:legal:full", "view_id": "full"},
                        "status": "ok", "decoder_outputs": decoder}}


def test_convert_canonical_mapping_and_views():
    rows = convert_evidence(_evidence([_official_row(i) for i in range(4)]), _request_row())
    assert len(rows) == 4
    # canonical_to_local 逆映射：local 0..3 → canonical 10..13
    assert [r.canonical_unit_id for r in rows] == [10, 11, 12, 13]
    assert all(r.request_identity == "sha256:abc" for r in rows)
    assert all(r.view_id == "full" for r in rows)
    # raw view 取 raw_global_* + posterior 按 index 对齐
    r0 = rows[0]
    assert r0.raw.start_sec == 0.0 and r0.raw.end_sec == 0.8
    assert r0.raw.start_entropy == 0.1 and r0.raw.end_entropy == 0.2
    assert r0.raw.start_margin == 0.3 and r0.raw.end_margin == 0.4
    assert r0.raw.topk == (((0, 0.6), (1, 0.3)), ((2, 0.5), (3, 0.4)))
    # official view 取 official_fixed_global_* + repair shift 匹配 gci=0
    assert r0.official.start_sec == 0.05 and r0.official.end_sec == 0.82
    assert r0.official.repair_start_shift_sec == 0.05
    assert r0.official.repair_end_shift_sec == 0.02
    # 无 move 的行（trace 存在）→ shift 0.0
    r1 = rows[1]
    assert r1.official.repair_start_shift_sec == 0.0
    assert r1.official.repair_end_shift_sec == 0.0
    # hidden blocked：schema None → available False
    assert r0.hidden.available is False and r0.hidden.schema is None
    # 每行 to_dict 干净过 leak guard
    for r in rows:
        assert assert_no_label_leak(r.to_dict())["ok"]


def test_convert_raw_geometry_fallback_to_raw_rows():
    # official row 无 raw_global_* → 回退 raw.rows 的 fixed_global_*（real_executor 语义）
    row = _official_row(2)
    row.pop("raw_global_start_sec")
    row.pop("raw_global_end_sec")
    rr = dict(_official_row(2))
    rr["fixed_global_start_sec"] = rr["raw_global_start_sec"]
    rr["fixed_global_end_sec"] = rr["raw_global_end_sec"]
    ev = {"content_identity": "sha256:abc",
          "attempt": {"status": "ok",
                      "decoder_outputs": {"official": {"rows": [row]},
                                          "raw": {"rows": [rr]}}}}
    rows = convert_evidence(ev, _request_row())
    assert rows[0].raw.start_sec == 2.0 and rows[0].raw.end_sec == 2.8
    assert rows[0].official.start_sec == 2.05


def test_convert_no_repair_trace_yields_none_shifts():
    ev = _evidence([_official_row(i) for i in range(2)], repair=False)
    rows = convert_evidence(ev, _request_row())
    assert rows[0].official.repair_start_shift_sec is None
    assert rows[0].official.repair_end_shift_sec is None


def test_convert_hidden_schema_without_data_blocked():
    rows = convert_evidence(_evidence([_official_row(0)]),
                            _request_row(hidden_schema="boundary_last4_v1"))
    assert rows[0].hidden.available is False
    assert rows[0].hidden.schema == "boundary_last4_v1"


def test_convert_hidden_data_populated():
    ev = _evidence([_official_row(0)])
    ev["attempt"]["decoder_outputs"]["_hidden"] = {
        "rows": [{"global_character_index": 0,
                  "start": {"norm": 1.2}, "end": {"norm": 0.8}}]}
    rows = convert_evidence(ev, _request_row(hidden_schema="boundary_last4_v1"))
    assert rows[0].hidden.available is True
    assert rows[0].hidden.schema == "boundary_last4_v1"
    assert rows[0].hidden.start == {0: {"norm": 1.2}}


def test_convert_cross_view_from_multiview_manifest():
    groups = [{"pair_id": "song:0:legal",
               "views": ["song:0:legal:full", "song:0:legal:sparse"],
               "canonical_ids": [10, 11, 12, 13]}]
    rows = convert_evidence(_evidence([_official_row(i) for i in range(4)]),
                            _request_row(rid="song:0:legal:full"), multiview_groups=groups)
    cv = rows[0].cross_view
    assert cv["view_group"] == "song:0:legal"
    assert cv["n_views"] == 2
    assert set(cv["view_ids"]) == {"song:0:legal:full", "song:0:legal:sparse"}
    assert set(cv["unit_covered_by"]) == {"song:0:legal:full", "song:0:legal:sparse"}
    # 组外 canonical unit → unit_covered_by 空
    ev2 = _evidence([_official_row(i) for i in range(4)])
    rows2 = convert_evidence(ev2, _request_row(rid="other:0:legal:full"), multiview_groups=groups)
    assert rows2[0].cross_view == {}


def test_convert_leak_rejected_hidden_and_row_fields_ignored():
    # official row 携带 GT 字段：converter 白名单取值，不得进入 row
    row = _official_row(0)
    row["gt_start_sec"] = 99.0
    row["family"] = "replace"
    rows = convert_evidence(_evidence([row]), _request_row())
    d = rows[0].to_dict()
    assert "gt_start_sec" not in d["official"] and "family" not in d["official"]
    assert assert_no_label_leak(d)["ok"]
    # 透传风险点（hidden start dict 内嵌 GT）→ 递归 leak 检查拒绝
    ev = _evidence([_official_row(0)])
    ev["attempt"]["decoder_outputs"]["_hidden"] = {
        "rows": [{"global_character_index": 0,
                  "start": {"gt_start_sec": 1.0}, "end": {"norm": 0.8}}]}
    with pytest.raises(ValueError, match="forbidden label fields"):
        convert_evidence(ev, _request_row(hidden_schema="boundary_last4_v1"))


def test_convert_missing_canonical_to_local_raises():
    row = _request_row()
    row.pop("canonical_to_local")
    with pytest.raises(ValueError, match="canonical_to_local"):
        convert_evidence(_evidence([_official_row(0)]), row)


def test_convert_index_out_of_mapping_raises():
    row = _request_row(n=4)
    with pytest.raises(ValueError, match="not covered by canonical_to_local"):
        convert_evidence(_evidence([_official_row(5)]), row)


def test_convert_missing_official_rows_raises():
    ev = _evidence([])
    ev["attempt"]["decoder_outputs"] = {"raw": {"rows": []}}
    with pytest.raises(ValueError, match="official"):
        convert_evidence(ev, _request_row())


def test_convert_missing_gci_raises():
    row = _official_row(0)
    row.pop("global_character_index")
    with pytest.raises(ValueError, match="global_character_index"):
        convert_evidence(_evidence([row]), _request_row())


def test_convert_empty_rows_ok():
    rows = convert_evidence(_evidence([]), _request_row())
    assert rows == []


def test_convert_to_dict_roundtrip_json():
    rows = convert_evidence(_evidence([_official_row(i) for i in range(2)]), _request_row())
    payload = json.dumps([r.to_dict() for r in rows], ensure_ascii=False)
    loaded = json.loads(payload)
    assert loaded[0]["canonical_unit_id"] == 10
    assert loaded[0]["official"]["repair_start_shift_sec"] == 0.05
    assert loaded[1]["official"]["repair_start_shift_sec"] == 0.0


def test_cli_end_to_end(tmp_path):
    run = tmp_path / "run1"
    (run / "evidence").mkdir(parents=True)
    (run / "manifests").mkdir(parents=True)
    req = _request_row(n=3, rid="s:0:legal:full")
    req["audio_start_sec"] = 0.0
    (run / "manifests" / "ANOMALY_MANIFEST.jsonl").write_text(
        json.dumps(req, ensure_ascii=False, sort_keys=True) + "\n")
    (run / "manifests" / "MULTIVIEW_MANIFEST.jsonl").write_text(
        json.dumps({"pair_id": "s:0:legal", "views": ["s:0:legal:full", "s:0:legal:sparse"],
                    "canonical_ids": [10, 11, 12]}, ensure_ascii=False, sort_keys=True) + "\n")
    ev = _evidence([_official_row(i) for i in range(3)], content_identity="sha256:xyz")
    ev["attempt"]["request"]["request_id"] = "s:0:legal:full"
    (run / "evidence" / "sha256:xyz.json").write_text(
        json.dumps(ev, ensure_ascii=False, sort_keys=True))
    r = subprocess.run([sys.executable,
                        str(ROOT / "scripts/research_v7/build_detector_v2_evidence.py"),
                        "--run-root", str(run)],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    out = run / "evidence_v2"
    lines = (out / "sha256:xyz.jsonl").read_text().splitlines()
    assert len(lines) == 1
    rows = json.loads(lines[0])
    assert len(rows) == 3
    assert [r_["canonical_unit_id"] for r_ in rows] == [10, 11, 12]
    assert rows[0]["cross_view"]["view_group"] == "s:0:legal"
    schema = json.loads((out / "FEATURE_SCHEMA.json").read_text())
    assert schema["counts"]["converted"] == 1 and schema["counts"]["rows"] == 3
    assert not (out / "failures.jsonl").exists()


def test_cli_records_failure_for_unknown_request(tmp_path):
    run = tmp_path / "run2"
    (run / "evidence").mkdir(parents=True)
    (run / "manifests").mkdir(parents=True)
    (run / "manifests" / "ANOMALY_MANIFEST.jsonl").write_text(
        json.dumps(_request_row(n=1, rid="known:0:legal:full"), ensure_ascii=False) + "\n")
    (run / "manifests" / "MULTIVIEW_MANIFEST.jsonl").write_text("")
    ev = _evidence([_official_row(0)], content_identity="sha256:unknown")
    ev["attempt"]["request"]["request_id"] = "ghost:0:legal:full"
    (run / "evidence" / "sha256:unknown.json").write_text(json.dumps(ev, ensure_ascii=False))
    r = subprocess.run([sys.executable,
                        str(ROOT / "scripts/research_v7/build_detector_v2_evidence.py"),
                        "--run-root", str(run)],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    out = run / "evidence_v2"
    failures = [json.loads(l) for l in (out / "failures.jsonl").read_text().splitlines() if l.strip()]
    assert len(failures) == 1
    assert "ghost:0:legal:full" in failures[0]["error"]
    schema = json.loads((out / "FEATURE_SCHEMA.json").read_text())
    assert schema["counts"]["converted"] == 0 and schema["counts"]["failed"] == 1
