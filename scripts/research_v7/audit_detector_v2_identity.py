#!/usr/bin/env python3
"""Detector V2 Phase0-4：request identity audit（G2 gate）。

校验 Detector V2 请求 identity 是否覆盖 19 §G2 全部维度：
audio content/crop/transform、normalized units、slot mask/topology、view、
window/lineage、model/checkpoint/processor、hidden schema、decoder、GT mapping version。

产出 REQUEST_IDENTITY_AUDIT.json：每维度是否入 identity（content 字段或 context）、
示例请求覆盖情况、缺失维度清单。纯 CPU 只读审计。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# (维度, AlignmentRequest content 字段或 context 键, 来源)
DIMENSIONS = [
    ("audio_content", "context.audio_content_sha256", "runner ctx"),
    ("audio_crop", "audio_start_sec+audio_end_sec", "request content"),
    ("audio_transform", "context.audio_transform_schema", "runner ctx"),
    ("normalized_units", "text_units", "request content"),
    ("slot_mask_topology", "timestamp_slot_indices", "request content"),
    ("view", "view_id", "request content"),
    ("window_lineage", "parent_request_id+source_window_sec", "request content"),
    ("model_checkpoint", "model_id+checkpoint_id", "request content"),
    ("processor", "context.processor_schema", "runner ctx"),
    ("hidden_schema", "hidden_schema", "request content"),
    ("decoder", "context.decoder", "runner ctx"),
    ("gt_mapping_version", "canonical_adapter_version", "request content"),
]

# M11/M8（review）：runner 运行时 ctx 维度，manifest 层不可验证——既不误报 covered
# 也不误报 missing（request_identity 存在不等于 ctx 真的并入，旧实现属审计失真）。
RUNNER_CTX_DIMENSIONS = {"audio_content", "audio_transform", "processor", "decoder"}
RUNNER_CTX_NOTES = {
    "audio_content": "音频内容 hash 由 runner 运行时对实际解码音频自算，manifest 层不可验证"
                     "（request_identity 存在不能作为音频内容已并入 identity 的证据）",
    "audio_transform": "transform schema 由 runner 构造 identity context 时并入，manifest 层不可验证",
    "processor": "processor schema 由 runner 构造 identity context 时并入，manifest 层不可验证",
    "decoder": "decoder 选择由 runner 构造 identity context 时并入，manifest 层不可验证",
}


def audit_requests(requests_path: Path) -> dict:
    rows = [json.loads(l) for l in requests_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    dimensions: dict[str, dict] = {}
    missing: list[str] = []
    for name, field, source in DIMENSIONS:
        if name in RUNNER_CTX_DIMENSIONS:
            dimensions[name] = {
                "verification": "unverifiable_from_manifest",
                "present_in_requests": None,
                "null_value_in_requests": None,
                "absent_in_requests": None,
                "source": source,
                "note": RUNNER_CTX_NOTES[name],
            }
            continue
        keys = [k.strip() for k in field.split("+")]
        present = 0
        nulls = 0
        for r in rows:
            if all(k in r for k in keys):
                present += 1
                if all(r.get(k) is None for k in keys):
                    nulls += 1
        covered = present == len(rows) and present > 0
        if not covered:
            missing.append(name)
        dimensions[name] = {
            "verification": "covered" if covered else "missing",
            "present_in_requests": present,
            "null_value_in_requests": nulls,
            "absent_in_requests": len(rows) - present,
            "source": source,
        }
    return {
        "schema_version": "detector_v2_request_identity_audit_v2",
        "n_requests_checked": len(rows),
        "dimensions": dimensions,
        "fully_covered": not missing,
        "missing_dimensions": missing,
        "unverifiable_from_manifest": [n for n, d in dimensions.items()
                                       if d["verification"] == "unverifiable_from_manifest"],
        "note": "content 维度以键存在为准（字段存在但值 None 亦计声明，另以 "
                "null_value_in_requests 透明披露；键缺失才计 missing）；"
                "audio_content/audio_transform/processor/decoder 由 runner 运行时/ctx 提供，"
                "manifest 层不可验证（unverifiable_from_manifest），既不误报 covered 也不误报 missing",
    }


def _atomic_write(path: Path, payload: dict) -> None:
    import os
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--requests", required=True, help="REQUESTS.jsonl（Detector V2 请求清单）")
    p.add_argument("--out-root", required=True)
    a = p.parse_args(argv)
    audit = audit_requests(Path(a.requests))
    out = Path(a.out_root)
    _atomic_write(out / "REQUEST_IDENTITY_AUDIT.json", audit)
    print(json.dumps({"ok": True, "n_requests": audit["n_requests_checked"],
                      "fully_covered": audit["fully_covered"],
                      "missing": audit["missing_dimensions"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
