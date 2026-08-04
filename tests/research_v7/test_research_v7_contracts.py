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


def _creq_canonical(units=("乙", "女"), cids=None, c2l=None, cstart=0, cend=2,
                    role=None, tl_file="f", tl_row="r", adapter="c3_text_adapter_v1",
                    sw=(40.0, 42.0), auto_ids=True, auto_c2l=True, **kw):
    """构造带 canonical lineage 的 request，便于 validate 自洽性测试。

    auto_ids/auto_c2l 为 True 时自动生成与 text_units 一致的 ids/mapping；
    置 False 则保留传入的 None（用于验证字段缺失时的拒绝/放行）。
    """
    n = len(units)
    use_ids = [i for i in range(n)] if auto_ids and cids is None else cids
    use_c2l = {i: i for i in range(n)} if auto_c2l and c2l is None and use_ids else c2l
    return AlignmentRequest(
        request_id="t:canon", item_id="c1", parent_request_id=None,
        audio_source="generated_c3_wav", audio_start_sec=0.0, audio_end_sec=2.0,
        text_source="canon", text_start_index=0, text_end_index=n,
        text_units=units, timestamp_slot_indices=None, workflow_mode="behavior",
        mutation_type="baseline", mutation_parameters={}, model_id="Q",
        checkpoint_id="r2", input_variant="text",
        canonical_text_start=cstart, canonical_text_end=cend,
        canonical_to_local=use_c2l,
        canonical_ids=use_ids,
        canonical_timeline_file_sha=tl_file, canonical_timeline_row_sha=tl_row,
        canonical_adapter_version=adapter, source_window_sec=sw,
        metadata={"evaluation_role": role} if role else {},
        **kw)


def test_canonical_validate_ok_when_consistent():
    _creq_canonical().validate()


def test_canonical_validate_rejects_id_length_mismatch():
    with pytest.raises(ValueError, match="canonical_ids len"):
        _creq_canonical(cids=[0, 1, 2]).validate()  # 3 ids vs 2 units


def test_canonical_validate_rejects_non_increasing_ids():
    with pytest.raises(ValueError, match="strictly increasing"):
        _creq_canonical(cids=[1, 0]).validate()


def test_canonical_validate_rejects_mapping_keys_not_equal_ids():
    with pytest.raises(ValueError, match="keys must equal canonical_ids"):
        _creq_canonical(c2l={0: 0}).validate()


def test_canonical_validate_rejects_mapping_values_not_0_n_minus_1():
    with pytest.raises(ValueError, match="exactly 0..N-1"):
        _creq_canonical(c2l={0: 0, 1: 2}).validate()  # 值含越界 2


def test_canonical_validate_rejects_range_not_containing_ids():
    with pytest.raises(ValueError, match="range must contain all canonical_ids"):
        _creq_canonical(cstart=40, cend=42).validate()  # ids 0,1 不在 [40,42)


def test_canonical_validate_requires_canonical_ids_when_fields_present():
    with pytest.raises(ValueError, match="canonical_ids required"):
        _creq_canonical(cids=None, auto_ids=False).validate()


def test_lyrics_aligned_requires_canonical_lineage():
    with pytest.raises(ValueError, match="lyrics_aligned requires canonical source_window_sec"):
        _creq_canonical(role="lyrics_aligned", sw=None).validate()
    with pytest.raises(ValueError, match="lyrics_aligned requires canonical canonical_timeline_file_sha"):
        _creq_canonical(role="lyrics_aligned", tl_file=None).validate()


def test_probe_request_does_not_require_canonical():
    """acoustic_probe 角色不强制 canonical lineage（与 lyrics_aligned 相反）。"""
    _creq_canonical(role="acoustic_probe", tl_file=None, tl_row=None, adapter=None, sw=None,
                    cids=None, c2l=None, auto_ids=False, auto_c2l=False,
                    cstart=None, cend=None).validate()


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


