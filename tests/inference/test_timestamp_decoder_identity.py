from __future__ import annotations

import pytest

from lyricalign.inference.qwen_forced_aligner import TIMESTAMP_DECODERS, QwenForcedAligner


def _bare(decoder: str) -> QwenForcedAligner:
    """不加载模型地测身份字典契约：把 load() 换成空操作，生产代码一行不动。"""
    aligner = object.__new__(QwenForcedAligner)
    aligner.load = lambda: None
    aligner.model_id_or_path = "Qwen/Qwen3-ForcedAligner-0.6B-hf"
    aligner.timestamp_decoder = decoder
    aligner.requested_revision = "c07281df297b9905d24a508279258cccf987a064"
    aligner.resolved_revision = aligner.requested_revision
    aligner.device = "cuda"
    aligner.dtype_name = "bfloat16"
    return aligner


def test_default_decoder_is_official_and_available_options_are_two():
    signature_default = QwenForcedAligner.__init__.__kwdefaults__ or {}
    assert signature_default.get("timestamp_decoder") == "official"
    assert TIMESTAMP_DECODERS == ("official", "dp")


def test_unknown_decoder_is_rejected_before_any_model_loading():
    with pytest.raises(ValueError) as excinfo:
        QwenForcedAligner("does-not-exist", timestamp_decoder="viterbi")
    assert "unknown timestamp decoder" in str(excinfo.value)


def test_official_identity_is_byte_identical_and_dp_extends_it():
    official = _bare("official").model_identity()
    dp = _bare("dp").model_identity()
    assert "timestamp_decoder" not in official, "默认路径的身份字典必须与启用本功能前完全一致"
    assert dp["timestamp_decoder"] == "dp"
    assert {k: v for k, v in dp.items() if k != "timestamp_decoder"} == official
