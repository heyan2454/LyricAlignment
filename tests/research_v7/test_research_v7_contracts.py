# -*- coding: utf-8 -*-
"""research_v7 align_behavior 契约与单 case smoke 测试（纯 CPU，无模型）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.research_v7.attempt import AlignmentAttempt, run_request
from lyricalign.research_v7.mutations import (
    DonorSpec,
    extra_ratio,
    missing_ratio,
    no_match,
    replace_ratio,
)
from lyricalign.research_v7.requests import AlignmentRequest

BASE = tuple("ABCDEFGHIJ"[:10])


def _req(units=BASE, mtype="baseline", ratio=0.0):
    return AlignmentRequest(
        request_id=f"t:{mtype}:{ratio}",
        item_id="t1",
        parent_request_id=None,
        audio_source="demucs_vocal",
        audio_start_sec=0.0,
        audio_end_sec=60.0,
        text_source="lyrics",
        text_start_index=0,
        text_end_index=len(units),
        text_units=units,
        timestamp_slot_indices=None,
        workflow_mode="single_attempt",
        mutation_type=mtype,
        mutation_parameters={"ratio": ratio},
        model_id="Qwen3-ForcedAligner-0.6B-hf",
        checkpoint_id="r2-step-000750",
        input_variant="text_mutation",
    )


def test_request_validate_and_derive():
    r = _req()
    r.validate(total_units=10, duration_sec=60.0)
    d = r.derive(text_end_index=5)
    assert d.text_end_index == 5
    assert d.request_id == r.request_id
    assert r.to_dict()["text_units"] == BASE  # asdict 对 tuple 保持 tuple


def test_request_invalid_audio_raises():
    r = _req()
    with pytest.raises(ValueError):
        r.derive(audio_start_sec=5.0, audio_end_sec=3.0).validate()


def test_extra_ratio_tail():
    m = extra_ratio(BASE, 0.5, source="lookahead")
    assert m.mutation_type == "extra"
    assert m.base_count == 10
    assert m.mutated_count == 15
    assert abs(m.actual_ratio - 0.5) < 1e-9
    assert len(m.mutated_units) == 15


def test_extra_ratio_zero():
    m = extra_ratio(BASE, 0.0)
    assert m.mutated_units == BASE


def test_missing_ratio_tail():
    m = missing_ratio(BASE, 0.5, position="tail")
    # 0.5*10=5 移除
    assert len(m.mutated_units) == 5
    assert m.mutated_units == BASE[:5]


def test_missing_ratio_head_and_dispersed_deterministic():
    mh = missing_ratio(BASE, 0.5, position="head")
    assert mh.mutated_units == BASE[5:]
    m1 = missing_ratio(BASE, 0.5, position="dispersed", seed=1)
    m2 = missing_ratio(BASE, 0.5, position="dispersed", seed=1)
    assert m1.mutated_units == m2.mutated_units  # 固定 seed 可复现
    assert len({u for u in m1.mutated_units}) == 5


def test_replace_ratio_keeps_length():
    donor = DonorSpec("donor", 0, ("X", "Y", "Z", "W", "V", "U", "T", "S", "R", "Q"), "zh", "char")
    m = replace_ratio(BASE, 0.5, donor=donor, position="whole")
    assert len(m.mutated_units) == 10
    assert m.mutated_count == m.base_count
    assert m.mutated_units != BASE


def test_no_match_len():
    donor = DonorSpec("other_song", 0, ("甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"), "zh", "char")
    m = no_match(BASE, donor=donor, language="zh", unit_mode="char")
    assert len(m.mutated_units) == 10
    assert m.mutation_type == "no_match"
    assert m.mutated_units != BASE


def test_request_run_with_fake_executor():
    # 用 fake executor 验证单 case 流程产 EvidencePack 且契约自洽
    req = _req(mtype="extra", ratio=0.5)

    def fake(r):
        rows = [{"global_character_index": i, "start_sec": 0.0, "end_sec": 0.5} for i in range(len(r.text_units))]
        return AlignmentAttempt(
            request=r, attempt_id="a1",
            decoder_outputs={"official": {"rows": rows}, "raw": {"rows": rows}},
            committed=True, status="ok",
        )

    ev = run_request(req, fake)
    assert ev.attempt.request.text_end_index == len(req.text_units)
    assert ev.parent_request_id is None
    ev.to_dict()["metadata"]["mutation"] == "extra"


def test_mutation_catalog_yaml_shape(tmp_path):
    import yaml
    spec = {
        "mutations": [
            {"type": "extra", "ratio": 1.0, "position": "tail", "source": "future"},
            {"type": "missing", "ratio": 0.5, "position": "dispersed"},
        ]
    }
    from lyricalign.research_v7.mutations import MutationCatalog
    cat = MutationCatalog(spec, seed=3)
    out = cat.build(BASE)
    assert len(out) == 2
    assert out[0].mutation_type == "extra" and out[0].mutated_count == 20
    assert out[1].mutation_type == "missing"