def test_extra_ratio_middle_inserts_at_middle():
    m = extra_ratio(BASE, 0.2, position="middle")
    assert m.mutated_units[:5] == BASE[:5]
    assert m.mutated_units[7:] == BASE[5:]


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
    assert ev.audio_hash and ev.text_hash


def test_real_executor_adapter_passes_the_complete_request():
    from lyricalign.research_v7.real_executor import make_real_executor

    class StubAligner:
        def __init__(self):
            self.seen = None

        def align_request(self, request):
            self.seen = request
            return [{"global_character_index": 0, "fixed_global_start_sec": 0.0, "fixed_global_end_sec": 0.4}]

    aligner = StubAligner()
    attempt = make_real_executor(aligner)(_req())
    assert attempt.status == "ok"
    assert aligner.seen.item_id == "t1"


def test_sparse_slot_transform_keeps_only_requested_marker_pairs():
    import torch
    from lyricalign.research_v7.sparse_slots import retain_timestamp_slots

    # Three units, two timestamp markers each; non-marker text context remains.
    inputs = {"input_ids": torch.tensor([[10, 99, 99, 11, 99, 99, 12, 99, 99, 13]]),
              "attention_mask": torch.ones((1, 10), dtype=torch.long),
              "input_features": torch.ones((1, 3, 4))}
    sparse, slots = retain_timestamp_slots(inputs, timestamp_token_id=99, unit_indices=[1], total_units=3)
    assert slots == (1,)
    assert sparse["input_ids"].tolist() == [[10, 11, 99, 99, 12, 13]]
    assert sparse["attention_mask"].shape[-1] == 6
    assert sparse["input_features"].shape == (1, 3, 4)


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


def _real_request(units=BASE, a0=0.0, a1=60.0, audio_source="whatever.wav"):
    return AlignmentRequest(
        request_id="r:real", item_id="i1", parent_request_id=None,
        audio_source=audio_source, audio_start_sec=a0, audio_end_sec=a1,
        text_source="labels", text_start_index=0, text_end_index=len(units),
        text_units=units, timestamp_slot_indices=None, workflow_mode="behavior",
        mutation_type="baseline", mutation_parameters={}, model_id="Q",
        checkpoint_id="r2", input_variant="text",
    )


class _StubAudioModule:
    """模拟 align_qwen_fa_serial_demo 的 infer_slice 输出（含多组 global 键）。"""
    from types import SimpleNamespace

    @staticmethod
    def process_lyric_text(text, language="Chinese"):
        from types import SimpleNamespace as _SN
        chars = [c for line in text.split("\n") for c in line]
        return _SN(characters=chars)

    @staticmethod
    def infer_slice(processor, model, audio, document, character_start, character_end,
                    global_audio_offset_sec, args, timestamp_slot_indices=None):
        rows = []
        for i in range(character_start, character_end):
            rows.append({
                "global_character_index": i,
                "raw_global_start_sec": i * 0.5 + global_audio_offset_sec,
                "raw_global_end_sec": i * 0.5 + 0.4 + global_audio_offset_sec,
                "official_fixed_global_start_sec": i * 0.5 + 0.01 + global_audio_offset_sec,
                "official_fixed_global_end_sec": i * 0.5 + 0.41 + global_audio_offset_sec,
                "gpu_fixed_global_start_sec": i * 0.5 + 0.02 + global_audio_offset_sec,
                "gpu_fixed_global_end_sec": i * 0.5 + 0.42 + global_audio_offset_sec,
                "fixed_global_start_sec": i * 0.5 + 0.03 + global_audio_offset_sec,
                "fixed_global_end_sec": i * 0.5 + 0.43 + global_audio_offset_sec,
                "start_sec": i * 0.5, "end_sec": i * 0.5 + 0.4,
            })
        return rows, {}


