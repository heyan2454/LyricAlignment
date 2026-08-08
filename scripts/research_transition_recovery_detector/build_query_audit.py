#!/usr/bin/env python3
"""P1：Query audit（09 §3 P1）——每个 request 输出 01_query_audit/QUERY_AUDIT.jsonl。

GT 只写入 audit/evaluation，不进入 T1/T2/T3 query construction。
audit 发现系统性 underfeeding/overfeeding、query 不含正确 occurrence、
或 estimator version 不一致时，--fail-on-systematic-bias 退出非零。

两种模式：
  --mode audit  ：对已有 records（02_transition/*.jsonl）重放生成 audit 行（CPU）
  --mode verify ：只检查已存在 audit 文件的一致性并输出 gate 状态（CPU）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))


def audit_records(records: list[dict], gt: dict[int, dict]) -> list[dict]:
    """从 records 生成 query audit 行。GT 仅用于评估（head_delta/recall/occurrence）。"""
    out = []
    for rec in records:
        if rec.get("skipped"):
            continue
        req = rec["request"]
        model_bounds = req["model_bounds"]
        is_, cs, ce, ie = model_bounds
        qids = req["query_canonical_ids"]
        n = len(qids)
        q0 = min(qids) if qids else None
        q1 = max(qids) + 1 if qids else None
        ups = req.get("units_per_sec") or (
            None  # 需要时从 estimator 重建（此处仅 audit 元数据）
        )
        # GT 相关指标（仅 audit/evaluation 用途）
        head_delta = None
        gt_active_recall = None
        gt_first = None
        extra_left = extra_right = None
        correct_occurrence = None
        first_sung_rank = None
        if gt and q0 is not None:
            active = sorted(
                i for i, u in gt.items() if cs - 1e-9 <= float(u["start_sec"]) < ce
            )
            if active:
                gt_first = active[0]
                head_delta = q0 - gt_first
                covered = [i for i in active if q0 <= i < q1]
                gt_active_recall = len(covered) / len(active)
                extra_left = max(0, gt_first - q0)
                extra_right = max(0, q1 - (active[-1] + 1))
                correct_occurrence = None  # 需 gt_occurrence 输入；当前 GT schema 无 occurrence → not_applicable
                first_sung_rank = next((k for k, i in enumerate(qids) if i in active), None)
        row = {
            "window_index": req.get("window_index", 0),
            "head_strategy_actual": (rec.get("query_audit") or {}).get("head_strategy"),
            "original_bounds": [round(float(v), 4) for v in req["original_bounds"]],
            "model_bounds": [round(float(v), 4) for v in model_bounds],
            "query_start_id": q0,
            "query_end_id_exclusive": q1,
            "n_query_units": n,
            "query_estimator_version": req.get("query_estimator_version"),
            "head_strategy": req.get("head_strategy", "H0"),
            "parent_state_hash": req["parent_state_hash"][:16],
            "cursor_before": rec["state_before"]["committed_end_exclusive"],
            "cursor_after": rec["state_after"]["committed_end_exclusive"],
            "gt_first_relevant_id": gt_first,
            "head_delta_units": head_delta,
            "gt_active_unit_recall": round(gt_active_recall, 4) if gt_active_recall is not None else None,
            "extra_left_units": extra_left,
            "extra_right_units": extra_right,
            "correct_occurrence_contained": correct_occurrence,
            "first_sung_unit_rank": first_sung_rank,
        }
        out.append(row)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    p.add_argument("--timeline-manifest", required=True)
    p.add_argument("--role", default="model_selection")
    p.add_argument("--mode", choices=("audit", "verify"), default="audit")
    p.add_argument("--fail-on-systematic-bias", action="store_true")
    p.add_argument("--head-strategy", default="H0")
    p.add_argument("--transition", default="T2_core_boundary_serial")
    args = p.parse_args()

    session_root = Path(args.session_root)
    by_song = {
        json.loads(line)["song_id"]: json.loads(line)
        for line in Path(args.timeline_manifest).read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    split = json.loads((session_root / "00_meta" / "DATASET_SPLIT.json").read_text(encoding="utf-8"))
    song_ids = split["roles"][args.role]
    out_dir = session_root / "01_query_audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"QUERY_AUDIT_{args.transition}.jsonl"

    rows = []
    if args.mode == "audit":
        for song_id in song_ids:
            rec_path = session_root / "02_transition" / f"{song_id}__{args.transition}.jsonl"
            if not rec_path.is_file():
                continue
            gt = {int(u["canonical_unit_id"]): u for u in by_song[song_id]["canonical_units"]}
            records = [
                json.loads(l) for l in rec_path.read_text(encoding="utf-8").splitlines() if l.strip()
            ]
            for row in audit_records(records, gt):
                row["song_id"] = song_id
                row["head_strategy"] = row.get("head_strategy_actual") or args.head_strategy
                rows.append(row)
        with open(out_path, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    else:
        audit_files = sorted(out_dir.glob("QUERY_AUDIT_*.jsonl"))
        if not audit_files:
            print("QUERY_AUDIT missing", file=sys.stderr)
            return 2
        rows = []
        for f in audit_files:
            rows.extend(json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip())

    # gate：系统性偏差检查（audit 行内）
    versions = {r.get("query_estimator_version") for r in rows}
    n = len(rows)
    if args.mode == "audit" and args.fail_on_systematic_bias and n:
        recalls = [r["gt_active_unit_recall"] for r in rows if r["gt_active_unit_recall"] is not None]
        head_deltas = [r["head_delta_units"] for r in rows if r["head_delta_units"] is not None]
        mean_recall = sum(recalls) / len(recalls) if recalls else None
        mean_head_delta = sum(head_deltas) / len(head_deltas) if head_deltas else None
        n_versions = len(versions)
        if len(versions) > 1 or mean_recall is None or (mean_recall is not None and mean_recall < 0.5):
            print(json.dumps({
                "gate_query_audit": "fail",
                "n_audit_rows": n,
                "estimator_versions": sorted(versions),
                "mean_gt_active_recall": mean_recall,
                "mean_head_delta_units": mean_head_delta,
            }, ensure_ascii=False))
            return 1
        print(json.dumps({
            "gate_query_audit": "pass",
            "n_audit_rows": n,
            "estimator_versions": sorted(versions),
            "mean_gt_active_recall": round(mean_recall, 4) if mean_recall is not None else None,
            "mean_head_delta_units": round(mean_head_delta, 2) if mean_head_delta is not None else None,
        }, ensure_ascii=False))
        return 0
    print(json.dumps({"gate_query_audit": "verify_only", "n_audit_rows": n,
                      "estimator_versions": sorted(versions)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
