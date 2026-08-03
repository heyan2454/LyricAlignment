#!/usr/bin/env python3
"""A1：E1 event 指标修复 —— 按 item 分组的事件级 micro/macro F1 重算。

背景：v6 summarize 只取 single formal.event_metrics 做跨 item 聚合，未按
dataset/source_song_id/item_id 分组做 one-to-one matching。本脚本从 v8 formal 各 item
的 E1_detector.json 的 active_event_threshold_curve 中提取 reference/prediction event spans，
按 item 分组重算 micro（全局 TP/FP/FN）、item-macro F1 与 source-song bootstrap。

输入：v8 formal root（--formal-root），只用 gt_available 的 item（demo 无 GT 剔除）。
输出：v7 目录下 repair_e1_event_metrics.json + 精简汇总到 stdout。
纯 CPU，不重新模型推理；参考 detector.py event_metrics/_merge_indices 语义。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def load_item_data(formal_items: Path, item_id: str) -> dict:
    """读取一个 item 的 E1_detector.json 与 item_summary.json（compact 可能精简 gt，改走 manifest）。"""
    d_dir = formal_items / item_id
    det = json.loads((d_dir / "E1_detector.json").read_text())
    summ = json.loads((d_dir / "item_summary.json").read_text())
    return {"item_id": item_id, "det": det, "summary": summ}


def load_manifest_index(manifest_path: Path) -> dict[str, dict]:
    """从 active_manifest.jsonl 构建 item_id -> {dataset, source_song_id, gt_path} 索引。

    注意：v8 用 --compact-artifacts，item_summary.json 被精简、不含 gt 字段；
    gt/dataset/source_song 的权威来源是 manifest（不受 compact 影响）。
    """
    index: dict[str, dict] = {}
    for line in manifest_path.read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        iid = d.get("item_id")
        if not iid:
            continue
        index[iid] = {
            "dataset": d.get("dataset"),
            "source_song_id": d.get("source_song_id") or d.get("source_song"),
            "gt_path": d.get("gt_path"),
            "split": d.get("split"),
            "selection_role": d.get("selection_role"),
        }
    return index


def active_spans(det: dict) -> tuple[list[dict], list[dict]]:
    """从 active_event_threshold_curve 挑 threshold 最接近 active_risk_threshold 的条目。"""
    target = float(det.get("active_risk_threshold", 0.0))
    curve = det.get("active_event_threshold_curve", []) or []
    if not curve:
        return [], []
    best = min(curve, key=lambda c: abs(float(c.get("threshold", 0.0)) - target))
    return best.get("predicted_spans", []) or [], best.get("reference_spans", []) or []


def merge_spans(spans, gap: int) -> list[tuple[int, int]]:
    """合并连续 index 跨度：value<=previous+gap+1 则并入（同 detector._merge_indices）。"""
    merged: list[tuple[int, int]] = []
    for s in sorted(spans, key=lambda x: int(x.get("character_start", 0))):
        cs, ce = int(s.get("character_start", 0)), int(s.get("character_end", 0))
        if ce < cs:
            ce = cs
        if merged and cs <= merged[-1][1] + gap + 1:
            prev_s, prev_e = merged[-1]
            merged[-1] = (prev_s, max(prev_e, ce))
        else:
            merged.append((cs, ce))
    return merged


def one_to_one_match(pred: list[tuple[int, int]], ref: list[tuple[int, int]]) -> tuple[int, int, int]:
    """最大索引重叠的贪心 one-to-one matching：返回 (tp, fp, fn)。"""
    tp = 0
    used_ref = set()
    for ps, pe in pred:
        best, best_overlap = None, -1
        for ri, (rs, re) in enumerate(ref):
            if ri in used_ref:
                continue
            overlap = max(0, min(pe, re) - max(ps, rs) + 1)
            if overlap > best_overlap:
                best, best_overlap = ri, overlap
        if best is not None and best_overlap > 0:
            tp += 1
            used_ref.add(best)
    fp = len(pred) - tp
    fn = len(ref) - len(used_ref)
    return tp, fp, fn


def precision_recall_f1(tp, fp, fn) -> dict:
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return {"precision": p, "recall": r, "f1": f1}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--formal-root", required=True)
    p.add_argument("--manifest", default=None, help="active_manifest.jsonl（缺省用 <formal-root>/manifest/active_manifest.jsonl）")
    p.add_argument("--out", required=True)
    p.add_argument("--limit", type=int, default=0, help="0=全部，>0 仅处理前 N 个 item（smoke 用）")
    args = p.parse_args(argv)

    formal_items = Path(args.formal_root) / "formal" / "items"
    if not formal_items.is_dir():
        print(f"[error] bad formal root: {formal_items}", file=sys.stderr)
        return 2
    manifest_path = Path(args.manifest) if args.manifest else Path(args.formal_root) / "manifest" / "active_manifest.jsonl"
    index = load_manifest_index(manifest_path)

    item_ids = sorted(
        d.name
        for d in formal_items.iterdir()
        if d.is_dir() and (d / "E1_detector.json").exists()
    )
    if args.limit:
        import random

        random.seed(0)
        item_ids = random.sample(item_ids, args.limit)

    # 全局 TP/FP/FN 与 per-item 记录
    gtp = gfp = gfn = 0
    item_rows: list[dict] = []
    used_items = 0
    for iid in item_ids:
        meta = index.get(iid, {})
        if not meta.get("gt_path"):
            continue  # 无 GT（demo）剔除
        try:
            data = load_item_data(formal_items, iid)
        except Exception as e:
            print(f"  [warn] skip {iid}: {e}")
            continue
        ps, rs = active_spans(data["det"])
        pred_merged = merge_spans(ps, gap=1)
        ref_merged = merge_spans(rs, gap=0)
        tp, fp, fn = one_to_one_match(pred_merged, ref_merged)
        gtp += tp
        gfp += fp
        gfn += fn
        item_rows.append({
            "item_id": iid,
            "dataset": meta.get("dataset"),
            "source_song_id": meta.get("source_song_id"),
            "n_pred": len(pred_merged),
            "n_ref": len(ref_merged),
            "tp": tp, "fp": fp, "fn": fn,
            "event_f1": precision_recall_f1(tp, fp, fn)["f1"],
        })
        used_items += 1

    micro = precision_recall_f1(gtp, gfp, gfn)
    macro = (sum(r["event_f1"] for r in item_rows) / len(item_rows)) if item_rows else 0.0

    # source-song bootstrap（按 item 级 F1 采样 200 次）
    import random

    rng = random.Random(0)
    if item_rows:
        boot = []
        for _ in range(200):
            sample = rng.choices(item_rows, k=len(item_rows))
            boot.append(sum(r["event_f1"] for r in sample) / len(sample))
        boot.sort()
        bootstrap = {
            "n": len(boot),
            "median": round(boot[len(boot) // 2], 6),
            "p5": round(boot[int(len(boot) * 0.05)], 6),
            "p95": round(boot[int(len(boot) * 0.95)], 6),
        }
    else:
        bootstrap = {"n": 0, "median": None, "p5": None, "p95": None}

    out = {
        "schema": "v7/e1_event_recompute_v1",
        "n_items_total": len(item_ids),
        "n_gt_items_used": used_items,
        "micro": micro,
        "macro_f1": round(macro, 6),
        "bootstrap": bootstrap,
        "n_source_songs": len({r["source_song_id"] for r in item_rows if r["source_song_id"]}),
        "items": item_rows,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps({
        "ok": True,
        "total_items": len(item_ids),
        "gt_items": used_items,
        "micro": micro,
        "macro_f1": out["macro_f1"],
        "bootstrap_median": bootstrap["median"],
        "out": args.out,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