def _patch_decode_audio(monkeypatch, audio_np):
    """monkeypatch qwen_fa_runtime.decode_audio（real_executor 在函数内 import）。"""
    import types as _t
    runtime = _t.ModuleType("lyricalign.training.qwen_fa_runtime")
    runtime.decode_audio = lambda p: audio_np
    monkeypatch.setitem(sys.modules, "lyricalign.training.qwen_fa_runtime", runtime)


def test_real_executor_shifts_all_global_keys(tmp_path, monkeypatch):
    """C1（review12）：audio_start_sec>0 时，所有 *_global_* 键必须随窗平移，
    official_fixed_global_* 不得停留在局部坐标（混坐标会破坏绝对时间评价）。"""
    import sys as _sys
    from types import SimpleNamespace as _SN

    from lyricalign.research_v7 import real_executor as re_mod
    _sys.modules["qwen_fa_serial_demo"] = _StubAudioModule
    # 把 _load_serial_demo 指向 stub（避免 import 真实脚本）
    monkeypatch.setattr(re_mod, "_load_serial_demo", lambda: _StubAudioModule())
    # decode_audio 返回 16k mono numpy（65s 音频，覆盖 60-62 窗）
    import numpy as np
    _patch_decode_audio(monkeypatch, np.zeros(65 * 16000, dtype=np.float32))

    aligner = re_mod.RealAligner("modeldir", "rev", "ckpt", device="cpu")
    # 跳过模型加载：直接构造并调用 align_request 前先注入 stub 模块方法
    aligner._mod = _StubAudioModule()
    aligner._args = _SN(timestamp_segment_sec=0.08)
    (tmp_path / "a.wav").write_bytes(b"RIFF")
    req = _real_request(units=("春", "风"), a0=60.0, a1=62.0, audio_source=str(tmp_path / "a.wav"))
    rows = aligner.align_request(req)
    assert rows, "no rows"
    # 全局坐标系：raw/fixed/official_fixed/gpu_fixed 全部含窗偏移 60s
    for row in rows:
        for k in ("raw_global_start_sec", "raw_global_end_sec",
                  "official_fixed_global_start_sec", "official_fixed_global_end_sec",
                  "gpu_fixed_global_start_sec", "gpu_fixed_global_end_sec",
                  "fixed_global_start_sec", "fixed_global_end_sec"):
            assert float(row[k]) >= 60.0, f"{k}={row[k]} not shifted (window 60s)"
        # official_fixed 与 fixed 同一坐标系（差值只含 decoder 内部偏移，不应是整窗量级）
        assert abs(float(row["official_fixed_global_start_sec"]) - float(row["fixed_global_start_sec"])) < 1.0


def test_real_executor_audio_range_tolerance(tmp_path, monkeypatch):
    """M2（review12）：audio_end 因 manifest 四舍五入超出解码长度 ≤2 sample 时 clamp 而非拒绝。"""
    import sys as _sys
    from types import SimpleNamespace as _SN

    from lyricalign.research_v7 import real_executor as re_mod
    _sys.modules["qwen_fa_serial_demo"] = _StubAudioModule
    monkeypatch.setattr(re_mod, "_load_serial_demo", lambda: _StubAudioModule())
    import numpy as np
    _patch_decode_audio(monkeypatch, np.zeros(20 * 16000, dtype=np.float32))  # 恰好 20s
    aligner = re_mod.RealAligner("m", "r", "c", device="cpu")
    aligner._mod = _StubAudioModule()
    aligner._args = _SN(timestamp_segment_sec=0.08)
    (tmp_path / "b.wav").write_bytes(b"RIFF")
    # audio_end_sec 略超 20s（round 误差 ~0.00006s ≈ 1 sample）
    req = _real_request(units=("春", "风"), a0=0.0, a1=20.00006, audio_source=str(tmp_path / "b.wav"))
    rows = aligner.align_request(req)
    assert rows
    # 超太多仍拒绝
    req2 = _real_request(units=("春", "风"), a0=0.0, a1=25.0, audio_source=str(tmp_path / "b.wav"))
    import pytest as _pt
    with _pt.raises(ValueError, match="outside decoded audio"):
        aligner.align_request(req2)


