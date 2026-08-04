#!/usr/bin/env python3
"""review11-4：region assessor train/freeze consumer —— 只消费 guarded evidence collection。

现有 analysis/evaluate 脚本仍读旧 `{out_root,records}` collection；本 CLI 是接入新
`research_v7_trainable_evidence_collection_v1` schema 的实际 consumer：

- 入口唯一：`--collection` 必须经 `load_verified()` 校验（guard present=True +
  collection_sha256 + 每份 evidence 文件存在），否则拒绝；
- 对每个 trainable evidence 提取 unit 特征（features.unit_features，R/O/H）；
- 标签只允许来自 evidence 的 `attempt.gt_eval["unsafe_unit_indices"]`（评审：GT 不进输入特征，
  标签不参与 request identity）；无标签时明确记录 labels_available=false 并拒绝训练/冻结，
  不假装产 operating points；
- 按 item_id 划分 train/val（train_frac），fit_and_freeze 只从 train 拟合、val 选 operating point；
- 输出 ASSESSOR_RUN_MANIFEST.json：collection SHA、实际 train/eval 分母、输出路径。

用法：
  PYTHONPATH=src python scripts/research_v7/assessor_train_eval.py \
      --collection <collection.json> --out <run_dir> [--train-frac 0.7] [--include-hidden]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.research_v7.features import unit_features  # noqa: E402
from lyricalign.research_v7.region_assessor import fit_and_freeze  # noqa: E402

COLLECTION_SCHEMA = "research_v7_trainable_evidence_collection_v1"


def _atomic_write(path: Path, payload: dict) -> None:
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def _load_verified_collection(path: Path):
    """唯一入口：校验 guard/collection_sha256/evidence 存在；返回 (collection, sha)。"""
    sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
    from collect_trainable_evidence import load_verified
    return load_verified(path)


def _unit_rows(evidence: dict) -> list[tuple[dict, int]]:
    """从 evidence 的 official decoder rows 提取 (row, row_index)。无 rows → 空。"""
    attempt = evidence.get("attempt") or {}
    rows = (attempt.get("decoder_outputs") or {}).get("official") or {}
    rows = rows.get("rows") or []
    return [(r, i) for i, r in enumerate(rows) if isinstance(r, dict)]


def _labels_from_gt_eval(attempt: dict) -> tuple[set[int] | None, str | None]:
    """读取 GT 标签：attempt.gt_eval.unsafe_unit_indices（unit 局部索引）。

    返回 (unsafe_set, error)；无标签/格式错误 → (None, reason)，不训练。
    """
    gt = attempt.get("gt_eval")
    if not isinstance(gt, dict):
        return None, "no gt_eval in evidence"
    raw = gt.get("unsafe_unit_indices")
    if raw is None:
        return None, "gt_eval lacks unsafe_unit_indices"
    try:
        idx = [int(i) for i in raw]
    except (TypeError, ValueError) as e:
        return None, f"gt_eval unsafe_unit_indices malformed: {e}"
    return set(idx), None


def consume(collection_path: Path, out: Path, *, train_frac: float = 0.7,
            include_hidden: bool = False) -> dict:
    """消费 collection：特征提取 + 标签 + assessor train/freeze；返回 run manifest dict。"""
    if not (0.0 < train_frac < 1.0):
        raise ValueError(f"train_frac must be in (0,1), got {train_frac}")
    c, collection_sha = _load_verified_collection(collection_path)
    if c.get("schema") != COLLECTION_SCHEMA:
        raise ValueError(f"collection schema mismatch: {c.get('schema')!r}")
    feature_rows: list[dict] = []
    labels: dict[str, set[int]] = {}      # request_identity -> unsafe unit indices
    denominator = {"trainable_evidence": 0, "units": 0, "items": 0}
    per_item: dict[str, list] = {}        # item_id -> [feature rows] 用于 train/val split
    label_errors: list[str] = []
    for t in c.get("trainable_evidence", []):
        idn = t.get("request_identity")
        ev_path = Path(t.get("path"))
        if not ev_path.is_file():
            raise ValueError(f"collection lists missing evidence file: {ev_path}")
        ev = json.loads(ev_path.read_text(encoding="utf-8"))
        attempt = ev.get("attempt") or {}
        request = attempt.get("request") or {}
        item_id = request.get("item_id") or t.get("item_id") or "?"
        rows = _unit_rows(ev)
        denominator["trainable_evidence"] += 1
        denominator["items"] += 1
        unsafe, lerr = _labels_from_gt_eval(attempt)
        if lerr:
            label_errors.append(f"{idn}: {lerr}")
        else:
            labels[idn] = unsafe
        for row, row_i in rows:
            feats = unit_features(row, include_hidden=include_hidden)
            fr = {
                "request_identity": idn,
                "item_id": item_id,
                "unit_index": row_i,
                "features": feats,
            }
            feature_rows.append(fr)
            per_item.setdefault(item_id, []).append(fr)
            denominator["units"] += 1
    denominator["items"] = len(per_item)   # 唯一 item 数（同 item 多条 evidence 只计一次）
    # 统一特征键集合：跨行列对齐（不同 evidence 可能缺 official geometry 等键），
    # 缺失键填 0.0，避免 np.asarray 形状不一致导致 fit 崩溃。
    feature_keys = sorted({k for fr in feature_rows for k in fr["features"]
                           if isinstance(fr["features"][k], (int, float)) and fr["features"][k] is not None})
    # 标签可用性：任何 evidence 无 gt_eval → 整体拒绝训练（不假装 operating points）
    labels_available = (not label_errors) and bool(labels) and denominator["units"] > 0
    assessor = {"labels_available": labels_available, "operating_points": None,
                "reason": None, "train_units": None, "val_units": None}
    if labels_available:
        # 按 item_id 划分 train/val（同 item 不跨集合），只从 train 拟合；
        # 单 item（item 级任一为空）时回退为 unit 级固定 seed 随机划分，并在 manifest 记录。
        item_ids = sorted(per_item)
        split = max(1, int(len(item_ids) * train_frac))
        train_items, val_items = set(item_ids[:split]), set(item_ids[split:])
        split_mode = "by_item"
        if not val_items:
            # 单 item → unit 级固定 seed 划分：先 shuffle 再按 train_frac 切分，
            # 保证 train/val 两折都非空（不用逐 unit random()，避免全落一折）。
            split_mode = "by_unit_fallback"
            import random as _r
            rng = _r.Random(0)
            order = list(range(len(feature_rows)))
            rng.shuffle(order)
            k = max(1, int(len(order) * train_frac))
            train_units, val_units = set(order[:k]), set(order[k:])
            for i, fr in enumerate(feature_rows):
                fr["_fold"] = "train" if i in train_units else "val"
        Xt, yt, Xv, yv = [], [], [], []
        for fr in feature_rows:
            xvec = [float(fr["features"].get(k) or 0.0) for k in feature_keys]
            y = 1.0 if fr["unit_index"] in labels.get(fr["request_identity"], set()) else 0.0
            if split_mode == "by_item":
                in_train = fr["item_id"] in train_items
            else:
                in_train = fr.get("_fold") == "train"
            if in_train:
                Xt.append(xvec); yt.append(y)
            else:
                Xv.append(xvec); yv.append(y)
        if not Xt or not Xv:
            assessor["reason"] = "not enough units for train/val split"
            assessor["labels_available"] = False
        else:
            import numpy as np
            res = fit_and_freeze(np.asarray(Xt, dtype=float), np.asarray(yt, dtype=float),
                                 np.asarray(Xv, dtype=float), np.asarray(yv, dtype=float))
            assessor["operating_points"] = res["operating_points"]
            assessor["train_units"] = len(Xt)
            assessor["val_units"] = len(Xv)
            assessor["split_mode"] = split_mode
    else:
        assessor["reason"] = "; ".join(label_errors[:5]) if label_errors else "no labels in collection"
    # 输出：特征行 + assessor + run manifest（记录 collection SHA、实际分母、输出路径）
    features_file = out / "UNIT_FEATURES.jsonl"
    features_file.parent.mkdir(parents=True, exist_ok=True)
    with open(features_file, "w", encoding="utf-8") as f:
        for fr in feature_rows:
            f.write(json.dumps(fr, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    assessor_file = out / "ASSESSOR.json"
    _atomic_write(assessor_file, assessor)
    manifest = {
        "schema": "research_v7_assessor_consumer_run_v1",
        "collection_sha256": collection_sha,
        "input_collection": str(collection_path.resolve()),
        "code": {"script": "assessor_train_eval.py",
                 "features_module": "lyricalign.research_v7.features",
                 "assessor_module": "lyricalign.research_v7.region_assessor"},
        "denominator": denominator,
        "feature_keys": feature_keys,
        "labels": {"available": labels_available, "evidence_with_labels": len(labels),
                   "error_count": len(label_errors)},
        "assessor": {k: v for k, v in assessor.items()},
        "outputs": {"features": str(features_file), "assessor": str(assessor_file),
                    "manifest": str(out / "ASSESSOR_RUN_MANIFEST.json")},
    }
    _atomic_write(out / "ASSESSOR_RUN_MANIFEST.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--collection", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--train-frac", type=float, default=0.7)
    p.add_argument("--include-hidden", action="store_true")
    a = p.parse_args(argv)
    m = consume(Path(a.collection), Path(a.out), train_frac=a.train_frac,
                include_hidden=a.include_hidden)
    print(json.dumps({"ok": True, "collection_sha256": m["collection_sha256"][:16],
                      "trainable_evidence": m["denominator"]["trainable_evidence"],
                      "units": m["denominator"]["units"],
                      "labels_available": m["labels"]["available"],
                      "operating_points": m["assessor"]["operating_points"],
                      "out": str(Path(a.out))}, ensure_ascii=False))
    # C3（review12）：无标签时输出已写（含 reason），但退出码非 0，
    # 防止 formal 管线把"无标签的 assessor"误当训练成功继续推进。
    if not m["labels"]["available"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
