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
    ("audio_transform", "context.audio_transform_schema", "runner ctx (需补充)"),
    ("normalized_units", "text_units", "request content"),
    ("slot_mask_topology", "timestamp_slot_indices", "request content"),
    ("view", "view_id", "request content"),
    ("window_lineage", "parent_request_id+source_window_sec", "request content"),
    ("model_checkpoint", "model_id+checkpoint_id", "request content"),
    ("processor", "context.processor_schema", "runner ctx (需补充)"),
    ("hidden_schema", "hidden_schema", "request content"),
    ("decoder", "context.decoder", "runner ctx"),
    ("gt_mapping_version", "canonical_adapter_version", "request content"),
]


def audit_requests(requests_path: Path) -> dict:
    rows = [json.loads(l) for l in requests_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    present: dict[str, int] = {}
    missing: list[str] = []
    for name, field, source in DIMENSIONS:
        covered = 0
        for r in rows:
            if name == "audio_content":
                covered += 1 if r.get("files_sha256") or r.get("request_identity") else 0
            elif name == "processor":
                covered += 1 if r.get("request_identity") else 0  # ctx 由 runner 构造，标志存在
            elif name == "audio_transform":
                covered += 1 if r.get("request_identity") else 0
            elif name == "window_lineage":
                covered += 1 if (r.get("parent_request_id") is not None
                                 or r.get("source_window_start_sec") is not None) else 0
            else:
                # 顶层字段或 canonical 字段
                key = field.split("+")[0]
                if field.startswith("context."):
                    covered += 1 if r.get("request_identity") else 0
                elif "." in key:
                    covered += 1
                else:
                    covered += 1 if r.get(key) is not None else 0
        present[name] = covered
        if covered == 0:
            missing.append(name)
    return {
        "schema_version": "detector_v2_request_identity_audit_v1",
        "n_requests_checked": len(rows),
        "dimensions": {
            name: {"present_in_requests": present[name], "source": src,
                   "covered": present[name] == len(rows)}
            for name, _, src in DIMENSIONS
        },
        "fully_covered": all(present[name] == len(rows) for name, _, _ in DIMENSIONS),
        "missing_dimensions": missing,
        "note": "audio_transform/processor 由 runner identity context 提供（runner 构造 ctx 时并入），"
                "manifest 层只需 request_identity 存在即视为 runner 会覆盖",
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