def test_real_executor_rejects_multi_char_units(tmp_path, monkeypatch):
    """M4（review12）：document.characters 与 text_units 不等长（多字 unit）时显式报错，
    不得静默错位。"""
    import sys as _sys
    from types import SimpleNamespace as _SN

    from lyricalign.research_v7 import real_executor as re_mod
    _sys.modules["qwen_fa_serial_demo"] = _StubAudioModule
    monkeypatch.setattr(re_mod, "_load_serial_demo", lambda: _StubAudioModule())
    import numpy as np
    _patch_decode_audio(monkeypatch, np.zeros(10 * 16000, dtype=np.float32))
    aligner = re_mod.RealAligner("m", "r", "c", device="cpu")
    aligner._mod = _StubAudioModule()
    aligner._args = _SN(timestamp_segment_sec=0.08)
    (tmp_path / "c.wav").write_bytes(b"RIFF")
    # "春风" 是一个 multi-char unit → document 2 chars vs 1 unit → 拒绝
    req = _real_request(units=("春风",), a0=0.0, a1=10.0, audio_source=str(tmp_path / "c.wav"))
    with pytest.raises(ValueError, match="character-aligned"):
        aligner.align_request(req)


def test_real_executor_rejects_english_word_unit(tmp_path, monkeypatch):
    """T3：英文单词（"hello"）是词级 unit，v7 仅支持字符级 unit（英单字）。
    区别于中文多字 unit（"春风"），同样被显式拒绝，错误消息含 character-aligned。"""
    import sys as _sys
    from types import SimpleNamespace as _SN

    from lyricalign.research_v7 import real_executor as re_mod
    _sys.modules["qwen_fa_serial_demo"] = _StubAudioModule
    monkeypatch.setattr(re_mod, "_load_serial_demo", lambda: _StubAudioModule())
    import numpy as np
    _patch_decode_audio(monkeypatch, np.zeros(10 * 16000, dtype=np.float32))
    aligner = re_mod.RealAligner("m", "r", "c", device="cpu")
    aligner._mod = _StubAudioModule()
    aligner._args = _SN(timestamp_segment_sec=0.08)
    (tmp_path / "d.wav").write_bytes(b"RIFF")
    # "hello" 是英文单词 unit → document 5 chars vs 1 unit → 拒绝
    req = _real_request(units=("hello",), a0=0.0, a1=10.0, audio_source=str(tmp_path / "d.wav"))
    with pytest.raises(ValueError, match="character-aligned"):
        aligner.align_request(req)


def test_checkpoint_content_hash_changes_with_content(tmp_path):
    """C2（review12）：checkpoint 内容 SHA 随文件内容变化；不同 checkpoint 目录产生不同 hash。
    进程内缓存（一次运行中 checkpoint 不变），覆盖内容后用新实例验证变化。"""
    from lyricalign.research_v7.real_executor import RealAligner
    a = tmp_path / "ckpt_a"; a.mkdir()
    (a / "adapter_model.safetensors").write_bytes(b"weights-v1")
    b = tmp_path / "ckpt_b"; b.mkdir()
    (b / "adapter_model.safetensors").write_bytes(b"weights-v2")
    aligner = RealAligner("m", "r", str(a))
    h1 = aligner.checkpoint_content_hash()
    aligner2 = RealAligner("m", "r", str(b))
    h2 = aligner2.checkpoint_content_hash()
    assert h1 and h2 and h1 != h2
    # 覆盖 checkpoint 内容 → 新实例（同路径）hash 变化
    (a / "adapter_model.safetensors").write_bytes(b"weights-v3")
    aligner3 = RealAligner("m", "r", str(a))
    assert aligner3.checkpoint_content_hash() != h1
