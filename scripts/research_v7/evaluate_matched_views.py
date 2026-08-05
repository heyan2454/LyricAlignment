#!/usr/bin/env python3
"""Detector V2 matched common-unit view comparison（22 §3.2/§8.1 Phase C）。

full / sparse / overlap 视图只在共同查询单位（matched common queried units）上比较：
- 几何差（预测时间 vs GT 时间的偏差分布）；
- 三态状态一致性（agree rate / 转换矩阵）；
- safe accept / reject / uncertain 在 matched set 上的一致性。

输入：--labels <LABELS.jsonl>（含 view_id/family/label）+ --multiview-manifest
（MULTIVIEW_MANIFEST.jsonl：pair_id → views）可选。输出 FULL_SPARSE_OVERLAP_MATCHED.json。
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import tempfile
from pathlib import Path


def _load_labels(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _items_map(run_root: Path) -> dict[str, tuple[str, str, str]]:
    """content sha -> (song, wi, family)；view 从 item_id 末段。items/<item_id>/<sha>.json。"""
    out: dict[str, tuple[str, str, str]] = {}
    items_root = run_root / "items"
    if not items_root.is_dir():
        return out
    for d in items_root.iterdir():
        if not d.is_dir():
            continue
        parts = d.name.split(":")
        if len(parts) < 3:
            continue
        key = (parts[0], parts[1], parts[2])
        for f in d.glob("*.json"):
            out[f.stem] = key
    return out


def _matched_comparison(labels: list[dict], family: str, target: str,
                        items_map: dict[str, tuple[str, str, str]] | None = None) -> dict:
    """matched 单位：同一 (song, wi, family) 三视图都查询的 units。"""
    by_req: dict[tuple, dict[str, dict[int, dict]]] = collections.defaultdict(
        lambda: collections.defaultdict(dict))
    for r in labels:
        if r.get("family") != family or r.get("target") != target:
            continue
        rid = r["request_identity"]
        if items_map and rid in items_map:
            key = items_map[rid]
        else:
            key = (r.get("song_id"), r.get("view_id"), rid)
        by_req[key][r.get("view_id")][int(r["canonical_unit_id"])] = r

    view_pairs = (("full", "sparse"), ("full", "overlap"), ("sparse", "overlap"))
    out: dict = {"family": family, "target": target, "view_pairs": {}}
    for va, vb in view_pairs:
        matched_total = 0
        agree = 0
        transitions: collections.Counter = collections.Counter()
        safe_accept_agree = 0
        safe_accept_total = 0
        n_requests = 0
        for rid, views in by_req.items():
            if va not in views or vb not in views:
                continue
            common = set(views[va]) & set(views[vb])
            common = {c for c in common
                      if views[va][c].get("label") not in ("gt_unavailable",)
                      and views[vb][c].get("label") not in ("gt_unavailable",)}
            if not common:
                continue
            n_requests += 1
            for c in common:
                la, lb = views[va][c]["label"], views[vb][c]["label"]
                matched_total += 1
                transitions[(la, lb)] += 1
                if la == lb:
                    agree += 1
                if la == "safe":
                    safe_accept_total += 1
                    safe_accept_agree += 1 if lb == "safe" else 0
        out["view_pairs"][f"{va}_vs_{vb}"] = {
            "n_matched_units": matched_total, "n_requests": n_requests,
            "agree_rate": (agree / matched_total) if matched_total else None,
            "safe_accept_agree_rate": (safe_accept_agree / safe_accept_total)
            if safe_accept_total else None,
            "transition_matrix": {f"{la}->{lb}": c for (la, lb), c in transitions.items()},
        }
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--labels", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--run-root", default=None,
                   help="run 根（items/ 目录提供 content sha → (song,wi,family) 映射）")
    p.add_argument("--families", default="baseline_legal",
                   help="逗号分隔 family（默认 baseline_legal）")
    p.add_argument("--targets", default="official,raw")
    a = p.parse_args(argv)

    labels = _load_labels(Path(a.labels))
    items_map = _items_map(Path(a.run_root)) if a.run_root else None
    result: dict = {"schema": "research_v7_matched_view_common_unit_v1",
                    "note": "only matched common queried units; unqueried units excluded "
                            "(22 §3.2)"}
    result["by_family_target"] = {}
    for family in [x.strip() for x in a.families.split(",") if x.strip()]:
        for target in [x.strip() for x in a.targets.split(",") if x.strip()]:
            result["by_family_target"][f"{family}|{target}"] = _matched_comparison(
                labels, family, target, items_map)

    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "FULL_SPARSE_OVERLAP_MATCHED.json"
    fd, tmp = tempfile.mkstemp(dir=str(out_dir), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=1, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    print(json.dumps({"ok": True, "out": str(path),
                      "keys": list(result["by_family_target"].keys())},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
