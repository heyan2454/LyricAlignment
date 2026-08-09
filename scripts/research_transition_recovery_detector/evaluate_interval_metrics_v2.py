#!/usr/bin/env python3
"""11 计划实验 C：正式 interval-level detector evaluation（可复现入口）。

输入显式记录 prediction/threshold/target/split/label 定义/intervalization rule hash。
C1 三口径（interval 内错误 100%/≥75% 捕捉、unit unsafe recall）× REJECT-only / REJECT+UNCERTAIN；
C2 正确区代价；C3 SA60/SA80/R95 + joint（UNCERTAIN 不算 REJECT）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from lyricalign.research_transition_recovery_detector.detector_intervals import build_intervals  # noqa: E402
from lyricalign.research_transition_recovery_detector.thresholds import (  # noqa: E402
    STATE_ACCEPT,
    STATE_REJECT,
    STATE_UNCERTAIN,
)

RULE = ("interval=maximal run of identical tristate over contiguous canonical ids; "
        "Safe<=100ms Grey(100,250] Unsafe>250ms; Grey excluded from binary denominator; "
        "REJECT if p_bad>=t_reject; ACCEPT if p_bad<t_accept; UNCERTAIN otherwise")
RULE_HASH = hashlib.sha256(RULE.encode()).hexdigest()[:16]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    p.add_argument("--eval", required=True, help="EVAL json with p_bad/labels")
    p.add_argument("--thresholds", required=True, help="FROZEN_WORKING_POINTS_v2.json")
    p.add_argument("--out", required=True)
    p.add_argument("--role", default="model_selection")
    args = p.parse_args()

    eval_data = json.loads(Path(args.eval).read_text(encoding="utf-8"))
    frozen = json.loads(Path(args.thresholds).read_text(encoding="utf-8"))
    wps = frozen.get("working_points_v3_format") or {}
    p_bad = eval_data["p_bad"]
    labels = eval_data["labels"]  # 0/1/2 (safe/grey/unsafe from v2 labeling), None=no GT

    results: dict[str, dict] = {}
    joint_candidates = []
    for name, wp in wps.items():
        ta, tr = wp["t_accept"], wp["t_reject"]
        states = []
        for pb in p_bad:
            if float(pb) < float(ta):
                states.append(STATE_ACCEPT)
            elif float(pb) >= float(tr):
                states.append(STATE_REJECT)
            else:
                states.append(STATE_UNCERTAIN)
        unit_states = [(i, s) for i, s in enumerate(states)]
        intervals = build_intervals(unit_states)
        # labels: 0=safe 1=grey 2=unsafe
        # 兼容 v2 二元 EVAL（1=unsafe，grey 已排除）与 v3 三态（2=unsafe）
        unsafe_ids = {i for i, l in enumerate(labels) if l in (1, 2)}
        safe_ids = {i for i, l in enumerate(labels) if l == 0}

        def _interval_capture(protected_uncertain: bool) -> dict:
            captured_all = captured_75 = 0
            for iv in intervals:
                ids = [cid for cid in range(iv["start_id"], iv["end_id"] + 1)
                       if cid < len(labels) and labels[cid] is not None]
                n_unsafe = sum(1 for cid in ids if cid in unsafe_ids)
                if n_unsafe == 0:
                    continue
                if iv["state"] == STATE_REJECT or (protected_uncertain and iv["state"] == STATE_UNCERTAIN):
                    if n_unsafe == len(ids):
                        captured_all += 1
                    if n_unsafe / len(ids) >= 0.75:
                        captured_75 += 1
            return {"intervals_with_unsafe": sum(
                1 for iv in intervals
                if any(cid in unsafe_ids for cid in range(iv["start_id"], iv["end_id"] + 1))),
                "captured_100pct": captured_all, "captured_75pct": captured_75}

        rejected = [s for s in states if s == STATE_REJECT]
        rejected_or_uncertain = [s for s in states if s in (STATE_REJECT, STATE_UNCERTAIN)]
        safe_accept = sum(1 for i in safe_ids if states[i] == STATE_ACCEPT)
        safe_reject = sum(1 for i in safe_ids if states[i] == STATE_REJECT)
        safe_uncertain = sum(1 for i in safe_ids if states[i] == STATE_UNCERTAIN)
        unsafe_reject = sum(1 for i in unsafe_ids if states[i] == STATE_REJECT)
        unsafe_uncertain = sum(1 for i in unsafe_ids if states[i] == STATE_UNCERTAIN)
        n_safe = len(safe_ids)
        n_unsafe = len(unsafe_ids)
        # 最长 unsafe ACCEPT run（危险放行）
        longest_unsafe_accept = 0
        cur = 0
        for i in range(len(states)):
            if i in unsafe_ids and states[i] == STATE_ACCEPT:
                cur += 1
                longest_unsafe_accept = max(longest_unsafe_accept, cur)
            else:
                cur = 0
        # interval 长度统计
        iv_lens = [iv["end_id"] - iv["start_id"] + 1 for iv in intervals]
        res = {
            "n_intervals": len(intervals),
            "interval_states": {STATE_ACCEPT: sum(1 for iv in intervals if iv["state"] == STATE_ACCEPT),
                                STATE_REJECT: sum(1 for iv in intervals if iv["state"] == STATE_REJECT),
                                STATE_UNCERTAIN: sum(1 for iv in intervals if iv["state"] == STATE_UNCERTAIN)},
            "interval_len_mean": round(sum(iv_lens) / max(len(iv_lens), 1), 2),
            "interval_len_median": sorted(iv_lens)[len(iv_lens) // 2] if iv_lens else None,
            "C1": {
                "reject_only": _interval_capture(False),
                "reject_plus_uncertain": _interval_capture(True),
                "unit_unsafe_recall_reject_only": round(unsafe_reject / max(n_unsafe, 1), 4),
                "unit_unsafe_recall_reject_plus_uncertain": round(
                    (unsafe_reject + unsafe_uncertain) / max(n_unsafe, 1), 4),
            },
            "C2": {
                "safe_accept_rate": round(safe_accept / max(n_safe, 1), 4),
                "safe_reject_rate": round(safe_reject / max(n_safe, 1), 4),
                "safe_uncertain_rate": round(safe_uncertain / max(n_safe, 1), 4),
                "safe_intervals_shattered": sum(
                    1 for iv in intervals
                    if iv["state"] in (STATE_REJECT, STATE_UNCERTAIN)
                    and any(cid in safe_ids for cid in range(iv["start_id"], iv["end_id"] + 1))),
                "longest_unsafe_accept_run": longest_unsafe_accept,
            },
            "C3": {
                "safe_accept": round(safe_accept / max(n_safe, 1), 4),
                "unsafe_reject": round(unsafe_reject / max(n_unsafe, 1), 4),
                "uncertain_rate": round(sum(1 for s in states if s == STATE_UNCERTAIN) / max(len(states), 1), 4),
                "n_safe": n_safe, "n_unsafe": n_unsafe, "n_grey_excluded": sum(1 for l in labels if l == 1),
            },
            "t_accept": float(ta), "t_reject": float(tr),
        }
        results[name] = res
        joint_candidates.append((res["C3"]["safe_accept"], res["C3"]["unsafe_reject"], name))
    joint_feasible = any(sa >= 0.60 and ur >= 0.95 for sa, ur, _ in joint_candidates)
    joint_best_sa = max(joint_candidates, key=lambda x: x[0])
    joint_best_r95 = max(joint_candidates, key=lambda x: x[1])
    out = {
        "schema_version": "interval_metrics_reproducible_v1",
        "inputs": {"prediction_artifact": args.eval, "threshold_artifact": args.thresholds,
                   "target": "raw", "split": args.role,
                   "label_definition": "Safe<=100ms Grey(100,250] Unsafe>250ms; Grey excluded from binary",
                   "intervalization_rule_hash": RULE_HASH,
                   "C3_denominator_note": "C3.n_unsafe 为 intervalization 后的 unsafe unit 计数（unit 可跨 interval 重复），"
                                          "与 FROZEN_WORKING_POINTS 的全体 unsafe 单元基数不同；unsafe_reject 为 REJECT-only recall"},
        "working_points": results,
        "joint_sa60_r95": {
            "feasible": joint_feasible,
            "max_safe_accept_at_r95": round(joint_best_r95[0], 4),
            "max_unsafe_reject_at_sa60": round(joint_best_sa[1], 4),
        },
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({k: {"safe_accept": v["C3"]["safe_accept"], "unsafe_reject": v["C3"]["unsafe_reject"],
                          "unsafe_reject_rate_rename_note": "unsafe_reject = REJECT-only recall (UNCERTAIN 不算)"}
                      for k, v in results.items()}, ensure_ascii=False, indent=1))
    print(json.dumps({"joint": out["joint_sa60_r95"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
