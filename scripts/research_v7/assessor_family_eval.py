#!/usr/bin/env python3
"""round18：assessor family 分层 + per-song LOO 汇总驱动（13 §10.3/§10.2，全 CPU）。

输入 formal run root（RUN_MANIFEST.json + evidence/，如 review12 formal_v2_run_c）：
  1. collect_trainable_evidence 生成 guarded collection（--out/collection.json）；
  2. 4 family 分别训练（--family）+ 全 family 混合训练 → family 表：每 family 的
     train/val 折（evidence/items/units）、frozen op（95/99）、val unit_recall /
     correct_unit_fpr（弱标签口径，同 evaluate_cross_domain_assessor）；
  3. family-LOO：每 family 留出重训 + 对留出 family 打分（assessor_train_eval.family_loo，
     留出 family 完全不可见）；
  4. per-song LOO：逐歌留出重训（split_by=song 歌隔离）→ op 均值/方差/std 与
     pooled recall 波动；
  5. 迁移结论：现役（baseline+missing 训练）assessor 对 replace/extra 打分。

mutation family 只用于分层/评价，不进特征（13 §10.1）。输出 ASSESSOR_FAMILY_EVAL.json
（schema research_v7_assessor_family_eval_v1）。

用法：
  PYTHONPATH=src python scripts/research_v7/assessor_family_eval.py \
      --run-root <formal_v2_run_c> --out <dir> [--train-frac 0.7] [--split-by item|song]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[0]))

import numpy as np  # noqa: E402

from lyricalign.research_v7.region_assessor import LogisticAssessor  # noqa: E402

from assessor_train_eval import (  # noqa: E402
    _binary_scores, _extract_rows, _feature_keys, _row_y, _xvec,
    consume, family_loo, group_loo,
)
from collect_trainable_evidence import collect, finalize_collection  # noqa: E402

SCHEMA = "research_v7_assessor_family_eval_v1"
OP_DELTA_FLAG = 0.05          # |op_family - op_mixed| 超过该值 → family 改变 op
FPR_OVERSHOOT = 2.0           # 留出 family FPR 超过训练 family 中位 FPR 的倍数 → 迁移劣化
OUTPUT_NAME = "ASSESSOR_FAMILY_EVAL.json"
FORMAL_FAMILIES = ("baseline", "missing", "replace", "extra")


def _atomic_write(path: Path, payload: dict) -> None:
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _family_row(m: dict) -> dict:
    """从 consume 的 run manifest 提取 family 表行（train/val 折 + frozen op + val 指标）。"""
    a = m["assessor"]
    vm = a.get("val_metrics") or {}
    op = a.get("operating_points") or {}
    return {
        "split_by": m.get("split_by"),
        "split_mode": a.get("split_mode"),
        "n_evidence": m["denominator"]["trainable_evidence"],
        "n_items": m["denominator"]["items"],
        "n_units": m["denominator"]["units"],
        "train_units": a.get("train_units"),
        "val_units": a.get("val_units"),
        "op95": op.get("high_recall_95"),
        "op99": op.get("high_recall_99"),
        "val_unit_recall_95": vm.get("unit_recall_95"),
        "val_unit_recall_99": vm.get("unit_recall_99"),
        "val_correct_unit_fpr_95": vm.get("correct_unit_fpr_95"),
        "val_correct_unit_fpr_99": vm.get("correct_unit_fpr_99"),
        "labels_available": a.get("labels_available"),
    }


def _stat(vals: list[float]) -> dict:
    """均值/方差/std（样本方差 ddof=1；n=1 时 var/std=0）与 min/max。"""
    if not vals:
        return {"n": 0, "mean": None, "var": None, "std": None, "min": None, "max": None}
    a = np.asarray(vals, dtype=float)
    n = len(a)
    var = float(a.var(ddof=1)) if n > 1 else 0.0
    return {"n": n, "mean": round(float(a.mean()), 6), "var": round(var, 8),
            "std": round(float(a.std(ddof=1)), 6) if n > 1 else 0.0,
            "min": round(float(a.min()), 6), "max": round(float(a.max()), 6)}


def _pool_from_rows(rows: list[dict], tag: str) -> tuple[float | None, float | None, int, int]:
    """跨 group 汇总（每 group 由各自 LOO 模型打分）：(recall, fpr, n_gt, n_safe)。"""
    hit = sum(r.get(f"n_hit_{tag}", 0) for r in rows)
    pred = sum(r.get(f"n_pred_{tag}", 0) for r in rows)
    fp = sum(r.get(f"n_fp_{tag}", 0) for r in rows)
    n_gt = sum(r.get("n_gt_unsafe_units", 0) for r in rows)
    n_safe = sum(r.get("n_safe_units", 0) for r in rows)
    if n_gt or pred:
        recall = hit / n_gt if n_gt else 0.0
    else:
        recall = None
    return (round(recall, 4) if recall is not None else None,
            round(fp / n_safe, 4) if n_safe else 0.0, n_gt, n_safe)


def _run_song_loo(rows: list[dict], labels: dict, keys: list[str],
                  train_frac: float) -> dict:
    """per-song LOO：逐歌留出重训（split_by=song），统计 op 波动与 pooled recall。"""
    songs = sorted({fr["song"] for fr in rows})
    loo = group_loo(rows, labels, keys, songs, lambda fr: fr["song"], train_frac, "song")
    song_rows = []
    for r in loo:
        te = r.get("test") or {}
        op = r.get("operating_points") or {}
        song_rows.append({
            "song": r["group"],
            "n_units": te.get("n_units"),
            "n_gt_unsafe_units": te.get("n_gt_unsafe_units"),
            "n_safe_units": te.get("n_safe_units"),
            "op95": op.get("high_recall_95"),
            "op99": op.get("high_recall_99"),
            "unit_recall_95": te.get("unit_recall_95"),
            "unit_recall_99": te.get("unit_recall_99"),
            "correct_unit_fpr_95": te.get("correct_unit_fpr_95"),
            "correct_unit_fpr_99": te.get("correct_unit_fpr_99"),
            "n_hit_95": te.get("n_hit_95"), "n_hit_99": te.get("n_hit_99"),
            "n_pred_95": te.get("n_pred_95"), "n_pred_99": te.get("n_pred_99"),
            "n_fp_95": te.get("n_fp_95"), "n_fp_99": te.get("n_fp_99"),
        })
    rec95, fpr95, gt95, _ = _pool_from_rows(song_rows, "95")
    rec99, fpr99, gt99, _ = _pool_from_rows(song_rows, "99")
    return {
        "n_songs": len(song_rows),
        "songs": song_rows,
        "stats": {
            "op95": _stat([r["op95"] for r in song_rows if r["op95"] is not None]),
            "op99": _stat([r["op99"] for r in song_rows if r["op99"] is not None]),
            "unit_recall_95": _stat([r["unit_recall_95"] for r in song_rows
                                     if r["unit_recall_95"] is not None]),
            "unit_recall_99": _stat([r["unit_recall_99"] for r in song_rows
                                     if r["unit_recall_99"] is not None]),
            "correct_unit_fpr_95": _stat([r["correct_unit_fpr_95"] for r in song_rows
                                          if r["correct_unit_fpr_95"] is not None]),
            "correct_unit_fpr_99": _stat([r["correct_unit_fpr_99"] for r in song_rows
                                          if r["correct_unit_fpr_99"] is not None]),
            "pooled_unit_recall_95": rec95,
            "pooled_unit_recall_99": rec99,
            "pooled_correct_unit_fpr_95": fpr95,
            "pooled_correct_unit_fpr_99": fpr99,
            "pooled_n_gt_unsafe_units_95": gt95,
            "pooled_n_gt_unsafe_units_99": gt99,
        },
    }


def run(run_root: Path, out: Path, *, train_frac: float = 0.7,
        split_by: str = "item", families: list[str] | None = None) -> dict:
    """汇总驱动：collection + family 表 + family-LOO + per-song LOO + 迁移结论。"""
    out.mkdir(parents=True, exist_ok=True)
    collection_path = out / "collection.json"
    c = finalize_collection(collect(run_root / "RUN_MANIFEST.json", collection_path),
                            collection_path)
    collection_sha = c["collection_sha256"]

    fam_names = sorted({t.get("mutation_type") for t in c["trainable_evidence"]
                        if t.get("mutation_type")})
    fam_names = [f for f in fam_names if not families or f in set(families)]

    # 2) family 表：每 family 单独训练 + 全 family 混合训练
    family_table = {}
    for f in fam_names:
        m = consume(collection_path, out / f"family_{f}", train_frac=train_frac,
                    split_by=split_by, families=[f])
        family_table[f] = _family_row(m)
    mm = consume(collection_path, out / "mixed", train_frac=train_frac, split_by=split_by)
    family_table["mixed"] = _family_row(mm)

    # 3) family-LOO（每 family 留出重训，留出 family 完全不可见）
    fl = family_loo(collection_path, out, train_frac=train_frac, split_by=split_by)

    # 4) per-song LOO（split_by=song 歌隔离）
    ex = _extract_rows(c)
    rows = ex["feature_rows"]
    labels = ex["labels"]
    keys = _feature_keys(rows)
    song_loo = _run_song_loo(rows, labels, keys, train_frac)

    # 5) 迁移：现役（baseline+missing 训练）assessor 对各 family 打分
    transfer = None
    if not families or {"baseline", "missing"} <= set(families):
        tm = consume(collection_path, out / "transfer_baseline_missing",
                     train_frac=train_frac, split_by=split_by,
                     families=["baseline", "missing"])
        tmodel = tm["assessor"]["model"]
        if not tm.get("labels", {}).get("available") or tmodel is None:
            # MAJOR-1（round18 review）：无标签 collection（未先跑 label_evidence_gt_eval）
            # 时 consume 不产 model 权重——不得裸 TypeError，记录 reason 继续。
            transfer = {"reason": "baseline+missing consume produced no model (labels unavailable?)",
                        "details": None}
        else:
            top = tm["assessor"]["operating_points"] or {}
            predictor = LogisticAssessor(beta=np.asarray(tmodel["beta"], dtype=float),
                                         mean=np.asarray(tmodel["mean"], dtype=float),
                                         std=np.asarray(tmodel["std"], dtype=float))
            predictor.frozen = True
            mk = tmodel["feature_keys"]
            tr_rows = {}
            for f in sorted({fr["family"] for fr in rows if fr["family"] is not None}):
                frows = [fr for fr in rows if fr["family"] == f]
                if not frows:
                    tr_rows[f] = {"n_units": 0, "n_gt_unsafe_units": 0,
                                  "unit_recall_95": None, "correct_unit_fpr_95": None}
                    continue
                X = np.asarray([_xvec(fr, mk) for fr in frows], dtype=float)
            y = np.asarray([_row_y(fr, labels) for fr in frows], dtype=float)
            tr_rows[f] = _binary_scores(y, predictor.predict_proba(X),
                                        top.get("high_recall_95", 0.5),
                                        top.get("high_recall_99", 0.5))
            transfer = {
                "trained_on": ["baseline", "missing"],
                "operating_points": top,
                "train_units": tm["assessor"].get("train_units"),
                "val_units": tm["assessor"].get("val_units"),
                "val_metrics": tm["assessor"].get("val_metrics"),
                "scored_families": tr_rows,
            }

    # 6) 结论
    mixed = family_table.get("mixed") or {}
    deltas = {}
    max_delta = 0.0
    for f in fam_names:
        row = family_table.get(f) or {}
        d = {}
        for k, tag in (("op95", "95"), ("op99", "99")):
            a, b = row.get(k), mixed.get(k)
            v = abs(a - b) if (a is not None and b is not None) else None
            d[f"op{tag}_abs_delta"] = round(v, 4) if v is not None else None
            if v is not None:
                max_delta = max(max_delta, v)
        deltas[f] = d
    family_changes_op = {
        "flag": max_delta >= OP_DELTA_FLAG,
        "threshold": OP_DELTA_FLAG,
        "max_abs_delta": round(max_delta, 4),
        "per_family_abs_delta": deltas,
        "note": "|op_family - op_mixed| >= threshold 视为 family 改变 frozen operating point",
    }
    transfer_conclusion = None
    if transfer:
        tr = transfer["scored_families"]
        in_fpr = [tr[f]["correct_unit_fpr_99"] for f in ("baseline", "missing")
                  if tr.get(f, {}).get("n_units")]
        in_recall = [tr[f]["unit_recall_99"] for f in ("baseline", "missing")
                     if tr.get(f, {}).get("n_units")]
        out_fpr = {f: tr[f]["correct_unit_fpr_99"] for f in ("replace", "extra")
                   if tr.get(f, {}).get("n_units")}
        out_recall = {f: tr[f]["unit_recall_99"] for f in ("replace", "extra")
                      if tr.get(f, {}).get("n_units")}
        base_fpr = sorted(in_fpr)[len(in_fpr) // 2] if in_fpr else None      # 中位 FPR
        base_recall = sorted(in_recall)[len(in_recall) // 2] if in_recall else None
        degrades = {}
        for f, fpr in out_fpr.items():
            degrades[f] = bool(base_fpr is not None and fpr is not None
                               and fpr > base_fpr * FPR_OVERSHOOT)
        collapse = {}
        for f, rec in out_recall.items():
            n_gt = tr.get(f, {}).get("n_gt_unsafe_units", 0)
            if not n_gt:
                collapse[f] = "vacuous_no_gt"  # 该 family 弱标签无 unsafe 正例，recall 不可比
            else:
                collapse[f] = bool(base_recall is not None and rec is not None
                                   and rec < base_recall * 0.5)
        transfer_conclusion = {
            "trained_on": ["baseline", "missing"],
            "in_family_fpr99_reference": base_fpr,
            "in_family_recall99_reference": base_recall,
            "out_of_family_fpr99": out_fpr,
            "out_of_family_recall99": out_recall,
            "fpr_degrades_flag": degrades,
            "recall_collapse_flag": collapse,
            "overshoot_factor": FPR_OVERSHOOT,
            "recall_collapse_factor": 0.5,
            "note": ("现役 baseline+missing 训练的 assessor 对 replace/extra 打分；"
                     "fpr_degrades_flag：留出 family FPR 超过训练 family 中位 FPR 的 "
                     "FPR_OVERSHOOT 倍；recall_collapse_flag：留出 family recall 低于 "
                     "训练 family 中位 recall 的一半"),
        }
    conclusions = {
        "family_changes_operating_point": family_changes_op,
        "baseline_missing_to_replace_extra_transfer": transfer_conclusion,
        "structural_notes": [
            "baseline/extra family 的弱标签 unsafe unit 数为 0（weak label 结构，非人工 GT）："
            "其 val 全安全 → frozen op 为 1.0（vacuous），unit_recall=0 系无正例口径，"
            "不作为迁移失败的证据；",
            # MAJOR-2（round18 review）：数字从 family_counts 派生，不硬编码
            "带标签 family（missing/replace）的 unsafe unit 数见 family_counts；"
            "recall/FPR 仅在带标签 family 间可比。",
        ],
        "family_counts": {f: table.get("units") for f, table in family_table.items()},
    }

    result = {
        "schema": SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {
            "run_root": str(run_root.resolve()),
            "collection": str(collection_path.resolve()),
            "collection_sha256": collection_sha,
        },
        "config": {"train_frac": train_frac, "split_by": split_by,
                   "families": fam_names or None},
        "family_counts": {f: sum(1 for t in c["trainable_evidence"]
                                 if t.get("mutation_type") == f)
                          for f in sorted({t.get("mutation_type")
                                           for t in c["trainable_evidence"]
                                           if t.get("mutation_type")})},
        "family_table": family_table,
        "family_loo": {
            "schema": fl.get("schema"),
            "labels_available": fl.get("labels_available"),
            "loo": fl.get("loo"),
            "pooled_test": fl.get("pooled_test"),
        },
        "song_loo": song_loo,
        "transfer_baseline_missing": transfer,
        "conclusions": conclusions,
        "leak_check": {
            "family_in_features": any(
                k in {"family", "mutation_type", "mutation_family"} for k in keys),
            "feature_keys": keys,
            "note": "mutation family 只用于分层/标签，不进特征（13 §10.1）",
        },
        "note": (
            "labels are weak supervision (gt_eval.unsafe_unit_indices from qwen_fa timestamps), "
            "not human GT; family/song-LOO 均保证留出组完全不可见（不参与拟合也不参与冻结）；"
            "family/song 不合并成一个准确率（13 §10.3）"
        ),
    }
    _atomic_write(out / OUTPUT_NAME, result)
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", required=True, help="formal run root（RUN_MANIFEST.json + evidence/）")
    p.add_argument("--out", required=True, help="输出目录（写 collection.json + ASSESSOR_FAMILY_EVAL.json）")
    p.add_argument("--train-frac", type=float, default=0.7)
    p.add_argument("--split-by", choices=("item", "song"), default="item",
                   help="family 表与 family-LOO 的 fit/val 切分维度（song-LOO 恒为 song）")
    p.add_argument("--family", default=None,
                   help="只评价指定 mutation family（逗号分隔；默认全部 present family）")
    a = p.parse_args(argv)
    families = [f.strip() for f in a.family.split(",")] if a.family else None
    try:
        result = run(Path(a.run_root), Path(a.out), train_frac=a.train_frac,
                     split_by=a.split_by, families=families)
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    out_file = Path(a.out) / OUTPUT_NAME
    ft = result["family_table"]
    song_stats = result["song_loo"]["stats"]
    print(json.dumps({
        "ok": True,
        "schema": result["schema"],
        "collection_sha256": result["inputs"]["collection_sha256"][:16],
        "family_table": {f: {"n_evidence": r.get("n_evidence"), "n_units": r.get("n_units"),
                             "op95": r.get("op95"), "op99": r.get("op99"),
                             "val_unit_recall_95": r.get("val_unit_recall_95"),
                             "val_correct_unit_fpr_95": r.get("val_correct_unit_fpr_95")}
                         for f, r in ft.items()},
        "song_loo_stats": {
            "op95": song_stats["op95"], "op99": song_stats["op99"],
            "pooled_unit_recall_95": song_stats["pooled_unit_recall_95"],
            "pooled_unit_recall_99": song_stats["pooled_unit_recall_99"],
            "pooled_correct_unit_fpr_95": song_stats["pooled_correct_unit_fpr_95"],
            "pooled_correct_unit_fpr_99": song_stats["pooled_correct_unit_fpr_99"],
        },
        "conclusions": result["conclusions"],
        "out": str(out_file),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
