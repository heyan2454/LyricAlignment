#!/usr/bin/env python3
"""WP7：report_long_slot_region —— draft 汇总与 budget/pilot 报告。

读取 smoke/pilot/formal 结果，输出 AUTO_SUMMARY.json + AUTO_FINDINGS_DRAFT.md + RUNTIME_BUDGET.json。
标签明确 draft=true；formal 只有显式 --formal-approved-manifest 才采信。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", required=True)
    p.add_argument("--formal-approved-manifest", default="", help="仅正式汇总使用；缺省为 smoke/pilot draft")
    args = p.parse_args(argv)

    run = Path(args.run_root)
    smoke_f = run / "smoke" / "LONG_SLOT_SMOKE.json"
    if not smoke_f.exists():
        print(json.dumps({"ok": False, "reason": "no smoke result"}), ensure_ascii=False)
        return 3
    d = json.loads(smoke_f.read_text())

    auto = {
        "schema": "research_v7_long_slot_report_v1",
        "created_at_utc": "2026-08-04T00:00:00Z",
        "draft": not bool(args.formal_approved_manifest),
        "formal_approved": bool(args.formal_approved_manifest),
        "status": "smoke_draft",
        "key": {
            "timeline_duration_sec": d.get("timeline", {}).get("duration_sec"),
            "timeline_ge180": d.get("timeline", {}).get("ge180"),
            "slot_topology": d.get("slot", {}).get("topology"),
            "non_contiguous": d.get("slot", {}).get("non_contiguous"),
            "unit_recall": d.get("metrics", {}).get("unit_recall"),
            "correct_unit_fpr": d.get("metrics", {}).get("fpr"),
            "gap_recall": d.get("metrics", {}).get("gap_recall"),
            "assessor_op": d.get("assessor", {}).get("operating_points"),
        },
    }

    (run / "report").mkdir(parents=True, exist_ok=True)
    (run / "report" / "AUTO_SUMMARY.json").write_text(json.dumps(auto, ensure_ascii=False, indent=1))

    budget = {
        "schema": "runtime_budget_v1", "draft": True,
        "formal_target_h": 10, "formal_hard_cap_h": 12,
        "smoke": "run in CPU (no model)", "note": "pilot must measure elapsed/forward/cache before formal",
    }
    (run / "report" / "RUNTIME_BUDGET.json").write_text(json.dumps(budget, ensure_ascii=False, indent=1))

    md = f"""# AUTO_FINDINGS_DRAFT (draft=true)

- Timeline: {auto['key']['timeline_duration_sec']}s (ge180={auto['key']['timeline_ge180']})
- Slot topology: {auto['key']['slot_topology']} (non-contiguous={auto['key']['non_contiguous']})
- unit_recall={auto['key']['unit_recall']}, correct_unit_fpr={auto['key']['correct_unit_fpr']}, gap_recall={auto['key']['gap_recall']}
- Assessor operating points: {auto['key']['assessor_op']}

> 自动 draft。正式科研结论需人工复核并使用 --formal-approved-manifest。
"""
    (run / "report" / "AUTO_FINDINGS_DRAFT.md").write_text(md)

    print(json.dumps({"ok": True, "draft": auto["draft"], "out": str(run / "report"),
                      "key": auto["key"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
