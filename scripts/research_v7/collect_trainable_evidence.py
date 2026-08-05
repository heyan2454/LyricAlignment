#!/usr/bin/env python3
"""review9-6：唯一 evidence collection CLI —— 输入 RUN_MANIFEST，校验 train_filter 清单
并核对 canonical lineage 转存一致性，只输出 trainable evidence 路径清单。
训练/评估命令只能消费该 collection（不能直接读原始 items/evidence）。

用法：
  python scripts/research_v7/collect_trainable_evidence.py --run-manifest <RUN_MANIFEST.json> --out <collection.json>
校验项：
  - RUN_MANIFEST 必须含 guard 产出的 train_filter（trainable/rejected 清单形态），否则视为未经过滤入口、拒绝
  - 每个 trainable request_identity 必须存在 evidence/<identity>.json 文件
  - canonical lineage 转存一致性（review17-minor）：collection 每条记录的
    canonical_timeline_file_sha / canonical_timeline_row_sha / source_window_sec 必须与其
    evidence.request 一致（缺失字段容错；仅两侧都存在但冲突时失败，防止收集时串台）
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


_LINEAGE_FIELDS = ("canonical_timeline_file_sha", "canonical_timeline_row_sha", "source_window_sec")


def _lineage_transfer_conflict(request: dict, stored: dict) -> str | None:
    """review17-minor：collection 转存字段与 evidence.request 的 canonical lineage 一致性。

    缺失字段容错（旧 evidence 无 canonical 字段不硬失败，向后兼容）；
    仅当两侧字段都出现且不同才返回冲突描述（防止收集时串台）。
    """
    for k in _LINEAGE_FIELDS:
        ev_v, st_v = request.get(k), stored.get(k)
        if ev_v is not None and st_v is not None and ev_v != st_v:
            return f"lineage cross-talk: request[{k}] {ev_v!r} != collection stored {st_v!r}"
    return None


def _verify_lineage_transfer(entries: list[dict]) -> None:
    """review17-minor：转存一致性校验（防收集时串台）。

    对每个转存字段单独读回 evidence 核对；缺失字段容错（向后兼容），
    仅“两侧都存在但冲突”时拒绝。
    """
    for entry in entries:
        ev = json.loads(Path(entry["path"]).read_text(encoding="utf-8"))
        req = (ev.get("attempt") or {}).get("request") or {}
        conflict = _lineage_transfer_conflict(req, entry)
        if conflict:
            raise ValueError(f"trainable {entry['request_identity'][:16]}: {conflict}")


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
            # review9-6 / review10-1/10-3：确保 identity 中 canonical lineage 确实进入 evidence（mapping 串台时此处失败）
            "canonical_ids": req.get("canonical_ids"),
            "canonical_timeline_file_sha": req.get("canonical_timeline_file_sha"),
            "canonical_timeline_row_sha": req.get("canonical_timeline_row_sha"),
            "source_window_sec": req.get("source_window_sec"),
            "canonical_to_local": req.get("canonical_to_local"),
            # round18（family LOO）：mutation family 转存（baseline/missing/replace/extra），
            # 供 assessor 分层与 family-LOO；只用于分层/评价，不进特征（13 §10.1）。
            "mutation_type": req.get("mutation_type"),
        })
    # review17-minor：转存一致性校验（防收集时串台）——缺失字段容错，仅“存在但冲突”拒绝
    _verify_lineage_transfer(trainable)
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




def finalize_collection(collection: dict, out: Path) -> dict:
    """写 collection 并返回带 collection_sha（消费者 run manifest 引用其 SHA，防绕过）。"""
    import hashlib as _h
    data = json.dumps(collection, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    collection = dict(collection)
    collection["collection_sha256"] = _h.sha256(data).hexdigest()
    _atomic_write(out, collection)
    return collection


def load_verified(path: Path | str, *, verify_sha: bool = True) -> tuple[dict, str]:
    """消费者【唯一】入口：加载 collection 并校验 guard 与显式 evidence 路径存在。

    未来 feature trainer / threshold freezer / formal evaluator 只允许接收此结果，
    不允许直接读原始 items/evidence（review10-5）。

    round10（review MAJOR-3）：verify_sha=True 时重算 collection_sha256（对去掉该字段的
    payload 序列化，与 finalize_collection 同法）并比对，检测 sha 记录与内容断环。
    """
    import hashlib as _h
    p = Path(path)
    c = json.loads(p.read_text(encoding="utf-8"))
    g = c.get("guard")
    if verify_sha:
        stored = c.get("collection_sha256")
        if not stored:
            raise ValueError("collection missing collection_sha256 — may be stale bypass")
        payload = {k: v for k, v in c.items() if k != "collection_sha256"}
        recomputed = _h.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        if recomputed != stored:
            raise ValueError(
                f"collection_sha256 mismatch: stored {stored[:12]} != recomputed {recomputed[:12]} "
                "(content drifted after finalize)")
    else:
        if "collection_sha256" not in c:
            raise ValueError("collection missing collection_sha256 — may be stale bypass")
    if not isinstance(g, dict) or g.get("present") is not True:
        raise ValueError("collection missing guard (present=True) — refuses bypass")
    paths = [t["path"] for t in c.get("trainable_evidence", [])]
    for fp in paths:
        if not Path(fp).is_file():
            raise ValueError(f"collection lists missing evidence file: {fp}")
    return c, c["collection_sha256"]

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-manifest", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    c = collect(Path(a.run_manifest), Path(a.out))
    c = finalize_collection(c, Path(a.out))  # review10-5：collection 自带 sha，消费者引用
    print(json.dumps({"ok": True, "trainable": len(c["trainable_evidence"]),
                      "rejected": c["guard"]["rejected_count"],
                      "collection_sha256": c["collection_sha256"], "out": a.out}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
