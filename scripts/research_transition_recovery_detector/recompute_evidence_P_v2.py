#!/usr/bin/env python3
"""二次补充 Stage B：用新 P 算法从 posterior npy 重算 evidence_P（CPU，无重新 forward）。

读取 serial_infer_v3 cache 的 full_posterior npy（含请求 identity），用
posterior_paths.competing_path_features / unit_p_features 生成新的 request-level
与 unit-level P evidence，写 evidence_P_{role}.jsonl（v2 schema）。

输入：
- --cache-root：serial_infer_v3 cache 目录（含 *_posterior.npy）
- --session-root：目标 session（evidence jsonl 写入 06_detector）
- --records-root：records（提供 committed request identity / query ids）
- --role：detector_train / model_selection / threshold_validation
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from lyricalign.research_transition_recovery_detector.posterior_paths import (  # noqa: E402
    competing_path_features,
    unit_p_features,
)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache-root", required=True)
    p.add_argument("--session-root", required=True)
    p.add_argument("--records-root", required=True)
    p.add_argument("--role", required=True, choices=("detector_train", "model_selection", "threshold_validation"))
    p.add_argument("--timeline-manifest", required=True)
    args = p.parse_args()

    cache_root = Path(args.cache_root)
    session = Path(args.session_root)
    records_root = Path(args.records_root)
    out_dir = session / "06_detector"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 角色歌曲
    split = json.loads((records_root / "00_meta" / "DATASET_SPLIT.json").read_text(encoding="utf-8"))
    song_ids = set(split["roles"][args.role])

    # 收集该角色的 request identity（从 records）
    transition = "T2_core_boundary_serial"
    requests: dict[str, dict] = {}
    for song in song_ids:
        cand = records_root / "02_transition" / f"{song}__{transition}.jsonl"
        if not cand.is_file():
            cands = sorted((records_root / "02_transition").glob(f"{song}__T2_core*.jsonl"))
            cand = cands[0] if cands else None
        if cand is None or not cand.is_file():
            continue
        for line in cand.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            req = rec["request"]
            qids = [int(c) for c in req.get("query_canonical_ids", [])]
            requests[req["request_id"]] = {
                "song_id": song,
                "window_index": rec.get("window_index"),
                "request_id": req["request_id"],
                "query_canonical_ids": qids,
                "n_units": len(qids),
            }

    out_rows: list[dict] = []
    n_ok = n_unique = n_no_monotone = n_missing = 0
    for req_id, meta in sorted(requests.items()):
        path = None
        # 优先从 recollect 生成的新 evidence_posterior jsonl 读 posterior path（正确 per-window）
        for src_name in (f"evidence_posterior_{args.role}.jsonl", f"evidence_P_{args.role}.jsonl"):
            src = out_dir / src_name
            if not src.is_file():
                continue
            for line in src.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                if r.get("request_id") == req_id and r.get("path"):
                    path = r["path"]
                    break
            if path:
                break
        if not path:
            n_missing += 1
            continue
        npy = Path(path)
        if not npy.is_file():
            # 尝试 cache-root 下
            npy = cache_root / "evidence_v3" / path.rsplit("/", 1)[-1]
        if not npy.is_file():
            n_missing += 1
            continue
        probs = np.load(npy, mmap_mode="r").astype(np.float32)
        req_feat = competing_path_features(probs, k=2, top_n=32)
        slot_to_unit = [min(i // 2, meta["n_units"] - 1) for i in range(min(probs.shape[0], 2 * meta["n_units"]))]
        unit_feats = unit_p_features(probs, slot_to_unit, k=2, top_n=32)
        status = req_feat.get("status")
        if status == "ok":
            n_ok += 1
        elif status == "unique_posterior":
            n_unique += 1
        elif status == "no_monotone_path":
            n_no_monotone += 1
        out_rows.append({
            "schema": "evidence_P_v2",
            "song_id": meta["song_id"],
            "window_index": meta["window_index"],
            "request_id": req_id,
            "n_units": meta["n_units"],
            "path": str(npy),
            "p_features": req_feat,
            "unit_p": unit_feats,
        })

    out_path = out_dir / f"evidence_P_{args.role}.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for row in out_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({
        "role": args.role, "requests": len(requests), "written": len(out_rows),
        "status": {"ok": n_ok, "unique_posterior": n_unique,
                   "no_monotone_path": n_no_monotone, "missing": n_missing},
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
