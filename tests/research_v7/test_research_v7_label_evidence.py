# -*- coding: utf-8 -*-
"""round13：label_evidence_gt_eval 弱标签 —— replace/extra/missing/baseline 的 gt_eval
标签语义（wrong-output / identity-error / omitted-units / expected-correct）。"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "research_v7"))

import label_evidence_gt_eval as le  # noqa: E402


def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False))


def _evidence(rid, mtype, n_units=20) -> dict:
    return {"content_identity": f"sha256:{rid}", "attempt": {
        "status": "ok",
        "request": {"request_id": rid, "item_id": rid, "mutation_type": mtype,
                    "text_units": [chr(97 + i) for i in range(n_units)]},
    }}


def test_label_replace_wrong_output_and_extra(tmp_path):
    """replace：unsafe = 被替换 canonical id 对应 local 行（wrong-output 方向，
    gt_source=replace_wrong_output）；extra：unsafe=[] 但 gt_source=extra_inserted_
    no_canonical_gt（identity-error）；missing/baseline 行为不变。"""
    ev_dir = tmp_path / "evidence"
    reqs_path = tmp_path / "REQUESTS.jsonl"
    rows = [
        {"request_id": "s1:w0:full", "mutation_type": "baseline"},
        {"request_id": "s1:w0:full:missing0.25", "mutation_type": "missing",
         "text_units": [chr(97 + i) for i in range(15)],
         "mutation_parameters": {"baseline_unit_count": 20}},
        {"request_id": "s1:w0:full:replace0.25", "mutation_type": "replace",
         "text_units": [chr(97 + i) for i in range(20)],
         "canonical_to_local": {str(i): i for i in range(20)},
         "mutation_parameters": {"replaced_canonical_ids": [16, 17, 18, 19],
                                 "donor_song_id": "s2"}},
        {"request_id": "s1:w0:full:extra0.10", "mutation_type": "extra",
         "text_units": [chr(97 + i) for i in range(22)],
         "mutation_parameters": {"actual_added_units": 2, "baseline_unit_count": 20}},
    ]
    reqs_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    for r in rows:
        n_units = len(r["text_units"]) if r["mutation_type"] == "missing" else 20
        _write(ev_dir / f"{r['request_id']}.json", _evidence(r["request_id"], r["mutation_type"], n_units=n_units))

    audit = le.label_evidence(reqs_path, ev_dir)
    assert audit["labeled"] == 4
    assert audit["baseline"] == 1 and audit["missing"] == 1
    assert audit["replace"] == 1 and audit["extra"] == 1

    labels = {}
    for p in sorted(ev_dir.glob("*.json")):
        ev = json.loads(p.read_text())
        rid = ev["attempt"]["request"]["request_id"]
        labels[rid] = ev["attempt"]["gt_eval"]

    # baseline：期望全对
    assert labels["s1:w0:full"]["gt_source"] == le.GT_SOURCE_BASELINE
    assert labels["s1:w0:full"]["unsafe_unit_indices"] == []
    # missing：被删尾部单位（round10 语义，truncated 请求的 request-local 索引）
    m = labels["s1:w0:full:missing0.25"]
    assert m["gt_source"] == le.GT_SOURCE_MISSING
    assert m["unsafe_unit_indices"] == list(range(10, 15))
    # replace：wrong-output 方向 = 被替换 canonical id 的 local 行
    rp = labels["s1:w0:full:replace0.25"]
    assert rp["gt_source"] == le.GT_SOURCE_REPLACE
    assert rp["unsafe_unit_indices"] == [16, 17, 18, 19]
    assert "replaced" in rp["label_definition"]
    # extra：identity-error，无 canonical GT 行可标 unsafe
    ex = labels["s1:w0:full:extra0.10"]
    assert ex["gt_source"] == le.GT_SOURCE_EXTRA
    assert ex["unsafe_unit_indices"] == []
    assert "no canonical GT" in ex["label_definition"]
