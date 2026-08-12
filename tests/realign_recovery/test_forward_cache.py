"""Forward identity / content-addressed cache tests (WP B2)."""
from __future__ import annotations

import json

import pytest

from lyricalign.realign_recovery.forward_cache import (
    REQUIRED_FORWARD_FIELDS,
    ContentAddressedCache,
    build_forward_key,
    canonical_forward_key,
    forward_digest,
    validate_forward_key,
)


def _base_request() -> dict:
    return {
        "model_id": "Qwen/Qwen3-ForcedAligner-0.6B-hf",
        "model_revision": "c07281df297b9905d24a508279258cccf987a064",
        "checkpoint_id": "ckpt-000750",
        "checkpoint_path": "/data/ckpt/step-000750",
        "processor_id": "Qwen/Qwen3-ForcedAligner-0.6B-hf",
        "audio_source": "song.wav",
        "audio_sha256": "a" * 64,
        "audio_start_sec": 0.0,
        "audio_end_sec": 60.0,
        "text_unit_ids": [0, 1, 2],
        "text_content_hash": "b" * 64,
        "request_mode": "slot",
        "core_sec": 60,
        "left_context_sec": 10,
        "right_context_sec": 10,
        "silence_aware_window_plan": True,
        "code_version": "test-code-v1",
        "schema_version": "realign_recovery_forward_v1",
    }


def test_same_input_same_digest_and_field_changes_digest() -> None:
    base = build_forward_key(_base_request())
    assert forward_digest(base) == forward_digest(build_forward_key(_base_request()))
    for field, new_value in (
        ("model_revision", "other-rev"),
        ("core_sec", 61),
        ("audio_sha256", "f" * 64),
        ("text_content_hash", "c" * 64),
    ):
        req = _base_request()
        req[field] = new_value
        assert forward_digest(base) != forward_digest(build_forward_key(req))


def test_validate_reports_missing_fields() -> None:
    for field in ("model_revision", "core_sec", "audio_sha256", "text_content_hash"):
        key = dict(build_forward_key(_base_request()))
        del key[field]
        problems = validate_forward_key(key)
        assert field in problems
    assert validate_forward_key(build_forward_key(_base_request())) == []


def test_publish_resolve_roundtrip(tmp_path) -> None:
    cache = ContentAddressedCache(tmp_path)
    output = tmp_path / "raw.bin"
    output.write_bytes(b"raw")
    key = build_forward_key(_base_request())
    digest = cache.publish(key, str(output), "c" * 64)
    entry = cache.resolve(key)
    assert entry is not None
    assert entry.digest == digest
    assert entry.reusable is True
    assert entry.raw_output_sha256 == "c" * 64


def test_resolve_none_when_key_changes(tmp_path) -> None:
    cache = ContentAddressedCache(tmp_path)
    key = build_forward_key(_base_request())
    cache.publish(key, "raw.bin", "c" * 64)
    req2 = _base_request()
    req2["audio_sha256"] = "e" * 64
    assert cache.resolve(build_forward_key(req2)) is None


def test_publish_same_key_twice_no_overwrite(tmp_path) -> None:
    cache = ContentAddressedCache(tmp_path)
    key = build_forward_key(_base_request())
    d1 = cache.publish(key, "raw.bin", "c" * 64)
    d2 = cache.publish(key, "raw2.bin", "d" * 64)
    assert d1 == d2
    entry = cache.resolve(key)
    assert entry is not None
    assert entry.raw_output_path == "raw.bin"
    assert entry.raw_output_sha256 == "c" * 64


def test_publish_invalid_key_raises(tmp_path) -> None:
    cache = ContentAddressedCache(tmp_path)
    req = _base_request()
    del req["text_content_hash"]
    with pytest.raises(ValueError):
        cache.publish(build_forward_key(req), "raw.bin", "c" * 64)


def test_resolve_not_reusable_on_missing_field(tmp_path) -> None:
    # not_reusable 语义：缺必需字段的 key 无法证明身份，resolve 一律返回 None
    # （与 key 变化/无缓存一致的"不可复用"出口，避免误用旧产物）。
    cache = ContentAddressedCache(tmp_path)
    cache.publish(build_forward_key(_base_request()), "raw.bin", "c" * 64)
    req = _base_request()
    del req["audio_sha256"]
    assert cache.resolve(build_forward_key(req)) is None


def test_cache_forward_json_records_key_identity(tmp_path) -> None:
    cache = ContentAddressedCache(tmp_path)
    key = build_forward_key(_base_request())
    digest = cache.publish(key, "raw.bin", "c" * 64)
    record = json.loads((tmp_path / digest / "forward.json").read_text(encoding="utf-8"))
    assert canonical_forward_key(record["key"]) == canonical_forward_key(key)
    assert set(record["key"]) == set(REQUIRED_FORWARD_FIELDS)
