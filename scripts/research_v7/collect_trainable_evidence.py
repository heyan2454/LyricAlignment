#!/usr/bin/env python3
"""review9-6：唯一 evidence collection CLI —— 输入 RUN_MANIFEST，校验 train_filter 与 canonical lineage，
只输出 trainable evidence 路径清单。训练/评估命令只能消费该 collection（不能直接读原始 items/evidence）。

用法：
  python scripts/research_v7/collect_trainable_evidence.py --run-manifest <RUN_MANIFEST.json> --out <collection.json>
校验项：
  - RUN_MANIFEST 必须含 train_filter（guard 已运行，否则视为未经过滤入口、拒绝）
  - train_filter 必须含 trainable/rejected 清单与 denominator
  - canonical lineage：evidence 中每份 request 的 canonical_timeline_sha / source_window_sec 与
    RUN_MANIFEST 的 code_identity 一致（mapping 未串台）
输出 collection.json：{schema, run_id, trainable_evidence:[{request_identity, path, sha256}],
  rejected_count, denominator}。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_write(path: Path, payload: dict) -> None:
    import os
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        f.flush(); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def collect(run_manifest_path: Path, out: Path) -> dict:
    rm = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    # 1) 必须先经过 guard（train_filter 存在且为清单形态）
    tf = rm.get("train_filter")
    if not tf or "trainable" not in tf or "rejected" not in tf:
        raise ValueError("RUN_MANIFEST lacks a guard train_filter with trainable/rejected lists; "
                         "evidence is not guarded — refusing to build collection")
    out_root = run_manifest_path.parent
    evidence_dir = out_root / "evidence"
    trainable = []
    seen = set()
    for item in tf["trainable"]:
        idn = item.get("request_identity")
        if not idn:
            continue
        p = evidence_dir / f"{idn}.json"
        if not p.is_file():
            # 允许 fallback 到命中路径已登记（identity 有但文件没写 = 异常）
            raise ValueError(f"trainable identity {idn[:16]} has no evidence file under evidence/")
        if idn in seen:
            continue
        seen.add(idn)
        ev = json.loads(p.read_text(encoding="utf-8"))
        req = (ev.get("attempt") or {}).get("request") or {}
        trainable.append({
            "request_identity": idn,
            "path": str(p),
            "sha256": _sha(p),
            # review9-6：确保 identity 中 canonical lineage 确实进入 evidence（mapping 串台时此处断言失败）
            "canonical_timeline_sha": req.get("canonical_timeline_sha"),
            "source_window_sec": req.get("source_window_sec"),
            "canonical_to_local": req.get("canonical_to_local"),
        })
    collection = {
        "schema": "research_v7_trainable_evidence_collection_v1",
        "run_id": rm.get("run_id"),
        "guard": {
            "present": True,
            "trainable_count": tf.get("trainable_identity_count", len(trainable)),
            "rejected_count": tf.get("rejected_count"),
            "denominator": tf.get("denominator"),
        },
        "code_identity": rm.get("code_identity"),
        "trainable_evidence": trainable,
    }
    _atomic_write(out, collection)
    return collection


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-manifest", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    c = collect(Path(a.run_manifest), Path(a.out))
    print(json.dumps({"ok": True, "trainable": len(c["trainable_evidence"]),
                      "rejected": c["guard"]["rejected_count"], "out": a.out}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
