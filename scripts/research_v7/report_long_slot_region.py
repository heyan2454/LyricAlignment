#!/usr/bin/env python3
"""WP7：report_long_slot_region —— draft 汇总与 budget/pilot 报告。

读取 smoke/pilot/formal 结果，输出 AUTO_SUMMARY.json + AUTO_FINDINGS_DRAFT.md + RUNTIME_BUDGET.json。
P0-5：除非提供的 --formal-approved-manifest 真实存在且其 sha256 与 --expected-manifest-sha256
一致，否则一律 draft=true；不可仅凭“传了参数”就降级。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", required=True)
    p.add_argument("--formal-approved-manifest", default="", help="正式汇总才使用该 manifest")
    p.add_argument("--expected-manifest-sha256", default="", help="冻结 manifest 的 sha256（须匹配才 formal_approved）")
    args = p.parse_args(argv)

    run = Path(args.run_root)
    smoke_f = run / "smoke" / "LONG_SLOT_SMOKE.json"
    if not smoke_f.exists():
        print(json.dumps({"ok": False, "reason": "no smoke result"}), ensure_ascii=False)
        return 3
    smoke = json.loads(smoke_f.read_text())

    # P0-5 round2：formal_approved 需真实 formal evidence + frozen manifest sha + 实际预算/gates。
    formal_approved = False
    reasons = []
    formal_manifest = run / "formal" / "RUN_MANIFEST.json"
    marker = run / "formal" / "FORMAL_MARKER.json"
    if not args.formal_approved_manifest:
        reasons.append("no formal-approved-manifest")
    elif not marker.is_file():
        reasons.append("no real formal evidence: run/formal/FORMAL_MARKER.json missing")
    elif not formal_manifest.is_file():
        reasons.append("missing real formal result: run/formal/RUN_MANIFEST.json")
    else:
        mp = Path(args.formal_approved_manifest)
        got_sha = _sha256(mp) if mp.is_file() else None
        if not mp.is_file():
            reasons.append("formal-approved-manifest not a file")
        elif not args.expected_manifest_sha256:
            reasons.append("expected-manifest-sha256 not provided")
        elif got_sha != args.expected_manifest_sha256:
            reasons.append("manifest sha256 mismatch (frozen expected)")
        else:
            try:
                marker_d = json.loads(marker.read_text())
                run_man = json.loads(formal_manifest.read_text())
            except Exception as e:
                reasons.append(f"formal marker/manifest unreadable: {e}")
            else:
                # marker 必须绑定 frozen manifest hash + run identity + 实际预算
                if marker_d.get("manifest_sha256") != args.expected_manifest_sha256:
                    reasons.append("FORMAL_MARKER manifest_sha256 != frozen expected")
                    formal_runner = None
                else:
                    formal_runner = run_man.get("run_id") == marker_d.get("run_id")
                    if not formal_runner:
                        reasons.append("FORMAL_MARKER run_id != RUN_MANIFEST.run_id")
                if not (marker_d.get("all_gates_passed") and marker_d.get("runtime_budget_ok")):
                    reasons.append("FORMAL_MARKER gates/budget not all passed")
                else:
                    # 真实结果应有实测预算字段（elapsed/forward/cache），不是凭空
                    fb = run_man.get("runtime_budget") or {}
                    if not (fb.get("elapsed_sec") and fb.get("forward_count") is not None):
                        reasons.append("RUN_MANIFEST.runtime_budget missing actual elapsed/forward")
                if not reasons:
                    formal_approved = True
    draft = not formal_approved

    # 数据源：formal→真实 RUN_MANIFEST；否则 smoke（draft）
    if formal_approved:
        result_kv = run_man
    else:
        result_kv = smoke

    auto = {
        "schema": "research_v7_long_slot_report_v1",
        "created_at_utc": "2026-08-04T00:00:00Z",
        "draft": draft,
        "formal_approved": formal_approved,
        "draft_reasons": reasons,
        "result_source": str(formal_manifest) if formal_approved else str(smoke_f),
        "data": {
            "timeline_duration_sec": result_kv.get("timeline", {}).get("duration_sec"),
            "timeline_ge180": result_kv.get("timeline", {}).get("ge180"),
            "slot_topology": result_kv.get("slot", result_kv.get("key", {})).get("topology"),
            "non_contiguous": (result_kv.get("slot", result_kv.get("key", {}))).get("non_contiguous"),
            "unit_recall": result_kv.get("metrics", {}).get("unit_recall")
                      or result_kv.get("key", {}).get("unit_recall"),
            "correct_unit_fpr": result_kv.get("metrics", {}).get("fpr")
                      or result_kv.get("key", {}).get("correct_unit_fpr"),
            "gap_recall": result_kv.get("metrics", {}).get("gap_recall")
                      or result_kv.get("key", {}).get("gap_recall"),
            "assessor_op": result_kv.get("assessor", {}).get("operating_points")
                      or result_kv.get("key", {}).get("assessor_op"),
        },
    }
    (run / "report").mkdir(parents=True, exist_ok=True)
    (run / "report" / "AUTO_SUMMARY.json").write_text(json.dumps(auto, ensure_ascii=False, indent=1))

    # P0(review3-3)：formal approved 时保留/引用实际 formal budget（不再写 draft=true 的自相矛盾占位）
    if formal_approved:
        budget = {
            "schema": "runtime_budget_v1", "draft": False,
            "source": "formal", "budget": result_kv.get("runtime_budget", {}) or run_man.get("runtime_budget", {}),
            "note": "actual formal run budget (elapsed/forward from RUN_MANIFEST)",
        }
    else:
        budget = {
            "schema": "runtime_budget_v1", "draft": True,
            "formal_target_h": 10, "formal_hard_cap_h": 12,
            "smoke": "run in CPU (no model)", "note": "pilot must measure elapsed/forward/cache before formal",
        }
    (run / "report" / "RUNTIME_BUDGET.json").write_text(json.dumps(budget, ensure_ascii=False, indent=1))

    md = f"""# AUTO_FINDINGS_{(not draft and 'SUMMARY' or 'DRAFT')}

- status: {'formal (approved)' if formal_approved else 'smoke/pilot draft'}
- Timeline: {auto['data']['timeline_duration_sec']}s (ge180={auto['data']['timeline_ge180']})
- Slot topology: {auto['data']['slot_topology']} (non-contiguous={auto['data']['non_contiguous']})
- unit_recall={auto['data']['unit_recall']}, correct_unit_fpr={auto['data']['correct_unit_fpr']}, gap_recall={auto['data']['gap_recall']}
- Assessor operating points: {auto['data']['assessor_op']}

> 自动。draft={draft}; reasons={reasons}。正式结论需 sha-matched frozen manifest；否则仅作 draft。
"""
    (run / "report" / "AUTO_FINDINGS_DRAFT.md").write_text(md)

    print(json.dumps({"ok": True, "draft": draft, "formal_approved": formal_approved,
                      "reasons": reasons, "out": str(run / "report"), "data": auto["data"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
